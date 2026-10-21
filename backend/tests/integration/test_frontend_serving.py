import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings


@pytest.fixture
async def web(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (tmp_path / "secret.txt").write_text("secret")
    monkeypatch.setenv("BANANA_FRONTEND_DIST_DIR", str(dist))
    get_settings.cache_clear()
    from app.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        yield client


async def test_the_favicon_is_served_as_an_image_not_as_the_app(web):
    response = await web.get("/favicon.svg")
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.text.startswith("<svg")


async def test_page_routes_still_get_the_app(web):
    for path in ("/", "/devices", "/ai/agents", "/missing.svg"):
        response = await web.get(path)
        assert response.text == "<html>app</html>", path


@pytest.mark.parametrize("path", ["/%2e%2e/secret.txt", "/..%2fsecret.txt", "/assets/../../secret.txt"])
async def test_files_outside_the_build_are_never_served(web, path):
    assert "secret" not in (await web.get(path)).text
