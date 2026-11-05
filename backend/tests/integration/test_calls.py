import asyncio
import base64
import copy
import json
import time
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.core.redis import get_redis
from app.db.session import get_sessionmaker
from app.main import app
from app.models.enums import Role, ScriptVersionStatus
from app.models.scripts import Script, ScriptVersion
from app.providers.telephony.mock import MockTelephony
from app.seeds import scm_delivery
from app.voice.deps import engine_dep, telephony_dep
from tests.fakes import supplier_conversation

API = "/api/v1"
ITEMS = {"items": [{"po_number": "450001", "material_description": "Hose", "original_delivery_date": "2026-11-20"}]}


@pytest.fixture
def telephony():
    mock = MockTelephony()
    app.dependency_overrides[telephony_dep] = lambda: mock
    yield mock
    app.dependency_overrides.pop(telephony_dep, None)


@pytest.fixture
def engine():
    fake = supplier_conversation()
    app.dependency_overrides[engine_dep] = lambda: fake
    yield fake
    app.dependency_overrides.pop(engine_dep, None)


@pytest.fixture(autouse=True)
def any_time(monkeypatch):
    monkeypatch.setattr(get_settings(), "individual_call_window_enforced", False)


@pytest.fixture
async def version_id(scm) -> str:
    """A published SCM script version."""
    async with get_sessionmaker()() as session:
        script = Script(department_id=scm.id, name="SCM")
        session.add(script)
        await session.flush()
        version = ScriptVersion(
            script_id=script.id,
            version_no=1,
            status=ScriptVersionStatus.PUBLISHED,
            config=copy.deepcopy(scm_delivery.CONFIG),
            extraction_schema=copy.deepcopy(scm_delivery.EXTRACTION_SCHEMA),
        )
        session.add(version)
        await session.commit()
        return str(version.id)


@pytest.fixture
async def operator(make_user, scm):
    return await make_user(Role.USER, scm)


async def contact(client, actor, phone="9876543210") -> str:
    created = await client.post(
        f"{API}/contacts",
        headers=actor.headers,
        json={"name": "Ravi", "company": "ABC Industries", "phone": phone, "language": "ta-IN"},
    )
    return created.json()["id"]


def token_of(url: str) -> str:
    return parse_qs(urlsplit(url).query)["t"][0]


# ---- placing calls ----


async def test_place_individual_call_with_mock_telephony(
    client, operator, make_user, scm, version_id, telephony, engine
):
    manager = await make_user(Role.USER, scm)
    contact_id = await contact(client, manager)
    response = await client.post(
        f"{API}/calls",
        headers=operator.headers,
        json={"contact_id": contact_id, "script_version_id": version_id, "context": ITEMS},
    )
    assert response.status_code == 201, response.text
    call = response.json()
    assert call["status"] == "dialing" and call["is_simulated"] is True and call["provider"] == "mock"
    assert call["phone_masked"] == "+91******3210"

    to, urls = telephony.placed[0]
    assert to == "+919876543210"
    assert "/telephony/mock/flow?t=" in urls.flow_url and "/telephony/mock/status?t=" in urls.status_url

    detail = (await client.get(f"{API}/calls/{call['id']}", headers=operator.headers)).json()
    assert detail["ai_config"]["language"] == "ta-IN"  # from the contact
    assert "Ravi from ABC Industries" in detail["ai_config"]["system_instruction"]
    assert detail["ai_config"]["telephony"] == "mock" and detail["context"] == ITEMS

    # The same number cannot be called twice at once.
    again = await client.post(
        f"{API}/calls",
        headers=operator.headers,
        json={"contact_id": contact_id, "script_version_id": version_id, "context": ITEMS},
    )
    assert again.status_code == 409 and "already being called" in again.json()["error"]["message"]


async def test_call_safety_checks(client, operator, admin, scm, version_id, telephony, engine, monkeypatch):
    body = {"phone": "9123456780", "name": "Test", "script_version_id": version_id, "context": ITEMS}
    # Script data is required.
    missing = await client.post(f"{API}/calls", headers=operator.headers, json={**body, "context": {}})
    assert missing.status_code == 422 and "no campaign data" in str(missing.json()["error"]["details"])
    # Language must be allowed by the script.
    assert (
        await client.post(f"{API}/calls", headers=operator.headers, json={**body, "language": "kn-IN"})
    ).status_code == 422
    # Do-not-call numbers are refused.
    await client.post(f"{API}/dnc", headers=operator.headers, json={"phone": "9123456780", "reason": "opted out"})
    dnc = await client.post(f"{API}/calls", headers=operator.headers, json=body)
    assert dnc.status_code == 409 and "do-not-call" in dnc.json()["error"]["message"]
    # Concurrency limit.
    monkeypatch.setattr(get_settings(), "max_concurrent_calls", 1)
    first = await client.post(f"{API}/calls", headers=operator.headers, json={**body, "phone": "9000012345"})
    assert first.status_code == 201
    limit = await client.post(f"{API}/calls", headers=operator.headers, json={**body, "phone": "9000054321"})
    assert limit.status_code == 429
    # Calling hours.
    monkeypatch.setattr(get_settings(), "individual_call_window_enforced", True)
    monkeypatch.setattr(get_settings(), "max_concurrent_calls", 5)
    from app.services import windows

    monkeypatch.setattr(windows, "in_window", lambda window, at: False)
    hours = await client.post(f"{API}/calls", headers=operator.headers, json={**body, "phone": "9000054321"})
    assert hours.status_code == 409 and "calling hours" in hours.json()["error"]["message"]


async def test_draft_script_and_other_department_refused(
    client, operator, make_user, quality, scm, version_id, telephony, engine
):
    async with get_sessionmaker()() as session:
        draft = await session.get(ScriptVersion, uuid.UUID(version_id))
        draft.status = ScriptVersionStatus.DRAFT
        await session.commit()
    body = {"phone": "9123456780", "script_version_id": version_id, "context": ITEMS}
    assert (await client.post(f"{API}/calls", headers=operator.headers, json=body)).status_code == 422
    qa_operator = await make_user(Role.USER, quality)
    assert (await client.post(f"{API}/calls", headers=qa_operator.headers, json=body)).status_code == 422


async def test_calling_disabled_and_permissions(client, operator, make_user, scm, version_id):
    get_settings_obj = get_settings()
    original = get_settings_obj.telephony_mode
    get_settings_obj.telephony_mode = "disabled"
    from app.providers.telephony import get_telephony

    get_telephony.cache_clear()
    try:
        body = {"phone": "9123456780", "script_version_id": version_id, "context": ITEMS}
        disabled = await client.post(f"{API}/calls", headers=operator.headers, json=body)
        assert disabled.status_code == 503 and disabled.json()["error"]["code"] == "calling_unavailable"
        assert (await client.get(f"{API}/calls/mode", headers=operator.headers)).json() == {"mode": "disabled"}
    finally:
        get_settings_obj.telephony_mode = original
        get_telephony.cache_clear()


# ---- provider callbacks ----


async def test_flow_status_and_tokens(client, operator, version_id, telephony, engine):
    call = (
        await client.post(
            f"{API}/calls",
            headers=operator.headers,
            json={"phone": "9123456780", "script_version_id": version_id, "context": ITEMS},
        )
    ).json()
    _, urls = telephony.placed[0]
    flow_path = urlsplit(urls.flow_url)._replace(scheme="", netloc="").geturl()
    status_path = urlsplit(urls.status_url)._replace(scheme="", netloc="").geturl()

    flow = (await client.post(flow_path)).json()
    assert flow["action"] == "stream" and flow["sample_rate"] == "16k"
    assert flow["ws_url"].startswith("wss://mock.invalid/telephony/mock/media?t=")

    # Tokens are checked: none, wrong purpose, or another provider.
    assert (await client.post("/telephony/mock/flow")).status_code == 403
    assert (await client.post(f"/telephony/mock/flow?t={token_of(urls.status_url)}")).status_code == 403
    assert (await client.post(f"/telephony/frejun/flow?t={token_of(urls.flow_url)}")).status_code == 403

    # Status events: idempotent, out-of-order safe, numbers masked.
    ringing = {"status": "ringing", "to": "+919123456780"}
    assert (await client.post(status_path, json=ringing)).status_code == 200
    assert (await client.post(status_path, json=ringing)).status_code == 200  # provider retry
    await client.post(status_path, json={"status": "no-answer", "to": "+919123456780"})
    await client.post(status_path, json={"status": "ringing", "late": True})  # arrives after the end

    detail = (await client.get(f"{API}/calls/{call['id']}", headers=operator.headers)).json()
    assert detail["status"] == "no_answer" and detail["end_reason"] == "no_answer"
    types = [e["event_type"] for e in detail["events"]]
    assert types.count("status:ringing") == 2 and types.count("flow") == 1  # the retry was stored once
    assert "9123456780" not in json.dumps(detail["events"])

    # A finished call answers the flow with a hang-up, and the number can be called again.
    assert (await client.post(flow_path)).json() == {"action": "hangup"}
    again = await client.post(
        f"{API}/calls",
        headers=operator.headers,
        json={"phone": "9123456780", "script_version_id": version_id, "context": ITEMS},
    )
    assert again.status_code == 201


async def test_user_hang_up_before_answer(client, operator, version_id, telephony, engine):
    call = (
        await client.post(
            f"{API}/calls",
            headers=operator.headers,
            json={"phone": "9123456780", "script_version_id": version_id, "context": ITEMS},
        )
    ).json()
    hung = await client.post(f"{API}/calls/{call['id']}/hang-up", headers=operator.headers)
    assert hung.json()["status"] == "cancelled"
    assert len(telephony.hung_up) == 1 and telephony.hung_up[0].startswith("mock-")
    assert (await client.post(f"{API}/calls/{call['id']}/hang-up", headers=operator.headers)).status_code == 409


# ---- a whole call over the media WebSocket ----


def _run_call(media_path: str, caller_chunks: int, call_id: str, headers: dict) -> list[dict]:
    """Plays the provider's side of the media stream in FreJun's format; returns what we sent back.

    After our server closes the stream, the app keeps running (as it would in production) until the call has
    been saved, so the post-call work is not cut short by the test shutting the app down.
    """
    get_redis.cache_clear()  # the app runs on this thread's event loop
    received: list[dict] = []
    audio = base64.b64encode(b"\x01\x00" * 800).decode()
    with TestClient(app) as http:
        with http.websocket_connect(media_path) as ws:
            ws.send_text(json.dumps({"type": "start", "data": {"call_id": "x"}}))
            for _ in range(caller_chunks):
                ws.send_text(json.dumps({"type": "audio", "data": {"audio_b64": audio}}))
            ws.send_text("not json")  # malformed messages are skipped
            try:
                while True:
                    received.append(json.loads(ws.receive_text()))
            except WebSocketDisconnect:  # the server closed the stream
                pass
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if http.get(f"{API}/calls/{call_id}", headers=headers).json()["end_reason"]:
                break
            time.sleep(0.1)
    get_redis.cache_clear()
    return received


async def test_full_call_over_media_stream(client, operator, version_id, telephony, engine):
    call = (
        await client.post(
            f"{API}/calls",
            headers=operator.headers,
            json={"phone": "9123456780", "name": "Ravi", "script_version_id": version_id, "context": ITEMS},
        )
    ).json()
    _, urls = telephony.placed[0]
    flow = (await client.post(urlsplit(urls.flow_url)._replace(scheme="", netloc="").geturl())).json()
    media_path = urlsplit(flow["ws_url"])._replace(scheme="", netloc="").geturl()

    sent = await asyncio.to_thread(_run_call, media_path, 5, call["id"], operator.headers)

    audio = [m for m in sent if m["type"] == "audio"]
    assert audio and [m["chunk_id"] for m in audio] == list(range(len(audio)))
    assert all(len(base64.b64decode(m["audio_b64"])) % 320 == 0 for m in audio)

    detail = (await client.get(f"{API}/calls/{call['id']}", headers=operator.headers)).json()
    assert detail["status"] == "completed" and detail["is_simulated"] is True
    assert detail["outcome"] == "completed" and detail["end_reason"] == "agent_end_call"
    assert [t["speaker"] for t in detail["transcript"]] == ["agent", "caller", "agent"]
    assert detail["metrics"]["turns"] == 2 and detail["duration_seconds"] is not None
    assert "media_connected" in [e["event_type"] for e in detail["events"]]
    assert len(telephony.hung_up) == 1  # we hung up after the agent's closing words
    # The engine got the script's instructions and the end_call tool.
    assert "Ravi" in engine.configs[0].system_instruction and engine.configs[0].tools[0]["name"] == "end_call"

    # The media stream can be opened only once per call.
    assert await asyncio.to_thread(_refused_code, media_path) == 1008


def _refused_code(media_path: str) -> int | None:
    get_redis.cache_clear()
    try:
        with TestClient(app) as http, http.websocket_connect(media_path):
            return None
    except WebSocketDisconnect as exc:
        return exc.code
    finally:
        get_redis.cache_clear()


async def test_opt_out_adds_number_to_do_not_call(client, operator, version_id, telephony):
    fake = supplier_conversation(outcome="opted_out")
    app.dependency_overrides[engine_dep] = lambda: fake
    try:
        call = (
            await client.post(
                f"{API}/calls",
                headers=operator.headers,
                json={"phone": "9123456780", "script_version_id": version_id, "context": ITEMS},
            )
        ).json()
        _, urls = telephony.placed[0]
        flow = (await client.post(urlsplit(urls.flow_url)._replace(scheme="", netloc="").geturl())).json()
        media_path = urlsplit(flow["ws_url"])._replace(scheme="", netloc="").geturl()
        await asyncio.to_thread(_run_call, media_path, 5, call["id"], operator.headers)
    finally:
        app.dependency_overrides.pop(engine_dep, None)

    detail = (await client.get(f"{API}/calls/{call['id']}", headers=operator.headers)).json()
    assert detail["outcome"] == "opted_out"
    dnc = (await client.get(f"{API}/dnc", headers=operator.headers)).json()
    assert dnc["total"] == 1 and dnc["items"][0]["source"] == "caller request"
    blocked = await client.post(
        f"{API}/calls",
        headers=operator.headers,
        json={"phone": "9123456780", "script_version_id": version_id, "context": ITEMS},
    )
    assert blocked.status_code == 409
