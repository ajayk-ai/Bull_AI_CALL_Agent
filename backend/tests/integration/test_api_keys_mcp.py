"""API keys for other systems, and the MCP server AI assistants use."""

import copy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.db.session import get_sessionmaker
from app.models.enums import Role
from app.models.integrations import ApiKey
from app.models.org import User
from app.seeds import scm_delivery

API = "/api/v1"


@pytest.fixture
async def manager(make_user, scm):
    return await make_user(Role.USER, scm)


@pytest.fixture
async def version_id(client, manager, make_user, scm) -> str:
    """A published SCM script (approved by a colleague)."""
    colleague = await make_user(Role.USER, scm)
    body = {
        "name": "Supplier dispatch confirmation",
        "config": copy.deepcopy(scm_delivery.CONFIG),
        "extraction_schema": copy.deepcopy(scm_delivery.EXTRACTION_SCHEMA),
    }
    vid = (await client.post(f"{API}/scripts", headers=manager.headers, json=body)).json()["versions"][0]["id"]
    await client.post(f"{API}/script-versions/{vid}/submit", headers=manager.headers)
    await client.post(f"{API}/script-versions/{vid}/approve", headers=colleague.headers, json={})
    return vid


async def new_key(client, actor, access="read", **extra) -> dict:
    body = {"name": "CRM", "access": access, **extra}
    response = await client.post(f"{API}/api-keys", headers=actor.headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def key_headers(key: dict) -> dict:
    return {"Authorization": f"Bearer {key['key']}"}


# ---- API keys on the REST API ----


async def test_key_is_shown_once_and_acts_as_its_owner(client, manager):
    key = await new_key(client, manager)
    assert key["key"].startswith("bmk_") and key["prefix"] == key["key"][:12]
    listed = (await client.get(f"{API}/api-keys", headers=manager.headers)).json()
    assert listed[0]["id"] == key["id"] and "key" not in listed[0]

    response = await client.get(f"{API}/campaigns", headers=key_headers(key))
    assert response.status_code == 200, response.text
    # The X-API-Key header works too.
    assert (await client.get(f"{API}/campaigns", headers={"X-API-Key": key["key"]})).status_code == 200
    shown = (await client.get(f"{API}/api-keys", headers=manager.headers)).json()[0]
    assert shown["last_used_at"] is not None


async def test_read_key_cannot_write(client, manager, version_id):
    key = await new_key(client, manager, "read")
    response = await client.post(
        f"{API}/campaigns", headers=key_headers(key), json={"name": "Nov", "script_version_id": version_id}
    )
    assert response.status_code == 403
    assert "access does not include" in response.json()["error"]["message"]


async def test_write_key_can_create_but_never_approve(client, manager, version_id):
    key = await new_key(client, manager, "write")
    created = await client.post(
        f"{API}/campaigns", headers=key_headers(key), json={"name": "Nov", "script_version_id": version_id}
    )
    assert created.status_code == 201, created.text
    approve = await client.post(f"{API}/campaigns/{created.json()['id']}/approve", headers=key_headers(key), json={})
    assert approve.status_code == 403


@pytest.mark.parametrize("path", ["/users", "/api-keys", "/auth/me", "/integrations", "/audit-logs", "/departments"])
async def test_keys_cannot_reach_account_endpoints(client, manager, path):
    key = await new_key(client, manager, "write")
    response = await client.get(f"{API}{path}", headers=key_headers(key))
    assert response.status_code == 403, path


async def test_revoked_expired_and_orphaned_keys_stop_working(client, manager):
    revoked = await new_key(client, manager)
    await client.post(f"{API}/api-keys/{revoked['id']}/revoke", headers=manager.headers)
    assert (await client.get(f"{API}/campaigns", headers=key_headers(revoked))).status_code == 401

    expired = await new_key(client, manager)
    async with get_sessionmaker()() as session:
        past = datetime.now(UTC) - timedelta(minutes=1)
        await session.execute(update(ApiKey).where(ApiKey.id == expired["id"]).values(expires_at=past))
        await session.commit()
    assert (await client.get(f"{API}/campaigns", headers=key_headers(expired))).status_code == 401

    orphaned = await new_key(client, manager)
    async with get_sessionmaker()() as session:
        await session.execute(update(User).where(User.id == manager.id).values(is_active=False))
        await session.commit()
    assert (await client.get(f"{API}/campaigns", headers=key_headers(orphaned))).status_code == 401


async def test_only_owner_or_admin_sees_and_revokes(client, manager, make_user, scm, admin):
    key = await new_key(client, manager)
    colleague = await make_user(Role.USER, scm)
    assert (await client.get(f"{API}/api-keys", headers=colleague.headers)).json() == []
    assert (await client.post(f"{API}/api-keys/{key['id']}/revoke", headers=colleague.headers)).status_code == 404
    assert [k["id"] for k in (await client.get(f"{API}/api-keys", headers=admin.headers)).json()] == [key["id"]]
    assert (await client.post(f"{API}/api-keys/{key['id']}/revoke", headers=admin.headers)).json()["revoked_at"]


# ---- MCP ----


async def rpc(client, key: dict, method: str, params: dict | None = None, message_id: int | None = 1):
    message = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})}
    if message_id is not None:
        message["id"] = message_id
    return await client.post(f"{API}/mcp", headers=key_headers(key), json=message)


async def call_tool(client, key: dict, name: str, arguments: dict) -> dict:
    response = await rpc(client, key, "tools/call", {"name": name, "arguments": arguments})
    assert response.status_code == 200, response.text
    return response.json()["result"]


async def test_mcp_handshake_and_tools_depend_on_access(client, manager):
    read = await new_key(client, manager, "read")
    init = (await rpc(client, read, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})).json()
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert (await rpc(client, read, "notifications/initialized", message_id=None)).status_code == 202
    assert (await rpc(client, read, "ping")).json()["result"] == {}

    names = {t["name"] for t in (await rpc(client, read, "tools/list")).json()["result"]["tools"]}
    assert names == {"list_scripts", "list_campaigns", "get_campaign", "list_calls", "get_call_result"}

    write = await new_key(client, manager, "write")
    tools = (await rpc(client, write, "tools/list")).json()["result"]["tools"]
    assert {"create_campaign", "add_contacts", "submit_campaign", "control_campaign"} <= {t["name"] for t in tools}
    assert all(t["inputSchema"]["type"] == "object" for t in tools)

    # A read key cannot call a write tool, even by name.
    denied = (await rpc(client, read, "tools/call", {"name": "create_campaign", "arguments": {}})).json()
    assert denied["error"]["code"] == -32602
    assert (await rpc(client, read, "no/such")).json()["error"]["code"] == -32601
    assert (await client.get(f"{API}/mcp", headers=key_headers(read))).status_code == 405


async def test_mcp_without_a_key_is_refused(client):
    response = await client.post(f"{API}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert response.status_code == 401


async def test_mcp_campaign_flow(client, manager, version_id):
    key = await new_key(client, manager, "write")

    scripts = await call_tool(client, key, "list_scripts", {})
    (script,) = scripts["structuredContent"]["scripts"]
    assert script["script_version_id"] == version_id
    fields = {f["key"] for f in script["upload_fields"]}
    assert fields == {"po_number", "material_description", "original_delivery_date"}

    created = await call_tool(
        client, key, "create_campaign", {"name": "Pending PO dispatch check", "script_version_id": version_id}
    )
    assert created.get("isError") is not True, created
    campaign_id = created["structuredContent"]["id"]

    line = {
        "po_number": "PO-45001",
        "material_description": "Hydraulic cylinder",
        "original_delivery_date": "2026-11-20",
    }
    people = [
        {
            "name": "Ravi Kumar",
            "phone": "9876543210",
            "company": "Sri Balaji Steels",
            "items": [line, {**line, "po_number": "PO-45034"}],
        },
        {"name": "Lakshmi N", "phone": "12345", "items": [line]},
    ]
    check = {"campaign_id": campaign_id, "contacts": people, "dry_run": True}
    checked = await call_tool(client, key, "add_contacts", check)
    result = checked["structuredContent"]
    assert result["checked_only"] is True and result["rows_with_errors"] == 1
    assert any("phone" in p["problem"].lower() for p in result["problems"])

    added = await call_tool(
        client, key, "add_contacts", {"campaign_id": campaign_id, "contacts": people[:1], "dry_run": False}
    )
    assert added["structuredContent"]["added_to_campaign"] == 1, added  # two PO lines, one call

    submitted = await call_tool(client, key, "submit_campaign", {"campaign_id": campaign_id})
    assert submitted["structuredContent"]["status"] == "pending_approval", submitted

    # Starting before a person approves is refused, as a tool error the assistant can read.
    started = await call_tool(client, key, "control_campaign", {"campaign_id": campaign_id, "action": "start"})
    assert started["isError"] is True

    listed = await call_tool(client, key, "list_campaigns", {})
    assert listed["structuredContent"]["campaigns"][0]["contacts"] == 1


async def test_mcp_reports_bad_arguments_as_tool_errors(client, manager):
    key = await new_key(client, manager, "write")
    result = await call_tool(client, key, "get_campaign", {"campaign_id": "not-a-uuid"})
    assert result["isError"] is True and "campaign_id" in result["content"][0]["text"]
    missing = await call_tool(client, key, "get_campaign", {"campaign_id": "00000000-0000-0000-0000-000000000000"})
    assert missing["isError"] is True and "not found" in missing["content"][0]["text"].lower()
