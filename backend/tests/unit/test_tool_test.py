"""`app.llm.tool_test` actually calls a custom tool - unlike `tool_availability.py`'s listing check -
to see whether it really works. These tests confirm it goes through the real `run_custom_tool` path
(so a bad config fails the same way a live agent call would) and never touches anything but loopback."""

import asyncio
import functools

import httpx
import pytest

from app.db.session import get_databases
from app.domain.models import AiCustomTool, AiGuardrail
from app.domain.models import Base as AppBase
from app.llm import custom_tools, tool_test
from app.llm.tool_test import TEST_TARGET, synthesize_test_arguments


@pytest.fixture
async def databases():
    dbs = get_databases()
    async with dbs.app_engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
    yield dbs
    await dbs.dispose()


def _command_tool(*, id: int = 1, name: str = "whatweb_scan") -> AiCustomTool:
    return AiCustomTool(id=id, name=name, description="d", kind="command", command=["whatweb", "{target}"])


def _mcp_tool() -> AiCustomTool:
    return AiCustomTool(
        id=2,
        name="brute_force",
        description="d",
        kind="mcp",
        command=[],
        mcp_url="http://hexstrike.local/mcp",
        mcp_tool="brute_force",
        parameters={
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "port": {"type": "integer"},
                "wordlist": {"type": "string"},
                "verbose": {"type": "boolean"},
                "users": {"type": "array"},
            },
            "required": ["target", "port", "wordlist", "verbose", "users"],
        },
    )


def test_a_command_tool_always_gets_only_the_test_target() -> None:
    assert synthesize_test_arguments(_command_tool()) == {"target": TEST_TARGET}


def test_an_mcp_tool_gets_the_test_target_plus_a_safe_empty_value_per_type() -> None:
    assert synthesize_test_arguments(_mcp_tool()) == {
        "target": TEST_TARGET,
        "port": 0,
        "wordlist": "",
        "verbose": False,
        "users": [],
    }


async def test_a_command_tool_is_actually_run_against_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    async def fake_run(args: list[str], timeout: float, stdin: bytes | None = None) -> dict:
        seen["args"] = args
        return {"exit_code": 0, "output": "ok"}

    monkeypatch.setattr(custom_tools, "_run", fake_run)
    result = await tool_test.test_custom_tool(None, _command_tool(), [])  # type: ignore[arg-type]

    assert seen["args"] == ["whatweb", TEST_TARGET]  # it really ran, with the loopback target
    assert result.ok is True and result.arguments_used == {"target": TEST_TARGET}


async def test_a_guardrail_blocking_the_synthesized_arguments_is_reported_as_the_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(args: list[str], timeout: float, stdin: bytes | None = None) -> dict:
        raise AssertionError("must not run once a guardrail has already refused the call")

    monkeypatch.setattr(custom_tools, "_run", fake_run)
    rule = AiGuardrail(
        name="no-loopback", kind="deny_regex", pattern="127\\.0\\.0\\.1", applies_to="all", enabled=True
    )

    result = await tool_test.test_custom_tool(None, _command_tool(), [rule])  # type: ignore[arg-type]

    assert result.ok is False and "blocked by guardrail 'no-loopback'" in result.detail


async def test_an_unreachable_mcp_server_is_reported_with_its_error(
    databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    real = httpx.AsyncClient
    monkeypatch.setattr(
        custom_tools.httpx, "AsyncClient", functools.partial(real, transport=httpx.MockTransport(handler))
    )

    result = await tool_test.test_custom_tool(databases, _mcp_tool(), [])

    assert result.ok is False and "ConnectError" in result.detail
    assert result.arguments_used["target"] == TEST_TARGET


async def test_a_slow_tool_times_out_rather_than_hanging(monkeypatch: pytest.MonkeyPatch) -> None:
    async def hangs_forever(*args: object, **kwargs: object) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(tool_test, "TOOL_TEST_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(tool_test, "run_custom_tool", hangs_forever)

    result = await tool_test.test_custom_tool(None, _command_tool(), [])  # type: ignore[arg-type]

    assert result.ok is False and "Timed out after 0s" in result.detail


async def test_test_all_runs_every_tool_concurrently_and_returns_one_result_each(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(args: list[str], timeout: float, stdin: bytes | None = None) -> dict:
        return {"exit_code": 0, "output": "ok"}

    monkeypatch.setattr(custom_tools, "_run", fake_run)
    tools = [_command_tool(id=1, name="a"), _command_tool(id=2, name="b"), _command_tool(id=3, name="c")]

    results = await tool_test.test_all_custom_tools(None, tools, [])  # type: ignore[arg-type]

    assert sorted(r.name for r in results) == ["a", "b", "c"]
    assert all(r.ok for r in results)
