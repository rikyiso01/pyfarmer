from __future__ import annotations
from string import printable
from random import choices
from typing import TypeVar
from anyio.streams.memory import MemoryObjectReceiveStream
from anyio import WouldBlock, EndOfStream
from anyio.to_thread import run_sync
from collections.abc import Callable
from typing_extensions import TypeVarTuple, Unpack
from collections.abc import AsyncGenerator
from logging import error

TT = TypeVarTuple("TT")
T = TypeVar("T")


async def run_in_background(
    function: Callable[[Unpack[TT]], T], args: tuple[Unpack[TT]]
) -> T:
    return await run_sync(function, *args, cancellable=True)


def random_string(length: int = 16, /, *, charset: str = printable) -> str:
    """Generates a random string

    - length: The length of the random string
    - charset: The characters to choose from

    - returns: The random string"""
    return "".join(choices(charset, k=length))


def print_exception(exception: Exception | None = None, /) -> None:
    """Print an exception with its traceback

    - exception: The exception to print or None if the exception should be the latest thrown
    """
    error(str(exception), exc_info=True if exception is None else exception)


async def iterate_queue(
    queue: MemoryObjectReceiveStream[T],
) -> AsyncGenerator[list[T], None]:
    with queue:
        try:
            while True:
                result: list[T] = []
                try:
                    while True:
                        result.append(queue.receive_nowait())
                except WouldBlock:
                    pass
                except EndOfStream:
                    pass
                if result:
                    yield result
                yield [await queue.receive()]
        except EndOfStream:
            pass
