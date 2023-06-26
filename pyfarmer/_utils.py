from __future__ import annotations
from collections.abc import Callable, Generator, Iterable
from typing_extensions import TypeVarTuple, Unpack
from functools import wraps
from multiprocessing import Process, Queue
from string import printable
from random import choices
from queue import Empty
from asyncio import get_running_loop
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar
from typing_extensions import TypeGuard, TypeVarTuple


class QueueClosedError(Exception):
    ...


TT = TypeVarTuple("TT")
T = TypeVar("T")

C = TypeVar("C", bound=Callable[..., object])


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


async def run_in_background(
    function: Callable[[Unpack[TT]], T], args: tuple[Unpack[TT]]
) -> T:
    looper = get_running_loop()
    with ThreadPoolExecutor(1) as executor:
        return await looper.run_in_executor(executor, function, *args)


def random_string(length: int = 16, charset: str = printable) -> str:
    return "".join(choices(charset, k=length))


def generator_to_producer(
    function: Callable[[Unpack[TT]], Iterable[T]],
    queue: Queue[tuple[Unpack[TT], T] | None],
) -> Callable[[Unpack[TT]], None]:
    @wraps(function)
    def result(*args: Unpack[TT]) -> None:
        for elem in function(*args):
            queue.put((*args, elem))

    return result


def is_list_not_null(l: list[T | None]) -> TypeGuard[list[T]]:
    for elem in l:
        if elem is None:
            return False
    return True


def handle_queue_close(
    function: Callable[[Queue[T | None]], list[T | None]]
) -> Callable[[Queue[T | None]], list[T]]:
    @wraps(function)
    def result(queue: Queue[T | None]) -> list[T]:
        elements = function(queue)
        if is_list_not_null(elements):
            return elements
        raise QueueClosedError()

    return result


def fast_queue_read(queue: Queue[T]) -> list[T]:
    result: list[T] = []
    try:
        while True:
            result.append(queue.get_nowait())
    except Empty:
        if result:
            return result
        return [queue.get()]


def suppress_exceptions(function: C) -> C:
    @wraps(function)
    def result(*args: object, **kwargs: object) -> object:
        try:
            return function(*args, **kwargs)
        except KeyboardInterrupt:
            pass

    return result  # type: ignore
