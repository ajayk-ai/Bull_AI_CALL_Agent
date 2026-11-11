"""The campaign dialer: one channel, one call at a time, with retries and skips."""

import copy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.models.calls import Call
from app.models.campaigns import CampaignContact
from app.models.enums import CallStatus, Role
from app.providers.telephony.mock import MockTelephony
from app.seeds import scm_delivery
from app.services import calls, dialer
from app.voice.session import SessionResult
from tests.fakes import FakeEngine

API = "/api/v1"
MONDAY_10_30_IST = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)
SUNDAY = datetime(2026, 11, 15, 5, 0, tzinfo=UTC)


def items(po: str) -> dict:
    return {"items": [{"po_number": po, "material_description": "Hose", "original_delivery_date": "2026-11-30"}]}


@pytest.fixture
async def team(make_user, scm):
    return {"manager": await make_user(Role.USER, scm), "checker": await make_user(Role.USER, scm)}


async def running_campaign(client, team, phones: list[str]) -> tuple[dict, list[str]]:
    manager, checker = team["manager"], team["checker"]
    body = {
        "name": "SCM",
        "config": copy.deepcopy(scm_delivery.CONFIG),
        "extraction_schema": copy.deepcopy(scm_delivery.EXTRACTION_SCHEMA),
    }
    version = (await client.post(f"{API}/scripts", headers=manager.headers, json=body)).json()["versions"][0]["id"]
    await client.post(f"{API}/script-versions/{version}/submit", headers=manager.headers)
    await client.post(f"{API}/script-versions/{version}/approve", headers=checker.headers, json={})
    campaign = (
        await client.post(
            f"{API}/campaigns", headers=manager.headers, json={"name": "Nov", "script_version_id": version}
        )
    ).json()
    contact_ids = []
    for i, number in enumerate(phones):
        contact = await client.post(
            f"{API}/contacts", headers=manager.headers, json={"name": f"Supplier {i}", "phone": number}
        )
        contact_ids.append(contact.json()["id"])
        added = await client.post(
            f"{API}/campaigns/{campaign['id']}/contacts",
            headers=manager.headers,
            json={"contact_ids": [contact_ids[-1]], "context": items(f"45000{i}")},
        )
        assert added.status_code == 200, added.text
    assert (await client.post(f"{API}/campaigns/{campaign['id']}/submit", headers=manager.headers)).status_code == 200
    approved = await client.post(f"{API}/campaigns/{campaign['id']}/approve", headers=checker.headers, json={})
    assert approved.status_code == 200, approved.text
    started = await client.post(f"{API}/campaigns/{campaign['id']}/start", headers=manager.headers)
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "running"
    return campaign, contact_ids


async def tick(telephony, now) -> Call | None:
    async with get_sessionmaker()() as session:
        return await dialer.tick(session, telephony, FakeEngine(), now=now)


async def answered(call_id, outcome: str = "completed") -> None:
    """The call was answered and the conversation ended with this outcome."""
    async with get_sessionmaker()() as session:
        call = await session.get(Call, call_id)
        call.status = CallStatus.IN_PROGRESS
        await session.commit()
        turns = [{"turn_id": 1, "speaker": "caller", "text": "Yes, on time."}]
        await calls.finish(session, call_id, SessionResult(end_reason="agent_end_call", outcome=outcome, turns=turns))


async def not_answered(call_id) -> None:
    async with get_sessionmaker()() as session:
        call = await session.get(Call, call_id)
        call.status = CallStatus.NO_ANSWER
        call.ended_at = MONDAY_10_30_IST
        await session.commit()
        await calls._release_lock(call)


async def statuses(campaign_id) -> list[tuple[str, int, str | None]]:
    async with get_sessionmaker()() as session:
        rows = await session.scalars(
            select(CampaignContact)
            .where(CampaignContact.campaign_id == campaign_id)
            .order_by(CampaignContact.created_at)
        )
        return [(str(cc.status), cc.attempts, cc.outcome) for cc in rows]


async def test_calls_go_out_one_at_a_time_with_retries(client, team):
    telephony = MockTelephony()
    campaign, _ = await running_campaign(client, team, ["9000000001", "9000000002"])
    now = MONDAY_10_30_IST

    first = await tick(telephony, now)
    assert first is not None and first.campaign_id is not None and first.attempt_no == 1
    # One channel: nothing else is placed while the first call is in progress.
    assert await tick(telephony, now) is None
    assert len(telephony.placed) == 1

    await answered(first.id)
    second = await tick(telephony, now)  # settles the first contact, then calls the second
    assert second is not None and second.id != first.id
    assert telephony.placed[1][0] == "+919000000002"

    # No answer: retried after the campaign's retry interval (60 minutes), not before.
    await not_answered(second.id)
    assert await tick(telephony, now) is None
    assert await statuses(campaign["id"]) == [("completed", 1, "completed"), ("retry_scheduled", 1, "no_answer")]
    assert await tick(telephony, now + timedelta(minutes=30)) is None
    retry = await tick(telephony, now + timedelta(minutes=61))
    assert retry is not None and retry.attempt_no == 2

    await answered(retry.id)
    assert await tick(telephony, now + timedelta(minutes=62)) is None
    assert await statuses(campaign["id"]) == [("completed", 1, "completed"), ("completed", 2, "completed")]
    detail = (await client.get(f"{API}/campaigns/{campaign['id']}", headers=team["manager"].headers)).json()
    assert detail["status"] == "completed" and detail["progress"] == {"completed": 2}


async def test_gives_up_after_max_attempts_and_skips_do_not_call(client, team, admin):
    telephony = MockTelephony()
    campaign, contact_ids = await running_campaign(client, team, ["9000000003", "9000000004"])
    # The second supplier asks not to be called after the campaign was approved.
    dnc = await client.post(
        f"{API}/dnc", headers=team["manager"].headers, json={"phone": "9000000004", "reason": "Asked by phone"}
    )
    assert dnc.status_code == 201

    now = MONDAY_10_30_IST
    first = await tick(telephony, now)
    assert first.attempt_no == 1 and telephony.placed[0][0] == "+919000000003"
    await not_answered(first.id)
    # Two hours later: the first supplier's retry is due, but the second supplier was never tried and comes
    # first. Their number is on the do-not-call list, so they are skipped, never dialled.
    assert await tick(telephony, now + timedelta(hours=2)) is None
    # The retry interval (60 minutes) counts from when the dialer saw the call end.
    second = await tick(telephony, now + timedelta(hours=3, minutes=1))
    assert second.attempt_no == 2
    await not_answered(second.id)
    assert await tick(telephony, now + timedelta(hours=4)) is None  # settles; retry due an hour later
    third = await tick(telephony, now + timedelta(hours=5, minutes=1))
    assert third.attempt_no == 3
    await not_answered(third.id)

    # max_attempts (3) reached: the contact fails and the campaign has nobody left to call.
    assert await tick(telephony, now + timedelta(hours=7)) is None
    rows = await statuses(campaign["id"])
    assert rows[0] == ("failed", 3, "no_answer")
    assert rows[1][0] == "skipped" and "do-not-call" in rows[1][2]
    assert [to for to, _ in telephony.placed] == ["+919000000003"] * 3
    detail = (await client.get(f"{API}/campaigns/{campaign['id']}", headers=team["manager"].headers)).json()
    assert detail["status"] == "completed" and detail["progress"] == {"failed": 1, "skipped": 1}


async def test_pause_window_and_switch(client, team, monkeypatch):
    telephony = MockTelephony()
    campaign, _ = await running_campaign(client, team, ["9000000005"])
    headers = team["manager"].headers

    assert await tick(telephony, SUNDAY) is None  # outside the calling window

    paused = await client.post(f"{API}/campaigns/{campaign['id']}/pause", headers=headers)
    assert paused.json()["status"] == "paused"
    assert await tick(telephony, MONDAY_10_30_IST) is None
    assert (await client.post(f"{API}/campaigns/{campaign['id']}/pause", headers=headers)).status_code == 409

    monkeypatch.setattr(get_settings(), "telephony_mode", "disabled")
    refused = await client.post(f"{API}/campaigns/{campaign['id']}/resume", headers=headers)
    assert refused.status_code == 409 and "TELEPHONY_MODE=disabled" in refused.json()["error"]["message"]
    monkeypatch.setattr(get_settings(), "telephony_mode", "mock")
    resumed = await client.post(f"{API}/campaigns/{campaign['id']}/resume", headers=headers)
    assert resumed.json()["status"] == "running"
    assert await tick(telephony, MONDAY_10_30_IST) is not None
