"""The web process, served on port 8083: REST API under /api/v1, FreJun webhooks and media under /telephony,
and the built React frontend for every other path.

Behind the shared nginx on ai.bullmachine.in the whole app lives under BASE_PATH (e.g. /aicall), the same way
the costing and voicecall apps do; nginx passes the full path through.
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import auth, calls, campaigns, contacts, health, imports, org, scripts
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, request_id_var
from app.core.paths import route_path
from app.core.redis import get_redis
from app.db.session import get_engine
from app.voice import routes as voice_routes

log = logging.getLogger("app.request")

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await voice_routes.pending_post_call_work()
    await get_redis().aclose()
    await get_engine().dispose()


def create_app() -> FastAPI:
    """The app, mounted under BASE_PATH when one is set."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    app = _create_inner(mounted=bool(settings.base_path))
    if not settings.base_path:
        return app
    base = settings.base_path
    # Sub-applications do not run their own lifespan, so the outer app runs it.
    outer = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @outer.get(base, include_in_schema=False)
    async def to_base_path() -> RedirectResponse:
        return RedirectResponse(f"{base}/")

    outer.mount(base, app)
    return outer


def _create_inner(mounted: bool) -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/api/v1/docs",
        redoc_url="/api/v1/redoc",
        openapi_url="/api/v1/openapi.json",
        lifespan=None if mounted else lifespan,
    )
    register_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=False,
        )

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(request_id[:64])
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["x-request-id"] = request_id[:64]
        response.headers.update(_SECURITY_HEADERS)
        if not route_path(request.scope).startswith("/api/v1/health"):
            log.info(
                "%s %s %s",
                request.method,
                request.url.path,
                response.status_code,
                extra={
                    "extra_fields": {
                        "request_id": request_id[:64],
                        "status": response.status_code,
                        "duration_ms": elapsed_ms,
                    }
                },
            )
        return response

    api = APIRouter(prefix="/api/v1")
    for module in (health, auth, org, contacts, imports, scripts, campaigns, calls):
        api.include_router(module.router)
    app.include_router(api)
    app.include_router(voice_routes.router)
    _mount_frontend(app, Path(settings.frontend_dist), settings.base_path)
    return app


def _mount_frontend(app: FastAPI, dist: Path, base_path: str) -> None:
    """Serves the built React app. Unknown non-API paths return index.html so client-side routes work."""
    index = dist / "index.html"
    if not index.is_file():
        log.warning("Frontend build not found at %s; serving the API only", dist)
        return
    # The frontend is built for one prefix; served under another, its pages stay blank.
    if f'"{base_path}/assets/' not in index.read_text():
        log.error(
            "The frontend at %s was not built for BASE_PATH=%r, so its pages will not load. "
            "Rebuild it with the same BASE_PATH (Docker: up -d --build with --env-file .env).",
            dist,
            base_path,
        )
    root = dist.resolve()
    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
