from subprocess import PIPE, run, Popen, TimeoutExpired, CompletedProcess
from time import sleep
from typing import Any
from pytest import raises


def run_script(*args: str, **kwargs: Any) -> CompletedProcess[str]:
    return run(["python3", "tests/sploit.py", *args], env={"PYTHONPATH": "."}, **kwargs)


def test_with_farm():
    farm = Popen(["destructivefarm/server/start_server.sh"])
    try:
        sleep(1)
        assert farm.poll() is None
        with raises(TimeoutExpired):
            run_script("-u", "127.0.0.1:5000", check=True, timeout=3)
    finally:
        pid = int(
            run(["pgrep", "start_server.sh"], stdout=PIPE, check=True)
            .stdout.strip()
            .decode()
        )
        run(["pkill", "-P", str(pid)], check=True)
        farm.wait()


def test_no_argument():
    process = run_script("-u", "127.0.0.1:5000", timeout=3)
    assert process.returncode == 1


def test_one_argument():
    assert run_script("127.0.0.1", check=True).returncode == 0
