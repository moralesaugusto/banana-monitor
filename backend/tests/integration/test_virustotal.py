import json

import httpx
import pytest
from sqlalchemy import select

from app.credentials.crypto import get_secret_box
from app.credentials.models import CredentialsBase
from app.credentials.service import CredentialService
from app.db.session import get_databases
from app.domain.enums import CredentialType
from app.domain.models import Base as AppBase
from app.domain.models import Event, Integration
from app.integrations.virustotal.plugin import VirusTotalPlugin
from app.llm import agent_tools, virustotal_tool

API_KEY = "ab" * 32
SHA = "a" * 64


@pytest.fixture
async def databases():
    virustotal_tool.limiter.clear()
    dbs = get_databases()
    async with dbs.app_engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
    async with dbs.credentials_engine.begin() as conn:
        await conn.run_sync(CredentialsBase.metadata.create_all)
    yield dbs
    await dbs.dispose()


async def _configure(dbs, config=None):
    async with dbs.credentials_session_factory() as session:
        credential = await CredentialService(get_secret_box()).create(
            session, "vt", CredentialType.API_TOKEN, {"api_key": API_KEY}
        )
    async with dbs.app_session_factory() as session:
        session.add(
            Integration(
                integration_type="virustotal", name="vt", config=config or {}, credential_id=credential.id
            )
        )
        await session.commit()


class _FakeClient:
    requests: list[tuple[str, dict]] = []
    response: httpx.Response = httpx.Response(200, json={})

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        _FakeClient.requests.append((url, headers or {}))
        return _FakeClient.response


@pytest.fixture(autouse=True)
def fake_http(monkeypatch):
    _FakeClient.requests = []
    _FakeClient.response = httpx.Response(
        200,
        json={
            "data": {
                "attributes": {
                    "last_analysis_stats": {"malicious": 5, "harmless": 60},
                    "reputation": -10,
                    "meaningful_name": "evil.exe",
                    "popular_threat_classification": {"suggested_threat_label": "trojan.x"},
                    "secret_extra": "dropped",
                }
            }
        },
    )
    monkeypatch.setattr("app.llm.virustotal_tool.httpx.AsyncClient", _FakeClient)


async def _lookup(dbs, kind, value):
    return await agent_tools.dispatch(
        dbs, "virustotal_lookup", {"kind": kind, "value": value}, enabled=["virustotal_lookup"]
    )


async def test_hash_lookup_sends_the_key_and_summarizes(databases):
    await _configure(databases)

    result = await _lookup(databases, "file_hash", SHA.upper())

    url, headers = _FakeClient.requests[0]
    assert url.endswith(f"/files/{SHA}") and headers == {"x-apikey": API_KEY}
    assert result["analysis"] == {"malicious": 5, "harmless": 60}
    assert result["suggested_threat_label"] == "trojan.x" and "secret_extra" not in result
    assert API_KEY not in json.dumps(result)
    async with databases.app_session_factory() as session:
        events = list(await session.scalars(select(Event).where(Event.category == "outbound")))
    assert len(events) == 1 and SHA not in events[0].message


async def test_results_are_cached(databases):
    await _configure(databases)
    await _lookup(databases, "file_hash", SHA)
    second = await _lookup(databases, "file_hash", SHA)
    assert second["cached"] is True and len(_FakeClient.requests) == 1


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("ip", "192.168.1.5"),
        ("ip", "10.0.0.1"),
        ("ip", "127.0.0.1"),
        ("ip", "169.254.169.254"),
        ("ip", "not-an-ip"),
        ("domain", "nas.local"),
        ("domain", "router"),
        ("domain", "printer.home"),
        ("domain", "host.internal"),
        ("domain", "a b.com"),
        ("file_hash", "xyz"),
        ("file_hash", "abc"),
        ("url", "http://x.com"),
    ],
)
async def test_private_or_malformed_values_never_leave(databases, kind, value):
    await _configure(databases)
    with pytest.raises(agent_tools.AgentToolError):
        await _lookup(databases, kind, value)
    assert _FakeClient.requests == []


async def test_public_ip_and_domain_are_allowed(databases):
    await _configure(databases)
    await _lookup(databases, "ip", "8.8.8.8")
    await _lookup(databases, "domain", "Example.com.")
    assert [u.rsplit("/", 2)[-2:] for u, _ in _FakeClient.requests] == [
        ["ip_addresses", "8.8.8.8"],
        ["domains", "example.com"],
    ]


async def test_rate_limit_per_minute(databases):
    await _configure(databases, {"requests_per_minute": 2, "requests_per_day": 500})
    await _lookup(databases, "ip", "8.8.8.8")
    await _lookup(databases, "ip", "8.8.4.4")
    with pytest.raises(agent_tools.AgentToolError, match="per-minute"):
        await _lookup(databases, "ip", "1.1.1.1")
    assert len(_FakeClient.requests) == 2


async def test_not_found_and_errors(databases):
    await _configure(databases)
    _FakeClient.response = httpx.Response(404)
    assert (await _lookup(databases, "file_hash", SHA))["found"] is False
    _FakeClient.response = httpx.Response(401)
    with pytest.raises(agent_tools.AgentToolError, match="rejected"):
        await _lookup(databases, "ip", "8.8.8.8")


async def test_not_configured(databases):
    with pytest.raises(agent_tools.AgentToolError, match="not configured"):
        await _lookup(databases, "ip", "8.8.8.8")


async def test_kill_switch_blocks_virustotal(databases):
    from app.domain.bootstrap import ensure_default_discovery_settings

    await _configure(databases)
    async with databases.app_session_factory() as session:
        (await ensure_default_discovery_settings(session)).agent_internet_blocked = True
        await session.commit()
    with pytest.raises(agent_tools.AgentToolError, match="kill switch"):
        await _lookup(databases, "ip", "8.8.8.8")
    assert _FakeClient.requests == []


async def test_plugin_validates_key_format():
    plugin = VirusTotalPlugin()
    assert not (await plugin.validate_config({}, {"api_key": "short"})).ok
    assert not (await plugin.validate_config({}, None)).ok
    assert not (await plugin.validate_config({"requests_per_minute": 0}, {"api_key": API_KEY})).ok


async def test_plugin_validate_config_makes_a_real_check_against_virustotal(monkeypatch):
    """validate_config() must not stop at the key's shape - a well-formed but wrong/revoked key should
    fail at creation time, not silently succeed and only fail later when an agent tries to use it."""

    class _Client:
        response: httpx.Response = httpx.Response(200)

        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None):
            return _Client.response

    monkeypatch.setattr("app.integrations.virustotal.plugin.httpx.AsyncClient", _Client)
    plugin = VirusTotalPlugin()

    _Client.response = httpx.Response(200)
    assert (await plugin.validate_config({}, {"api_key": API_KEY})).ok

    _Client.response = httpx.Response(404)  # the probe indicator not being found is still a working key
    assert (await plugin.validate_config({}, {"api_key": API_KEY})).ok

    _Client.response = httpx.Response(401)
    result = await plugin.validate_config({}, {"api_key": API_KEY})
    assert not result.ok and "Could not verify" in (result.message or "")


async def test_plugin_validate_config_fails_closed_when_virustotal_is_unreachable(monkeypatch):
    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None):
            raise httpx.ConnectTimeout("no route")

    monkeypatch.setattr("app.integrations.virustotal.plugin.httpx.AsyncClient", _Client)
    plugin = VirusTotalPlugin()
    assert not (await plugin.validate_config({}, {"api_key": API_KEY})).ok
