#!/usr/bin/env python3

from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace
from binascii import crc32
from itertools import count
from json import dumps, loads
from logging import DEBUG, basicConfig, critical, error, info, warning
from random import choice
from re import fullmatch, compile, Pattern
from os.path import basename, isfile, abspath
from subprocess import PIPE, STDOUT, Popen, TimeoutExpired
from threading import Event, RLock, Thread
from time import time
from os import environ
from typing import IO, Any
from collections.abc import Generator, Iterable
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from math import ceil
from urllib.parse import urljoin
from urllib.request import Request, urlopen


HEADER = r"""
 ____            _                   _   _             _____
|  _ \  ___  ___| |_ _ __ _   _  ___| |_(_)_   _____  |  ___|_ _ _ __ _ __ ___
| | | |/ _ \/ __| __| '__| | | |/ __| __| \ \ / / _ \ | |_ / _` | '__| '_ ` _ `
| |_| |  __/\__ \ |_| |  | |_| | (__| |_| |\ V /  __/ |  _| (_| | |  | | | | |
|____/ \___||___/\__|_|   \__,_|\___|\__|_| \_/ \___| |_|  \__,_|_|  |_| |_| |_

Note that this software is highly destructive. Keep it away from children.
"""[
    1:
]


class Style(Enum):
    """
    Bash escape sequences, see:
    https://misc.flogisoft.com/bash/tip_colors_and_formatting
    """

    BOLD = 1

    FG_BLACK = 30
    FG_RED = 31
    FG_GREEN = 32
    FG_YELLOW = 33
    FG_BLUE = 34
    FG_MAGENTA = 35
    FG_CYAN = 36
    FG_LIGHT_GRAY = 37


BRIGHT_COLORS = [
    Style.FG_RED,
    Style.FG_GREEN,
    Style.FG_BLUE,
    Style.FG_MAGENTA,
    Style.FG_CYAN,
]


def highlight(text: str, style: list[Style] | None = None) -> str:
    if style is None:
        style = [Style.BOLD, choice(BRIGHT_COLORS)]
    return (
        "\033[{}m".format(";".join(str(item.value) for item in style))
        + text
        + "\033[0m"
    )


log_format = "%(asctime)s {} %(message)s".format(
    highlight("%(levelname)s", [Style.FG_YELLOW])
)
basicConfig(format=log_format, datefmt="%H:%M:%S", level=DEBUG)


def parse_args():
    parser = ArgumentParser(
        description="Run a sploit on all teams in a loop",
        formatter_class=ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "sploit",
        help="Sploit executable (should take a victim's host as the first argument)",
    )
    parser.add_argument(
        "-u",
        "--server-url",
        metavar="URL",
        default="http://farm.kolambda.com:5000",
        help="Server URL",
    )
    parser.add_argument(
        "-a", "--alias", metavar="ALIAS", default=None, help="Sploit alias"
    )
    parser.add_argument("--token", metavar="TOKEN", help="Farm authorization token")
    parser.add_argument(
        "--interpreter",
        metavar="COMMAND",
        help="Explicitly specify sploit interpreter (use on Windows, which doesn't "
        "understand shebangs)",
    )

    parser.add_argument(
        "--pool-size",
        metavar="N",
        type=int,
        default=50,
        help="Maximal number of concurrent sploit instances. "
        "Too little value will make time limits for sploits smaller, "
        "too big will eat all RAM on your computer",
    )
    parser.add_argument(
        "--attack-period",
        metavar="N",
        type=float,
        default=120,
        help="Rerun the sploit on all teams each N seconds "
        "Too little value will make time limits for sploits smaller, "
        "too big will miss flags from some rounds",
    )

    parser.add_argument(
        "-v",
        "--verbose-attacks",
        metavar="N",
        type=int,
        default=1,
        help="Sploits' outputs and found flags will be shown for the N first attacks",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--not-per-team",
        action="store_true",
        help="Run a single instance of the sploit instead of an instance per team",
    )
    group.add_argument(
        "--distribute",
        metavar="K/N",
        help="Divide the team list to N parts (by address hash modulo N) "
        "and run the sploits only on Kth part of it (K >= 1)",
    )

    return parser.parse_args()


def fix_args(args: Namespace):
    check_sploit(args)

    if "://" not in args.server_url:
        args.server_url = "http://" + args.server_url

    if args.distribute is not None:
        valid = False
        match = fullmatch(r"(\d+)/(\d+)", args.distribute)
        if match is not None:
            k, n = (int(match.group(1)), int(match.group(2)))
            if n >= 2 and 1 <= k <= n:
                args.distribute = k, n
                valid = True

        if not valid:
            raise ValueError(
                "Wrong syntax for --distribute, use --distribute K/N (N >= 2, 1 <= K <= N)"
            )


def check_sploit(args: Namespace) -> None:
    path: str = args.sploit
    if not isfile(path):
        raise ValueError("No such file: {}".format(path))


class APIException(Exception):
    pass


SERVER_TIMEOUT = 5


def get_config(args: Namespace) -> Any:
    req = Request(urljoin(args.server_url, "/api/get_config"))
    if args.token is not None:
        req.add_header("X-Token", args.token)
    with urlopen(req, timeout=SERVER_TIMEOUT) as conn:
        if conn.status != 200:
            raise APIException(conn.read())

        return loads(conn.read().decode())


def post_flags(args: Namespace, flags: list[dict[str, str]]) -> None:
    if args.alias is not None:
        sploit_name = args.alias
    else:
        sploit_name = basename(args.sploit)

    data = [
        {"flag": item["flag"], "sploit": sploit_name, "team": item["team"]}
        for item in flags
    ]

    req = Request(urljoin(args.server_url, "/api/post_flags"))
    req.add_header("Content-Type", "application/json")
    if args.token is not None:
        req.add_header("X-Token", args.token)
    with urlopen(req, data=dumps(data).encode(), timeout=SERVER_TIMEOUT) as conn:
        if conn.status != 200:
            raise APIException(conn.read())


exit_event = Event()


def once_in_a_period(period: float) -> Generator[int, None, None]:
    for iter_no in count(1):
        start_time = time()
        yield iter_no

        time_spent = time() - start_time
        if period > time_spent:
            exit_event.wait(period - time_spent)
        if exit_event.is_set():
            break


class FlagStorage:
    """
    Thread-safe storage comprised of a set and a post queue.

    Any number of threads may call add(), but only one "consumer thread"
    may call pick_flags() and mark_as_sent().
    """

    def __init__(self):
        self._flags_seen: set[str] = set()
        self._queue: list[dict[str, str]] = []
        self._lock = RLock()

    def add(self, flags: Iterable[str], team_name: str):
        with self._lock:
            for item in flags:
                if item not in self._flags_seen:
                    self._flags_seen.add(item)
                    self._queue.append({"flag": item, "team": team_name})

    def pick_flags(self) -> list[dict[str, str]]:
        with self._lock:
            return self._queue[:]

    def mark_as_sent(self, count: int) -> None:
        with self._lock:
            self._queue = self._queue[count:]

    @property
    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)


flag_storage = FlagStorage()


POST_PERIOD = 5


def run_post_loop(args: Namespace) -> None:
    try:
        for _ in once_in_a_period(POST_PERIOD):
            flags_to_post = flag_storage.pick_flags()

            if flags_to_post:
                try:
                    post_flags(args, flags_to_post)

                    flag_storage.mark_as_sent(len(flags_to_post))
                    info(
                        "{} flags posted to the server ({} in the queue)".format(
                            len(flags_to_post), flag_storage.queue_size
                        )
                    )
                except Exception as e:
                    error("Can't post flags to the server: {}".format(repr(e)))
                    info("The flags will be posted next time")
    except Exception as e:
        critical("Posting loop died: {}".format(repr(e)))
        shutdown()


display_output_lock = RLock()


def display_sploit_output(team_name: str, output_lines: list[str]) -> None:
    if not output_lines:
        info("{}: No output from the sploit".format(team_name))
        return

    prefix = highlight(team_name + ": ")
    with display_output_lock:
        print("\n" + "\n".join(prefix + line.rstrip() for line in output_lines) + "\n")


def process_sploit_output(
    stream: IO[bytes],
    args: Namespace,
    team_name: str,
    flag_format: Pattern[str],
    attack_no: int,
) -> None:
    try:
        output_lines: list[str] = []
        instance_flags: set[str] = set()

        while True:
            line = stream.readline()
            if not line:
                break
            line = line.decode(errors="replace")
            output_lines.append(line)

            line_flags = set(flag_format.findall(line))
            if line_flags:
                flag_storage.add(line_flags, team_name)
                instance_flags |= line_flags

        if attack_no <= args.verbose_attacks and not exit_event.is_set():
            # We don't want to spam the terminal on KeyboardInterrupt

            display_sploit_output(team_name, output_lines)
            if instance_flags:
                info(
                    'Got {} flags from "{}": {}'.format(
                        len(instance_flags), team_name, instance_flags
                    )
                )
    except Exception as e:
        error("Failed to process sploit output: {}".format(repr(e)))


class InstanceStorage:
    """
    Storage comprised of a dictionary of all running sploit instances and some statistics.

    Always acquire instance_lock before using this class. Do not release the lock
    between actual spawning/killing a process and calling register_start()/register_stop().
    """

    def __init__(self):
        self._counter = 0
        self.instances: dict[int, Popen[bytes]] = {}

        self.n_completed = 0
        self.n_killed = 0

    def register_start(self, process: Popen[bytes]):
        instance_id = self._counter
        self.instances[instance_id] = process
        self._counter += 1
        return instance_id

    def register_stop(self, instance_id: int, was_killed: bool):
        del self.instances[instance_id]

        self.n_completed += 1
        self.n_killed += was_killed


instance_storage = InstanceStorage()
instance_lock = RLock()


def launch_sploit(
    args: Namespace,
    team_name: str,
    team_addr: str,
    attack_no: int,
    flag_format: Pattern[str],
):
    # For sploits written in Python, this env variable forces the interpreter to flush
    # stdout and stderr after each newline. Note that this is not default behavior
    # if the sploit's output is redirected to a pipe.
    env = environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    command = ["/usr/bin/env", "python3", abspath(args.sploit)]
    if args.interpreter is not None:
        command = [args.interpreter] + command
    if team_addr is not None:
        command.append(team_addr)
    proc = Popen(
        command,
        stdout=PIPE,
        stderr=STDOUT,
        bufsize=1,
        env=env,
    )

    out = proc.stdout
    assert out is not None

    Thread(
        target=lambda: process_sploit_output(
            out, args, team_name, flag_format, attack_no
        )
    ).start()

    return proc, instance_storage.register_start(proc)


def run_sploit(
    args: Namespace,
    team_name: str,
    team_addr: str,
    attack_no: int,
    max_runtime: float,
    flag_format: Pattern[str],
):
    try:
        with instance_lock:
            if exit_event.is_set():
                return

            proc, instance_id = launch_sploit(
                args, team_name, team_addr, attack_no, flag_format
            )
    except Exception as e:
        if isinstance(e, FileNotFoundError):
            error("Sploit file or the interpreter for it not found: {}".format(repr(e)))
            error(
                "Check presence of the sploit file and the shebang (use {} for compatibility)".format(
                    highlight("#!/usr/bin/env ...", [Style.FG_GREEN])
                )
            )
        else:
            error("Failed to run sploit: {}".format(repr(e)))

        if attack_no == 1:
            shutdown()
        exit(1)

    try:
        try:
            proc.wait(timeout=max_runtime)
            need_kill = False
        except TimeoutExpired:
            need_kill = True
            if attack_no <= args.verbose_attacks:
                warning(
                    'Sploit for "{}" ({}) ran out of time'.format(team_name, team_addr)
                )

        with instance_lock:
            if need_kill:
                proc.kill()

            instance_storage.register_stop(instance_id, need_kill)
    except Exception as e:
        error("Failed to finish sploit: {}".format(repr(e)))


def show_time_limit_info(
    args: Namespace, config: dict[str, Any], max_runtime: float, attack_no: int
):
    if attack_no == 1:
        min_attack_period = (
            config["FLAG_LIFETIME"] - config["SUBMIT_PERIOD"] - POST_PERIOD
        )
        if args.attack_period >= min_attack_period:
            warning(
                "--attack-period should be < {:.1f} sec, "
                "otherwise the sploit will not have time "
                "to catch flags for each round before their expiration".format(
                    min_attack_period
                )
            )

    info("Time limit for a sploit instance: {:.1f} sec".format(max_runtime))
    with instance_lock:
        if instance_storage.n_completed > 0:
            # TODO: Maybe better for 10 last attacks
            info(
                "Total {:.1f}% of instances ran out of time".format(
                    float(instance_storage.n_killed)
                    / instance_storage.n_completed
                    * 100
                )
            )


PRINTED_TEAM_NAMES = 5


def get_target_teams(args: Namespace, teams: dict[str, str], attack_no: int):
    if args.not_per_team:
        return {"*": None}

    if args.distribute is not None:
        k, n = args.distribute
        teams = {
            name: addr
            for name, addr in teams.items()
            if crc32(addr.encode()) % n == k - 1
        }

    if teams:
        if attack_no <= args.verbose_attacks:
            names = sorted(teams.keys())
            if len(names) > PRINTED_TEAM_NAMES:
                names = names[:PRINTED_TEAM_NAMES] + ["..."]
            info(
                "Sploit will be run on {} teams: {}".format(
                    len(teams), ", ".join(names)
                )
            )
    else:
        error(
            'There is no teams to attack for this farm client, fix "TEAMS" value '
            "in your server config or the usage of --distribute"
        )

    return teams


def main(args: Namespace):
    try:
        fix_args(args)
    except ValueError as e:
        critical(str(e))
        exit(1)

    print(highlight(HEADER))
    info("Connecting to the farm server at {}".format(args.server_url))

    Thread(target=lambda: run_post_loop(args)).start()

    config: Any = None
    flag_format = None
    pool = ThreadPoolExecutor(max_workers=args.pool_size)
    for attack_no in once_in_a_period(args.attack_period):
        try:
            config = get_config(args)
            flag_format = compile(config["FLAG_FORMAT"])
        except Exception as e:
            error("Can't get config from the server: {}".format(repr(e)))
            if attack_no == 1:
                exit(1)
            info("Using the old config")
        teams = get_target_teams(args, config["TEAMS"], attack_no)
        if not teams:
            if attack_no == 1:
                exit(1)
            continue

        print()
        info("Launching an attack #{}".format(attack_no))

        max_runtime = args.attack_period / ceil(len(teams) / args.pool_size)
        show_time_limit_info(args, config, max_runtime, attack_no)

        for team_name, team_addr in teams.items():
            assert flag_format is not None
            assert team_addr is not None
            pool.submit(
                run_sploit,
                args,
                team_name,
                team_addr,
                attack_no,
                max_runtime,
                flag_format,
            )


def shutdown():
    # Stop run_post_loop thread
    exit_event.set()
    # Kill all child processes (so consume_sploit_ouput and run_sploit also will stop)
    with instance_lock:
        for proc in instance_storage.instances.values():
            proc.kill()


if __name__ == "__main__":
    try:
        main(parse_args())
    except KeyboardInterrupt:
        info("Got Ctrl+C, shutting down")
    finally:
        shutdown()
