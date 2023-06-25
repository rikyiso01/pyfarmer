from __future__ import annotations
from multiprocessing import Queue
from pyfarmer._pyfarmer import FarmingStrategy
from concurrent.futures import Executor, wait
from abc import abstractmethod
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor


class SequentialStrategy(FarmingStrategy):
    def farm(self, queue: Queue[tuple[str, str]], targets: list[str]) -> None:
        for target in targets:
            self._call(queue, target)


class ExecutorStrategy(FarmingStrategy):
    @abstractmethod
    def _create_executor(self, pool_size: int, /) -> Executor:
        ...

    def farm(self, queue: Queue[tuple[str, str]], targets: list[str]) -> None:
        executor = self._create_executor(len(targets))
        wait(executor.submit(self._call, queue, target) for target in targets)


class ThreadPoolStrategy(ExecutorStrategy):
    def _create_executor(self, pool_size: int, /) -> Executor:
        return ThreadPoolExecutor(pool_size)


class ProcessPoolStrategy(ExecutorStrategy):
    def _create_executor(self, pool_size: int) -> Executor:
        return ProcessPoolExecutor(pool_size)
