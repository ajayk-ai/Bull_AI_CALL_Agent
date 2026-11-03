"""Administrative commands.

    python -m app.cli create-admin --email admin@bullmachine.com --name "Platform Admin"
    python -m app.cli create-department --code SCM --name "Supply Chain Management"

The admin password is read from the prompt (or ADMIN_PASSWORD), never from the command line.
"""

import argparse
import asyncio
import getpass
import os
import sys

from app.core.security import hash_password
from app.db.session import get_engine, get_sessionmaker
from app.models.enums import Role
from app.models.org import Department, User
from app.services import audit
from app.services.auth import find_by_email


async def create_admin(email: str, name: str, password: str) -> None:
    async with get_sessionmaker()() as session:
        if await find_by_email(session, email):
            sys.exit(f"A user with email {email} already exists")
        user = User(email=email.lower(), full_name=name, password_hash=hash_password(password), role=Role.ADMIN)
        session.add(user)
        await session.flush()
        audit.record(
            session,
            None,
            "user.create",
            actor_email="cli",
            entity_type="user",
            entity_id=user.id,
            changes={"email": user.email, "role": Role.ADMIN, "via": "cli"},
        )
        await session.commit()
        print(f"Admin created: {user.email} ({user.id})")


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    dept = commands.add_parser("create-department")
    dept.add_argument("--code", required=True)
    dept.add_argument("--name", required=True)
    args = parser.parse_args()

    if args.command == "create-admin":
        password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password (min 10 characters): ")
        if len(password) < 10:
            sys.exit("Password must be at least 10 characters")
        coro = create_admin(args.email, args.name, password)
    else:
        coro = create_department(args.code, args.name)

    async def run() -> None:
        try:
            await coro
        finally:
            await get_engine().dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
