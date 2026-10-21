"""Applies every pending Alembic migration to the three databases; run at startup
so an upgrade needs no separate `make migrate` step (which still works)."""

from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATABASES = ("app", "metrics", "credentials")


def upgrade_all() -> None:
    for name in DATABASES:
        config = Config(str(BACKEND_DIR / f"alembic_{name}.ini"))
        config.attributes["configure_logger"] = False  # keep the app's own logging
        command.upgrade(config, "head")
