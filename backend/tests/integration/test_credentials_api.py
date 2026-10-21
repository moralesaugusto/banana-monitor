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
    }

    response = await client.get("/api/credentials")
    assert response.status_code == 200
    listed = response.json()
    assert len(listed) == 1
    assert "secret" not in listed[0]
    assert "ciphertext" not in listed[0]


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
