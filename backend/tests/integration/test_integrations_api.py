import pytest
from httpx import AsyncClient

from app.db.session import get_databases
from app.domain.models import Integration, IntegrationTarget


@pytest.mark.asyncio
async def test_types_endpoint_lists_registered_plugins(client: AsyncClient) -> None:
    response = await client.get("/api/integrations/types")
    assert response.status_code == 200
    type_keys = {t["type_key"] for t in response.json()}
    assert {
        "http_tcp",
        "generic_ssh",
        "proxmox",
        "dns",
        "dhcp",
        "adguard_home",
        "homebridge",
        "omada",
    } <= type_keys


@pytest.mark.asyncio
async def test_create_list_update_delete_integration(client: AsyncClient) -> None:
    # An unregistered type skips plugin validation entirely - this test is
    # about generic Integration CRUD, not any specific plugin's config rules.
    response = await client.post(
        "/api/integrations",
        json={"integration_type": "custom_unregistered", "name": "pve1", "config": {"host": "192.168.1.10"}},
    )
    assert response.status_code == 201
    integration = response.json()
    assert integration["status"] == "unknown"
    assert integration["credential_id"] is None

    response = await client.get("/api/integrations")
    assert response.status_code == 200
    assert len(response.json()) == 1

    response = await client.patch(f"/api/integrations/{integration['id']}", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    response = await client.delete(f"/api/integrations/{integration['id']}")
    assert response.status_code == 204

    response = await client.get(f"/api/integrations/{integration['id']}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_integration_with_auto_discovered_targets(client: AsyncClient) -> None:
    """Regression test: deleting an integration that produced IntegrationTarget
    rows (e.g. Proxmox auto-discovery) must not fail on the NOT NULL FK."""
    device = (
        await client.post("/api/devices", json={"display_name": "vm1", "device_type": "proxmox_vm"})
    ).json()
    integration = (
        await client.post(
            "/api/integrations",
            json={"integration_type": "custom_unregistered", "name": "pve1", "config": {}},
        )
    ).json()

    databases = get_databases()
    async with databases.app_session_factory() as session:
        db_integration = await session.get(Integration, integration["id"])
        session.add(
            IntegrationTarget(
                integration_id=db_integration.id,
                device_id=device["id"],
                external_ref="qemu:pve1:100",
            )
        )
        await session.commit()

    response = await client.delete(f"/api/integrations/{integration['id']}")
    assert response.status_code == 204
