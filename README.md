# PyFarmer

## Introduction

> A farmer for your [Destructive Farm](https://github.com/DestructiveVoice/DestructiveFarm)
>
> <img src="https://i.kym-cdn.com/entries/icons/original/000/028/021/work.jpg" style="zoom: 50%;" />
>
> You can read the documentation at [rikyiso01.github.io/pyfarmer](https://rikyiso01.github.io/pyfarmer)

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
