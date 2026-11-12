import copy
from datetime import date, timedelta

import pytest

from app.models.enums import Role
from app.seeds import scm_delivery

API = "/api/v1"
ITEM = {"po_number": "450001", "material_description": "Hydraulic hose", "original_delivery_date": "2026-11-05"}


def script_body(**extra) -> dict:
    return {
        "name": "SCM Delivery",
        "config": copy.deepcopy(scm_delivery.CONFIG),
        "extraction_schema": copy.deepcopy(scm_delivery.EXTRACTION_SCHEMA),
        **extra,
    }


@pytest.fixture
async def team(make_user, scm):
    return {
        "manager": await make_user(Role.USER, scm),
        "hod": await make_user(Role.USER, scm),
        "operator": await make_user(Role.USER, scm),
    }


async def publish_script(client, team) -> tuple[str, str]:
    """Create, submit and approve a script. Returns (script_id, version_id)."""
    script = (await client.post(f"{API}/scripts", headers=team["manager"].headers, json=script_body())).json()
    version_id = script["versions"][0]["id"]
    await client.post(f"{API}/script-versions/{version_id}/submit", headers=team["manager"].headers)
    approved = await client.post(f"{API}/script-versions/{version_id}/approve", headers=team["hod"].headers, json={})
    assert approved.status_code == 200, approved.text
    return script["id"], version_id


# ---- scripts ----


async def test_script_version_lifecycle(client, team, admin):
    manager, hod = team["manager"], team["hod"]
    created = await client.post(f"{API}/scripts", headers=manager.headers, json=script_body())
    assert created.status_code == 201, created.text
    script = created.json()
    v1 = script["versions"][0]
    assert v1["version_no"] == 1 and v1["status"] == "draft"

    # Only one open version at a time.
    second = await client.post(f"{API}/scripts/{script['id']}/versions", headers=manager.headers, json=script_body())
    assert second.status_code == 409

    # Drafts are editable.
    body = script_body()
    body["config"]["limits"]["max_call_seconds"] = 240
    edited = await client.put(f"{API}/script-versions/{v1['id']}", headers=manager.headers, json=body)
    assert edited.json()["config"]["limits"]["max_call_seconds"] == 240

    # Approval needs a second person: the author cannot approve; a colleague can. Nothing to approve before submit.
    assert (
        await client.post(f"{API}/script-versions/{v1['id']}/approve", headers=hod.headers, json={})
    ).status_code == 409
    await client.post(f"{API}/script-versions/{v1['id']}/submit", headers=manager.headers)
    response = await client.post(f"{API}/script-versions/{v1['id']}/approve", headers=manager.headers, json={})
    assert response.status_code == 403
    rejected = await client.post(
        f"{API}/script-versions/{v1['id']}/reject", headers=hod.headers, json={"comments": "Shorten the intro"}
    )
    assert rejected.json()["status"] == "draft"
    await client.post(f"{API}/script-versions/{v1['id']}/submit", headers=manager.headers)
    published = (await client.post(f"{API}/script-versions/{v1['id']}/approve", headers=hod.headers, json={})).json()
    assert published["status"] == "published" and published["approved_by_id"] == str(hod.id)

    # Published versions are frozen.
    assert (
        await client.put(f"{API}/script-versions/{v1['id']}", headers=manager.headers, json=body)
    ).status_code == 409

    # Version 2 retires version 1 when published.
    v2 = (
        await client.post(f"{API}/scripts/{script['id']}/versions", headers=manager.headers, json=script_body())
    ).json()
    assert v2["version_no"] == 2
    await client.post(f"{API}/script-versions/{v2['id']}/submit", headers=manager.headers)
    await client.post(f"{API}/script-versions/{v2['id']}/approve", headers=hod.headers, json={})
    statuses = {
        v["version_no"]: v["status"]
        for v in (await client.get(f"{API}/scripts/{script['id']}", headers=manager.headers)).json()["versions"]
    }
    assert statuses == {1: "retired", 2: "published"}

    actions = [
        e["action"]
        for e in (await client.get(f"{API}/audit-logs?entity_id={v1['id']}", headers=admin.headers)).json()["items"]
    ]
    assert actions.count("script_version.approve") == 1 and "script_version.reject" in actions


async def test_author_cannot_approve_own_script(client, make_user, scm):
    hod = await make_user(Role.USER, scm)
    script = (await client.post(f"{API}/scripts", headers=hod.headers, json=script_body())).json()
    version_id = script["versions"][0]["id"]
    await client.post(f"{API}/script-versions/{version_id}/submit", headers=hod.headers)
    response = await client.post(f"{API}/script-versions/{version_id}/approve", headers=hod.headers, json={})
    assert response.status_code == 403
    assert "other than its author" in response.json()["error"]["message"]


async def test_author_can_publish_own_script_when_second_approver_not_required(client, make_user, scm, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "require_second_approver", False)
    author = await make_user(Role.USER, scm)
    me = (await client.get(f"{API}/auth/me", headers=author.headers)).json()
    assert me["second_approver_required"] is False
    script = (await client.post(f"{API}/scripts", headers=author.headers, json=script_body())).json()
    version_id = script["versions"][0]["id"]
    await client.post(f"{API}/script-versions/{version_id}/submit", headers=author.headers)
    response = await client.post(f"{API}/script-versions/{version_id}/approve", headers=author.headers, json={})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "published"


async def test_invalid_script_rejected_and_scripts_are_department_scoped(client, team, make_user, scm, quality):
    bad = script_body()
    bad["config"]["closing"]["statement"] = "Thanks {context.unknown_field}"
    response = await client.post(f"{API}/scripts", headers=team["manager"].headers, json=bad)
    assert response.status_code == 422

    script = (await client.post(f"{API}/scripts", headers=team["manager"].headers, json=script_body())).json()
    qa = await make_user(Role.USER, quality)
    assert (await client.get(f"{API}/scripts/{script['id']}", headers=qa.headers)).status_code == 404
    assert (await client.get(f"{API}/scripts", headers=qa.headers)).json() == []
    assert (await client.get(f"{API}/scripts", headers=team["operator"].headers)).status_code == 200
    # A user cannot create a script in another department.
    assert (
        await client.post(f"{API}/scripts", headers=qa.headers, json=script_body(department_id=str(scm.id)))
    ).status_code == 403


# ---- campaigns ----


async def make_contact(client, actor, phone="9876543210", name="ABC Industries") -> str:
    response = await client.post(
        f"{API}/contacts", headers=actor.headers, json={"name": name, "phone": phone, "company": name}
    )
    return response.json()["id"]


async def test_campaign_end_to_end_approval(client, team):
    manager, hod = team["manager"], team["hod"]
    _, version_id = await publish_script(client, team)
    created = await client.post(
        f"{API}/campaigns",
        headers=manager.headers,
        json={"name": "Nov deliveries", "script_version_id": version_id, "language": "ta-IN"},
    )
    assert created.status_code == 201, created.text
    campaign = created.json()
    assert campaign["status"] == "draft" and campaign["owner_id"] == str(manager.id)
    assert campaign["calling_window"]["timezone"] == "Asia/Kolkata" and campaign["max_concurrency"] == 5

    # Not ready: no contacts.
    not_ready = await client.post(f"{API}/campaigns/{campaign['id']}/submit", headers=manager.headers)
    assert not_ready.status_code == 422
    assert "The campaign has no contacts" in not_ready.json()["error"]["details"]["problems"]

    contact_id = await make_contact(client, manager)
    # Contact without the PO data the script needs.
    await client.post(
        f"{API}/campaigns/{campaign['id']}/contacts", headers=manager.headers, json={"contact_ids": [contact_id]}
    )
    missing = await client.post(f"{API}/campaigns/{campaign['id']}/submit", headers=manager.headers)
    assert any("no campaign data" in p for p in missing.json()["error"]["details"]["problems"])

    await client.delete(f"{API}/campaigns/{campaign['id']}/contacts/{contact_id}", headers=manager.headers)
    added = await client.post(
        f"{API}/campaigns/{campaign['id']}/contacts",
        headers=manager.headers,
        json={"contact_ids": [contact_id, contact_id], "context": {"items": [ITEM]}},
    )
    assert added.json() == {"added": 1, "already_present": 0}

    submitted = await client.post(f"{API}/campaigns/{campaign['id']}/submit", headers=manager.headers)
    assert submitted.status_code == 200 and submitted.json()["status"] == "pending_approval"
    # Frozen while pending.
    assert (
        await client.patch(f"{API}/campaigns/{campaign['id']}", headers=manager.headers, json={"name": "x"})
    ).status_code == 409

    # The submitter cannot approve; the HOD can.
    assert (
        await client.post(f"{API}/campaigns/{campaign['id']}/approve", headers=manager.headers, json={})
    ).status_code == 403
    approved = await client.post(
        f"{API}/campaigns/{campaign['id']}/approve", headers=hod.headers, json={"comments": "OK"}
    )
    assert approved.json()["status"] == "approved"

    history = (await client.get(f"{API}/campaigns/{campaign['id']}/approvals", headers=team["operator"].headers)).json()
    assert history[0]["decision"] == "approved" and history[0]["decided_by_id"] == str(hod.id)

    members = (await client.get(f"{API}/campaigns/{campaign['id']}/contacts", headers=manager.headers)).json()
    assert members["total"] == 1 and members["items"][0]["phone_masked"] == "+91******3210"

    cancelled = await client.post(f"{API}/campaigns/{campaign['id']}/cancel", headers=manager.headers, json={})
    assert cancelled.json()["status"] == "cancelled"
    again = await client.post(f"{API}/campaigns/{campaign['id']}/cancel", headers=manager.headers, json={})
    assert again.status_code == 409


async def test_hod_self_submitted_campaign_needs_another_approver(client, team, admin):
    _, version_id = await publish_script(client, team)
    hod = team["hod"]
    campaign = (
        await client.post(f"{API}/campaigns", headers=hod.headers, json={"name": "C", "script_version_id": version_id})
    ).json()
    contact_id = await make_contact(client, hod)
    await client.post(
        f"{API}/campaigns/{campaign['id']}/contacts",
        headers=hod.headers,
        json={"contact_ids": [contact_id], "context": {"items": [ITEM]}},
    )
    await client.post(f"{API}/campaigns/{campaign['id']}/submit", headers=hod.headers)
    assert (
        await client.post(f"{API}/campaigns/{campaign['id']}/approve", headers=hod.headers, json={})
    ).status_code == 403
    rejected = await client.post(
        f"{API}/campaigns/{campaign['id']}/reject", headers=hod.headers, json={"comments": "redo"}
    )
    assert rejected.json()["status"] == "draft"  # anyone with approval rights may send it back
    await client.post(f"{API}/campaigns/{campaign['id']}/submit", headers=hod.headers)
    assert (await client.post(f"{API}/campaigns/{campaign['id']}/approve", headers=admin.headers, json={})).json()[
        "status"
    ] == "approved"


async def test_campaign_validation(client, team, make_user, quality, admin):
    manager = team["manager"]
    qa_user = await make_user(Role.USER, quality)
    script = (await client.post(f"{API}/scripts", headers=manager.headers, json=script_body())).json()
    draft_version = script["versions"][0]["id"]
    # Draft scripts cannot be used.
    response = await client.post(
        f"{API}/campaigns", headers=manager.headers, json={"name": "C", "script_version_id": draft_version}
    )
    assert response.status_code == 422 and "published" in response.json()["error"]["message"]

    # Publish a second script for the remaining checks.
    script2 = (await client.post(f"{API}/scripts", headers=manager.headers, json=script_body(name="Other"))).json()
    v = script2["versions"][0]["id"]
    await client.post(f"{API}/script-versions/{v}/submit", headers=manager.headers)
    await client.post(f"{API}/script-versions/{v}/approve", headers=team["hod"].headers, json={})

    cases = [
        ({"language": "kn-IN"}, 422),  # not allowed by the script
        ({"max_concurrency": 6}, 422),  # above the platform limit of 5
        ({"start_date": "2026-12-10", "end_date": "2026-12-01"}, 422),
        ({"calling_window": {"start": "19:00", "end": "09:00"}}, 422),
        ({"owner_id": str(qa_user.id)}, 422),  # the owner must belong to the campaign's department
    ]
    for extra, expected in cases:
        body = {"name": "C", "script_version_id": v, **extra}
        assert (await client.post(f"{API}/campaigns", headers=manager.headers, json=body)).status_code == expected, (
            extra
        )

    # Another department's script version is not usable.
    qa_campaign = await client.post(
        f"{API}/campaigns",
        headers=admin.headers,
        json={"name": "QA", "department_id": str(quality.id), "script_version_id": v},
    )
    assert qa_campaign.status_code == 422

    # Past end date blocks submission.
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    campaign = (
        await client.post(
            f"{API}/campaigns",
            headers=manager.headers,
            json={"name": "Old", "script_version_id": v, "end_date": yesterday},
        )
    ).json()
    problems = (await client.post(f"{API}/campaigns/{campaign['id']}/submit", headers=manager.headers)).json()
    assert "The end date is in the past" in problems["error"]["details"]["problems"]

    # Fields that must not be cleared.
    patch = await client.patch(f"{API}/campaigns/{campaign['id']}", headers=manager.headers, json={"name": None})
    assert patch.status_code == 422


async def test_campaigns_are_department_scoped(client, team, make_user, quality):
    _, version_id = await publish_script(client, team)
    campaign = (
        await client.post(
            f"{API}/campaigns", headers=team["manager"].headers, json={"name": "C", "script_version_id": version_id}
        )
    ).json()
    qa = await make_user(Role.USER, quality)
    assert (await client.get(f"{API}/campaigns/{campaign['id']}", headers=qa.headers)).status_code == 404
    assert (await client.get(f"{API}/campaigns", headers=qa.headers)).json()["total"] == 0
    # A QA contact cannot be added to an SCM campaign.
    qa_contact = await make_contact(client, qa)
    response = await client.post(
        f"{API}/campaigns/{campaign['id']}/contacts",
        headers=team["manager"].headers,
        json={"contact_ids": [qa_contact]},
    )
    assert response.status_code == 422
