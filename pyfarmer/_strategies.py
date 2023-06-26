from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing_extensions import TypeVarTuple, TypeVar
from typing import Literal, Protocol
from multiprocessing import Pipe, get_context
from multiprocessing.connection import Connection
from types import FrameType
from threading import Thread
from sys import settrace


TT = TypeVarTuple("TT")
T = TypeVar("T")


class FarmingStrategy(ABC):
    @abstractmethod
    def create(
        self, function: Callable[..., None], args: tuple[object, ...], /
    ) -> FarmingTool:
        ...

    def after_start(self, connection: Connection, /) -> None:
        pass

    @abstractmethod
    def create_communication(self) -> tuple[Connection, Connection]:
        ...

    def after_stop(self, connection: Connection, /) -> None:
        ...


class FarmingTool(Protocol):
    def start(self) -> None:
        ...

    def join(self, timeout: float, /) -> None:
        ...

    def is_alive(self) -> bool:
        ...

    @property
    def exitcode(self) -> int | None:
        ...

    def kill(self) -> None:
        ...


class ProcessStrategy(FarmingStrategy):
    def __init__(
        self, spawn_type: Literal["spawn", "fork", "forkserver"] | None = None, /
    ):
        self.__context = get_context(spawn_type)

    def create(
        self, function: Callable[..., None], args: tuple[object, ...]
    ) -> FarmingTool:
        return self.__context.Process(target=function, args=args)

    def after_start(self, connection: Connection) -> None:
        connection.close()

    def create_communication(self) -> tuple[Connection, Connection]:
        return self.__context.Pipe(False)


class ThreadStrategy(FarmingStrategy):
    def __init__(self, trace_kill: bool = True):
        self.__trace_kill = trace_kill

    def create(
        self, function: Callable[..., None], args: tuple[object, ...]
    ) -> FarmingTool:
        method = StoppableThread if self.__trace_kill else FakeStoppableThread
        return method(target=function, args=args)

    def create_communication(self) -> tuple[Connection, Connection]:
        return Pipe(False)

    def after_stop(self, connection: Connection) -> None:
        connection.close()


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

    def __trace(self, a: FrameType, b: str, c: object) -> None:
        if self.__stop:
            raise SystemExit()

    def kill(self):
        self.__stop = True
