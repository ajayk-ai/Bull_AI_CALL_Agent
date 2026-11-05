"""Administrative commands.

    python -m app.cli create-admin --user-id admin --name "Platform Admin" [--email admin@bullmachine.com]
    python -m app.cli create-department --code SCM --name "Supply Chain Management"
    python -m app.cli seed-scm-script --department SCM

The admin password is read from the prompt (or ADMIN_PASSWORD), never from the command line.
"""

import argparse
import asyncio
import getpass
import os
import sys

from pydantic import ValidationError
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import get_engine, get_sessionmaker
from app.models.enums import Role
from app.models.org import Department, User
from app.models.scripts import Script, ScriptVersion
from app.schemas.org import UserCreate
from app.schemas.scripts import ScriptVersionBody
from app.seeds import scm_delivery
from app.services import audit
from app.services.auth import find_by_email, find_by_username


async def create_admin(username: str, email: str | None, name: str, password: str) -> None:
    try:
        username = UserCreate(username=username, full_name=name, email=email, role=Role.ADMIN).username
    except ValidationError as exc:
        sys.exit(f"Invalid admin details: {exc.errors()[0]['msg']}")
    async with get_sessionmaker()() as session:
        if await find_by_username(session, username) or (email and await find_by_email(session, email)):
            sys.exit(f"An account with user ID {username} or that e-mail already exists")
        user = User(
            username=username,
            email=email.lower() if email else None,
            full_name=name,
            password_hash=hash_password(password),
            role=Role.ADMIN,
        )
        session.add(user)
        await session.flush()
        audit.record(
            session,
            None,
            "user.create",
            actor_email="cli",
            entity_type="user",
            entity_id=user.id,
            changes={"username": user.username, "email": user.email, "role": Role.ADMIN, "via": "cli"},
        )
        await session.commit()
        print(f"Admin created: user ID {user.username} ({user.id})")


async def create_department(code: str, name: str) -> None:
    async with get_sessionmaker()() as session:
        department = Department(code=code.upper(), name=name)
        session.add(department)
        await session.flush()
        audit.record(
            session,
            None,
            "department.create",
            actor_email="cli",
            entity_type="department",
            entity_id=department.id,
            department_id=department.id,
            changes={"code": department.code, "name": name, "via": "cli"},
        )
        await session.commit()
        print(f"Department created: {department.code} ({department.id})")


async def seed_scm_script(department_code: str) -> None:
    """Creates the SCM delivery confirmation script as a draft version 1. It still needs approval."""
    body = ScriptVersionBody(config=scm_delivery.CONFIG, extraction_schema=scm_delivery.EXTRACTION_SCHEMA)
    async with get_sessionmaker()() as session:
        department = await session.scalar(select(Department).where(Department.code == department_code.upper()))
        if department is None:
            sys.exit(f"No department with code {department_code}")
        if await session.scalar(
            select(Script.id).where(Script.department_id == department.id, Script.name == scm_delivery.NAME)
        ):
            sys.exit(f"Script {scm_delivery.NAME!r} already exists in {department.code}")
        script = Script(department_id=department.id, name=scm_delivery.NAME, description=scm_delivery.DESCRIPTION)
        session.add(script)
        await session.flush()
        version = ScriptVersion(
            script_id=script.id,
            version_no=1,
            config=body.config.model_dump(mode="json"),
            extraction_schema=body.extraction_schema,
        )
        session.add(version)
        await session.flush()
        audit.record(
            session,
            None,
            "script.create",
            actor_email="cli",
            entity_type="script",
            entity_id=script.id,
            department_id=department.id,
            changes={"name": script.name, "version_id": version.id, "via": "cli seed"},
        )
        await session.commit()
        print(f"Draft script created: {script.name} ({script.id}), version 1 ({version.id}). Submit it for approval.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin")
    admin.add_argument("--user-id", required=True, help="the ID the admin signs in with")
    admin.add_argument("--email")
    admin.add_argument("--name", required=True)
    dept = commands.add_parser("create-department")
    dept.add_argument("--code", required=True)
    dept.add_argument("--name", required=True)
    seed = commands.add_parser("seed-scm-script")
    seed.add_argument("--department", required=True, help="department code, e.g. SCM")
    args = parser.parse_args()

    if args.command == "create-admin":
        password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password (min 10 characters): ")
        if len(password) < 10:
            sys.exit("Password must be at least 10 characters")
        coro = create_admin(args.user_id, args.email, args.name, password)
    elif args.command == "create-department":
        coro = create_department(args.code, args.name)
    else:
        coro = seed_scm_script(args.department)

    async def run() -> None:
        try:
            await coro
        finally:
            await get_engine().dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
