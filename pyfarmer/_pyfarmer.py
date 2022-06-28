from collections.abc import Callable
from string import printable
from typing import Any
from subprocess import run
from sys import argv
from os.path import dirname, join
from requests import get
from random import choice
from traceback import print_exc, print_exception as print_except

IP = argv[1] if len(argv) > 1 else None


def farm(function: Callable[[str], Any], file: str) -> None:
    if len(argv) == 1:
        exit(run([join(dirname(__file__), "_client.py"), *argv[1:]]).returncode)
    elif len(argv) == 2 and argv[1][0].isdigit():
        assert IP is not None
        function(IP)
    else:
        exit(run([join(dirname(__file__), "_client.py"), file, *argv[1:]]).returncode)


def submit_flag(flag: str) -> None:
    print(flag, flush=True)


def get_ids(url: str, service: str) -> list[str]:
    return get(url).json()[service][IP]


def random_string(length: int = 16, charset: str = printable) -> str:
    return "".join(choice(charset) for _ in range(length))


def print_exception(exception: Exception | None = None) -> None:
    if exception is not None:
        print_except(exception)
    else:
        print_exc()
