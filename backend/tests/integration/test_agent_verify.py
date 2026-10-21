import pytest
from httpx import AsyncClient

from app.credentials.models import CredentialsBase
from app.db.session import get_databases
from app.domain.enums import ServiceType
from app.domain.models import Integration, Service
from app.llm.client import LLMRequestError


@pytest.fixture(autouse=True)
def ollama(monkeypatch):
    state = {"models": ["qwen3:8b", "llama3"], "error": None, "hosts": []}

    async def fake(host, timeout=5.0):
        state["hosts"].append(host)
        if state["error"]:
            raise LLMRequestError(state["error"])
        return state["models"]

    monkeypatch.setattr("app.llm.agent_verify.list_models", fake)
    return state


@pytest.fixture(autouse=True)
def completion(monkeypatch):
    # delay is simulated via a faked clock, not a real sleep - a "slow model" test must not actually
    # take 25 real seconds.
    state = {"delay": 0.0, "error": None}
    clock = {"now": 0.0}

    def fake_monotonic() -> float:
        clock["now"] += state["delay"] or 0.001
        return clock["now"]

    async def fake(**kwargs):
        if state["error"]:
            raise LLMRequestError(state["error"])
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr("app.llm.agent_verify.call_chat_completions", fake)
    monkeypatch.setattr("app.llm.agent_verify.time.monotonic", fake_monotonic)
    return state


def _agent(**changes):
    body = {
        "name": "scout",
        "role": "r",
        "system_prompt": "You are scout.",
        "base_url": "",
        "model_override": "",
        "temperature": 0.2,
        "max_iterations": 10,
        "enabled_tools": ["publish_message"],
        "subscribes": ["task.scout"],
        "publishes": ["result.#"],
        "require_approval": "none",
        "enabled": True,
        "allow_changes": False,
    }
    return {**body, **changes}


async def _verify(client: AsyncClient, body, agent_id=None):
    response = await client.post(
        "/api/ai-mode/agents/verify", json=body, params={"agent_id": agent_id} if agent_id else {}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    return data, {c["id"]: c for c in data["checks"]}


async def test_a_sound_draft_passes(client, ollama):
    data, checks = await _verify(client, _agent())

    assert data["ok"] is True
    assert checks["host"]["status"] == "ok" and checks["model"]["status"] == "ok"
    assert checks["name"]["status"] == "ok"
    assert checks["receivers"]["status"] == "warn"  # a new name that nobody listens to yet
    assert ollama["hosts"] == ["http://localhost:11434/v1"]  # the assistant's default host


async def test_a_seeded_agents_results_reach_the_reporter(client):
    agents = (await client.get("/api/ai-mode/agents")).json()
    bellaco = next(a for a in agents if a["name"] == "bellaco")
    body = {k: v for k, v in bellaco.items() if k not in ("id", "created_at", "updated_at")}

    data, checks = await _verify(client, body, agent_id=bellaco["id"])

    assert checks["receivers"]["status"] == "ok" and "reporter" in checks["receivers"]["detail"]
    assert checks["name"]["status"] == "ok"
    assert checks["needs:apply_updates"]["status"] == "warn"  # no SSH integration in a fresh install


async def test_unreachable_host_and_missing_model_fail(client, ollama):
    ollama["error"] = "connection refused"
    data, checks = await _verify(client, _agent(base_url="http://gpu:11434/v1"))
    assert data["ok"] is False
    assert checks["host"]["status"] == "fail" and "gpu" in checks["host"]["detail"]
    assert "model" not in checks

    ollama["error"] = None
    data, checks = await _verify(client, _agent(model_override="missing:1b"))
    assert data["ok"] is False and checks["model"]["status"] == "fail"
    assert "qwen3:8b" in checks["model"]["detail"]
    assert "latency" not in checks  # never timed - the model itself wasn't even found


async def test_latency_check_warns_on_a_slow_model_and_fails_on_no_response(client, ollama, completion):
    """An unusably slow self-hosted model should be caught here, before a real run times out mid-way."""
    data, checks = await _verify(client, _agent())
    assert data["ok"] is True and checks["latency"]["status"] == "ok"

    completion["delay"] = 25.0
    data, checks = await _verify(client, _agent())
    assert data["ok"] is True  # a warning does not fail the verdict
    assert checks["latency"]["status"] == "warn" and "slow" in checks["latency"]["title"]

    completion["delay"] = 0.0
    completion["error"] = "ReadTimeout (no response within 45s)"
    data, checks = await _verify(client, _agent())
    assert data["ok"] is False  # this one does: the model never answered at all
    assert checks["latency"]["status"] == "fail"
    assert "45s" in checks["latency"]["detail"]


async def test_tool_rules(client):
    _, checks = await _verify(client, _agent(enabled_tools=["nope"]))
    assert checks["tools"]["status"] == "fail" and "nope" in checks["tools"]["detail"]

    _, checks = await _verify(client, _agent(enabled_tools=["apply_updates"]))
    assert checks["tools"]["status"] == "fail" and "May change hosts" in checks["tools"]["detail"]

    data, checks = await _verify(client, _agent(enabled_tools=["apply_updates"], allow_changes=True))
    assert checks["tools"]["status"] == "ok"
    assert checks["needs:apply_updates"]["status"] == "warn"  # no SSH integration yet
    assert data["ok"] is True  # warnings do not fail the verdict


async def test_messaging_warnings(client):
    _, checks = await _verify(client, _agent(name="loner", publishes=[], system_prompt="", enabled_tools=[]))
    assert checks["publishes"]["status"] == "warn" and checks["prompt"]["status"] == "warn"
    assert checks["receivers"]["status"] == "warn"  # nobody subscribes to result.loner

    _, checks = await _verify(client, _agent(publishes=[], enabled_tools=["publish_message"]))
    assert checks["publishes"]["status"] == "fail"


async def test_name_uniqueness_ignores_the_agent_itself(client):
    agents = (await client.get("/api/ai-mode/agents")).json()
    reviewer = next(a for a in agents if a["name"] == "reviewer")
    body = _agent(name="reviewer")

    _, checks = await _verify(client, body)
    assert checks["name"]["status"] == "fail"
    _, checks = await _verify(client, body, agent_id=reviewer["id"])
    assert checks["name"]["status"] == "ok"


async def test_integration_prerequisites_are_counted(client):
    async with get_databases().app_session_factory() as session:
        session.add(Integration(integration_type="generic_ssh", name="x", config={}, credential_id=1))
        session.add(Service(name="web", service_type=ServiceType.HTTP, config={"url": "http://x/"}))
        await session.commit()

    _, checks = await _verify(client, _agent(enabled_tools=["ssh_readonly", "http_inspect", "proxmox_get"]))

    assert checks["needs:ssh_readonly"]["status"] == "ok"
    assert checks["needs:http_inspect"]["status"] == "ok"
    assert checks["needs:proxmox_get"]["status"] == "warn"


async def test_internet_and_state_notes(client):
    _, checks = await _verify(client, _agent(enabled_tools=["web_search"], enabled=False))
    assert checks["internet"]["status"] == "info" and checks["state"]["status"] == "info"

    await client.put("/api/system/internet-access", json={"blocked": True})
    _, checks = await _verify(client, _agent(enabled_tools=["web_search"]))
    assert checks["internet"]["status"] == "warn"


async def test_response_carries_no_credentials(client):
    async with get_databases().credentials_engine.begin() as conn:
        await conn.run_sync(CredentialsBase.metadata.create_all)
    secret = "sUpErSeCrEt-verify-1234"
    credential = (
        await client.post(
            "/api/credentials",
            json={"label": "k", "credential_type": "api_token", "secret": {"token": secret}},
        )
    ).json()
    async with get_databases().app_session_factory() as session:
        session.add(
            Integration(integration_type="proxmox", name="p", config={}, credential_id=credential["id"])
        )
        await session.commit()

    response = await client.post("/api/ai-mode/agents/verify", json=_agent(enabled_tools=["proxmox_get"]))
    assert secret not in response.text


async def test_a_malformed_draft_is_a_422(client):
    response = await client.post("/api/ai-mode/agents/verify", json=_agent(name="Bad Name"))
    assert response.status_code == 422
