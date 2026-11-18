import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_list_credential_hides_secret(client: AsyncClient) -> None:
    response = await client.post(
        "/api/credentials",
        json={
            "label": "pve1-ssh",
            "credential_type": "ssh_key",
            "secret": {"username": "banana", "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----"},
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert created["label"] == "pve1-ssh"
    assert set(created.keys()) == {
        "id",
        "label",
        "credential_type",
        "created_at",
        "rotated_at",
        "last_used_at",
        "in_agent_pool",
        "used_by",
    }

    response = await client.get("/api/credentials")
    assert response.status_code == 200
    listed = response.json()
    assert len(listed) == 1
    assert "secret" not in listed[0]
    assert "ciphertext" not in listed[0]


@pytest.mark.asyncio
async def test_rename_a_credential_without_touching_its_secret(client: AsyncClient) -> None:
    cred_id = await _new_credential(client, "old label")

    response = await client.patch(f"/api/credentials/{cred_id}", json={"label": "new label"})
    assert response.status_code == 200
    assert response.json()["label"] == "new label"
    assert response.json()["rotated_at"] is None  # label-only change is not a rotation

    listed = (await client.get("/api/credentials")).json()
    assert listed[0]["label"] == "new label"


@pytest.mark.asyncio
async def test_rotate_a_credential_replaces_its_secret_and_stamps_rotated_at(client: AsyncClient) -> None:
    cred_id = await _new_credential(client, "key")

    response = await client.patch(f"/api/credentials/{cred_id}", json={"secret": {"token": "new-secret"}})
    assert response.status_code == 200
    assert response.json()["rotated_at"] is not None

    from app.credentials.crypto import get_secret_box
    from app.credentials.service import CredentialService
    from app.db.session import get_databases

    async with get_databases().credentials_session_factory() as session:
        decrypted = await CredentialService(get_secret_box()).get_decrypted(session, cred_id)
    assert decrypted == {"token": "new-secret"}


@pytest.mark.asyncio
async def test_patching_an_unknown_credential_404s(client: AsyncClient) -> None:
    response = await client.patch("/api/credentials/999999", json={"label": "x"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_credential(client: AsyncClient) -> None:
    created = (
        await client.post(
            "/api/credentials",
            json={"label": "token", "credential_type": "api_token", "secret": {"token": "xyz"}},
        )
    ).json()

    response = await client.delete(f"/api/credentials/{created['id']}")
    assert response.status_code == 204

    response = await client.delete(f"/api/credentials/{created['id']}")
    assert response.status_code == 404


async def _new_credential(client: AsyncClient, label: str = "token") -> int:
    created = (
        await client.post(
            "/api/credentials",
            json={"label": label, "credential_type": "api_token", "secret": {"token": "xyz"}},
        )
    ).json()
    return created["id"]


@pytest.mark.asyncio
async def test_list_shows_unused_credential_as_unused(client: AsyncClient) -> None:
    await _new_credential(client)
    listed = (await client.get("/api/credentials")).json()
    assert listed[0]["used_by"] == []


@pytest.mark.asyncio
async def test_credential_used_by_the_agents_default_llm_blocks_delete(client: AsyncClient) -> None:
    """AiModeSettings.llm_credential_id was missing from the original usage check entirely - a
    credential actively used as the agents' default OpenRouter key could be deleted with no
    warning, silently breaking every agent that relies on that default."""
    cred_id = await _new_credential(client, "agents-default-key")
    await client.put(
        "/api/ai-mode/settings", json={"llm_provider": "openrouter", "llm_credential_id": cred_id}
    )

    listed = (await client.get("/api/credentials")).json()
    assert listed[0]["used_by"] == ["the agents' default LLM"]

    response = await client.delete(f"/api/credentials/{cred_id}")
    assert response.status_code == 409
    assert "agents' default LLM" in response.json()["detail"]

    # restore so other tests in this run aren't affected by a dangling reference
    await client.put("/api/ai-mode/settings", json={"llm_provider": "ollama", "llm_credential_id": None})


@pytest.mark.asyncio
async def test_credential_used_by_an_agent_blocks_delete(client: AsyncClient) -> None:
    """AiAgent.credential_id was also missing from the original usage check - deleting a
    credential a specific agent was using broke that agent with no warning at all."""
    cred_id = await _new_credential(client, "agent-key")
    all_agents = (await client.get("/api/ai-mode/agents")).json()
    bellaco = next(a for a in all_agents if a["name"] == "bellaco")
    updated = await client.put(
        f"/api/ai-mode/agents/{bellaco['id']}",
        json={
            **bellaco,
            "provider": "openrouter",
            "model_override": "anthropic/claude-3.5-sonnet",
            "credential_id": cred_id,
        },
    )
    assert updated.status_code == 200, updated.text

    listed = (await client.get("/api/credentials")).json()
    assert listed[0]["used_by"] == ["agent bellaco"]

    response = await client.delete(f"/api/credentials/{cred_id}")
    assert response.status_code == 409
    assert "agent bellaco" in response.json()["detail"]


@pytest.mark.asyncio
async def test_credential_used_by_telegram_blocks_delete(client: AsyncClient) -> None:
    """TelegramConfig.credential_id was also missing from the original usage check."""
    from app.db.session import get_databases
    from app.domain.bootstrap import ensure_default_telegram_config

    cred_id = await _new_credential(client, "telegram-bot-token")
    async with get_databases().app_session_factory() as session:
        (await ensure_default_telegram_config(session)).credential_id = cred_id
        await session.commit()

    listed = (await client.get("/api/credentials")).json()
    assert listed[0]["used_by"] == ["Telegram"]

    response = await client.delete(f"/api/credentials/{cred_id}")
    assert response.status_code == 409
    assert "Telegram" in response.json()["detail"]
