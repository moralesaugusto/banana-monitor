from fastapi import APIRouter

from app.api.schemas.topology import Topology
from app.db.session import get_databases
from app.discovery.topology import build_topology

router = APIRouter(prefix="/topology", tags=["topology"])


@router.get("", response_model=Topology)
async def get_topology(network_id: int | None = None, include_services: bool = True) -> dict[str, object]:
    return await build_topology(get_databases(), network_id=network_id, include_services=include_services)
