import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.alerting.engine import ALERT_SWEEP_INTERVAL_SECONDS, get_alert_engine
from app.api.routes import (
    about,
    ai_agents,
    ai_cost,
    ai_mode,
    ai_performance,
    alerts,
    assistant,
    auth,
    credentials,
    devices,
    discovery,
    events,
    integrations,
    maintenance,
    networks,
    overview,
    reports,
    services,
    ssh_host_keys,
    system,
    telegram,
    topology,
)
from app.audit import AuditMiddleware
from app.auth.middleware import AuthMiddleware
from app.auth.service import ensure_default_admin
from app.background import cancel_all
from app.config import get_settings
from app.credentials.crypto import load_master_key
from app.credentials.permissions import enforce_private_file
from app.db.session import Databases, get_databases
from app.discovery.network_scanner import SCHEDULER_TICK_SECONDS, run_scheduled_discovery
from app.discovery.reachability import REACHABILITY_INTERVAL_SECONDS, run_reachability
from app.discovery.service import DiscoveredServiceStore, DiscoveryService
from app.domain.bootstrap import (
    ensure_default_assistant_config,
    ensure_default_discovery_settings,
    ensure_default_site,
)
from app.llm.schedule import SCHEDULE_TICK_SECONDS, run_ai_schedule
from app.logging_setup import configure_logging, get_logger
from app.metrics.rollup import ROLLUP_INTERVAL_SECONDS, enforce_size_limit, run_rollup_and_retention
from app.metrics.writer import get_metrics_writer
from app.migrate import upgrade_all
from app.scheduler.periodic import PeriodicTask
from app.scheduler.supervisor import get_supervisor
from app.security import OriginGuardMiddleware, SecurityHeadersMiddleware
from app.selfhealth.monitor import SELF_HEALTH_INTERVAL_SECONDS, get_self_health_monitor
from app.telegram.bot import POLL_INTERVAL_SECONDS, poll_once

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    logger.info("app_starting", data_dir=str(settings.data_dir), bind=f"{settings.host}:{settings.port}")
    if settings.host not in ("127.0.0.1", "::1", "localhost"):
        logger.warning(
            "listening_beyond_localhost",
            host=settings.host,
            note="The dashboard is reachable from the network; set BANANA_ALLOWED_HOSTS and use a firewall.",
        )

    await asyncio.to_thread(upgrade_all)
    logger.info("migrations_applied")
    load_master_key(settings)

    databases = get_databases()
    await databases.apply_pragmas()
    enforce_private_file(settings.credentials_db_path)

    async with databases.app_session_factory() as session:
        await ensure_default_site(session)
        await ensure_default_assistant_config(session)
        await ensure_default_discovery_settings(session)
        await ensure_default_admin(session)

    await DiscoveryService(databases).merge_duplicate_devices()
    await DiscoveredServiceStore(databases).reconcile()

    metrics_writer = get_metrics_writer()
    await metrics_writer.start()

    supervisor = get_supervisor()
    await supervisor.start()

    discovery_job = PeriodicTask(
        "discovery", SCHEDULER_TICK_SECONDS, lambda: run_scheduled_discovery(databases)
    )
    discovery_job.start()

    alert_sweep_job = PeriodicTask(
        "alert_sweep", ALERT_SWEEP_INTERVAL_SECONDS, get_alert_engine().run_staleness_sweep
    )
    alert_sweep_job.start()

    self_health_job = PeriodicTask(
        "self_health", SELF_HEALTH_INTERVAL_SECONDS, get_self_health_monitor().run_once
    )
    self_health_job.start()

    reachability_job = PeriodicTask(
        "reachability", REACHABILITY_INTERVAL_SECONDS, lambda: run_reachability(databases)
    )
    reachability_job.start()

    ai_schedule_job = PeriodicTask(
        "ai_schedule", SCHEDULE_TICK_SECONDS, lambda: run_ai_schedule(databases)
    )
    ai_schedule_job.start()

    telegram_job = PeriodicTask("telegram", POLL_INTERVAL_SECONDS, lambda: poll_once(databases))
    telegram_job.start()

    rollup_job = PeriodicTask(
        "rollup", ROLLUP_INTERVAL_SECONDS, lambda: _rollup_and_trim(databases)
    )
    rollup_job.start()

    yield

    await cancel_all()
    await rollup_job.stop()
    await telegram_job.stop()
    await ai_schedule_job.stop()
    await reachability_job.stop()
    await self_health_job.stop()
    await alert_sweep_job.stop()
    await discovery_job.stop()
    await supervisor.stop()
    await metrics_writer.stop()
    await databases.dispose()
    logger.info("app_stopping")


async def _rollup_and_trim(databases: Databases) -> None:
    await run_rollup_and_retention(databases)
    async with databases.app_session_factory() as session:
        limit_mb = (await ensure_default_discovery_settings(session)).max_db_size_mb
    await enforce_size_limit(databases, get_settings().metrics_db_path, limit_mb * 1024 * 1024)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)

    app = FastAPI(
        title="Banana",
        lifespan=lifespan,
        docs_url="/docs" if settings.enable_api_docs else None,
        redoc_url="/redoc" if settings.enable_api_docs else None,
        openapi_url="/openapi.json" if settings.enable_api_docs else None,
    )
    # The last one added is the outermost: headers wrap everything, then the origin check, then the login,
    # then the audit log (which needs the user the login found).
    app.add_middleware(AuditMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(OriginGuardMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router, prefix="/api")
    app.include_router(networks.router, prefix="/api")
    app.include_router(devices.router, prefix="/api")
    app.include_router(services.router, prefix="/api")
    app.include_router(credentials.router, prefix="/api")
    app.include_router(integrations.router, prefix="/api")
    app.include_router(discovery.router, prefix="/api")
    app.include_router(alerts.router, prefix="/api")
    app.include_router(events.router, prefix="/api")
    app.include_router(overview.router, prefix="/api")
    app.include_router(assistant.router, prefix="/api")
    app.include_router(about.router, prefix="/api")
    app.include_router(ai_mode.router, prefix="/api")
    app.include_router(ai_agents.router, prefix="/api")
    app.include_router(ai_cost.router, prefix="/api")
    app.include_router(ai_performance.router, prefix="/api")
    app.include_router(topology.router, prefix="/api")
    app.include_router(ssh_host_keys.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(telegram.router, prefix="/api")
    app.include_router(system.router, prefix="/api")
    app.include_router(maintenance.router, prefix="/api")

    _mount_frontend(app, settings.frontend_dist_dir)

    return app


def _mount_frontend(app: FastAPI, dist_dir: Path) -> None:
    if not dist_dir.is_dir():
        logger.warning("frontend_dist_missing", path=str(dist_dir))
        return

    app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="frontend-assets")

    index_path = dist_dir / "index.html"
    root = dist_dir.resolve()

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        """A real file in the build (favicon.svg) is served as itself; any other path is a page route."""
        candidate = (root / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index_path)


app = create_app()


def run() -> None:
    """`python -m app.main` entrypoint. The plain `uvicorn app.main:app` CLI
    invocation (used for local dev, see Makefile) still works for HTTP, but
    HTTPS needs the cert/key files to exist on disk *before* uvicorn builds
    its SSL context - which happens before it imports the ASGI app - so
    auto-generating a missing self-signed cert has to happen here, ahead of
    that, rather than as an app-import side effect."""
    import uvicorn

    settings = get_settings()

    if not settings.https_enabled:
        uvicorn.run("app.main:app", host=settings.host, port=settings.port)
        return

    cert_path, key_path = settings.ssl_certfile, settings.ssl_keyfile
    if cert_path is None or key_path is None:
        from app.tls import ensure_self_signed_certificate

        cert_path, key_path = ensure_self_signed_certificate(settings.cert_dir)
    logger.info("https_enabled", cert=str(cert_path))

    from app.tls import hardened_uvicorn_config

    uvicorn.Server(hardened_uvicorn_config(app, settings.host, settings.port, cert_path, key_path)).run()


if __name__ == "__main__":
    run()
