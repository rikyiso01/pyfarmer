from __future__ import annotations
from argparse import ArgumentParser
from httpx import get, post
from urllib.parse import urljoin
from sys import argv
from os.path import basename
from collections.abc import Callable, Generator, Iterable
from abc import ABC, abstractmethod
from multiprocessing import Queue
from time import time
from queue import Empty
from typing import TypedDict
from typing_extensions import TypeAlias
from pyfarmer._utils import ensure_generator, create_subprocess
from traceback import print_exc

SploitFunction: TypeAlias = "Callable[[str], Iterable[str] | None]"


class Config(TypedDict):
    TEAMS: dict[str, str]
    FLAG_LIFETIME: int


def entry(strategy: FarmingStrategy):
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
        type=int,
        help="Sploits' outputs and found flags will be shown for the N first attacks",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--not-per-team",
        action="store_true",
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
    main(strategy, **{key: value for key, value in args.items() if value is not None})


def main(
    strategy: FarmingStrategy,
    ip: str | None = None,
    server_url: str | None = None,
    alias: str | None = None,
    token: str | None = None,
    pool_size: int = 8,
    attack_period: float | None = None,
    verbose_attacks: int | None = 1,
    not_per_team: bool = False,
    distribute: tuple[int, int] | None = None,
):
    if server_url is not None:
        if "http" not in server_url:
            server_url = f"http://{server_url}"
        config = get_config(server_url, token)
        loop(
            strategy,
            server_url,
            token,
            [*config["TEAMS"].values()],
            strategy.function.__name__ if alias is None else alias,
            pool_size,
            config["FLAG_LIFETIME"] if attack_period is None else attack_period,
        )
    else:
        assert ip is not None
        for flag in strategy.function(ip):
            print(flag)


def get_config(server_url: str, token: str | None) -> Config:
    response = get(
        urljoin(server_url, "/api/get_config"),
        headers={"X-Token": token} if token is not None else None,
    )
    if response.status_code != 200:
        raise Exception()
    return response.json()


def post_flags(
    server_url: str, alias: str | None, token: str | None, flags: list[tuple[str, str]]
):
    if alias is None:
        alias = basename(argv[0])
    data = [{"flag": flag, "sploit": alias, "team": team} for team, flag in flags]
    response = post(
        urljoin(server_url, "/api/post_flags"),
        json=data,
        headers={"X-Token": token} if token is not None else None,
    )
    if response.status_code != 200:
        raise Exception()


def loop(
    strategy: FarmingStrategy,
    server_url: str | None,
    token: str | None,
    targets: list[str],
    alias: str,
    pool_size: int,
    attack_period: float,
) -> None:
    while True:
        attack_round(
            strategy, server_url, token, targets, alias, pool_size, attack_period
        )
        if server_url is None:
            break


def attack_round(
    strategy: FarmingStrategy,
    server_url: str | None,
    token: str | None,
    targets: list[str],
    alias: str,
    pool_size: int,
    attack_period: float,
) -> None:
    flags = run_attack_round(strategy, targets, pool_size, attack_period)
    if server_url is None:
        for flag in flags:
            print(flag)
    else:
        for flag in flags:
            post_flags(server_url, alias, token, [flag])


def run_attack_round(
    strategy: FarmingStrategy, targets: list[str], pool_size: int, attack_period: float
) -> Generator[tuple[str, str], None, None]:
    rounds = len(targets) / pool_size
    for i in range(0, len(targets), pool_size):
        yield from run_strategy(
            strategy, targets[i : i + pool_size], attack_period / rounds
        )


def run_strategy(
    strategy: FarmingStrategy,
    targets: list[str],
    attack_period: float,
) -> Generator[tuple[str, str], None, None]:
    queue: Queue[tuple[str, str]] = Queue()
    process = create_subprocess(strategy.farm, (queue, targets))
    process.start()
    try:
        start = time()
        while True:
            remaining = attack_period - (time() - start)
            if remaining <= 0:
                while True:
                    yield queue.get_nowait()
            yield queue.get(timeout=remaining)
    except Empty:
        process.kill()


class FarmingStrategy(ABC):
    @abstractmethod
    def farm(self, queue: Queue[tuple[str, str]], targets: list[str], /) -> None:
        ...

    def __init__(
        self,
        function: SploitFunction,
    ):
        self._function = ensure_generator(function)

    def _call(self, queue: Queue[tuple[str, str]], target: str, /) -> None:
        try:
            for flag in self._function(target):
                queue.put((target, flag))
        except:
            print_exc()

    @property
    def function(self):
        return self._function
