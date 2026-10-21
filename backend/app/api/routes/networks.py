
from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update

from app.api.deps import AppSession, CredentialsSession
from app.api.schemas.networks import (
    NetworkCreate,
    NetworkCredentialBindingCreate,
    NetworkCredentialBindingRead,
    NetworkMap,
    NetworkRead,
    NetworkUpdate,
    ScanStatusRead,
)
from app.background import spawn
from app.credentials.models import Credential
from app.db.session import get_databases
from app.discovery.network_map import build_network_map
from app.discovery.network_scanner import scan_network
from app.discovery.scan_status import ScanStatus, get_scan_status_registry
from app.domain.bootstrap import ensure_default_site
from app.domain.models import DiscoveredCandidate, Network, NetworkCredentialBinding

router = APIRouter(prefix="/networks", tags=["networks"])


async def _get_or_404(session: AppSession, network_id: int) -> Network:
    network = await session.get(Network, network_id)
    if network is None:
        raise HTTPException(status_code=404, detail="Network not found")
    return network


@router.get("", response_model=list[NetworkRead])
async def list_networks(session: AppSession) -> list[Network]:
    result = await session.execute(select(Network).order_by(Network.name))
    return list(result.scalars().all())


@router.post("", response_model=NetworkRead, status_code=201)
async def create_network(payload: NetworkCreate, session: AppSession) -> Network:
    site_id = payload.site_id
    if site_id is None:
        site = await ensure_default_site(session)
        site_id = site.id

    network = Network(
        site_id=site_id,
        name=payload.name,
        cidr=payload.cidr,
        vlan_id=payload.vlan_id,
        description=payload.description,
    )
    session.add(network)
    await session.commit()
    await session.refresh(network)
    return network


@router.get("/{network_id}", response_model=NetworkRead)
async def get_network(network_id: int, session: AppSession) -> Network:
    return await _get_or_404(session, network_id)


@router.patch("/{network_id}", response_model=NetworkRead)
async def update_network(network_id: int, payload: NetworkUpdate, session: AppSession) -> Network:
    network = await _get_or_404(session, network_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(network, field, value)
    await session.commit()
    await session.refresh(network)
    return network


@router.delete("/{network_id}", status_code=204)
async def delete_network(network_id: int, session: AppSession) -> None:
    network = await _get_or_404(session, network_id)
    # Devices are detached by the ORM relationship; candidates have none, so they'd keep a dangling id.
    await session.execute(
        update(DiscoveredCandidate)
        .where(DiscoveredCandidate.network_id == network_id)
        .values(network_id=None)
    )
    await session.delete(network)
    await session.commit()


@router.post("/{network_id}/scan", status_code=202)
async def trigger_scan(network_id: int, session: AppSession) -> dict[str, str]:
    await _get_or_404(session, network_id)
    spawn(scan_network(get_databases(), network_id), f"scan-network-{network_id}")
    return {"status": "scan started"}


@router.get("/{network_id}/scan-status", response_model=ScanStatusRead)
async def get_scan_status(network_id: int, session: AppSession) -> ScanStatus:
    await _get_or_404(session, network_id)
    return get_scan_status_registry().get(network_id)


@router.get("/{network_id}/map", response_model=NetworkMap)
async def get_network_map(network_id: int, session: AppSession) -> dict[str, object]:
    network = await _get_or_404(session, network_id)
    return await build_network_map(get_databases(), network)


@router.get("/{network_id}/credentials", response_model=list[NetworkCredentialBindingRead])
async def list_network_credentials(network_id: int, session: AppSession) -> list[NetworkCredentialBinding]:
    await _get_or_404(session, network_id)
    result = await session.execute(
        select(NetworkCredentialBinding)
        .where(NetworkCredentialBinding.network_id == network_id)
        .order_by(NetworkCredentialBinding.priority)
    )
    return list(result.scalars().all())


@router.post("/{network_id}/credentials", response_model=NetworkCredentialBindingRead, status_code=201)
async def add_network_credential(
    network_id: int,
    payload: NetworkCredentialBindingCreate,
    session: AppSession,
    credentials_session: CredentialsSession,
) -> NetworkCredentialBinding:
    """Attaches a credential this network's discovery scan should try against
    any host it finds with SSH open, in `priority` order - see
    docs/decisions.md "Auto-login on discovery". Only checks the credential
    exists; never decrypts it here."""
    await _get_or_404(session, network_id)
    if await credentials_session.get(Credential, payload.credential_id) is None:
        raise HTTPException(status_code=400, detail="Credential not found")

    binding = NetworkCredentialBinding(
        network_id=network_id, credential_id=payload.credential_id, priority=payload.priority
    )
    session.add(binding)
    await session.commit()
    await session.refresh(binding)
    return binding


@router.delete("/{network_id}/credentials/{binding_id}", status_code=204)
async def remove_network_credential(network_id: int, binding_id: int, session: AppSession) -> None:
    await _get_or_404(session, network_id)
    binding = await session.get(NetworkCredentialBinding, binding_id)
    if binding is None or binding.network_id != network_id:
        raise HTTPException(status_code=404, detail="Credential binding not found")
    await session.delete(binding)
    await session.commit()
