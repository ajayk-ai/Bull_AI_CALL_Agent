import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models.contacts import Contact
from app.models.enums import Role

API = "/api/v1"
NUMBER = "9876543210"
E164 = "+919876543210"


def contact_body(**overrides):
    return {
        "name": "ABC Industries - Ravi",
        "phone": NUMBER,
        "company": "ABC Industries",
        "language": "ta-IN",
        "custom_fields": {"po_number": "450001", "material": "Hydraulic hose"},
        **overrides,
    }


async def test_create_contact_masks_and_encrypts_number(client, make_user, scm):
    manager = await make_user(Role.CAMPAIGN_MANAGER, scm)
    response = await client.post(f"{API}/contacts", headers=manager.headers, json=contact_body())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["phone_masked"] == "+91******3210"
    assert body["department_id"] == str(scm.id)
    assert body["do_not_call"] is False
    assert NUMBER not in json.dumps(body)

    async with get_sessionmaker()() as session:
        stored = await session.scalar(select(Contact))
    assert NUMBER not in stored.phone_encrypted and E164 not in stored.phone_encrypted


async def test_duplicate_detection_across_formats_and_departments(client, admin, make_user, scm, quality):
    manager = await make_user(Role.CAMPAIGN_MANAGER, scm)
    first = await client.post(f"{API}/contacts", headers=manager.headers, json=contact_body())
    dup = await client.post(f"{API}/contacts", headers=manager.headers, json=contact_body(phone="+91 98765-43210"))
    assert dup.status_code == 409
    assert dup.json()["error"]["details"]["existing_contact_id"] == first.json()["id"]

    # The same number may exist once in another department.
    other = await client.post(
        f"{API}/contacts", headers=admin.headers, json=contact_body(department_id=str(quality.id))
    )
    assert other.status_code == 201


async def test_deleted_contact_frees_the_number(client, make_user, scm):
    manager = await make_user(Role.CAMPAIGN_MANAGER, scm)
    first = (await client.post(f"{API}/contacts", headers=manager.headers, json=contact_body())).json()
    assert (await client.delete(f"{API}/contacts/{first['id']}", headers=manager.headers)).status_code == 204
    assert (await client.get(f"{API}/contacts/{first['id']}", headers=manager.headers)).status_code == 404
    again = await client.post(f"{API}/contacts", headers=manager.headers, json=contact_body())
    assert again.status_code == 201


async def test_department_isolation(client, make_user, scm, quality):
    scm_manager = await make_user(Role.CAMPAIGN_MANAGER, scm)
    qa_hod = await make_user(Role.HOD, quality)
    contact = (await client.post(f"{API}/contacts", headers=scm_manager.headers, json=contact_body())).json()

    assert (await client.get(f"{API}/contacts/{contact['id']}", headers=qa_hod.headers)).status_code == 404
    patch = await client.patch(f"{API}/contacts/{contact['id']}", headers=qa_hod.headers, json={"name": "Hijack"})
    assert patch.status_code == 404
    assert (await client.delete(f"{API}/contacts/{contact['id']}", headers=qa_hod.headers)).status_code == 404
    assert (await client.get(f"{API}/contacts/{contact['id']}/phone", headers=qa_hod.headers)).status_code == 404
    assert (await client.get(f"{API}/contacts", headers=qa_hod.headers)).json()["total"] == 0
    # Filtering by another department's id does not widen the scope.
    scoped = await client.get(f"{API}/contacts?department_id={scm.id}", headers=qa_hod.headers)
    assert scoped.json()["total"] == 0
    # Writing into another department is refused.
    cross = await client.post(
        f"{API}/contacts", headers=qa_hod.headers, json=contact_body(department_id=str(scm.id), phone="9876500001")
    )
    assert cross.status_code == 403


async def test_role_permissions_on_contacts(client, make_user, scm):
    operator = await make_user(Role.OPERATOR, scm)
    manager = await make_user(Role.CAMPAIGN_MANAGER, scm)
    contact = (await client.post(f"{API}/contacts", headers=manager.headers, json=contact_body())).json()

    assert (await client.get(f"{API}/contacts/{contact['id']}", headers=operator.headers)).status_code == 200
    assert (await client.post(f"{API}/contacts", headers=operator.headers, json=contact_body())).status_code == 403
    assert (await client.delete(f"{API}/contacts/{contact['id']}", headers=operator.headers)).status_code == 403
    # Only HOD and admin can see the full number.
    assert (await client.get(f"{API}/contacts/{contact['id']}/phone", headers=manager.headers)).status_code == 403


async def test_reveal_phone_is_audited(client, make_user, scm):
    hod = await make_user(Role.HOD, scm)
    contact = (await client.post(f"{API}/contacts", headers=hod.headers, json=contact_body())).json()
    revealed = await client.get(f"{API}/contacts/{contact['id']}/phone", headers=hod.headers)
    assert revealed.json()["phone"] == E164

    logs = (await client.get(f"{API}/audit-logs?entity_id={contact['id']}", headers=hod.headers)).json()
    assert [e["action"] for e in logs["items"]] == ["contact.phone_revealed", "contact.create"]
    assert NUMBER not in json.dumps(logs)


async def test_search_and_update(client, make_user, scm):
    manager = await make_user(Role.CAMPAIGN_MANAGER, scm)
    a = (await client.post(f"{API}/contacts", headers=manager.headers, json=contact_body())).json()
    await client.post(
        f"{API}/contacts",
        headers=manager.headers,
        json=contact_body(name="XYZ Castings", company="XYZ", phone="9123456780", language="hi-IN"),
    )

    by_phone = await client.get(f"{API}/contacts", headers=manager.headers, params={"search": "+91 98765 43210"})
    assert [c["id"] for c in by_phone.json()["items"]] == [a["id"]]
    by_name = await client.get(f"{API}/contacts", headers=manager.headers, params={"search": "xyz"})
    assert by_name.json()["total"] == 1
    by_language = await client.get(f"{API}/contacts", headers=manager.headers, params={"language": "hi-IN"})
    assert by_language.json()["total"] == 1

    # Changing to a number another contact already has is refused.
    clash = await client.patch(f"{API}/contacts/{a['id']}", headers=manager.headers, json={"phone": "9123456780"})
    assert clash.status_code == 409
    updated = await client.patch(
        f"{API}/contacts/{a['id']}", headers=manager.headers, json={"phone": "9000012345", "language": "en-IN"}
    )
    assert updated.status_code == 200
    assert updated.json()["phone_masked"] == "+91******2345" and updated.json()["language"] == "en-IN"


async def test_contact_validation(client, make_user, scm):
    manager = await make_user(Role.CAMPAIGN_MANAGER, scm)
    for bad in [
        {"phone": "12345"},
        {"language": "tamil"},
        {"name": "   "},
        {"custom_fields": {"x" * 65: "too long a key"}},
    ]:
        response = await client.post(f"{API}/contacts", headers=manager.headers, json=contact_body(**bad))
        assert response.status_code == 422, bad


# ---- do-not-call ----


async def test_dnc_flags_contacts_and_respects_scope(client, admin, make_user, scm, quality):
    operator = await make_user(Role.OPERATOR, scm)
    manager = await make_user(Role.CAMPAIGN_MANAGER, scm)
    qa_manager = await make_user(Role.CAMPAIGN_MANAGER, quality)
    contact = (await client.post(f"{API}/contacts", headers=manager.headers, json=contact_body())).json()
    qa_contact = (await client.post(f"{API}/contacts", headers=qa_manager.headers, json=contact_body())).json()

    # An operator records an opt-out for their department.
    entry = await client.post(
        f"{API}/dnc", headers=operator.headers, json={"phone": "+91 98765 43210", "reason": "Asked not to be called"}
    )
    assert entry.status_code == 201 and entry.json()["department_id"] == str(scm.id)
    again = await client.post(f"{API}/dnc", headers=operator.headers, json={"phone": NUMBER, "reason": "again"})
    assert again.status_code == 409

    assert (await client.get(f"{API}/contacts/{contact['id']}", headers=manager.headers)).json()["do_not_call"]
    listed = (await client.get(f"{API}/contacts", headers=manager.headers)).json()["items"]
    assert listed[0]["do_not_call"] is True
    # Department-level suppression does not affect other departments.
    assert not (await client.get(f"{API}/contacts/{qa_contact['id']}", headers=qa_manager.headers)).json()[
        "do_not_call"
    ]

    # Global entries are admin-only and apply everywhere.
    glob = {"phone": NUMBER, "reason": "Legal request", "global_scope": True}
    assert (await client.post(f"{API}/dnc", headers=manager.headers, json=glob)).status_code == 403
    assert (await client.post(f"{API}/dnc", headers=admin.headers, json=glob)).status_code == 201
    assert (await client.get(f"{API}/contacts/{qa_contact['id']}", headers=qa_manager.headers)).json()["do_not_call"]

    # Operators cannot remove entries; HODs can remove their department's but not global ones.
    entries = (await client.get(f"{API}/dnc", headers=operator.headers)).json()
    assert entries["total"] == 2
    assert NUMBER not in json.dumps(entries)
    dept_entry = next(e for e in entries["items"] if e["department_id"])
    global_entry = next(e for e in entries["items"] if not e["department_id"])
    assert (await client.delete(f"{API}/dnc/{dept_entry['id']}", headers=operator.headers)).status_code == 403
    hod = await make_user(Role.HOD, scm)
    assert (await client.delete(f"{API}/dnc/{global_entry['id']}", headers=hod.headers)).status_code == 403
    assert (await client.delete(f"{API}/dnc/{dept_entry['id']}", headers=hod.headers)).status_code == 204


async def test_expired_dnc_no_longer_suppresses(client, make_user, scm):
    manager = await make_user(Role.CAMPAIGN_MANAGER, scm)
    contact = (await client.post(f"{API}/contacts", headers=manager.headers, json=contact_body())).json()
    expired = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    await client.post(
        f"{API}/dnc", headers=manager.headers, json={"phone": NUMBER, "reason": "temporary", "expires_at": expired}
    )
    assert not (await client.get(f"{API}/contacts/{contact['id']}", headers=manager.headers)).json()["do_not_call"]


# ---- consent ----


async def test_consent_history_is_kept(client, make_user, scm):
    operator = await make_user(Role.OPERATOR, scm)
    manager = await make_user(Role.CAMPAIGN_MANAGER, scm)
    contact = (await client.post(f"{API}/contacts", headers=manager.headers, json=contact_body())).json()
    url = f"{API}/contacts/{contact['id']}/consents"
    granted = {
        "consent_type": "recording",
        "status": "granted",
        "source": "supplier agreement",
        "captured_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
    }
    withdrawn = {"consent_type": "recording", "status": "withdrawn", "source": "call"}
    assert (await client.post(url, headers=operator.headers, json=granted)).status_code == 201
    assert (await client.post(url, headers=operator.headers, json=withdrawn)).status_code == 201

    history = (await client.get(url, headers=operator.headers)).json()
    assert [r["status"] for r in history] == ["withdrawn", "granted"]
    bad = await client.post(url, headers=operator.headers, json={**withdrawn, "consent_type": "marketing"})
    assert bad.status_code == 422


# ---- audit ----


async def test_audit_scope_and_redaction(client, admin, make_user, scm, quality):
    scm_hod = await make_user(Role.HOD, scm)
    qa_hod = await make_user(Role.HOD, quality)
    contact = (await client.post(f"{API}/contacts", headers=scm_hod.headers, json=contact_body())).json()
    await client.patch(f"{API}/contacts/{contact['id']}", headers=scm_hod.headers, json={"phone": "9000012345"})

    scm_logs = (await client.get(f"{API}/audit-logs?entity_type=contact", headers=scm_hod.headers)).json()
    assert scm_logs["total"] == 2
    update = next(e for e in scm_logs["items"] if e["action"] == "contact.update")
    assert update["changes"]["phone_masked"] == {"from": "+91******3210", "to": "+91******2345"}
    assert update["actor_email"] == scm_hod.user.email and update["request_id"]
    text = json.dumps(scm_logs)
    assert NUMBER not in text and "9000012345" not in text

    assert (await client.get(f"{API}/audit-logs?entity_type=contact", headers=qa_hod.headers)).json()["total"] == 0
    assert (await client.get(f"{API}/audit-logs?entity_type=contact", headers=admin.headers)).json()["total"] == 2
