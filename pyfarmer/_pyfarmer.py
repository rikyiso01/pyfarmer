from __future__ import annotations

from argparse import ArgumentParser
from asyncio import run, sleep, Task, Semaphore, CancelledError
from collections import Counter
from collections.abc import Callable, Generator, AsyncIterable
from os.path import basename
from random import shuffle
from sys import argv
from time import time
from typing import TypedDict, cast
from urllib.parse import urljoin
from contextlib import AbstractContextManager
from functools import partial
from math import ceil

from httpx import AsyncClient, HTTPError
from typing_extensions import TypeAlias
from anyio import create_memory_object_stream
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from logging import basicConfig, INFO, getLogger

from pyfarmer._strategies import (
    FarmingStrategy,
    ProcessStrategy,
    WriteCommunication,
    Status,
)
from pyfarmer._utils import iterate_queue
from enum import Enum
from aiotools import TaskGroup

RealSploitFunction: TypeAlias = "Callable[[str], object]"
SploitFunction: TypeAlias = "Callable[[str], Generator[str, None, None]]"
"""Type alias of a function that given an ip returns the flags"""


class Config(TypedDict):
    TEAMS: dict[str, str]
    FLAG_LIFETIME: int


class Mode(Enum):
    """Phases to use for the pyfarmer"""

    ALL = "all"
    """Value to use to indicate all phases"""
    SPRINT = "sprint"
    """First phase where all ip are attacked as fast as possible"""
    SLOW = "slow"
    """Second phase where the attacks are cycled in the most resource efficient way"""


DEFAULT_POOL_SIZE = 8
DEFAULT_VERBOSE_ATTACKS = 1
FLAG_BUFFER_SIZE = 1024
MAX_FLAGS_PER_PROCESS = 250
LOGGER = getLogger("pyfarmer")


def farm(function: SploitFunction, /, *, strategy: FarmingStrategy = ProcessStrategy()):
    """Starts the pyfarmer.
    It will start an event loop.
    If an event loop is already running in the current thread use async_farm

    - function: The function containing the sploit to run
    - strategy: The farming strategy to use"""
    parser = ArgumentParser(
        prog=f"python {argv[0]}",
        description="Run a sploit on all teams in a loop",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "ip", metavar="IP", nargs="?", help="IP address to test the sploit on"
    )
    group.add_argument(
        "-u", "--server-url", metavar="URL", help="Destructive Farm Server URL"
    )
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
        "--debug",
        "-d",
        default=False,
        action="store_true",
        help="Add more verbose logs",
    )
    parser.add_argument(
        "--mode",
        "-m",
        choices=[m.value for m in Mode],
        default=Mode.ALL.value,
        help="Skip some phases in the scheduler algorithm",
    )
    parser.add_argument(
        "--cycles", type=int, help="Limit the number of cycles of the slow mode"
    )
    parser.add_argument("--timeout", type=float, help="Manually set the sploit timeout")
    args = vars(parser.parse_args())
    args["mode"] = Mode(args["mode"])
    if args["debug"]:
        basicConfig(level=INFO)
    else:
        basicConfig()
    del args["debug"]
    try:
        run(main(function, strategy, **args))
    except KeyboardInterrupt:
        pass


async def async_farm(
    function: SploitFunction,
    strategy: FarmingStrategy,
    /,
    *,
    server_url: str,
    alias: str,
    token: str | None = None,
    pool_size: int = DEFAULT_POOL_SIZE,
    timeout: float | None = None,
    attack_period: float | None = None,
    mode: Mode = Mode.ALL,
    cycles: int | None = None,
):
    """Start the pyfarmer using an external event loop

    - function: The function containing the sploit to run
    - strategy: The farming strategy to use
    - server_url: The destructive farm use to use
    - alias: The sploit alias name
    - token: The api token to use when connecting to the destructive farm, None to not use any token
    - pool_size: The maximum number of parallel sploit to run
    - attack_period: How often to rerun an attack against the same ip, None to use the default
    - timeout: The sploit timeout, None to use the default
    - mode: Which steps to perform
    - cycles: Number of cycles of slow mode before exiting, None for infinity"""
    await main(
        function,
        strategy,
        ip=None,
        server_url=server_url,
        alias=alias,
        token=token,
        pool_size=pool_size,
        attack_period=attack_period,
        timeout=timeout,
        mode=mode,
        cycles=cycles,
    )


async def main(
    function: RealSploitFunction,
    strategy: FarmingStrategy,
    /,
    *,
    ip: str | None,
    server_url: str | None,
    alias: str | None,
    token: str | None,
    pool_size: int,
    attack_period: float | None,
    timeout: float | None,
    mode: Mode,
    cycles: int | None = None,
):
    if server_url is not None:
        if "http" not in server_url:
            server_url = f"http://{server_url}"
        if alias is None:
            alias = basename(argv[0])
        send_stream: MemoryObjectSendStream[tuple[str, str]]
        receive_stream: MemoryObjectReceiveStream[tuple[str, str]]
        send_stream, receive_stream = create_memory_object_stream(FLAG_BUFFER_SIZE)
        async with AsyncClient() as client:
            config = await get_config(client, server_url=server_url, token=token)
            targets = [*config["TEAMS"].values()]
            shuffle(targets)
            slots = ceil(len(targets) / pool_size)
            if attack_period is None:
                attack_period = config["FLAG_LIFETIME"]
                optimal_timeout = attack_period / (slots + 1)
                attack_period -= optimal_timeout
            if timeout is None:
                timeout = attack_period / slots
            print("Config:")
            print("\t#targets:", len(targets))
            print("\tflag_lifetime:", attack_period)
            print("\tsploit_timeout:", timeout)
            print("\talias:", alias)
            print("\tpool_size:", pool_size)
            print("Starting first sprint")
            async with TaskGroup() as group:
                group.create_task(
                    upload_thread(
                        client,
                        iterate_queue(receive_stream),
                        server_url=server_url,
                        alias=alias,
                        token=token,
                    )
                )
                group.create_task(
                    main_loop(
                        function,
                        send_stream,
                        targets,
                        pool_size=pool_size,
                        attack_period=attack_period,
                        timeout=timeout,
                        strategy=strategy,
                        mode=mode,
                        cycles=cycles,
                    )
                )
    else:
        assert ip is not None
        for flag in check_sploit(function(ip)):
            print(flag)


async def get_config(
    client: AsyncClient, /, *, server_url: str, token: str | None
) -> Config:
    response = await client.get(
        urljoin(server_url, "/api/get_config"),
        headers={"X-Token": token} if token is not None else None,
    )
    if response.status_code != 200:
        LOGGER.error(
            f"Farm get_config responded with non 200 status code: {response.status_code} {response.text}"
        )
    response.raise_for_status()
    return response.json()


async def upload_thread(
    client: AsyncClient,
    receive_stream: AsyncIterable[list[tuple[str, str]]],
    /,
    *,
    server_url: str,
    alias: str,
    token: str | None,
):
    to_submit: list[tuple[str, str]] = []
    async for flags in receive_stream:
        to_submit += flags
        try:
            await post_flags(
                client, to_submit, server_url=server_url, alias=alias, token=token
            )
            to_submit = []
        except HTTPError:
            LOGGER.error("Error submitting flags", exc_info=True)


async def post_flags(
    client: AsyncClient,
    flags: list[tuple[str, str]],
    /,
    *,
    server_url: str,
    alias: str,
    token: str | None,
):
    LOGGER.info(f"Submitting {len(flags)} flags")
    data = [{"flag": flag, "sploit": alias, "team": team} for team, flag in flags]
    response = await client.post(
        urljoin(server_url, "/api/post_flags"),
        json=data,
        headers={"X-Token": token} if token is not None else None,
    )
    if response.status_code != 200:
        LOGGER.error(
            f"Farm post_flags responded with non 200 status code: {response.status_code} {response.text}"
        )
    response.raise_for_status()


async def main_loop(
    function: RealSploitFunction,
    queue: MemoryObjectSendStream[tuple[str, str]],
    targets: list[str],
    /,
    *,
    pool_size: int,
    attack_period: float,
    timeout: float,
    strategy: FarmingStrategy,
    mode: Mode,
    cycles: int | None = None,
):
    with queue:
        if mode != Mode.SLOW:
            await run_all(
                function,
                queue,
                targets,
                timeout=timeout,
                pool_size=pool_size,
                strategy=strategy,
            )
        if mode == Mode.ALL:
            print("Entering slow mode")
        if mode != Mode.SPRINT:
            LOGGER.info(f"Average sleep time: {attack_period / len(targets)}")
            counter = 0
            start_time = time()
            while True:
                target_time = start_time + attack_period * (counter + 1)
                if cycles is not None and counter >= cycles:
                    break
                print("Starting cycle", counter + 1)
                await slow_mode(
                    function,
                    queue,
                    targets,
                    timeout=timeout,
                    strategy=strategy,
                    target_time=target_time,
                )
                counter += 1


async def slow_mode(
    function: RealSploitFunction,
    queue: MemoryObjectSendStream[tuple[str, str]],
    targets: list[str],
    /,
    *,
    timeout: float,
    strategy: FarmingStrategy,
    target_time: float,
) -> None:
    LOGGER.info(f"Time allocated for slow mode cycle: {target_time-time()}")
    counter: Counter[Status] = Counter()
    async with TaskGroup() as group:
        for i, target in enumerate(targets):
            print(f"Starting attack {i+1}/{len(targets)}")

            def callback(i: int, task: Task[tuple[Status, int]]):
                try:
                    status, count = task.result()
                    print(
                        f"Attack {i+1}/{len(targets)} result: {status.name}, submitted {count} flags"
                    )
                    counter[status] += 1
                except CancelledError:
                    pass
                except:
                    LOGGER.warning(
                        "Exception in print_attack_result callback", exc_info=True
                    )

            task = group.create_task(
                run_attack(function, queue, target, timeout=timeout, strategy=strategy)
            )
            task.add_done_callback(partial(callback, i))
            sleep_time = (target_time - time()) / (len(targets) - i)
            LOGGER.info(f"Entering sleep for {sleep_time} seconds")
            await sleep(sleep_time)
    print("Slow mode cycle completed")
    print_stats(counter)


def print_stats(stats: Counter[Status]):
    total = sum(stats.values())
    print("Stats:")
    print(f"\tOK: {stats[Status.OK]}/{total}")
    print(f"\tERROR: {stats[Status.ERROR]}/{total}")
    print(f"\tTIMEOUT: {stats[Status.TIMEOUT]}/{total}")


async def run_all(
    function: RealSploitFunction,
    queue: MemoryObjectSendStream[tuple[str, str]],
    targets: list[str],
    /,
    *,
    timeout: float,
    pool_size: int,
    strategy: FarmingStrategy,
) -> None:
    def print_remaining(task: Task[tuple[Status, int]]):
        try:
            status, count = task.result()
            stats[status] += 1
            done = sum(stats.values())
            print(
                f"Submitted {count} flags, remaining targets in the sprint:",
                len(targets) - done,
            )
        except CancelledError:
            pass
        except:
            LOGGER.warning("Exception in print_remaining callback", exc_info=True)

    stats: Counter[Status] = Counter()
    semaphore = Semaphore(pool_size)
    async with TaskGroup() as group:
        for target in targets:
            task = group.create_task(
                schedule_attack(
                    function,
                    queue,
                    semaphore,
                    target,
                    timeout=timeout,
                    strategy=strategy,
                )
            )
            task.add_done_callback(print_remaining)
    print(f"Sprint completed")
    print_stats(stats)


async def schedule_attack(
    function: RealSploitFunction,
    queue: MemoryObjectSendStream[tuple[str, str]],
    semaphore: Semaphore,
    target: str,
    /,
    *,
    timeout: float,
    strategy: FarmingStrategy,
):
    async with semaphore:
        return await run_attack(
            function, queue, target, timeout=timeout, strategy=strategy
        )


async def run_attack(
    function: RealSploitFunction,
    queue: MemoryObjectSendStream[tuple[str, str]],
    target: str,
    /,
    *,
    timeout: float,
    strategy: FarmingStrategy,
) -> tuple[Status, int]:
    read, write = strategy.create_communication()
    async with TaskGroup() as group:
        status = group.create_task(
            attack_process(function, write, target, timeout=timeout, strategy=strategy)
        )
        count = group.create_task(read_connection(read, queue.clone(), target))
    return await status, await count


async def read_connection(
    connection: AsyncIterable[str],
    queue: MemoryObjectSendStream[tuple[str, str]],
    target: str,
) -> int:
    with queue:
        counter = 0
        async for data in connection:
            assert isinstance(data, str)
            await queue.send((target, data))
            counter += 1
        return counter


async def attack_process(
    function: RealSploitFunction,
    write: AbstractContextManager[WriteCommunication],
    target: str,
    /,
    *,
    timeout: float,
    strategy: FarmingStrategy,
) -> Status:
    with write as w:
        base_process = strategy.create_process(process_main, (function, w, target))
        with base_process as process:
            return await process(timeout)


def process_main(
    function: RealSploitFunction,
    connection: WriteCommunication,
    target: str,
) -> None:
    try:
        for i, flag in enumerate(check_sploit(function(target))):
            if i >= MAX_FLAGS_PER_PROCESS:
                LOGGER.error("Attack sent too many flags")
                exit(1)
            connection.send(flag)
    except KeyboardInterrupt:
        pass
    except SystemExit as e:
        exit(e.code)
    except:
        LOGGER.error("Subprocess terminated with an error", exc_info=True)
        exit(1)


def check_sploit(iterator: object) -> Generator[str, None, None]:
    if not isinstance(iterator, Generator):
        LOGGER.error(
            "The sploit doesn't have any yield, you must use the yield keyword to submit flags"
        )
        exit(1)
    iterator = cast("Generator[object, object, object]", iterator)
    for flag in iterator:
        if not isinstance(flag, str):
            LOGGER.error(f"The flag must be a str, found {type(flag)}")
            exit(1)
        yield flag
