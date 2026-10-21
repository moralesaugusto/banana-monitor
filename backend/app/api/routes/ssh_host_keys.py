import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import AppSession
from app.domain.models import SshHostKey

router = APIRouter(prefix="/ssh-host-keys", tags=["ssh-host-keys"])


class SshHostKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    host: str
    port: int
    fingerprint: str
    approved: bool
    changed: bool
    first_seen_at: datetime.datetime


async def _get_or_404(session: AppSession, key_id: int) -> SshHostKey:
    row = await session.get(SshHostKey, key_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Host key not found")
    return row


@router.get("", response_model=list[SshHostKeyRead])
async def list_host_keys(session: AppSession) -> list[SshHostKey]:
    result = await session.execute(select(SshHostKey).order_by(SshHostKey.approved, SshHostKey.host))
    return list(result.scalars().all())


@router.post("/{key_id}/approve", response_model=SshHostKeyRead)
async def approve_host_key(key_id: int, session: AppSession) -> SshHostKey:
    """Trust the key that was shown. The next scan can then try the network's credentials on this host."""
    row = await _get_or_404(session, key_id)
    row.approved, row.changed = True, False
    await session.commit()
    return row


@router.delete("/{key_id}", status_code=204)
async def forget_host_key(key_id: int, session: AppSession) -> None:
    """Forget the key; the host is treated as unseen on the next scan."""
    await session.delete(await _get_or_404(session, key_id))
    await session.commit()
