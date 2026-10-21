from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import AppSession, CredentialServiceDep, CredentialsSession
from app.api.schemas.integrations import (
    IntegrationCreate,
    IntegrationRead,
    IntegrationTypeInfo,
    IntegrationUpdate,
)
from app.credentials.service import CredentialNotFoundError
from app.domain.models import Integration
from app.integrations import registry
from app.scheduler.supervisor import get_supervisor

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/types", response_model=list[IntegrationTypeInfo])
async def list_integration_types() -> list[IntegrationTypeInfo]:
    return [
        IntegrationTypeInfo(
            type_key=plugin.type_key,
            display_name=plugin.display_name,
            config_schema=plugin.config_schema.model_json_schema(),
            credential_schema=(
                plugin.credential_schema.model_json_schema() if plugin.credential_schema else None
            ),
        )
        for plugin in registry.list_plugins()
    ]


async def _get_or_404(session: AppSession, integration_id: int) -> Integration:
    integration = await session.get(Integration, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integration


async def _validate(
    integration_type: str,
    config: dict[str, Any],
    credential_id: int | None,
    credentials_session: CredentialsSession,
    credential_service: CredentialServiceDep,
) -> None:
    plugin = registry.get_plugin(integration_type)
    if plugin is None:
        return

    credential = None
    if credential_id is not None:
        try:
            credential = await credential_service.get_decrypted(credentials_session, credential_id)
        except CredentialNotFoundError as exc:
            raise HTTPException(status_code=400, detail="Credential not found") from exc

    result = await plugin.validate_config(config, credential)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.message or "Invalid integration config")


@router.get("", response_model=list[IntegrationRead])
async def list_integrations(session: AppSession) -> list[Integration]:
    result = await session.execute(select(Integration).order_by(Integration.name))
    return list(result.scalars().all())


@router.post("", response_model=IntegrationRead, status_code=201)
async def create_integration(
    payload: IntegrationCreate,
    session: AppSession,
    credentials_session: CredentialsSession,
    credential_service: CredentialServiceDep,
) -> Integration:
    await _validate(
        payload.integration_type,
        payload.config,
        payload.credential_id,
        credentials_session,
        credential_service,
    )

    integration = Integration(
        integration_type=payload.integration_type,
        name=payload.name,
        config=payload.config,
        credential_id=payload.credential_id,
        enabled=payload.enabled,
    )
    session.add(integration)
    await session.commit()
    await session.refresh(integration)

    await get_supervisor().add_integration(integration)
    return integration


@router.get("/{integration_id}", response_model=IntegrationRead)
async def get_integration(integration_id: int, session: AppSession) -> Integration:
    return await _get_or_404(session, integration_id)


@router.patch("/{integration_id}", response_model=IntegrationRead)
async def update_integration(
    integration_id: int,
    payload: IntegrationUpdate,
    session: AppSession,
    credentials_session: CredentialsSession,
    credential_service: CredentialServiceDep,
) -> Integration:
    integration = await _get_or_404(session, integration_id)

    updates = payload.model_dump(exclude_unset=True)
    if "config" in updates or "credential_id" in updates:
        await _validate(
            integration.integration_type,
            updates.get("config", integration.config),
            updates.get("credential_id", integration.credential_id),
            credentials_session,
            credential_service,
        )

    for field, value in updates.items():
        setattr(integration, field, value)
    await session.commit()
    await session.refresh(integration)

    await get_supervisor().reload_integration(integration)
    return integration


@router.post("/{integration_id}/forget-host-key", response_model=IntegrationRead)
async def forget_pinned_host_key(integration_id: int, session: AppSession) -> Integration:
    """Clears the SSH host key pinned for this integration; the next poll pins whatever key the host
    presents. For a host that was reinstalled."""
    integration = await _get_or_404(session, integration_id)
    integration.config = {k: v for k, v in integration.config.items() if k != "host_key"}
    await session.commit()
    await session.refresh(integration)
    await get_supervisor().reload_integration(integration)
    return integration


@router.delete("/{integration_id}", status_code=204)
async def delete_integration(integration_id: int, session: AppSession) -> None:
    integration = await _get_or_404(session, integration_id)
    await session.delete(integration)
    await session.commit()

    get_supervisor().remove_integration(integration_id)
