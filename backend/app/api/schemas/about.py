from pydantic import BaseModel


class StorageFile(BaseModel):
    name: str
    size_bytes: int


class SecurityCheck(BaseModel):
    """One posture fact; `ok` is None when it is informational rather than pass/fail."""

    label: str
    value: str
    ok: bool | None = None
    detail: str | None = None


class AboutInfo(BaseModel):
    """Read-only version/system info for the About page - never includes
    anything credential-adjacent (see app.api.routes.about)."""

    app_version: str
    python_version: str
    platform: str
    hostname: str
    https_enabled: bool
    data_dir: str
    storage: list[StorageFile] = []
    max_db_size_mb: int = 512
    security: list[SecurityCheck] = []
