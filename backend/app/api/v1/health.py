"""Liveness: the process is up. Readiness: PostgreSQL and Redis answer."""

import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.redis import get_redis
from app.db.session import get_engine

router = APIRouter(prefix="/health", tags=["health"])
log = logging.getLogger(__name__)


async def _check_db() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis() -> None:
    await get_redis().ping()


@router.get("/live")
async def live() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> JSONResponse:
    checks = {"database": _check_db, "redis": _check_redis}
    results: dict[str, str] = {}
    for name, check in checks.items():
        try:
            await asyncio.wait_for(check(), timeout=3)
            results[name] = "ok"
        except Exception as exc:
            log.warning("Readiness check %s failed: %s", name, exc)
            results[name] = "unavailable"
    healthy = all(v == "ok" for v in results.values())
    return JSONResponse({"status": "ok" if healthy else "degraded", "checks": results}, 200 if healthy else 503)
