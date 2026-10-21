
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import AppSession
from app.api.schemas.system import (
    DiscoverySettingsRead,
    DiscoverySettingsUpdate,
    InternetAccess,
    InternetAccessUpdate,
    ScanOverview,
)
from app.background import spawn
from app.db.session import get_databases
from app.discovery.network_scanner import run_discovery_for_all_networks
from app.discovery.scan_status import get_scan_status_registry
from app.domain.bootstrap import ensure_default_discovery_settings
from app.domain.models import AiAgent, DiscoverySettings
from app.llm.agent_tools import WEB_TOOL_NAMES
from app.maintenance import reset_inventory
from app.scheduler.supervisor import get_supervisor

router = APIRouter(prefix="/system", tags=["system"])

@router.get("/discovery-settings", response_model=DiscoverySettingsRead)
async def get_discovery_settings(session: AppSession) -> DiscoverySettings:
    return await ensure_default_discovery_settings(session)


@router.put("/discovery-settings", response_model=DiscoverySettingsRead)
async def update_discovery_settings(
    payload: DiscoverySettingsUpdate, session: AppSession
) -> DiscoverySettings:
    settings = await ensure_default_discovery_settings(session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)
    await session.commit()
    await session.refresh(settings)
    return settings


@router.get("/internet-access", response_model=InternetAccess)
async def internet_access(session: AppSession) -> InternetAccess:
    return await _internet_access(session)


@router.put("/internet-access", response_model=InternetAccess)
async def set_internet_access(payload: InternetAccessUpdate, session: AppSession) -> InternetAccess:
    """The agent kill switch. Human-only: it has its own endpoint so a stale settings form cannot flip it."""
    (await ensure_default_discovery_settings(session)).agent_internet_blocked = payload.blocked
    await session.commit()
    return await _internet_access(session)


async def _internet_access(session: AppSession) -> InternetAccess:
    settings = await ensure_default_discovery_settings(session)
    agents = await session.scalars(select(AiAgent).where(AiAgent.enabled).order_by(AiAgent.id))
    return InternetAccess(
        blocked=settings.agent_internet_blocked,
        agents=[a.name for a in agents if WEB_TOOL_NAMES & set(a.enabled_tools)],
    )


@router.post("/scan-all", status_code=202)
async def scan_all() -> dict[str, str]:
    spawn(run_discovery_for_all_networks(get_databases()), "scan-all-networks")
    return {"status": "scan started"}


@router.get("/scan-status", response_model=ScanOverview)
async def scan_status() -> ScanOverview:
    statuses = get_scan_status_registry().all()
    return ScanOverview(
        scanning=any(s.status == "scanning" for s in statuses),
        total_hosts=sum(s.total_hosts for s in statuses if s.status == "scanning"),
        scanned_hosts=sum(s.scanned_hosts for s in statuses if s.status == "scanning"),
    )


class ResetRequest(BaseModel):
    confirm: str


@router.post("/reset")
async def reset(payload: ResetRequest) -> dict[str, int]:
    """Wipes devices, services, candidates and their history so discovery restarts clean."""
    if payload.confirm != "RESET":
        raise HTTPException(status_code=400, detail='Send {"confirm": "RESET"} to proceed')
    return await reset_inventory(get_databases(), get_supervisor())
