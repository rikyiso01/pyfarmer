from __future__ import annotations
from collections.abc import Callable, AsyncIterable, AsyncGenerator, Awaitable
from contextlib import AbstractContextManager, contextmanager
from typing_extensions import TypeVarTuple, TypeVar, Unpack
from typing import Literal, Protocol, Any
from multiprocessing import Pipe, get_context
from threading import Thread
from sys import settrace
from types import FrameType
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from enum import IntEnum, auto
from pyfarmer._utils import run_in_background
from logging import getLogger

LOGGER = getLogger("pyfarmer.strategies")

TT = TypeVarTuple("TT")
T = TypeVar("T")


class FarmingStrategy(Protocol):
    """The strategy to use to run the sploit"""

    def create_communication(
        self,
    ) -> tuple[AsyncIterable[str], AbstractContextManager[WriteCommunication]]:
        """Open a communication channel

        - returns: A tuple containing the readable part as an async iterable
                   and the writeable part as an abstract context manager
                   of the write communication protocol
        """
        ...

    def create_process(
        self, function: Callable[[Unpack[TT]], None], args: tuple[Unpack[TT]], /
    ) -> AbstractContextManager[Callable[[float], Awaitable[Status]]]:
        """Prepare the environment to run the sploit into

        - function: The function to run
        - args: The arguments of the function

        - returns: An abstract context manager of an async function that waits
                   for the function to terminate for an amount passed as an input
                   and returns the exit status of the function
        """
        ...


class WriteCommunication(Protocol):
    """Abstraction of the write part of a Connection object"""

    def send(self, data: str, /) -> Any:
        """Send a string to the other end of the communication

        - data: The string to send"""
        ...


class ReadCommunication(Protocol):
    """Abstraction of the read part of a Connection object"""

    def recv(self) -> object:
        """Receive an object sent by the other end of the communication

        - returns: The received object"""
        ...

    def poll(self, timeout: None, /) -> Any:
        """Blocks until some data is available to read

        - timeout: Always None"""
        ...


async def iterate_connection(
    connection: AbstractContextManager[ReadCommunication],
) -> AsyncGenerator[str, None]:
    with connection as conn:
        try:
            while True:
                await run_in_background(conn.poll, (None,))
                data: object = conn.recv()
                assert isinstance(data, str)
                yield data
        except EOFError:
            pass


class Process(Protocol):
    """Abstraction of the Python Process object"""

    def join(self, timeout: float, /) -> Any:
        """Wait until the process terminates

        - timeout: The maximum amount to wait"""
        ...

    def start(self) -> Any:
        """Start the process"""
        ...

    def kill(self) -> Any:
        """Kill the process"""
        ...

    def is_alive(self) -> bool:
        """Check if the process is alive"""
        ...

    @property
    def exitcode(self) -> int | None:
        """The exitcode of the process

        - returns: The exitcode or None if the process is still running"""
        ...


class Status(IntEnum):
    """Possible exit status of sploit"""

    OK = auto()
    """The sploit completed successfully"""
    TIMEOUT = auto()
    """The sploit timed out"""
    ERROR = auto()
    """The sploit terminated with an error"""


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


class SimpleFarmingStrategy(FarmingStrategy, ABC):
    """Abstract base class to simplify Strategy creation"""

    @abstractmethod
    def _create_communication(
        self,
    ) -> tuple[
        AbstractContextManager[ReadCommunication],
        AbstractContextManager[WriteCommunication],
    ]:
        """Open a communication channel

        - returns: A tuple containing two context managers with
                   the read and the write part of the communication channel
        """
        ...

    def create_communication(
        self,
    ) -> tuple[AsyncIterable[str], AbstractContextManager[WriteCommunication]]:
        read, write = self._create_communication()
        return iterate_connection(read), write

    def create_process(
        self, function: Callable[..., None], args: tuple[object, ...]
    ) -> AbstractContextManager[Callable[[float], Any]]:
        return stoppable_process(self._create_process(function, args))

    @abstractmethod
    def _create_process(
        self, function: Callable[[Unpack[TT]], None], args: tuple[Unpack[TT]]
    ) -> Process:
        """Prepare the environment to run the sploit into

        - function: The function to run
        - args: The arguments of the function

        - returns: The process to use to start the sploit"""
        ...


class ProcessStrategy(SimpleFarmingStrategy):
    """Strategy to use Processes"""

    def __init__(
        self, *, start_method: Literal["spawn", "fork", "forkserver"] | None = None
    ):
        """- start_method: The Process start method to use"""
        self.__context = get_context(start_method)

    def _create_communication(
        self,
    ) -> tuple[
        AbstractContextManager[ReadCommunication],
        AbstractContextManager[WriteCommunication],
    ]:
        return self.__context.Pipe(False)

    def _create_process(
        self, function: Callable[..., None], args: tuple[object, ...]
    ) -> Process:
        return self.__context.Process(target=function, args=args)


class ThreadStrategy(SimpleFarmingStrategy):
    """Strategy to use threads
    Warning: There is no safe way to kill a thread so a non terminating sploit will run forever
    """

    def __init__(self, *, trace_kill: bool = True):
        """- trace_kill: Try kill the thread using debugger features, doesn't always work"""
        self.__trace_kill = trace_kill

    def _create_communication(
        self,
    ) -> tuple[
        AbstractContextManager[ReadCommunication],
        AbstractContextManager[WriteCommunication],
    ]:
        return Pipe(False)

    def _create_process(
        self, function: Callable[..., None], args: tuple[object, ...]
    ) -> StoppableThread | FakeStoppableThread:
        method = StoppableThread if self.__trace_kill else FakeStoppableThread
        return method(target=function, args=args)


class FakeStoppableThread(Thread):
    @property
    def exitcode(self) -> int:
        return 0

    def kill(self):
        if self.is_alive():
            LOGGER.warning("Cannot kill a running thread, a new zombie is born")


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
        if self.is_alive():
            LOGGER.warning(
                "Trying to kill a running thread, a new zombie might be born"
            )
        self.__stop = True
