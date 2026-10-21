import httpx
from fastapi import APIRouter, HTTPException

from app.api.schemas.devices import DeviceRead
from app.api.schemas.discovery import (
    AcceptDevicePayload,
    AcceptServicePayload,
    DiscoveredCandidateRead,
    OuiStatusRead,
)
from app.api.schemas.services import ServiceRead
from app.db.session import get_databases
from app.discovery.oui import get_oui_registry
from app.discovery.service import CandidateNotFoundError, CandidateStateError, DiscoveryService
from app.domain.enums import CandidateStatus, CandidateType
from app.scheduler.supervisor import get_supervisor

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/oui/status", response_model=OuiStatusRead)
async def oui_status() -> OuiStatusRead:
    status = get_oui_registry().status()
    return OuiStatusRead(entry_count=status.entry_count, updated_at=status.updated_at)


@router.post("/oui/update", response_model=OuiStatusRead)
async def oui_update() -> OuiStatusRead:
    try:
        status = await get_oui_registry().update()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to download OUI registry: {exc}") from exc
    return OuiStatusRead(entry_count=status.entry_count, updated_at=status.updated_at)


@router.get("/candidates", response_model=list[DiscoveredCandidateRead])
async def list_candidates(
    status: CandidateStatus | None = None, candidate_type: CandidateType | None = None
) -> list[DiscoveredCandidateRead]:
    service = DiscoveryService(get_databases())
    candidates = await service.list_candidates(status, candidate_type)
    return [DiscoveredCandidateRead.model_validate(c) for c in candidates]


@router.post("/candidates/{candidate_id}/accept-device", response_model=DeviceRead, status_code=201)
async def accept_device(candidate_id: int, payload: AcceptDevicePayload) -> DeviceRead:
    service = DiscoveryService(get_databases())
    try:
        device = await service.accept_device(candidate_id, payload.device_type, payload.display_name)
    except CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DeviceRead.model_validate(device)


@router.post("/candidates/{candidate_id}/accept-service", response_model=ServiceRead, status_code=201)
async def accept_service(candidate_id: int, payload: AcceptServicePayload) -> ServiceRead:
    service = DiscoveryService(get_databases())
    try:
        created = await service.accept_service(
            candidate_id, payload.service_type, payload.name, payload.device_id, payload.config
        )
    except CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CandidateStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    get_supervisor().add_target(created)
    return ServiceRead.model_validate(created)


@router.post("/candidates/{candidate_id}/ignore", status_code=204)
async def ignore_candidate(candidate_id: int) -> None:
    service = DiscoveryService(get_databases())
    try:
        await service.ignore(candidate_id)
    except CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
