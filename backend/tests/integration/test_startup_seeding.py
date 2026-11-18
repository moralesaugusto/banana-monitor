import asyncio

from sqlalchemy import select

from app.db.session import get_databases
from app.domain.models import AiAgent
from app.main import create_app


async def test_default_agents_exist_before_the_first_request() -> None:
    """Left to the first read, several AI-page requests on a fresh DB each tried to seed them at once."""
    app = create_app()
    async with asyncio.timeout(60), app.router.lifespan_context(app):
        pass
    async with get_databases().app_session_factory() as session:
        names = set(await session.scalars(select(AiAgent.name)))
    assert {"discoverer", "reviewer", "reporter"} <= names
