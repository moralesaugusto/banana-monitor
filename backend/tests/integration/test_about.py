import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_about_returns_version_and_system_info(client: AsyncClient) -> None:
    response = await client.get("/api/about")
    assert response.status_code == 200
    body = response.json()

    assert body["app_version"]
    assert body["python_version"]
    assert body["platform"]
    assert body["hostname"]
    assert isinstance(body["https_enabled"], bool)
    assert body["data_dir"]


@pytest.mark.asyncio
async def test_about_reports_storage_and_security_without_secrets(client: AsyncClient) -> None:
    body = (await client.get("/api/about")).json()
    assert {f["name"] for f in body["storage"]} == {"app.db", "metrics.db", "credentials.db"}
    assert body["max_db_size_mb"] == 512
    labels = {c["label"] for c in body["security"]}
    assert {"Web UI authentication", "Credential encryption"} <= labels
    assert "master_key" not in str(body).lower().replace("master key", "")
