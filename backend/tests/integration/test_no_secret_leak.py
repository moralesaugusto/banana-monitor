from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

SECRET_MARKER = "sUpErSeCrEt-do-not-leak-9f3a"


@pytest.mark.asyncio
async def test_secret_never_appears_in_any_api_response(client: AsyncClient) -> None:
    credential = (
        await client.post(
            "/api/credentials",
            json={
                "label": "pve1-token",
                "credential_type": "api_token",
                "secret": {"token": SECRET_MARKER},
            },
        )
    ).json()

    await client.post(
        "/api/integrations",
        json={
            "integration_type": "proxmox",
            "name": "pve1",
            "config": {"host": "192.168.1.10"},
            "credential_id": credential["id"],
        },
    )

    endpoints = [
        "/api/credentials",
        "/api/integrations",
        "/api/integrations/types",
    ]

    for endpoint in endpoints:
        response = await client.get(endpoint)
        assert response.status_code == 200
        body = response.text
        assert SECRET_MARKER not in body, f"secret leaked via {endpoint}"
        assert "ciphertext" not in body.lower(), f"ciphertext field leaked via {endpoint}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "integration_type,host_field",
    [
        ("adguard_home", {"host": "192.168.1.20", "port": 3000}),
        ("homebridge", {"host": "192.168.1.21", "port": 8581}),
        ("omada", {"host": "192.168.1.22", "port": 8043}),
    ],
)
async def test_basic_auth_credential_never_appears_in_any_api_response(
    client: AsyncClient, integration_type: str, host_field: dict[str, object]
) -> None:
    """Regression coverage for the three new vendor plugins added alongside
    adguard_home/homebridge/omada: their credential_schema is username+password
    (BASIC_AUTH), which must never surface via any read endpoint."""
    marker = f"{SECRET_MARKER}-{integration_type}"
    credential = (
        await client.post(
            "/api/credentials",
            json={
                "label": f"{integration_type}-creds",
                "credential_type": "basic_auth",
                "secret": {"username": "banana", "password": marker},
            },
        )
    ).json()

    await client.post(
        "/api/integrations",
        json={
            "integration_type": integration_type,
            "name": integration_type,
            "config": host_field,
            "credential_id": credential["id"],
        },
    )

    endpoints = [
        "/api/credentials",
        "/api/integrations",
        "/api/integrations/types",
    ]

    for endpoint in endpoints:
        response = await client.get(endpoint)
        assert response.status_code == 200
        body = response.text
        assert marker not in body, f"secret leaked via {endpoint}"
        assert "ciphertext" not in body.lower(), f"ciphertext field leaked via {endpoint}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "integration_type,credential_type,secret_field,secret",
    [
        ("generic_ssh", "ssh_key", "private_key", {"username": "banana"}),
        ("proxmox", "api_token", "token_secret", {"token_id": "banana@pve!wallet"}),
        ("adguard_home", "basic_auth", "password", {"username": "admin"}),
        ("homebridge", "basic_auth", "password", {"username": "admin"}),
        ("omada", "basic_auth", "password", {"username": "admin"}),
        ("windows_winrm", "basic_auth", "password", {"username": "admin"}),
    ],
)
async def test_wallet_credential_never_appears_in_any_api_response(
    client: AsyncClient,
    integration_type: str,
    credential_type: str,
    secret_field: str,
    secret: dict[str, str],
) -> None:
    """Regression coverage for the credential wallet (docs/credentials.md): an Integration saved with a
    credential but no host - still must never leak that credential via any read endpoint."""
    marker = f"{SECRET_MARKER}-wallet-{integration_type}"
    credential = (
        await client.post(
            "/api/credentials",
            json={
                "label": f"{integration_type}-wallet",
                "credential_type": credential_type,
                "secret": {**secret, secret_field: marker},
            },
        )
    ).json()

    response = await client.post(
        "/api/integrations",
        json={
            "integration_type": integration_type,
            "name": f"{integration_type}-wallet",
            "config": {},
            "credential_id": credential["id"],
        },
    )
    assert response.status_code == 201, response.text

    endpoints = [
        "/api/credentials",
        "/api/integrations",
        "/api/integrations/types",
    ]
    for endpoint in endpoints:
        get_response = await client.get(endpoint)
        assert get_response.status_code == 200
        body = get_response.text
        assert marker not in body, f"secret leaked via {endpoint}"
        assert "ciphertext" not in body.lower(), f"ciphertext field leaked via {endpoint}"


@pytest.mark.asyncio
async def test_network_credential_binding_never_leaks_secret(client: AsyncClient) -> None:
    """Regression coverage for the auto-login credential bindings added to
    Networks (docs/decisions.md "Auto-login on discovery"): credential_id is
    stored as an opaque reference, same as Integration.credential_id, and
    must never surface via any read endpoint."""
    marker = f"{SECRET_MARKER}-sshkey"
    credential = (
        await client.post(
            "/api/credentials",
            json={
                "label": "homelab-ssh",
                "credential_type": "ssh_key",
                "secret": {"username": "banana", "private_key": marker},
            },
        )
    ).json()
    network = (await client.post("/api/networks", json={"name": "LAN", "cidr": "192.168.1.0/24"})).json()

    await client.post(
        f"/api/networks/{network['id']}/credentials",
        json={"credential_id": credential["id"], "priority": 0},
    )

    endpoints = [
        "/api/credentials",
        f"/api/networks/{network['id']}/credentials",
    ]
    for endpoint in endpoints:
        response = await client.get(endpoint)
        assert response.status_code == 200
        body = response.text
        assert marker not in body, f"secret leaked via {endpoint}"
        assert "ciphertext" not in body.lower(), f"ciphertext field leaked via {endpoint}"


@pytest.mark.asyncio
async def test_assistant_openrouter_key_never_appears_in_any_api_response(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = f"{SECRET_MARKER}-openrouter"
    credential = (
        await client.post(
            "/api/credentials",
            json={"label": "openrouter-key", "credential_type": "api_token", "secret": {"token": marker}},
        )
    ).json()

    response = await client.put(
        "/api/assistant/config",
        json={"provider": "openrouter", "credential_id": credential["id"]},
    )
    assert response.status_code == 200

    async def fake_call_chat_completions(**kwargs: object) -> dict:
        # The real key must have been passed as a header, never echoed back
        # into anything we persist or return.
        return {"choices": [{"message": {"content": "hi"}}]}

    monkeypatch.setattr("app.llm.service.call_chat_completions", fake_call_chat_completions)
    chat_response = await client.post("/api/assistant/chat", json={"message": "hello"})
    assert chat_response.status_code == 200

    endpoints = [
        "/api/credentials",
        "/api/assistant/config",
        "/api/assistant/messages",
    ]
    for endpoint in endpoints:
        response = await client.get(endpoint)
        assert response.status_code == 200
        body = response.text
        assert marker not in body, f"secret leaked via {endpoint}"
        assert "ciphertext" not in body.lower(), f"ciphertext field leaked via {endpoint}"
    assert marker not in chat_response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "integration_type,config,secret",
    [
        (
            "windows_winrm",
            {"device_id": 1, "host": "10.77.0.50"},
            {"username": "u", "password": SECRET_MARKER},
        ),
        ("virustotal", {}, {"api_key": "cd" * 32}),
    ],
)
async def test_windows_and_virustotal_secrets_never_appear_in_any_api_response(
    client: AsyncClient,
    integration_type: str,
    config: dict[str, object],
    secret: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # windows_winrm's validate_config() now makes a real connection attempt when host is set (see
    # docs/decisions.md); this test is about secret leakage, not live connectivity, so the connection
    # itself is stubbed out.
    if integration_type == "windows_winrm":
        from app.integrations.windows_winrm.plugin import WindowsWinrmPlugin

        monkeypatch.setattr(WindowsWinrmPlugin, "probe_credential", AsyncMock(return_value=True))
    if integration_type == "virustotal":
        # validate_config() now makes a real call to VirusTotal to verify the key; same reasoning as
        # windows_winrm above - this test is about secret leakage, not live connectivity.
        from app.integrations.virustotal.plugin import VirusTotalPlugin

        monkeypatch.setattr(VirusTotalPlugin, "verify_api_key", AsyncMock(return_value=True))

    credential = (
        await client.post(
            "/api/credentials",
            json={"label": integration_type, "credential_type": "basic_auth", "secret": secret},
        )
    ).json()
    created = await client.post(
        "/api/integrations",
        json={
            "integration_type": integration_type,
            "name": integration_type,
            "config": config,
            "credential_id": credential["id"],
        },
    )
    assert created.status_code == 201, created.text
    marker = next(iter(secret.values())) if integration_type == "virustotal" else SECRET_MARKER

    for endpoint in (
        "/api/credentials",
        "/api/integrations",
        "/api/integrations/types",
        "/api/system/internet-access",
    ):
        response = await client.get(endpoint)
        assert response.status_code == 200
        assert marker not in response.text, f"secret leaked via {endpoint}"
