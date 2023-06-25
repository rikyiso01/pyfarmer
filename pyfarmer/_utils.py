from __future__ import annotations
from collections.abc import Callable, Generator, Iterable
from typing_extensions import TypeVarTuple, Unpack
from functools import wraps
from multiprocessing import Process
from string import printable
from random import choices

TT = TypeVarTuple("TT")


def ensure_generator(
    function: Callable[[Unpack[TT]], Iterable[str] | None]
) -> Callable[[Unpack[TT]], Generator[str, None, None]]:
    @wraps(function)
    def result(*args: Unpack[TT]) -> Generator[str, None, None]:
        result = function(*args)
        if isinstance(result, str):
            yield result
        elif result is not None:
            yield from result

    return result


def create_subprocess(
    entry: Callable[[Unpack[TT]], None], args: tuple[Unpack[TT]]
) -> Process:
    return Process(target=entry, args=args)


def random_string(length: int = 16, charset: str = printable) -> str:
    return "".join(choices(charset, k=length))
