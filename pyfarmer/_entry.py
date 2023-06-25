from __future__ import annotations
from pyfarmer._pyfarmer import entry, SploitFunction, FarmingStrategy
from pyfarmer._strategies import ThreadPoolStrategy


def farm(function: SploitFunction | FarmingStrategy, /):
    if not isinstance(function, FarmingStrategy):
        function = ThreadPoolStrategy(function)
    entry(function)
