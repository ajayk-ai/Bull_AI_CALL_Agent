"""Test setup: a dedicated PostgreSQL database built with the real migrations, and Redis DB 15.

Needs the dev containers:  docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml \
    --env-file .env up -d postgres redis
"""

import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values

_env = {**dotenv_values(Path(__file__).parents[2] / ".env"), **os.environ}
TEST_DATABASE_URL = _env.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise RuntimeError("TEST_DATABASE_URL is not set (see .env.example)")
if urlsplit(TEST_DATABASE_URL).path.rstrip("/").split("/")[-1] == urlsplit(_env.get("DATABASE_URL", "")).path.strip(
    "/"
):
    raise RuntimeError("TEST_DATABASE_URL must point to a different database than DATABASE_URL")

# Must be set before any app module reads settings.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["APP_ENV"] = "test"
os.environ["LOG_JSON"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["STORAGE_ROOT"] = tempfile.mkdtemp(prefix="bullcall-test-storage-")
# No connection pool: the WebSocket tests run the app on another event loop.
os.environ["DATABASE_POOL"] = "false"
os.environ["TELEPHONY_MODE"] = "mock"
_redis = urlsplit(_env["REDIS_URL"])
os.environ["REDIS_URL"] = urlunsplit(_redis._replace(path="/15"))

import uuid  # noqa: E402
from dataclasses import dataclass  # noqa: E402

import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.models.enums import Role  # noqa: E402
from app.models.org import Department, User  # noqa: E402

PASSWORD = "Test-Password-123"
BACKEND_DIR = Path(__file__).parents[1]


def _plain_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.attributes["database_url"] = TEST_DATABASE_URL
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    parts = urlsplit(_plain_url(TEST_DATABASE_URL))
    name = parts.path.lstrip("/")
    with psycopg.connect(urlunsplit(parts._replace(path="/postgres")), autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            conn.execute(f'CREATE DATABASE "{name}"')
    config = alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.fixture(autouse=True)
async def clean_state() -> None:
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with get_sessionmaker()() as session:
        await session.execute(text(f"TRUNCATE {tables} CASCADE"))
        await session.commit()
    await get_redis().flushdb()


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


@dataclass
class Actor:
    user: User
    headers: dict[str, str]

    @property
    def id(self) -> uuid.UUID:
        return self.user.id


@pytest.fixture
def make_department():
    async def _make(code: str, name: str | None = None) -> Department:
        async with get_sessionmaker()() as session:
            department = Department(code=code, name=name or code)
            session.add(department)
            await session.commit()
            return department

    return _make


@pytest.fixture
def make_user(client: AsyncClient):
    """Create a user directly in the database and log in through the API."""

    async def _make(role: Role, department: Department | None = None, email: str | None = None) -> Actor:
        email = email or f"{role}-{uuid.uuid4().hex[:8]}@example.com"
        async with get_sessionmaker()() as session:
            user = User(
                username=email.split("@")[0].lower(),
                email=email,
                full_name=f"Test {role}",
                password_hash=hash_password(PASSWORD),
                role=role,
                department_id=department.id if department else None,
            )
            session.add(user)
            await session.commit()
        response = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert response.status_code == 200, response.text
        return Actor(user=user, headers={"Authorization": f"Bearer {response.json()['access_token']}"})

    return _make


@pytest.fixture
async def scm(make_department) -> Department:
    return await make_department("SCM", "Supply Chain Management")


@pytest.fixture
async def quality(make_department) -> Department:
    return await make_department("QA", "Quality")


@pytest.fixture
async def admin(make_user) -> Actor:
    return await make_user(Role.ADMIN)
