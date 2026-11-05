import json

import pytest

from alembic import command
from app.models.enums import Role
from tests.conftest import PASSWORD, alembic_config

API = "/api/v1"


async def test_migrations_match_models():
    command.check(alembic_config())  # raises if models and migrations have drifted


async def test_health(client):
    assert (await client.get(f"{API}/health/live")).json() == {"status": "ok"}
    ready = await client.get(f"{API}/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"database": "ok", "redis": "ok"}


async def test_openapi_published(client):
    paths = (await client.get(f"{API}/openapi.json")).json()["paths"]
    assert f"{API}/contacts" in paths and f"{API}/auth/login" in paths


# ---- authentication ----


async def test_login_me_and_refresh(client, make_user, scm):
    hod = await make_user(Role.USER, scm, email="Hod.Scm@Example.com")
    # E-mail matching is case-insensitive.
    login = await client.post(f"{API}/auth/login", json={"email": "hod.scm@example.com", "password": PASSWORD})
    assert login.status_code == 200
    tokens = login.json()

    me = await client.get(f"{API}/auth/me", headers=hod.headers)
    assert me.status_code == 200
    body = me.json()
    assert body["role"] == "user" and body["department_id"] == str(scm.id)
    assert "contacts:view_full_number" in body["permissions"] and "departments:manage" not in body["permissions"]
    assert "password_hash" not in body

    refreshed = await client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    # An access token cannot be used as a refresh token.
    wrong = await client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert wrong.status_code == 401


async def test_unauthenticated_requests_rejected(client):
    assert (await client.get(f"{API}/auth/me")).status_code == 401
    assert (await client.get(f"{API}/contacts", headers={"Authorization": "Bearer junk"})).status_code == 401


async def test_failed_logins_are_generic_audited_and_locked_out(client, admin, scm, make_user):
    operator = await make_user(Role.USER, scm)
    # Mixing user ID and e-mail does not give extra attempts: the count is per account.
    for login in [operator.user.username, operator.user.email] * 2 + [operator.user.username.upper()]:
        bad = await client.post(f"{API}/auth/login", json={"login": login, "password": "wrong-password"})
        assert bad.status_code == 401
        assert bad.json()["error"]["message"] == "Invalid user ID or password"
    unknown = await client.post(f"{API}/auth/login", json={"login": "nobody", "password": "x" * 12})
    assert unknown.json()["error"]["message"] == "Invalid user ID or password"

    # Locked even with the right password.
    locked = await client.post(f"{API}/auth/login", json={"login": operator.user.username, "password": PASSWORD})
    assert locked.status_code == 429
    users = (await client.get(f"{API}/users?search={operator.user.username}", headers=admin.headers)).json()
    assert users["items"][0]["locked"] is True

    # The admin unlocks it.
    assert (await client.post(f"{API}/users/{operator.id}/unlock", headers=admin.headers)).json()["locked"] is False
    ok = await client.post(f"{API}/auth/login", json={"login": operator.user.username, "password": PASSWORD})
    assert ok.status_code == 200

    logs = (await client.get(f"{API}/audit-logs?action=auth.login_failed", headers=admin.headers)).json()
    assert logs["total"] == 6
    assert {e["changes"]["reason"] for e in logs["items"]} == {"wrong_password", "unknown_account"}


async def test_password_change_signs_out_old_tokens(client, make_user, scm):
    operator = await make_user(Role.USER, scm)
    changed = await client.post(
        f"{API}/auth/change-password",
        headers=operator.headers,
        json={"current_password": PASSWORD, "new_password": "A-New-Password-456"},
    )
    assert changed.status_code == 200
    assert (await client.get(f"{API}/auth/me", headers=operator.headers)).status_code == 401
    new_headers = {"Authorization": f"Bearer {changed.json()['access_token']}"}
    assert (await client.get(f"{API}/auth/me", headers=new_headers)).status_code == 200


async def test_deactivated_user_is_signed_out(client, admin, make_user, scm):
    operator = await make_user(Role.USER, scm)
    response = await client.patch(f"{API}/users/{operator.id}", headers=admin.headers, json={"is_active": False})
    assert response.status_code == 200
    assert (await client.get(f"{API}/auth/me", headers=operator.headers)).status_code == 401
    login = await client.post(f"{API}/auth/login", json={"email": operator.user.email, "password": PASSWORD})
    assert login.status_code == 401


# ---- departments and users ----


async def test_admin_manages_departments(client, admin, make_user, scm):
    created = await client.post(f"{API}/departments", headers=admin.headers, json={"code": "rnd", "name": "R&D"})
    assert created.status_code == 201 and created.json()["code"] == "RND"
    dup = await client.post(f"{API}/departments", headers=admin.headers, json={"code": "RND", "name": "Again"})
    assert dup.status_code == 409

    hod = await make_user(Role.USER, scm)
    forbidden = await client.post(f"{API}/departments", headers=hod.headers, json={"code": "X1", "name": "X"})
    assert forbidden.status_code == 403
    # Non-admins see only their own department.
    visible = (await client.get(f"{API}/departments", headers=hod.headers)).json()
    assert [d["code"] for d in visible] == ["SCM"]


async def test_only_admin_manages_accounts(client, admin, make_user, scm, quality):
    hod = await make_user(Role.USER, scm)
    qa_hod = await make_user(Role.USER, quality)
    body = {"username": "op1", "full_name": "Operator One", "role": "user", "department_id": str(scm.id)}

    # Users cannot see, create or change accounts; that is the admin's job.
    assert (await client.post(f"{API}/users", headers=hod.headers, json=body)).status_code == 403
    assert (
        await client.patch(f"{API}/users/{qa_hod.id}", headers=hod.headers, json={"full_name": "x"})
    ).status_code == 403
    assert (
        await client.post(f"{API}/users/{qa_hod.id}/reset-password", headers=hod.headers, json={})
    ).status_code == 403
    assert (await client.get(f"{API}/users", headers=hod.headers)).status_code == 403
    assert (await client.get(f"{API}/users/{qa_hod.id}", headers=hod.headers)).status_code == 403

    created = await client.post(f"{API}/users", headers=admin.headers, json=body)
    assert created.status_code == 201
    assert created.json()["user"]["department_id"] == str(scm.id)


async def test_admin_creates_account_with_user_id_and_temporary_password(client, admin, scm):
    body = {"username": "Ravi.K", "full_name": "Ravi Kumar", "role": "user", "department_id": str(scm.id)}
    created = (await client.post(f"{API}/users", headers=admin.headers, json=body)).json()
    user, temp = created["user"], created["temporary_password"]
    assert user["username"] == "ravi.k" and user["email"] is None and user["must_change_password"] is True
    assert len(temp) == 12
    assert temp not in json.dumps((await client.get(f"{API}/audit-logs", headers=admin.headers)).json())

    # The user signs in with the user ID (any case) and must change the password before anything else.
    login = await client.post(f"{API}/auth/login", json={"login": "RAVI.K", "password": temp})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = (await client.get(f"{API}/auth/me", headers=headers)).json()
    assert me["must_change_password"] is True and me["username"] == "ravi.k"
    blocked = await client.get(f"{API}/contacts", headers=headers)
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "password_change_required"

    changed = await client.post(
        f"{API}/auth/change-password",
        headers=headers,
        json={"current_password": temp, "new_password": "My-Own-Password-9"},
    )
    assert changed.status_code == 200
    headers = {"Authorization": f"Bearer {changed.json()['access_token']}"}
    assert (await client.get(f"{API}/contacts", headers=headers)).status_code == 200
    assert (await client.get(f"{API}/auth/me", headers=headers)).json()["must_change_password"] is False

    # Admin-chosen password and duplicate user IDs.
    chosen = {**body, "username": "meena", "password": "Chosen-Pass-123", "email": "Meena@Example.com"}
    made = (await client.post(f"{API}/users", headers=admin.headers, json=chosen)).json()
    assert made["temporary_password"] == "Chosen-Pass-123" and made["user"]["email"] == "meena@example.com"
    assert (
        await client.post(f"{API}/users", headers=admin.headers, json={**body, "username": "RAVI.k"})
    ).status_code == 409
    bad_id = await client.post(f"{API}/users", headers=admin.headers, json={**body, "username": "a b"})
    assert bad_id.status_code == 422


async def test_admin_resets_password(client, admin, make_user, scm):
    operator = await make_user(Role.USER, scm)
    reset = (await client.post(f"{API}/users/{operator.id}/reset-password", headers=admin.headers, json={})).json()
    assert reset["user"]["must_change_password"] is True
    # Old sessions are signed out; the old password no longer works; the temporary one does.
    assert (await client.get(f"{API}/auth/me", headers=operator.headers)).status_code == 401
    old = await client.post(f"{API}/auth/login", json={"login": operator.user.username, "password": PASSWORD})
    assert old.status_code == 401
    new = await client.post(
        f"{API}/auth/login", json={"login": operator.user.username, "password": reset["temporary_password"]}
    )
    assert new.status_code == 200


async def test_admin_safety_rules(client, admin, make_user, scm):
    assert (
        await client.patch(f"{API}/users/{admin.id}", headers=admin.headers, json={"role": "user"})
    ).status_code == 403
    second = await make_user(Role.ADMIN)
    # Demoting the other admin is fine while one active admin remains.
    demoted = await client.patch(
        f"{API}/users/{second.id}", headers=admin.headers, json={"role": "user", "department_id": str(scm.id)}
    )
    assert demoted.status_code == 200 and demoted.json()["role"] == "user"
    # Moving a user to a role that needs a department, without one, is refused.
    third = await make_user(Role.ADMIN)
    assert (
        await client.patch(f"{API}/users/{third.id}", headers=admin.headers, json={"role": "user"})
    ).status_code == 422


async def test_last_admin_cannot_be_removed(make_user):
    """Through the API the last admin could only remove themselves, which the self-rule already blocks; the
    service also refuses it directly, whoever asks."""
    import uuid

    from app.core.context import RequestContext
    from app.core.errors import Conflict
    from app.db.session import get_sessionmaker
    from app.models.org import User
    from app.schemas.org import UserUpdate
    from app.services import org as org_service

    only = await make_user(Role.ADMIN)
    someone = User(id=uuid.uuid4(), username="x", role=Role.ADMIN)
    ctx = RequestContext(None, None, None)
    async with get_sessionmaker()() as session:
        for change in ({"is_active": False}, {"role": "user"}):
            with pytest.raises(Conflict, match="last active admin"):
                await org_service.update_user(session, someone, only.id, UserUpdate(**change), ctx)


async def test_non_admin_role_requires_department(client, admin):
    body = {"username": "nodept", "full_name": "A", "role": "user"}
    assert (await client.post(f"{API}/users", headers=admin.headers, json=body)).status_code == 422


async def test_operator_cannot_read_users_or_audit(client, make_user, scm):
    operator = await make_user(Role.USER, scm)
    assert (await client.get(f"{API}/users", headers=operator.headers)).status_code == 403
    assert (await client.get(f"{API}/audit-logs", headers=operator.headers)).status_code == 403


async def test_weak_password_rejected(client, admin, scm):
    body = {
        "username": "weak",
        "full_name": "A",
        "password": "short",
        "role": "user",
        "department_id": str(scm.id),
    }
    response = await client.post(f"{API}/users", headers=admin.headers, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
