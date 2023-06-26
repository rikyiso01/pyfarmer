from __future__ import annotations

from argparse import ArgumentParser
from asyncio import Queue, run, sleep
from collections import Counter
from collections.abc import Callable, Generator, Iterable
from enum import IntEnum, auto
from multiprocessing.connection import Connection
from os.path import basename
from random import shuffle
from sys import argv
from time import time
from traceback import print_exc
from typing import TYPE_CHECKING, TypedDict
from urllib.parse import urljoin

from httpx import AsyncClient, HTTPError
from typing_extensions import TypeAlias

from pyfarmer._strategies import FarmingStrategy, ProcessStrategy
from pyfarmer._utils import AsyncConnection, fast_queue_read, run_in_background

if TYPE_CHECKING:
    from asyncio import TaskGroup
else:
    from aiotools import TaskGroup

SploitFunction: TypeAlias = "Callable[[str], Iterable[str] | None]"
FlagQueue: TypeAlias = "Queue[tuple[str, str]]"
ProducerFunction: TypeAlias = "Callable[[str], None]"


class Status(IntEnum):
    OK = auto()
    TIMEOUT = auto()
    ERROR = auto()


class Config(TypedDict):
    TEAMS: dict[str, str]
    FLAG_LIFETIME: int


DEFAULT_POOL_SIZE = 8
DEFAULT_VERBOSE_ATTACKS = 1


def farm(
    function: SploitFunction, /, *, strategy: FarmingStrategy = ProcessStrategy(None)
):
    parser = ArgumentParser(description="Run a sploit on all teams in a loop")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("ip", metavar="IP", nargs="?")
    group.add_argument("-u", "--server-url", metavar="URL", help="Server URL")
    parser.add_argument("-a", "--alias", metavar="ALIAS", help="Sploit alias")
    parser.add_argument("--token", metavar="TOKEN", help="Farm authorization token")
    parser.add_argument(
        "--pool-size",
        metavar="N",
        type=int,
        default=DEFAULT_POOL_SIZE,
        help="Maximal number of concurrent sploit instances. "
        "Too little value will make time limits for sploits smaller, "
        "too big will eat all RAM on your computer",
    )
    parser.add_argument(
        "--attack-period",
        metavar="N",
        type=float,
        help="Rerun the sploit on all teams each N seconds "
        "Too little value will make time limits for sploits smaller, "
        "too big will miss flags from some rounds",
    )

    # parser.add_argument(
    #     "-v",
    #     "--verbose-attacks",
    #     metavar="N",
    #     default=DEFAULT_VERBOSE_ATTACKS,
    #     type=int,
    #     help="Sploits' outputs and found flags will be shown for the N first attacks",
    # )

    # group = parser.add_mutually_exclusive_group()
    # group.add_argument(
    #     "--not-per-team",
    #     action="store_true",
    #     default=False,
    #     help="Run a single instance of the sploit instead of an instance per team",
    # )
    # group.add_argument(
    #     "--distribute",
    #     nargs=2,
    #     metavar=("K", "N"),
    #     help="Divide the team list to N parts (by address hash modulo N) "
    #     "and run the sploits only on Kth part of it (K >= 1)",
    # )
    args = vars(parser.parse_args())
    try:
        run(main(function, strategy, **args))
    except KeyboardInterrupt:
        pass


async def main(
    function: SploitFunction,
    strategy: FarmingStrategy,
    /,
    *,
    ip: str | None,
    server_url: str | None,
    alias: str | None,
    token: str | None,
    pool_size: int,
    attack_period: float | None,
    # verbose_attacks: int | None,
    # not_per_team: bool,
    # distribute: tuple[int, int] | None,
):
    if server_url is not None:
        if "http" not in server_url:
            server_url = f"http://{server_url}"
        if alias is None:
            alias = basename(argv[0])
        queue: FlagQueue = Queue(1024)
        async with AsyncClient() as client:
            config = await get_config(client, server_url, token)
            targets = [*config["TEAMS"].values()]
            shuffle(targets)
            if attack_period is None:
                attack_period = config["FLAG_LIFETIME"]
            print("Config:")
            print("\t#targets:", len(targets))
            print("\tflag_lifetime:", attack_period)
            print("\tsploit_timeout:", attack_period / len(targets))
            print("\talias:", alias)
            print("\tsprint_pool_size:", pool_size)
            print("Starting first sprint")
            async with TaskGroup() as group:
                group.create_task(
                    upload_thread(client, queue, server_url, alias, token)
                )
                group.create_task(
                    main_loop(
                        function,
                        queue,
                        targets,
                        pool_size,
                        attack_period,
                        strategy,
                    )
                )
    else:
        assert ip is not None
        for flag in run_sploit(function, ip):
            print(flag)


async def get_config(client: AsyncClient, server_url: str, token: str | None) -> Config:
    response = await client.get(
        urljoin(server_url, "/api/get_config"),
        headers={"X-Token": token} if token is not None else None,
    )
    response.raise_for_status()
    return response.json()


async def post_flags(
    client: AsyncClient,
    server_url: str,
    alias: str,
    token: str | None,
    flags: list[tuple[str, str]],
):
    data = [{"flag": flag, "sploit": alias, "team": team} for team, flag in flags]
    response = await client.post(
        urljoin(server_url, "/api/post_flags"),
        json=data,
        headers={"X-Token": token} if token is not None else None,
    )
    response.raise_for_status()


async def upload_thread(
    client: AsyncClient,
    queue: FlagQueue,
    server_url: str,
    alias: str,
    token: str | None,
):
    to_submit: list[tuple[str, str]] = []
    while True:
        flags = await fast_queue_read(queue)
        to_submit += flags
        try:
            await post_flags(client, server_url, alias, token, to_submit)
            print(f"Posted {len(flags)} flags")
            to_submit = []
        except HTTPError:
            print_exc()


async def main_loop(
    function: SploitFunction,
    queue: FlagQueue,
    targets: list[str],
    pool_size: int,
    attack_period: float,
    strategy: FarmingStrategy,
):
    await run_all(function, queue, targets, pool_size, attack_period, strategy)
    print("Entering slow mode")
    while True:
        await slow_mode(function, queue, targets, attack_period, strategy)


async def slow_mode(
    function: SploitFunction,
    queue: FlagQueue,
    targets: list[str],
    attack_period: float,
    strategy: FarmingStrategy,
) -> None:
    counter: Counter[Status] = Counter()
    for i, target in enumerate(targets):
        timeout = attack_period / len(targets)
        print(f"Starting attack {i}/{len(targets)}")
        start = time()
        status = await run_attack(function, queue, target, timeout, strategy)
        counter[status] += 1
        print(f"Attack {i}/{len(targets)} result:", status.name)
        await sleep(timeout - (time() - start))
    print("Slow mode cycle completed")
    print_stats(counter)


def print_stats(stats: Counter[Status]):
    total = stats.total()
    print("Stats:")
    print(f"\tOK: {stats[Status.OK]}/{total}")
    print(f"\tERROR: {stats[Status.ERROR]}/{total}")
    print(f"\tTIMEOUT: {stats[Status.TIMEOUT]}/{total}")


async def run_all(
    function: SploitFunction,
    queue: FlagQueue,
    targets: list[str],
    pool_size: int,
    attack_period: float,
    strategy: FarmingStrategy,
) -> None:
    shared_list = [*reversed(targets)]
    async with TaskGroup() as group:
        tasks = [
            group.create_task(
                pool_tasks(
                    function, queue, shared_list, attack_period / len(targets), strategy
                )
            )
            for _ in range(pool_size)
        ]
    start: Counter[Status] = Counter()
    stats = sum([await task for task in tasks], start=start)
    print("Sprint completed")
    print_stats(stats)


async def pool_tasks(
    function: SploitFunction,
    queue: FlagQueue,
    pool: list[str],
    attack_period: float,
    strategy: FarmingStrategy,
) -> Counter[Status]:
    counter: Counter[Status] = Counter()
    while pool:
        print("Remaining targets in the sprint:", len(pool))
        target = pool.pop()
        status = await run_attack(function, queue, target, attack_period, strategy)
        counter[status] += 1
    return counter


async def run_attack(
    function: SploitFunction,
    queue: FlagQueue,
    target: str,
    attack_period: float,
    strategy: FarmingStrategy,
) -> Status:
    read, write = strategy.create_communication()
    async with TaskGroup() as group:
        task = group.create_task(
            attack_process(function, target, attack_period, strategy, write)
        )
        group.create_task(read_connection(read, queue, target))
    return await task


async def read_connection(connection: Connection, queue: FlagQueue, target: str):
    try:
        with AsyncConnection(connection) as c:
            while True:
                data = await c.read()
                await queue.put((target, data))
    except EOFError:
        pass


async def attack_process(
    function: SploitFunction,
    target: str,
    attack_period: float,
    strategy: FarmingStrategy,
    write: Connection,
) -> Status:
    process = strategy.create(process_main, (function, write, target))
    process.start()
    strategy.after_start(write)
    await run_in_background(process.join, (attack_period,))
    strategy.after_stop(write)
    if process.is_alive():
        process.kill()
        return Status.TIMEOUT
    assert process.exitcode is not None
    if process.exitcode != 0:
        return Status.ERROR
    return Status.OK


def process_main(function: SploitFunction, connection: Connection, target: str) -> None:
    try:
        for flag in run_sploit(function, target):
            connection.send(flag)
    except KeyboardInterrupt:
        pass


def run_sploit(function: SploitFunction, target: str) -> Generator[str, None, None]:
    result = function(target)
    if result is None:
        return
    if isinstance(result, str):
        result = [result]
    yield from result
