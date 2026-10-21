"""The single admin account and its login sessions."""

import datetime
import hashlib
import secrets

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password, verify_password
from app.domain.models import AdminUser, AuthSession, LoginAttempt, utcnow
from app.logging_setup import get_logger

logger = get_logger(__name__)

ADMIN_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"
SESSION_COOKIE = "banana_session"
SESSION_HOURS = 24
MAX_FAILURES = 5
LOCKOUT_SECONDS = 60


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def ensure_default_admin(session: AsyncSession) -> AdminUser:
    user = await session.scalar(select(AdminUser).where(AdminUser.username == ADMIN_USERNAME))
    if user is None:
        user = AdminUser(
            username=ADMIN_USERNAME, password_hash=hash_password(DEFAULT_PASSWORD), must_change_password=True
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        logger.warning(
            "default_admin_created",
            username=ADMIN_USERNAME,
            note="Sign in as admin/admin; you will be asked to change the password immediately.",
        )
    return user


async def authenticate(session: AsyncSession, username: str, password: str) -> AdminUser | None:
    user = await session.scalar(select(AdminUser).where(AdminUser.username == username))
    # Hash even for an unknown user, so response time does not reveal which usernames exist.
    stored = user.password_hash if user else hash_password("unknown-user")
    ok = verify_password(password, stored)
    return user if user and ok else None


async def create_session(session: AsyncSession) -> str:
    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            token_hash=_token_hash(token), expires_at=utcnow() + datetime.timedelta(hours=SESSION_HOURS)
        )
    )
    await session.commit()
    return token


async def user_for_token(session: AsyncSession, token: str) -> AdminUser | None:
    row = await session.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    if row is None:
        return None
    if row.expires_at <= utcnow():
        await session.delete(row)
        await session.commit()
        return None
    user: AdminUser | None = await session.scalar(select(AdminUser).order_by(AdminUser.id).limit(1))
    return user


async def end_session(session: AsyncSession, token: str) -> None:
    await session.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    await session.commit()


async def change_password(session: AsyncSession, user: AdminUser, new_password: str) -> str:
    """Sets the new password, ends every session (including other browsers) and returns a fresh token."""
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    await session.execute(delete(AuthSession))
    await session.commit()
    return await create_session(session)


async def is_locked(session: AsyncSession, client: str) -> bool:
    attempt = await session.get(LoginAttempt, client)
    return attempt is not None and attempt.locked_until is not None and attempt.locked_until > utcnow()


async def record_failure(session: AsyncSession, client: str) -> None:
    attempt = await session.get(LoginAttempt, client)
    if attempt is None:
        attempt = LoginAttempt(client=client, failures=0)
        session.add(attempt)
    attempt.failures += 1
    if attempt.failures >= MAX_FAILURES:
        attempt.locked_until = utcnow() + datetime.timedelta(seconds=LOCKOUT_SECONDS)
        attempt.failures = 0
    await session.commit()


async def clear_failures(session: AsyncSession, client: str) -> None:
    await session.execute(delete(LoginAttempt).where(LoginAttempt.client == client))
    await session.commit()
