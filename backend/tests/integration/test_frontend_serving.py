from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app


async def test_frontend_served_with_spa_fallback(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("outside")
    monkeypatch.setattr(get_settings(), "frontend_dist", str(tmp_path))
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/")).text == "<html>app</html>"
        deep_link = await client.get("/campaigns/123")
        assert deep_link.text == "<html>app</html>" and deep_link.headers["x-frame-options"] == "DENY"
        assert (await client.get("/assets/app.js")).text == "console.log(1)"
        assert (await client.get("/../secret.txt")).text != "outside"
        # Unknown API paths stay JSON 404s, not the app.
        missing = await client.get("/api/v1/nope")
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "http_error"
        assert (await client.get("/api/v1/health/live")).json() == {"status": "ok"}
