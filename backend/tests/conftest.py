from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.alerting.engine import get_alert_engine
from app.auth.service import SESSION_COOKIE, create_session, ensure_default_admin
from app.config import get_settings
from app.credentials.crypto import get_secret_box
from app.credentials.models import CredentialsBase
from app.db.session import get_databases
from app.discovery.oui import get_oui_registry
from app.discovery.scan_status import get_scan_status_registry
from app.domain.metrics_models import MetricsBase
from app.domain.models import Base as AppBase
from app.llm.bus import get_message_bus
from app.llm.orchestrator import _contexts
from app.metrics.writer import get_metrics_writer
from app.scheduler.supervisor import get_supervisor
from app.selfhealth.monitor import get_self_health_monitor


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BANANA_DATA_DIR", str(tmp_path))

    async def _no_answer(ip: str, timeout: float = 1.0) -> None:
        return None

    # Discovery tests must not send mDNS/NetBIOS packets to the addresses they use.
    monkeypatch.setattr("app.discovery.techniques.device_names.mdns_name", _no_answer)
    monkeypatch.setattr("app.discovery.techniques.device_names.netbios_name", _no_answer)
    monkeypatch.setenv("BANANA_MASTER_KEY_FILE", str(tmp_path / "secrets" / "master.key"))
    monkeypatch.setattr("app.auth.passwords.N", 2**10)  # production cost is 2**15; tests hash on every setup
    get_settings.cache_clear()
    get_databases.cache_clear()
    get_secret_box.cache_clear()
    get_metrics_writer.cache_clear()
    get_supervisor.cache_clear()
    get_alert_engine.cache_clear()
    get_self_health_monitor.cache_clear()
    get_oui_registry.cache_clear()
    get_scan_status_registry.cache_clear()
    get_message_bus.cache_clear()
    _contexts.clear()  # run ids restart per test database; a leftover context would look like a live run


async def _make_app_and_databases():  # noqa: ANN202
    from app.main import create_app

    app = create_app()
    databases = get_databases()

    async with databases.app_engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
    async with databases.metrics_engine.begin() as conn:
        await conn.run_sync(MetricsBase.metadata.create_all)
    async with databases.credentials_engine.begin() as conn:
        await conn.run_sync(CredentialsBase.metadata.create_all)
    return app, databases


@pytest_asyncio.fixture
async def anon_client() -> AsyncIterator[AsyncClient]:
    """No login: the default admin/admin account exists and must still change its password."""
    app, databases = await _make_app_and_databases()
    async with databases.app_session_factory() as session:
        await ensure_default_admin(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await databases.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Signed in as admin with the default password already replaced, so API tests see the real API."""
    app, databases = await _make_app_and_databases()
    async with databases.app_session_factory() as session:
        user = await ensure_default_admin(session)
        user.must_change_password = False
        await session.commit()
        token = await create_session(session)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies={SESSION_COOKIE: token}
    ) as ac:
        yield ac
    await databases.dispose()
