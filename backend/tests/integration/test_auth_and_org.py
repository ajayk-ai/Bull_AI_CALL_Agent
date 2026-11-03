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
    hod = await make_user(Role.HOD, scm, email="Hod.Scm@Example.com")
    # E-mail matching is case-insensitive.
    login = await client.post(f"{API}/auth/login", json={"email": "hod.scm@example.com", "password": PASSWORD})
    assert login.status_code == 200
    tokens = login.json()

    me = await client.get(f"{API}/auth/me", headers=hod.headers)
    assert me.status_code == 200
    body = me.json()
    assert body["role"] == "hod" and body["department_id"] == str(scm.id)
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
    operator = await make_user(Role.OPERATOR, scm)
    for _ in range(5):
        bad = await client.post(f"{API}/auth/login", json={"email": operator.user.email, "password": "wrong-password"})
        assert bad.status_code == 401
        assert bad.json()["error"]["message"] == "Invalid email or password"
    unknown = await client.post(f"{API}/auth/login", json={"email": "nobody@example.com", "password": "x" * 12})
    assert unknown.json()["error"]["message"] == "Invalid email or password"

    # Locked even with the right password.
    locked = await client.post(f"{API}/auth/login", json={"email": operator.user.email, "password": PASSWORD})
    assert locked.status_code == 429

    logs = (await client.get(f"{API}/audit-logs?action=auth.login_failed", headers=admin.headers)).json()
    assert logs["total"] == 6
    assert {e["changes"]["reason"] for e in logs["items"]} == {"wrong_password", "unknown_email"}


async def test_password_change_signs_out_old_tokens(client, make_user, scm):
    operator = await make_user(Role.OPERATOR, scm)
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
    operator = await make_user(Role.OPERATOR, scm)
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

    hod = await make_user(Role.HOD, scm)
    forbidden = await client.post(f"{API}/departments", headers=hod.headers, json={"code": "X1", "name": "X"})
    assert forbidden.status_code == 403
    # Non-admins see only their own department.
    visible = (await client.get(f"{API}/departments", headers=hod.headers)).json()
    assert [d["code"] for d in visible] == ["SCM"]


async def test_hod_user_management_is_limited_to_own_department(client, make_user, scm, quality):
    hod = await make_user(Role.HOD, scm)
    other_hod = await make_user(Role.HOD, quality)

    created = await client.post(
        f"{API}/users",
        headers=hod.headers,
        json={"email": "op1@example.com", "full_name": "Operator One", "password": PASSWORD, "role": "operator"},
    )
    assert created.status_code == 201
    assert created.json()["department_id"] == str(scm.id)  # forced to the HOD's department

    for payload, expected in [
        ({"role": "hod"}, 403),
        ({"role": "admin"}, 403),
        ({"role": "operator", "department_id": str(quality.id)}, 403),
    ]:
        body = {"email": "x@example.com", "full_name": "X", "password": PASSWORD, **payload}
        assert (await client.post(f"{API}/users", headers=hod.headers, json=body)).status_code == expected

    # Users of another department are invisible.
    assert (await client.get(f"{API}/users/{other_hod.id}", headers=hod.headers)).status_code == 404
    listed = (await client.get(f"{API}/users", headers=hod.headers)).json()
    assert other_hod.user.email not in {u["email"] for u in listed["items"]}

    # A HOD cannot edit a peer HOD or themselves into another role.
    peer = await make_user(Role.HOD, scm)
    assert (
        await client.patch(f"{API}/users/{peer.id}", headers=hod.headers, json={"full_name": "Z"})
    ).status_code == 403
    assert (
        await client.patch(f"{API}/users/{hod.id}", headers=hod.headers, json={"role": "operator"})
    ).status_code == 403


async def test_duplicate_email_case_insensitive(client, admin, scm):
    body = {
        "email": "Dup@Example.com",
        "full_name": "A",
        "password": PASSWORD,
        "role": "operator",
        "department_id": str(scm.id),
    }
    assert (await client.post(f"{API}/users", headers=admin.headers, json=body)).status_code == 201
    body["email"] = "dup@example.com"
    assert (await client.post(f"{API}/users", headers=admin.headers, json=body)).status_code == 409


async def test_non_admin_role_requires_department(client, admin):
    body = {"email": "nodept@example.com", "full_name": "A", "password": PASSWORD, "role": "operator"}
    assert (await client.post(f"{API}/users", headers=admin.headers, json=body)).status_code == 422


async def test_operator_cannot_read_users_or_audit(client, make_user, scm):
    operator = await make_user(Role.OPERATOR, scm)
    assert (await client.get(f"{API}/users", headers=operator.headers)).status_code == 403
    assert (await client.get(f"{API}/audit-logs", headers=operator.headers)).status_code == 403


async def test_weak_password_rejected(client, admin, scm):
    body = {
        "email": "weak@example.com",
        "full_name": "A",
        "password": "short",
        "role": "operator",
        "department_id": str(scm.id),
    }
    response = await client.post(f"{API}/users", headers=admin.headers, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
