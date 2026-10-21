import functools
import json

import httpx
import pytest

from app.domain.models import AiCustomTool
from app.llm import custom_tools
from app.llm.agent_tools import AgentToolError


def _server(seen: list[dict], *, sse: bool = False, fail: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"method": body["method"], "session": request.headers.get("mcp-session-id")})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        if body["method"] == "initialize":
            ok = {"jsonrpc": "2.0", "id": 1, "result": {}}
            return httpx.Response(200, json=ok, headers={"Mcp-Session-Id": "s1"})
        if fail:
            error = {"jsonrpc": "2.0", "id": 2, "error": {"message": "boom"}}
            return httpx.Response(200, json=error)
        result = {"content": [{"type": "text", "text": f"scanned {body['params']['arguments']['host']}"}]}
        payload = {"jsonrpc": "2.0", "id": 2, "result": result}
        if sse:
            stream = f"event: message\ndata: {json.dumps(payload)}\n\n"
            return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def _tool() -> AiCustomTool:
    return AiCustomTool(
        name="mcp_scan",
        description="d",
        kind="mcp",
        command=[],
        mcp_url="http://mcp.local/mcp",
        mcp_tool="scan",
        parameters={},
    )


@pytest.mark.parametrize("sse", [False, True])
async def test_mcp_call_does_the_handshake_and_returns_text(
    monkeypatch: pytest.MonkeyPatch, sse: bool
) -> None:
    seen: list[dict] = []
    real = httpx.AsyncClient
    transport = _server(seen, sse=sse)
    monkeypatch.setattr(custom_tools.httpx, "AsyncClient", functools.partial(real, transport=transport))

    result = await custom_tools._call_mcp(_tool(), {"host": "10.0.0.5"})

    assert result == {"is_error": False, "output": "scanned 10.0.0.5"}
    assert [s["method"] for s in seen] == ["initialize", "notifications/initialized", "tools/call"]
    assert seen[-1]["session"] == "s1"  # the session id from initialize is sent on later calls


async def test_mcp_error_becomes_a_tool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    real = httpx.AsyncClient
    transport = _server([], fail=True)
    monkeypatch.setattr(custom_tools.httpx, "AsyncClient", functools.partial(real, transport=transport))
    with pytest.raises(AgentToolError, match="boom"):
        await custom_tools._call_mcp(_tool(), {"host": "10.0.0.5"})
