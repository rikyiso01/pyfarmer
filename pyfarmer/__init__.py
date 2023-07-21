"""
# PyFarmer

## Introduction

> A farmer for your [Destructive Farm](https://github.com/DestructiveVoice/DestructiveFarm)
>
> <img src="https://i.kym-cdn.com/entries/icons/original/000/028/021/work.jpg" style="zoom: 50%;" />

## Code Samples

> ```python
> from httpx import post
> from pyfarmer import farm, print_exception
>
>
> def main(ip: str):
>     for flag_id in ["a", "b", "c"]:
>         try:
>             r = post(
>                 f"http://{ip}:5000/api/products/{flag_id}/download?a=/api/register"
>             )
>             flag = r.text
>             yield flag
>         except:
>             print_exception()
>
>
> if __name__ == "__main__":
>     farm(main)
> ```

## Installation

> Install locally with:
>
> ```bash
> pip install pyfarmer
> ```

"""

from pyfarmer._pyfarmer import (
    farm,
    async_farm,
    SploitFunction,
    Mode,
)
from pyfarmer._strategies import (
    ProcessStrategy,
    ThreadStrategy,
    FarmingStrategy,
    WriteCommunication,
    Process,
    Status,
    SimpleFarmingStrategy,
    ReadCommunication,
)
from pyfarmer._utils import random_string, print_exception

__all__ = [
    "farm",
    "async_farm",
    "SploitFunction",
    "Mode",
    "ProcessStrategy",
    "ThreadStrategy",
    "FarmingStrategy",
    "WriteCommunication",
    "random_string",
    "print_exception",
    "Process",
    "Status",
    "SimpleFarmingStrategy",
    "ReadCommunication",
]
