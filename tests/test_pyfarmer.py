from __future__ import annotations
from subprocess import PIPE, check_call, run, Popen
from time import sleep
from pytest import fixture
from collections.abc import Generator
from pyfarmer import async_farm, SploitFunction, FarmingStrategy, ProcessStrategy, Mode
from aiohttp.web import (
    AppRunner,
    TCPSite,
    Application,
    Response,
    Request,
    RouteTableDef,
    json_response,
)
from pyfarmer._pyfarmer import Config
from typing import TypedDict
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager
from pytest import mark
from time import sleep, time
from typing import NamedTuple


TEST_SLEEP = 1
TOLERANCE = 0.1
TEST_TOLERANCE = TEST_SLEEP * TOLERANCE
ALIAS = "test"
TARGETS = 20
POOL_SIZE = 10

TEST_SLOW_SLEEP = 0.01
SLOW_TOLERANCE = 0.3
TEST_SLOW_TOLERANCE = TEST_SLOW_SLEEP * SLOW_TOLERANCE


class SentFlag(TypedDict):
    flag: str
    sploit: str
    team: str


class Flag(NamedTuple):
    sploit: str
    team: str
    flag: str


def get_server(config: Config, callback: Callable[[SentFlag], None]) -> AppRunner:
    routes = RouteTableDef()

    @routes.get("/api/get_config")
    async def _(request: Request) -> Response:
        return json_response(config)

    @routes.post("/api/post_flags")
    async def _(request: Request) -> Response:
        data = await request.json()
        for flag in data:
            callback(flag)
        return Response()

    app = Application()
    app.add_routes(routes)
    runner = AppRunner(app)

    return runner


async def start_farm(
    function: SploitFunction,
    strategy: FarmingStrategy,
    pool_size: int,
    mode: Mode = Mode.ALL,
):
    await async_farm(
        function,
        strategy,
        server_url="127.0.0.1:5000",
        alias=ALIAS,
        pool_size=pool_size,
        mode=mode,
        cycles=1,
    )


@asynccontextmanager
async def server(config: Config):
    flags: list[Flag] = []
    runner = get_server(
        config,
        lambda flag: flags.append(
            Flag(flag=flag["flag"], sploit=flag["sploit"], team=flag["team"])
        ),
    )
    await runner.setup()
    site = TCPSite(runner, "127.0.0.1", 5000)
    await site.start()
    try:
        yield flags
    finally:
        await runner.cleanup()


@fixture
def destructivefarm() -> Generator[Popen[bytes], None, None]:
    farm = Popen(["destructivefarm/server/start_server.sh"])
    sleep(1)
    assert farm.poll() is None
    yield farm
    pid = int(run(["pgrep", "start_server.sh"], stdout=PIPE).stdout.strip().decode())
    check_call(["pkill", "-P", str(pid)])
    farm.wait()


async def run_sprint(
    sploit: SploitFunction,
    n: int,
    pool_size: int = POOL_SIZE,
    sploit_timeout: float = TEST_SLEEP + TEST_TOLERANCE,
) -> list[Flag]:
    async with server(
        {
            "TEAMS": {str(i): str(i) for i in range(n)},
            "FLAG_LIFETIME": int(sploit_timeout * n),
        },
    ) as actual:
        await start_farm(sploit, ProcessStrategy(), pool_size, mode=Mode.SPRINT)
    return actual


async def run_slow(
    sploit: SploitFunction,
    n: int,
    sploit_timeout: float = TEST_SLOW_SLEEP + TEST_SLOW_TOLERANCE,
) -> list[Flag]:
    async with server(
        {
            "TEAMS": {str(i): str(i) for i in range(n)},
            "FLAG_LIFETIME": int(sploit_timeout * n),
        },
    ) as actual:
        await start_farm(sploit, ProcessStrategy(), 1, mode=Mode.SLOW)
    return actual


@contextmanager
def require_time(max: float):
    start = time()
    yield
    delta = time() - start
    assert delta < max


@mark.asyncio
async def test_sprint_single():
    def sploit(ip: str):
        yield ip

    actual = await run_sprint(sploit, 1, sploit_timeout=1)
    expected = [Flag(sploit=ALIAS, team="0", flag="0")]
    assert sorted(actual) == sorted(expected)


@mark.asyncio
async def test_sprint_ok():
    def sploit(ip: str):
        yield ip

    actual = await run_sprint(sploit, TARGETS, sploit_timeout=1)
    expected = [Flag(sploit=ALIAS, team=str(i), flag=str(i)) for i in range(TARGETS)]
    assert sorted(actual) == sorted(expected)


@mark.asyncio
async def test_sprint_error():
    def sploit(ip: str):
        if int(ip) < TARGETS // 2:
            yield ip
            return
        raise Exception()

    actual = await run_sprint(sploit, TARGETS, sploit_timeout=1)
    expected = [
        Flag(sploit=ALIAS, team=str(i), flag=str(i)) for i in range(TARGETS // 2)
    ]
    assert sorted(actual) == sorted(expected)


@mark.asyncio
async def test_sprint_timeout():
    def sploit(ip: str):
        if int(ip) == 0:
            yield ip
            return
        while True:
            sleep(TEST_SLEEP)

    actual = await run_sprint(sploit, TARGETS, sploit_timeout=0)
    expected = [Flag(sploit=ALIAS, team="0", flag="0")]
    assert actual == expected


@mark.asyncio
async def test_sprint_stress():
    def sploit(ip: str):
        while True:
            yield ip

    actual = await run_sprint(sploit, TARGETS, POOL_SIZE, TEST_SLEEP)
    for i in range(TARGETS):
        assert Flag(sploit="test", team=str(i), flag=str(i)) in actual


# @mark.asyncio
# async def test_slow_ok():
#     def sploit(ip: str):
#         yield ip

#     with require_time(1 * TARGETS):
#         actual = await run_slow(sploit, TARGETS, sploit_timeout=1)
#         expected = [
#             Flag(sploit=ALIAS, team=str(i), flag=str(i)) for i in range(TARGETS)
#         ]
#         assert sorted(actual) == sorted(expected)


# @mark.asyncio
# async def test_slow_error():
#     def sploit(ip: str):
#         sleep(TEST_SLOW_SLEEP)
#         if int(ip) < TARGETS // 2:
#             yield ip
#             return
#         raise Exception()

#     with require_time((TEST_SLOW_SLEEP + TEST_SLOW_TOLERANCE) * TARGETS):
#         actual = await run_slow(sploit, TARGETS)
#         expected = [
#             Flag(sploit=ALIAS, team=str(i), flag=str(i)) for i in range(TARGETS // 2)
#         ]
#         assert sorted(actual) == sorted(expected)


# @mark.asyncio
# async def test_slow_timeout():
#     def sploit(ip: str):
#         if int(ip) == 0:
#             yield ip
#             return
#         while True:
#             sleep(TEST_SLOW_SLEEP)

#     with require_time((TEST_SLOW_SLEEP + TEST_SLOW_TOLERANCE) * TARGETS):
#         actual = await run_slow(sploit, TARGETS)
#         expected = [Flag(sploit=ALIAS, team="0", flag="0")]
#         assert actual == expected
