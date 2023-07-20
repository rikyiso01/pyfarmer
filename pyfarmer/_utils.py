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
from multiprocessing.connection import Connection
from logging import error
from typing import Protocol
from contextlib import contextmanager
from enum import IntEnum, auto

TT = TypeVarTuple("TT")
T = TypeVar("T")


async def run_in_background(
    function: Callable[[Unpack[TT]], T], args: tuple[Unpack[TT]]
) -> T:
    return await run_sync(function, *args, cancellable=True)


def random_string(length: int = 16, /, *, charset: str = printable) -> str:
    return "".join(choices(charset, k=length))


def print_exception(exception: Exception | None = None, /) -> None:
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


async def iterate_connection(connection: Connection) -> AsyncGenerator[str, None]:
    with connection:
        try:
            while True:
                await run_in_background(connection.poll, (None,))
                data: object = connection.recv()
                assert isinstance(data, str)
                yield data
        except EOFError:
            pass


class Process(Protocol):
    def join(self, timeout: float, /) -> None:
        ...

    def start(self) -> None:
        ...

    def kill(self) -> None:
        ...

    def is_alive(self) -> bool:
        ...

    @property
    def exitcode(self) -> int | None:
        ...


class Status(IntEnum):
    OK = auto()
    TIMEOUT = auto()
    ERROR = auto()


@contextmanager
def stoppable_process(process: Process):
    async def join(timeout: float) -> Status:
        await run_in_background(process.join, (timeout,))
        if process.is_alive():
            return Status.TIMEOUT
        assert process.exitcode is not None
        if process.exitcode != 0:
            return Status.ERROR
        return Status.OK

    process.start()
    try:
        yield join
    finally:
        process.kill()
