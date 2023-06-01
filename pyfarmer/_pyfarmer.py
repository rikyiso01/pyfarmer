from __future__ import annotations
from argparse import ArgumentParser
from collections.abc import Callable, Iterable
from string import printable
from typing import Any
from subprocess import call
from os.path import dirname, join, basename
from httpx import get
from random import choice
from traceback import print_exc, print_exception as print_except
from tempfile import NamedTemporaryFile
from sys import executable

ip: str = ""


def farm(function: Callable[[str], Any], file: str) -> None:
    remaining = parse_args(basename(file))
    if ip:
        function(ip)
    else:
        with NamedTemporaryFile("w", delete=False, suffix=".py") as tmp:
            with open(join(dirname(__file__), "_tmp.py")) as source:
                tmp.write(source.read().format(file))
        try:
            call(
                [
                    executable,
                    join(dirname(__file__), "_client.py"),
                    *remaining,
                    tmp.name,
                ]
            )
            exit(1)
        except KeyboardInterrupt:
            pass


def submit_flag(flag: str) -> None:
    print(flag, flush=True)


def submit_flags(flags: Iterable[str]) -> None:
    for flag in flags:
        submit_flag(flag)


def get_ids(url: str, service: str) -> list[str]:
    return get(url).json()[service][ip]


def random_string(length: int = 16, charset: str = printable) -> str:
    return "".join(choice(charset) for _ in range(length))


def print_exception(exception: Exception | None = None) -> None:
    if exception is not None:
        print_except(exception)
    else:
        print_exc()


def parse_args(default_alias: str) -> list[str]:
    global ip
    parser = ArgumentParser(
        description="Run a sploit on all teams in a loop",
    )
    parser.add_argument(
        "ip",
        help="IP address to attack",
        metavar="IP",
        nargs="?",
    )
    parser.add_argument(
        "-u",
        "--server-url",
        metavar="URL",
        help="Server URL",
    )
    parser.add_argument(
        "-a", "--alias", default=default_alias, metavar="ALIAS", help="Sploit alias"
    )
    parser.add_argument("--token", metavar="TOKEN", help="Farm authorization token")
    parser.add_argument(
        "--interpreter",
        metavar="COMMAND",
        help="Explicitly specify sploit interpreter (use on Windows, which doesn't "
        "understand shebangs)",
    )
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
        default=None,
        help="Run a single instance of the sploit instead of an instance per team",
    )
    group.add_argument(
        "--distribute",
        metavar="K/N",
        help="Divide the team list to N parts (by address hash modulo N) "
        "and run the sploits only on Kth part of it (K >= 1)",
    )

    args = vars(parser.parse_args())
    if args["ip"] is None and args["server_url"] is None:
        parser.error("one of the arguments --server-url ip is required")
    if args["ip"] is not None and args["server_url"] is not None:
        parser.error("argument ip: not allowed with argument --server-url")
    remaining: list[str] = []
    for key, value in args.items():
        if value is not None:
            if key == "ip":
                ip = value
            else:
                remaining.append(f"--{key.replace('_','-')}")
                if value != True:
                    remaining.append(str(value))
    return remaining
