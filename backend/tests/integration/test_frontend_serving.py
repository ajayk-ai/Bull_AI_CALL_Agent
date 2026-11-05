from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.main import create_app
from app.models.enums import Role


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


async def test_app_served_under_base_path(tmp_path, monkeypatch, make_user, scm):
    """Behind the shared nginx the whole app lives under BASE_PATH, like the costing and voicecall apps."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(get_settings(), "frontend_dist", str(tmp_path))
    monkeypatch.setattr(get_settings(), "base_path", "/aicall")
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        redirect = await client.get("/aicall")
        assert redirect.status_code == 307 and redirect.headers["location"] == "/aicall/"
        assert (await client.get("/aicall/")).text == "<html>app</html>"
        assert (await client.get("/aicall/calls/123")).text == "<html>app</html>"
        assert (await client.get("/aicall/assets/app.js")).text == "console.log(1)"
        assert (await client.get("/aicall/api/v1/health/live")).json() == {"status": "ok"}
        assert (await client.get("/api/v1/health/live")).status_code == 404  # nothing outside the prefix
        assert (await client.get("/")).status_code == 404

        # Path-based rules still apply under the prefix: before choosing a password, only /auth/me works.
        user = await make_user(Role.USER, scm)
        user.user.must_change_password = True
        async with get_sessionmaker()() as session:
            session.add(await session.merge(user.user))
            await session.commit()
        assert (await client.get("/aicall/api/v1/auth/me", headers=user.headers)).status_code == 200
        blocked = await client.get("/aicall/api/v1/contacts", headers=user.headers)
        assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "password_change_required"
