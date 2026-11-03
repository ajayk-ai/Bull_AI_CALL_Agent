"""The web process, served on port 8083: REST API under /api/v1.

The voice-gateway routers (Phase 3) and the built frontend (Phase 2) are mounted here as well while
the platform runs without Nginx. See docs/IMPLEMENTATION_PLAN.md, Section 3.
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import auth, campaigns, contacts, health, imports, org, scripts
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, request_id_var
from app.core.redis import get_redis
from app.db.session import get_engine

log = logging.getLogger("app.request")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await get_redis().aclose()
    await get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/api/v1/docs",
        redoc_url="/api/v1/redoc",
        openapi_url="/api/v1/openapi.json",
        lifespan=lifespan,
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
        if not request.url.path.startswith("/api/v1/health"):
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
    for module in (health, auth, org, contacts, imports, scripts, campaigns):
        api.include_router(module.router)
    app.include_router(api)
    return app


app = create_app()
