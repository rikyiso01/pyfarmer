from __future__ import annotations
from collections.abc import Callable, AsyncIterable, AsyncGenerator
from contextlib import AbstractContextManager
from typing_extensions import TypeVarTuple, TypeVar, Unpack
from typing import Literal, Protocol
from multiprocessing import Pipe, get_context
from multiprocessing.connection import Connection
from threading import Thread
from sys import settrace
from types import FrameType

from pyfarmer._utils import iterate_connection, Process


TT = TypeVarTuple("TT")
T = TypeVar("T")


class FarmingStrategy(Protocol):
    def create_communication(
        self,
    ) -> tuple[AsyncIterable[str], AbstractContextManager[WriteCommunication]]:
        ...

    def create_process(
        self, function: Callable[[Unpack[TT]], None], args: tuple[Unpack[TT]], /
    ) -> Process:
        ...


class WriteCommunication(Protocol):
    def send(self, data: str, /):
        ...


class ProcessStrategy(FarmingStrategy):
    def __init__(
        self, *, start_method: Literal["spawn", "fork", "forkserver"] | None = None
    ):
        self.__context = get_context(start_method)

    def create_communication(self) -> tuple[AsyncGenerator[str, None], Connection]:
        read, write = self.__context.Pipe(False)
        return iterate_connection(read), write

    def create_process(
        self, function: Callable[..., None], args: tuple[object, ...]
    ) -> Process:
        return self.__context.Process(target=function, args=args)


class ThreadStrategy(FarmingStrategy):
    def __init__(self, *, trace_kill: bool = True):
        self.__trace_kill = trace_kill

    def create_communication(self) -> tuple[AsyncGenerator[str, None], Connection]:
        read, write = Pipe(False)
        return iterate_connection(read), write

    def create_process(
        self, function: Callable[..., None], args: tuple[object, ...]
    ) -> StoppableThread | FakeStoppableThread:
        method = StoppableThread if self.__trace_kill else FakeStoppableThread
        return method(target=function, args=args)


class FakeStoppableThread(Thread):
    @property
    def exitcode(self) -> int:
        return 0

    def kill(self):
        pass


class StoppableThread(Thread):
    def start(self) -> None:
        self.exitcode = 0
        self.__stop = False
        return super().start()

    def run(self) -> None:
        settrace(self.__trace)
        try:
            return super().run()
        except:
            self.exitcode = 1
            raise

    def __trace(self, _: FrameType, __: str, ___: object, /) -> None:
        if self.__stop:
            raise SystemExit()

    def kill(self):
        self.__stop = True
