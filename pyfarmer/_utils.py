from __future__ import annotations
from collections.abc import Callable
from types import TracebackType
from typing_extensions import TypeVarTuple, Unpack
from multiprocessing.connection import Connection
from string import printable
from random import choices
from asyncio import get_running_loop
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar, Type
from typing_extensions import TypeVarTuple
from asyncio import Queue, QueueEmpty


TT = TypeVarTuple("TT")
T = TypeVar("T")


async def run_in_background(
    function: Callable[[Unpack[TT]], T], args: tuple[Unpack[TT]]
) -> T:
    looper = get_running_loop()
    with ThreadPoolExecutor(1) as executor:
        return await looper.run_in_executor(executor, function, *args)


def random_string(length: int = 16, charset: str = printable) -> str:
    return "".join(choices(charset, k=length))


async def fast_queue_read(queue: Queue[T]) -> list[T]:
    result: list[T] = []
    try:
        while True:
            result.append(queue.get_nowait())
    except QueueEmpty:
        pass
    if result:
        return result
    return [await queue.get()]


class AsyncConnection:
    def __init__(self, c: Connection):
        self.__connection = c
        self.__executor: None | ThreadPoolExecutor = None

    async def read(self) -> str:
        assert self.__executor is not None
        loop = get_running_loop()
        await loop.run_in_executor(self.__executor, self.__connection.poll, None)
        return self.__connection.recv()

    def __enter__(self) -> AsyncConnection:
        self.__executor = ThreadPoolExecutor(1)
        return self

    def __exit__(
        self,
        __exc_type: Type[BaseException] | None,
        __exc_value: BaseException | None,
        __traceback: TracebackType | None,
    ) -> bool | None:
        assert self.__executor is not None
        self.__connection.close()
        self.__executor.shutdown()
