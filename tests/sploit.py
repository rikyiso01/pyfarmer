from pyfarmer import farm, submit_flag, random_string
from string import ascii_uppercase, digits


def main(ip: str) -> None:

    print(
        "Hello! I am a little sploit. I could be written on any language, but "
        "my author loves Python. Look at my source - it is really simple. "
        "I should steal flags and print them on stdout or stderr. "
    )

    print("I need to attack a team with host: {}".format(ip))

    print("Here are some random flags for you:")

    for _ in range(3):
        flag = random_string(length=31, charset=ascii_uppercase + digits) + "="
        submit_flag(flag)


if __name__ == "__main__":
    farm(main, __file__)
