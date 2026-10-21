import datetime
import platform
import socket
import stat
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from cryptography import x509
from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import AppSession
from app.api.schemas.about import AboutInfo, SecurityCheck, StorageFile
from app.config import Settings, get_settings
from app.credentials.crypto import master_key_path
from app.domain.bootstrap import ensure_default_discovery_settings
from app.domain.models import AdminUser
from app.tls import CERT_FILENAME

router = APIRouter(prefix="/about", tags=["about"])


def _app_version() -> str:
    try:
        return version("banana")
    except PackageNotFoundError:
        return "unknown"  # e.g. running from a source checkout that was never `pip install`ed


def _mode(path: Path) -> int | None:
    return stat.S_IMODE(path.stat().st_mode) if path.exists() else None


def _private_file_check(label: str, path: Path) -> SecurityCheck:
    mode = _mode(path)
    if mode is None:
        return SecurityCheck(label=label, value="not present")
    private = not mode & (stat.S_IRWXG | stat.S_IRWXO)
    return SecurityCheck(
        label=label,
        value=oct(mode)[2:],
        ok=private,
        detail=None if private else "Readable by other users on this host; run chmod 600.",
    )


def _tls_check(settings: Settings) -> SecurityCheck:
    cert_path = settings.ssl_certfile or settings.cert_dir / CERT_FILENAME
    if not settings.https_enabled:
        return SecurityCheck(
            label="TLS",
            value="disabled",
            ok=False,
            detail="Traffic, including secrets you enter, is plaintext.",
        )
    if not cert_path.exists():
        return SecurityCheck(label="TLS certificate", value="not generated yet")
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    days_left = (cert.not_valid_after_utc - datetime.datetime.now(datetime.UTC)).days
    kind = "self-signed" if cert.issuer == cert.subject else "CA-issued"
    return SecurityCheck(
        label="TLS certificate",
        value=f"{kind}, expires in {days_left} days",
        ok=days_left > 14,
        detail=None if days_left > 14 else "Certificate is about to expire.",
    )


def _security_checks(settings: Settings, default_password: bool) -> list[SecurityCheck]:
    if settings.master_key:
        key_source = "environment variable"
    elif settings.master_key_file:
        key_source = "key file set in the environment"
    else:
        key_source = f"key file ({master_key_path(settings).name})"
    checks = [
        SecurityCheck(
            label="Web UI authentication",
            value="admin login" if not default_password else "admin login, default password",
            ok=not default_password,
            detail="Sign in and change the default password." if default_password else None,
        ),
        SecurityCheck(
            label="Listening on",
            value=f"{settings.host}:{settings.port}",
            ok=settings.host not in ("0.0.0.0", "::"),
            detail="All interfaces." if settings.host in ("0.0.0.0", "::") else None,
        ),
        _tls_check(settings),
        SecurityCheck(
            label="Transport policy",
            value="TLS 1.3, AES-256-GCM, EC certificate" if settings.https_enabled else "none (HTTP)",
            ok=settings.https_enabled,
        ),
        SecurityCheck(
            label="Credential encryption", value="Fernet (AES-128-CBC + HMAC-SHA256)", ok=True
        ),
        SecurityCheck(label="Master key source", value=key_source),
    ]
    if not settings.master_key:
        checks.append(_private_file_check("Master key file permissions", master_key_path(settings)))
    checks.append(_private_file_check("credentials.db permissions", settings.credentials_db_path))
    data_mode = _mode(settings.data_dir)
    if data_mode is not None:
        private = not data_mode & (stat.S_IRWXG | stat.S_IRWXO)
        checks.append(
            SecurityCheck(
                label="Data directory permissions",
                value=oct(data_mode)[2:],
                ok=private,
                detail=None if private else "Other users can list this directory.",
            )
        )
    checks.append(
        SecurityCheck(
            label="Secrets in API responses",
            value="never returned; decrypted only in memory while polling",
            ok=True,
        )
    )
    return checks


@router.get("", response_model=AboutInfo)
async def get_about(session: AppSession) -> AboutInfo:
    settings = get_settings()
    admin = await session.scalar(select(AdminUser).order_by(AdminUser.id).limit(1))
    paths = {
        "app.db": settings.app_db_path,
        "metrics.db": settings.metrics_db_path,
        "credentials.db": settings.credentials_db_path,
    }
    return AboutInfo(
        app_version=_app_version(),
        python_version=platform.python_version(),
        platform=platform.platform(),
        hostname=socket.gethostname(),
        https_enabled=settings.https_enabled,
        data_dir=str(settings.data_dir),
        storage=[
            StorageFile(name=name, size_bytes=path.stat().st_size if path.exists() else 0)
            for name, path in paths.items()
        ],
        max_db_size_mb=(await ensure_default_discovery_settings(session)).max_db_size_mb,
        security=_security_checks(settings, default_password=bool(admin and admin.must_change_password)),
    )
