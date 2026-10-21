from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # .env is looked up in the working directory (backend/) and in the repository root.
    model_config = SettingsConfigDict(env_prefix="BANANA_", env_file=("../.env", ".env"), extra="ignore")

    # Loopback by default: the dashboard is reachable from the LAN only when BANANA_HOST says so.
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    log_json: bool = False

    data_dir: Path = Path("data")
    # Resolved from this file, not the working directory: `uv run banana` runs from backend/.
    frontend_dist_dir: Path = Path(__file__).resolve().parents[2] / "frontend" / "dist"

    # Comma-separated Host names/IPs the server answers to (empty: any). Set it when the dashboard is exposed
    # beyond localhost; it stops DNS-rebinding pages from reaching the API.
    allowed_hosts: str = ""
    # FastAPI's interactive /docs, /redoc and /openapi.json. Off unless asked for.
    enable_api_docs: bool = False

    master_key: str | None = None
    master_key_file: Path | None = None

    # Off by default: `nmap -O` needs root/CAP_NET_RAW (the systemd unit runs
    # unprivileged - see deploy/banana.service) and adds several seconds per
    # host, so it's an explicit opt-in rather than a surprise cost/log-spam
    # source on a stock install. See docs/discovery.md.
    nmap_os_detection_enabled: bool = False

    # Initial values for the chat assistant and the AI agents the first time the database is created.
    # Afterwards they are edited in the UI and stored in app.db.
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3:8b"

    https_enabled: bool = True
    cert_dir: Path = Path("certificates")
    # Optional overrides to bring your own cert instead of the auto-generated
    # self-signed one - both must be set together, or neither.
    ssl_certfile: Path | None = None
    ssl_keyfile: Path | None = None

    @property
    def allowed_host_list(self) -> set[str]:
        return {h.strip().lower() for h in self.allowed_hosts.split(",") if h.strip()}

    @property
    def app_db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def metrics_db_path(self) -> Path:
        return self.data_dir / "metrics.db"

    @property
    def credentials_db_path(self) -> Path:
        return self.data_dir / "credentials.db"

    @property
    def app_db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.app_db_path}"

    @property
    def metrics_db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.metrics_db_path}"

    @property
    def credentials_db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.credentials_db_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
