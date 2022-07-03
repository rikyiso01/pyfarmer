from __future__ import annotations
from subprocess import PIPE, CompletedProcess, check_call, run, Popen, TimeoutExpired
from time import sleep
from typing import Any
from pytest import raises, fixture
from sys import executable
from collections.abc import Generator


@fixture
def destructivefarm() -> Generator[Popen[bytes], None, None]:
    farm = Popen(["destructivefarm/server/start_server.sh"])
    sleep(1)
    assert farm.poll() is None
    yield farm
    pid = int(run(["pgrep", "start_server.sh"], stdout=PIPE).stdout.strip().decode())
    check_call(["pkill", "-P", str(pid)])
    farm.wait()


def run_script(*args: str, **kwargs: Any) -> CompletedProcess[str]:
    return run(
        [executable, "tests/sploit.py", *args], env={"PYTHONPATH": "."}, **kwargs
    )


def test_with_farm(destructivefarm: Popen[bytes]) -> None:
    with raises(TimeoutExpired):
        run_script("-u", "127.0.0.1:5000", check=True, timeout=3)


def test_no_argument() -> None:
    process = run_script("-u", "127.0.0.1:5000", timeout=3)
    assert process.returncode == 1


def test_one_argument() -> None:
    assert run_script("127.0.0.1", check=True).returncode == 0
