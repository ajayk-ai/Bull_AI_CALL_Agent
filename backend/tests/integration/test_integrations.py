"""Connected apps: bringing contacts in from a department's system, and sending call results out."""

import hashlib
import hmac
import json
import uuid

import httpx
import pytest

from app.core.config import get_settings
from app.core.phone import normalise
from app.db.session import get_sessionmaker
from app.models.calls import Call
from app.models.enums import CallStatus, Role
from app.models.extraction import ExtractedResult
from app.services import integrations

API = "/api/v1"
PUBLIC_IP = "93.184.216.34"


@pytest.fixture
async def manager(make_user, scm):
    return await make_user(Role.USER, scm)


@pytest.fixture
def remote(monkeypatch):
    """A fake department system: every request is recorded and answered by `remote.reply`."""

    class Remote:
        requests: list[httpx.Request] = []
        addresses = [PUBLIC_IP]

        def reply(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

    fake = Remote()
    fake.requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        fake.requests.append(request)
        return fake.reply(request)

    async def resolve(host: str, port: int) -> list[str]:
        return fake.addresses

    monkeypatch.setattr(integrations, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(integrations, "_resolve", resolve)
    monkeypatch.setattr(get_settings(), "integration_retry_seconds", [0.0])
    return fake


def fetch_body(**extra) -> dict:
    return {
        "name": "Service CRM - machines due",
        "kind": "fetch_contacts",
        "url": "https://crm.example.com/api/service-due",
        "auth_type": "bearer",
        "secret": "crm-token-123",
        "records_path": "data.customers",
        "query": {"month": "2026-11"},
        **extra,
    }


CUSTOMERS = {
    "data": {
        "customers": [
            {
                "customer": {"name": "Ravi Kumar", "company": "Sri Murugan Earthmovers"},
                "mobile": "9876543210",
                "machine": {"serial": "BL-2024-0871", "model": "Backhoe loader"},
                "service_due": "2026-11-20",
                "active": True,
            },
            {
                "customer": {"name": "Lakshmi N", "company": "KMR Infra"},
                "mobile": "9123456780",
                "machine": {"serial": "SSL-2023-0112", "model": "Skid steer loader"},
                "service_due": "2026-11-22",
                "active": False,
            },
        ]
    }
}


async def test_create_hides_secrets_and_scopes_by_department(client, manager, make_user, quality):
    response = await client.post(f"{API}/integrations", headers=manager.headers, json=fetch_body())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["has_secret"] is True and "secret" not in body
    assert "crm-token-123" not in response.text

    listed = (await client.get(f"{API}/integrations", headers=manager.headers)).json()
    assert [c["id"] for c in listed] == [body["id"]]

    other = await make_user(Role.USER, quality)
    assert (await client.get(f"{API}/integrations", headers=other.headers)).json() == []
    assert (await client.get(f"{API}/integrations/{body['id']}", headers=other.headers)).status_code == 404

    # Keeping the secret on update (None), then removing it ("").
    kept = await client.put(f"{API}/integrations/{body['id']}", headers=manager.headers, json=fetch_body(secret=None))
    assert kept.json()["has_secret"] is True
    removed = await client.put(f"{API}/integrations/{body['id']}", headers=manager.headers, json=fetch_body(secret=""))
    assert removed.json()["has_secret"] is False


async def test_reserved_headers_are_refused(client, manager):
    response = await client.post(
        f"{API}/integrations", headers=manager.headers, json=fetch_body(headers={"Authorization": "Bearer x"})
    )
    assert response.status_code == 422


async def test_fetch_brings_contacts_in_like_a_file(client, manager, remote):
    remote.reply = lambda request: httpx.Response(200, json=CUSTOMERS)
    connection = (await client.post(f"{API}/integrations", headers=manager.headers, json=fetch_body())).json()

    tested = (await client.post(f"{API}/integrations/{connection['id']}/test", headers=manager.headers)).json()
    assert tested["ok"] is True and tested["records"] == 2
    assert "customer.name" in tested["columns"] and "machine.serial" in tested["columns"]
    sent = remote.requests[-1]
    assert sent.method == "GET" and sent.headers["Authorization"] == "Bearer crm-token-123"
    assert sent.url.params["month"] == "2026-11"

    upload = await client.post(f"{API}/integrations/{connection['id']}/fetch", headers=manager.headers, json={})
    assert upload.status_code == 201, upload.text
    upload = upload.json()
    assert upload["total_rows"] == 2
    assert upload["preview"][0]["machine.serial"] == "BL-2024-0871"
    assert upload["preview"][1]["active"] == "no"

    mapping = {"name": "customer.name", "phone": "mobile", "company": "customer.company", "contact_fields": {}}
    mapping["contact_fields"] = {"machine_serial": "machine.serial"}
    report = await client.post(
        f"{API}/imports/{upload['id']}/process", headers=manager.headers, json={"mapping": mapping, "dry_run": False}
    )
    assert report.status_code == 200, report.text
    assert report.json()["new_contacts"] == 2

    shown = (await client.get(f"{API}/integrations/{connection['id']}", headers=manager.headers)).json()
    assert shown["last_result"]["ok"] is True


@pytest.mark.parametrize(
    ("addresses", "reason"),
    [
        (["127.0.0.1"], "not allowed"),
        (["169.254.169.254"], "not allowed"),
        (["::ffff:127.0.0.1"], "not allowed"),
        (["10.0.0.5"], "private network"),
    ],
)
async def test_unsafe_addresses_are_refused(client, manager, remote, addresses, reason):
    remote.addresses = addresses
    connection = (await client.post(f"{API}/integrations", headers=manager.headers, json=fetch_body())).json()
    result = (await client.post(f"{API}/integrations/{connection['id']}/test", headers=manager.headers)).json()
    assert result["ok"] is False and reason in result["message"]
    assert remote.requests == []


async def test_private_networks_can_be_allowed(client, manager, remote, monkeypatch):
    monkeypatch.setattr(get_settings(), "integrations_allow_private_networks", True)
    remote.addresses = ["10.0.0.5"]
    remote.reply = lambda request: httpx.Response(200, json=CUSTOMERS)
    connection = (await client.post(f"{API}/integrations", headers=manager.headers, json=fetch_body())).json()
    result = (await client.post(f"{API}/integrations/{connection['id']}/test", headers=manager.headers)).json()
    assert result["ok"] is True


async def test_fetch_explains_a_wrong_records_path(client, manager, remote):
    remote.reply = lambda request: httpx.Response(200, json=CUSTOMERS)
    connection = (
        await client.post(f"{API}/integrations", headers=manager.headers, json=fetch_body(records_path="data.rows"))
    ).json()
    response = await client.post(f"{API}/integrations/{connection['id']}/fetch", headers=manager.headers, json={})
    assert response.status_code == 422
    assert 'no "rows"' in response.json()["error"]["message"]


def results_body(**extra) -> dict:
    return {
        "name": "Service CRM - call results",
        "kind": "send_results",
        "url": "https://crm.example.com/api/call-results",
        "auth_type": "api_key",
        "api_key_header": "X-Api-Key",
        "secret": "key-456",
        "signing_secret": "sign-789",
        **extra,
    }


def assert_signed(request: httpx.Request, secret: str) -> dict:
    timestamp = request.headers["X-BullCall-Timestamp"]
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + request.content, hashlib.sha256).hexdigest()
    assert request.headers["X-BullCall-Signature"] == f"sha256={expected}"
    return json.loads(request.content)


async def test_test_delivers_a_signed_sample(client, manager, remote):
    connection = (await client.post(f"{API}/integrations", headers=manager.headers, json=results_body())).json()
    result = (await client.post(f"{API}/integrations/{connection['id']}/test", headers=manager.headers)).json()
    assert result["ok"] is True
    request = remote.requests[-1]
    assert request.method == "POST" and request.headers["X-Api-Key"] == "key-456"
    assert assert_signed(request, "sign-789")["event"] == "test"


async def _finished_call(department_id, script_version_id) -> uuid.UUID:
    phone = normalise("9876543210")
    async with get_sessionmaker()() as session:
        call = Call(
            department_id=department_id,
            phone_encrypted=phone.encrypted,
            phone_hash=phone.hash,
            phone_masked=phone.masked,
            script_version_id=script_version_id,
            provider="mock",
            is_simulated=True,
            status=CallStatus.COMPLETED,
            outcome="completed",
            answers={"answers": {"service_booked": True}},
        )
        session.add(call)
        await session.flush()
        session.add(
            ExtractedResult(
                call_id=call.id,
                script_version_id=script_version_id,
                model="test",
                validated={"service_booked": True},
                summary="Booked for 18 November",
                confidence=0.9,
            )
        )
        await session.commit()
        return call.id


async def _script_version(client, actor) -> uuid.UUID:
    from app.seeds import scm_delivery

    body = {"name": "S", "config": scm_delivery.CONFIG, "extraction_schema": scm_delivery.EXTRACTION_SCHEMA}
    created = (await client.post(f"{API}/scripts", headers=actor.headers, json=body)).json()
    return uuid.UUID(created["versions"][0]["id"])


async def test_results_are_sent_after_a_call_and_retried(client, manager, remote, scm):
    replies = iter([httpx.Response(503), httpx.Response(200)])
    remote.reply = lambda request: next(replies)
    connection = (await client.post(f"{API}/integrations", headers=manager.headers, json=results_body())).json()
    # A switched-off connection receives nothing.
    await client.post(f"{API}/integrations", headers=manager.headers, json=results_body(is_active=False))

    call_id = await _finished_call(scm.id, await _script_version(client, manager))
    await integrations.deliver_call_results(call_id)

    assert len(remote.requests) == 2  # one failure, one retry
    payload = assert_signed(remote.requests[-1], "sign-789")
    assert payload["event"] == "call.completed"
    assert payload["call"]["id"] == str(call_id)
    assert payload["result"]["data"] == {"service_booked": True}
    assert payload["contact"]["phone_masked"].endswith("3210")
    assert "9876543210" not in remote.requests[-1].content.decode()  # never the full number
    shown = (await client.get(f"{API}/integrations/{connection['id']}", headers=manager.headers)).json()
    assert shown["last_result"]["ok"] is True


async def test_results_are_not_retried_on_a_client_error(client, manager, remote, scm):
    remote.reply = lambda request: httpx.Response(400)
    connection = (await client.post(f"{API}/integrations", headers=manager.headers, json=results_body())).json()
    await integrations.deliver_call_results(await _finished_call(scm.id, await _script_version(client, manager)))
    assert len(remote.requests) == 1
    shown = (await client.get(f"{API}/integrations/{connection['id']}", headers=manager.headers)).json()
    assert shown["last_result"]["ok"] is False and shown["last_result"]["status_code"] == 400
