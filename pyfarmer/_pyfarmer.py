from __future__ import annotations
from argparse import ArgumentParser
from httpx import AsyncClient, HTTPError
from urllib.parse import urljoin
from sys import argv
from os.path import basename
from collections.abc import Callable, Iterable
from multiprocessing import Queue, Process
from time import time
from typing import TypedDict, TYPE_CHECKING
from typing_extensions import TypeAlias

from multiprocessing.context import Process
from pyfarmer._utils import (
    ensure_generator,
    fast_queue_read,
    generator_to_producer,
)
from asyncio import run, sleep
from pyfarmer._utils import (
    ensure_generator,
    generator_to_producer,
    run_in_background,
    suppress_exceptions,
    handle_queue_close,
)
from random import shuffle
from signal import signal, SIGINT
from types import FrameType
from functools import partial
from traceback import print_exc
from typing import TypeVar, Protocol

if TYPE_CHECKING:
    from asyncio import TaskGroup
else:
    from aiotools import TaskGroup

SploitFunction: TypeAlias = "Callable[[str], Iterable[str] | None]"
FlagQueue: TypeAlias = "Queue[tuple[str, str] | None]"
ProducerFunction: TypeAlias = "Callable[[str], None]"

T = TypeVar("T")


class Config(TypedDict):
    TEAMS: dict[str, str]
    FLAG_LIFETIME: int


DEFAULT_POOL_SIZE = 8
DEFAULT_VERBOSE_ATTACKS = 1


def farm(function: SploitFunction, /, *, strategy: FarmingStrategyFactory = Process):
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

    parser.add_argument(
        "-v",
        "--verbose-attacks",
        metavar="N",
        default=DEFAULT_VERBOSE_ATTACKS,
        type=int,
        help="Sploits' outputs and found flags will be shown for the N first attacks",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--not-per-team",
        action="store_true",
        default=False,
        help="Run a single instance of the sploit instead of an instance per team",
    )
    group.add_argument(
        "--distribute",
        nargs=2,
        metavar=("K", "N"),
        help="Divide the team list to N parts (by address hash modulo N) "
        "and run the sploits only on Kth part of it (K >= 1)",
    )
    args = vars(parser.parse_args())
    try:
        run(main(function, strategy, **args))
    except KeyboardInterrupt:
        pass


def signal_handler(queue: FlagQueue, signum: int, frame: FrameType | None) -> None:
    assert signum == SIGINT
    queue.put(None)
    raise KeyboardInterrupt()


async def main(
    function: SploitFunction,
    strategy: FarmingStrategyFactory,
    /,
    *,
    ip: str | None,
    server_url: str | None,
    alias: str | None,
    token: str | None,
    pool_size: int,
    attack_period: float | None,
    verbose_attacks: int | None,
    not_per_team: bool,
    distribute: tuple[int, int] | None,
):
    function = ensure_generator(function)
    if server_url is not None:
        if "http" not in server_url:
            server_url = f"http://{server_url}"
        if alias is None:
            alias = basename(argv[0])
        queue: FlagQueue = Queue()
        signal(SIGINT, partial(signal_handler, queue))
        async with AsyncClient() as client:
            config = await get_config(client, server_url, token)
            targets = [*config["TEAMS"].values()]
            shuffle(targets)
            if attack_period is None:
                attack_period = config["FLAG_LIFETIME"]
            async with TaskGroup() as group:
                group.create_task(
                    upload_thread(client, queue, server_url, alias, token)
                )
                group.create_task(
                    main_loop(
                        suppress_exceptions(generator_to_producer(function, queue)),
                        targets,
                        pool_size,
                        attack_period,
                        strategy,
                    )
                )
    else:
        assert ip is not None
        for flag in function(ip):
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
        flags = await run_in_background(handle_queue_close(fast_queue_read), (queue,))
        to_submit += flags
        try:
            await post_flags(client, server_url, alias, token, to_submit)
            to_submit = []
        except HTTPError:
            print_exc()


async def main_loop(
    function: ProducerFunction,
    targets: list[str],
    pool_size: int,
    attack_period: float,
    strategy: FarmingStrategyFactory,
):
    await run_all(function, targets, pool_size, attack_period, strategy)
    while True:
        for target in targets:
            timeout = attack_period / len(targets)
            start = time()
            await run_attack(function, target, timeout, strategy)
            await sleep(timeout - (time() - start))


async def run_all(
    function: ProducerFunction,
    targets: list[str],
    pool_size: int,
    attack_period: float,
    strategy: FarmingStrategyFactory,
):
    shared_list = targets.copy()
    async with TaskGroup() as group:
        for _ in range(pool_size):
            group.create_task(
                pool_tasks(
                    function, shared_list, attack_period / len(targets), strategy
                )
            )


async def pool_tasks(
    function: ProducerFunction,
    pool: list[str],
    attack_period: float,
    strategy: FarmingStrategyFactory,
):
    while pool:
        target = pool.pop()
        await run_attack(function, target, attack_period, strategy)


async def run_attack(
    function: ProducerFunction,
    target: str,
    attack_period: float,
    strategy: FarmingStrategyFactory,
):
    process = strategy(target=partial(function, target))
    process.start()
    await run_in_background(process.join, (attack_period,))
    if process.is_alive():
        print("Process timed out")
    else:
        print("Process is done")
    if isinstance(process, Process):
        process.kill()


class FarmingStrategyFactory(Protocol):
    def __call__(self, *, target: Callable[[], None]) -> FarmingStrategy:
        ...


class FarmingStrategy(Protocol):
    def start(self) -> None:
        ...

    def join(self, timeout: float, /) -> None:
        ...

    def is_alive(self) -> bool:
        ...
