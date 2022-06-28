from pyfarmer import farm


def main(ip: str) -> None:
    print(ip, flush=True)


if __name__ == "__main__":
    farm(main, __file__)
