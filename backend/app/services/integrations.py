"""Connected apps: each department links its own CRM, ERP or HR system over HTTP.

- fetch_contacts: GET a JSON list of people and import it exactly like an uploaded file (same column matching,
  duplicate and do-not-call checks), by turning the records into a CSV.
- send_results: after each call is analysed, POST the result as JSON. Signed with HMAC-SHA256 when a signing
  secret is set: X-BullCall-Signature = "sha256=" + hex(HMAC(secret, timestamp + "." + body)).

Connections live in `integration_configs` (key "connection:<id>"); tokens and passwords are encrypted and never
returned. Outgoing requests refuse loopback and link-local (cloud metadata) addresses, and private networks
unless allowed in settings; redirects are not followed and replies are size-capped.
"""

import asyncio
import csv
import hashlib
import hmac
import io
import ipaddress
import json
import logging
import socket
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.errors import NotFound, ValidationFailed
from app.core.security import decrypt, encrypt
from app.db.session import get_sessionmaker
from app.models.calls import Call
from app.models.campaigns import Campaign
from app.models.contacts import Contact
from app.models.extraction import ExtractedResult
from app.models.integrations import IntegrationConfig
from app.models.org import User
from app.rbac.permissions import can_see, resolve_department, visible_departments
from app.schemas.imports import ImportUploadOut
from app.schemas.integrations import ConnectionIn, ConnectionOut, ConnectionTestResult, FetchRequest
from app.services import audit, imports

log = logging.getLogger(__name__)

KEY_PREFIX = "connection:"
MAX_CONNECTIONS_PER_DEPARTMENT = 50
USER_AGENT = "BullAICalling/1.0"
_WRAPPER_KEYS = ("data", "items", "results", "records", "contacts", "rows", "list")

# Tests swap these: an httpx transport instead of the network, and a resolver instead of DNS.
_transport: httpx.AsyncBaseTransport | None = None


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


class RemoteError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---- Stored connections ----


def _secrets(row: IntegrationConfig) -> dict[str, str]:
    return json.loads(decrypt(row.secrets_encrypted)) if row.secrets_encrypted else {}


def _set_secrets(row: IntegrationConfig, values: dict[str, str]) -> None:
    values = {k: v for k, v in values.items() if v}
    row.secrets_encrypted = encrypt(json.dumps(values)) if values else None


def to_out(row: IntegrationConfig) -> ConnectionOut:
    c = row.config
    s = _secrets(row)
    return ConnectionOut(
        id=row.id,
        name=c["name"],
        kind=c["kind"],
        url=c["url"],
        department_id=row.department_id,
        is_active=row.is_active,
        auth_type=c.get("auth_type", "none"),
        api_key_header=c.get("api_key_header", "X-API-Key"),
        username=c.get("username"),
        has_secret=bool(s.get("secret")),
        has_signing_secret=bool(s.get("signing_secret")),
        headers=c.get("headers") or {},
        records_path=c.get("records_path", ""),
        query=c.get("query") or {},
        campaign_ids=c.get("campaign_ids") or [],
        last_result=c.get("last_result"),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _public_config(body: ConnectionIn, previous: dict | None = None) -> dict[str, Any]:
    config = body.model_dump(mode="json", exclude={"secret", "signing_secret", "department_id", "is_active"})
    if previous and previous.get("last_result"):
        config["last_result"] = previous["last_result"]
    return config


async def _check_campaigns(session: AsyncSession, department_id: uuid.UUID, campaign_ids: list[uuid.UUID]) -> None:
    if not campaign_ids:
        return
    found = set(
        await session.scalars(
            select(Campaign.id).where(Campaign.id.in_(campaign_ids), Campaign.department_id == department_id)
        )
    )
    if missing := [str(c) for c in campaign_ids if c not in found]:
        raise ValidationFailed("Some campaigns are not in this department", details={"campaign_ids": missing})


async def _get(session: AsyncSession, actor: User, connection_id: uuid.UUID) -> IntegrationConfig:
    row = await session.get(IntegrationConfig, connection_id)
    if row is None or not row.key.startswith(KEY_PREFIX) or not can_see(actor, row.department_id):
        raise NotFound("Connection not found")
    return row


async def list_connections(session: AsyncSession, actor: User) -> list[ConnectionOut]:
    query = select(IntegrationConfig).where(IntegrationConfig.key.startswith(KEY_PREFIX))
    departments = visible_departments(actor)
    if departments is not None:
        query = query.where(IntegrationConfig.department_id.in_(departments))
    rows = await session.scalars(query.order_by(IntegrationConfig.created_at))
    return [to_out(r) for r in rows]


async def get_connection(session: AsyncSession, actor: User, connection_id: uuid.UUID) -> ConnectionOut:
    return to_out(await _get(session, actor, connection_id))


async def create(session: AsyncSession, actor: User, body: ConnectionIn, ctx: RequestContext) -> ConnectionOut:
    department_id = resolve_department(actor, body.department_id)
    await _check_campaigns(session, department_id, body.campaign_ids)
    count = len(
        list(
            await session.scalars(
                select(IntegrationConfig.id).where(
                    IntegrationConfig.key.startswith(KEY_PREFIX), IntegrationConfig.department_id == department_id
                )
            )
        )
    )
    if count >= MAX_CONNECTIONS_PER_DEPARTMENT:
        raise ValidationFailed(f"A department can have at most {MAX_CONNECTIONS_PER_DEPARTMENT} connections")
    connection_id = uuid.uuid7()
    row = IntegrationConfig(
        id=connection_id,
        key=f"{KEY_PREFIX}{connection_id}",
        department_id=department_id,
        config=_public_config(body),
        is_active=body.is_active,
    )
    _set_secrets(row, {"secret": body.secret or "", "signing_secret": body.signing_secret or ""})
    session.add(row)
    await session.flush()
    audit.record(
        session,
        ctx,
        "integration.create",
        actor=actor,
        entity_type="integration",
        entity_id=row.id,
        department_id=department_id,
        changes={"name": body.name, "kind": body.kind, "url": str(body.url)},
    )
    await session.commit()
    await session.refresh(row)
    return to_out(row)


async def update(
    session: AsyncSession, actor: User, connection_id: uuid.UUID, body: ConnectionIn, ctx: RequestContext
) -> ConnectionOut:
    row = await _get(session, actor, connection_id)
    if body.kind != row.config["kind"]:
        raise ValidationFailed("A connection's kind cannot be changed; create a new connection instead")
    await _check_campaigns(session, row.department_id, body.campaign_ids)
    secrets = _secrets(row)
    # None keeps the stored value, "" removes it.
    if body.secret is not None:
        secrets["secret"] = body.secret
    if body.signing_secret is not None:
        secrets["signing_secret"] = body.signing_secret
    row.config = _public_config(body, row.config)
    row.is_active = body.is_active
    _set_secrets(row, secrets)
    audit.record(
        session,
        ctx,
        "integration.update",
        actor=actor,
        entity_type="integration",
        entity_id=row.id,
        department_id=row.department_id,
        changes={
            "name": body.name,
            "url": str(body.url),
            "is_active": body.is_active,
            "secret_changed": body.secret is not None,
            "signing_secret_changed": body.signing_secret is not None,
        },
    )
    await session.commit()
    await session.refresh(row)
    return to_out(row)


async def delete(session: AsyncSession, actor: User, connection_id: uuid.UUID, ctx: RequestContext) -> None:
    row = await _get(session, actor, connection_id)
    audit.record(
        session,
        ctx,
        "integration.delete",
        actor=actor,
        entity_type="integration",
        entity_id=row.id,
        department_id=row.department_id,
        changes={"name": row.config.get("name")},
    )
    await session.delete(row)
    await session.commit()


def _remember(row: IntegrationConfig, ok: bool, message: str, status_code: int | None = None) -> None:
    result = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "ok": ok, "status_code": status_code}
    row.config = {**row.config, "last_result": {**result, "message": message[:300]}}


# ---- HTTP ----


async def _check_address(url: str) -> None:
    """Refuses addresses a connection must not reach. (The name is resolved again when connecting; with a
    short-lived DNS answer that could differ, which the private-network setting is the backstop for.)"""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise RemoteError("Only http:// and https:// addresses can be used")
    host = parts.hostname
    if not host:
        raise RemoteError("The address has no server name")
    try:
        addresses = await _resolve(host, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror, UnicodeError:
        raise RemoteError(f"Cannot find the server {host}. Check the address.")
    allow_private = get_settings().integrations_allow_private_networks
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise RemoteError(f"{host} points to an address that connections are not allowed to use")
        if ip.is_private and not allow_private:
            raise RemoteError(
                f"{host} is on a private network. The admin can allow this with INTEGRATIONS_ALLOW_PRIVATE_NETWORKS."
            )


def _request_auth(row: IntegrationConfig) -> tuple[dict[str, str], httpx.Auth | None]:
    config = row.config
    secret = _secrets(row).get("secret", "")
    headers = {"User-Agent": USER_AGENT, **(config.get("headers") or {})}
    auth: httpx.Auth | None = None
    match config.get("auth_type", "none"):
        case "bearer" if secret:
            headers["Authorization"] = f"Bearer {secret}"
        case "api_key" if secret:
            headers[config.get("api_key_header") or "X-API-Key"] = secret
        case "basic":
            auth = httpx.BasicAuth(config.get("username") or "", secret)
    return headers, auth


async def _send(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    auth: httpx.Auth | None = None,
    params: dict[str, str] | None = None,
    content: bytes | None = None,
    max_bytes: int,
) -> tuple[int, bytes]:
    await _check_address(url)
    timeout = get_settings().integration_timeout_seconds
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, transport=_transport) as client:
            async with client.stream(method, url, headers=headers, auth=auth, params=params, content=content) as r:
                body = bytearray()
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > max_bytes:
                        raise RemoteError(f"The reply is larger than {max_bytes // (1024 * 1024)} MB", r.status_code)
                return r.status_code, bytes(body)
    except httpx.TimeoutException:
        raise RemoteError(f"The server did not answer within {timeout:g} seconds")
    except httpx.HTTPError as exc:
        raise RemoteError(f"Could not connect to the server ({type(exc).__name__})")


def _status_problem(status_code: int) -> str | None:
    if 200 <= status_code < 300:
        return None
    if 300 <= status_code < 400:
        return f"The server redirected the request (HTTP {status_code}). Use the final address instead."
    if status_code in (401, 403):
        return f"The server refused the sign-in details (HTTP {status_code}). Check the token or password."
    if status_code == 404:
        return "The server says this address does not exist (HTTP 404). Check the address."
    return f"The server answered with an error (HTTP {status_code})"


# ---- Fetching contacts ----


def _flatten(value: Any, prefix: str = "", out: dict[str, str] | None = None) -> dict[str, str]:
    """{"dealer": {"name": "X"}, "tags": ["a", "b"]} -> {"dealer.name": "X", "tags": "a, b"}."""
    out = {} if out is None else out
    if isinstance(value, dict):
        for key, item in value.items():
            _flatten(item, f"{prefix}.{key}" if prefix else str(key), out)
    elif isinstance(value, list):
        if all(not isinstance(v, dict | list) for v in value):
            out[prefix] = ", ".join("" if v is None else str(v) for v in value)
        else:
            out[prefix] = json.dumps(value, ensure_ascii=False, default=str)
    elif value is None:
        out[prefix] = ""
    elif isinstance(value, bool):
        out[prefix] = "yes" if value else "no"
    elif isinstance(value, float) and value.is_integer():
        out[prefix] = str(int(value))
    else:
        out[prefix] = str(value)
    return out


def records_from(payload: Any, path: str) -> list[dict[str, str]]:
    node = payload
    for part in (p for p in path.split(".") if p):
        if not isinstance(node, dict) or part not in node:
            raise RemoteError(f'The reply has no "{part}". Check "Where the list is" (now "{path}").')
        node = node[part]
    if not path and isinstance(node, dict):
        lists = [k for k in _WRAPPER_KEYS if isinstance(node.get(k), list)]
        if lists:
            node = node[lists[0]]
    if not isinstance(node, list):
        raise RemoteError('The reply is not a list of people. Set "Where the list is", e.g. data.items.')
    rows = [_flatten(item) for item in node if isinstance(item, dict)]
    if not rows:
        raise RemoteError("The list is empty, or its entries are not records with fields")
    return rows


async def _fetch_rows(row: IntegrationConfig) -> tuple[int, list[dict[str, str]]]:
    settings = get_settings()
    headers, auth = _request_auth(row)
    headers["Accept"] = "application/json"
    status_code, body = await _send(
        "GET",
        row.config["url"],
        headers=headers,
        auth=auth,
        params=row.config.get("query") or None,
        max_bytes=settings.import_max_bytes,
    )
    if problem := _status_problem(status_code):
        raise RemoteError(problem, status_code)
    try:
        payload = json.loads(body)
    except ValueError:
        raise RemoteError("The reply is not JSON", status_code)
    rows = records_from(payload, row.config.get("records_path", ""))
    if len(rows) > settings.import_max_rows:
        raise RemoteError(
            f"The reply has {len(rows)} records; the limit is {settings.import_max_rows}. Add a filter to the address.",
            status_code,
        )
    return status_code, rows


def columns_of(rows: list[dict[str, str]]) -> list[str]:
    """Every field name, in the order first seen."""
    return list(dict.fromkeys(key for row in rows for key in row))


def rows_to_csv(rows: list[dict[str, str]]) -> bytes:
    headers = columns_of(rows)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(h, "") for h in headers])
    return buffer.getvalue().encode("utf-8")


async def fetch(
    session: AsyncSession, actor: User, connection_id: uuid.UUID, body: FetchRequest, ctx: RequestContext
) -> ImportUploadOut:
    row = await _get(session, actor, connection_id)
    if row.config["kind"] != "fetch_contacts":
        raise ValidationFailed("This connection sends results; it cannot bring contacts in")
    if not row.is_active:
        raise ValidationFailed("This connection is switched off")
    if body.campaign_id:
        campaign = await session.get(Campaign, body.campaign_id)
        if campaign is None or campaign.department_id != row.department_id:
            raise ValidationFailed("The campaign and the connection must be in the same department")
    try:
        status_code, rows = await _fetch_rows(row)
    except RemoteError as exc:
        _remember(row, False, exc.message, exc.status_code)
        await session.commit()
        raise ValidationFailed(exc.message)
    _remember(row, True, f"Fetched {len(rows)} records", status_code)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H%M")
    return await imports.store_upload(
        session,
        actor,
        row.department_id,
        f"{row.config['name']} {stamp}.csv",
        rows_to_csv(rows),
        ctx,
        source={"connection_id": str(row.id), "connection": row.config["name"]},
    )


# ---- Sending results ----


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def sample_payload() -> dict[str, Any]:
    """What a results delivery looks like; also sent by "Test"."""
    return {
        "event": "test",
        "call": {
            "id": "00000000-0000-0000-0000-000000000000",
            "campaign_id": None,
            "campaign_name": "Service due reminder - November",
            "attempt_no": 1,
            "status": "completed",
            "outcome": "completed",
            "end_reason": "agent_closed",
            "started_at": "2026-11-12T10:30:00+05:30",
            "ended_at": "2026-11-12T10:32:10+05:30",
            "duration_seconds": 130,
            "language": "ta-IN",
            "simulated": True,
        },
        "contact": {
            "id": None,
            "name": "Ravi Kumar",
            "company": "Sri Murugan Earthmovers",
            "phone_masked": "+91******3210",
            "fields": {"customer_id": "CRM-10442"},
        },
        "items": [{"machine_serial": "BL-2024-0871", "service_due": "2026-11-20"}],
        "answers": {"service_booked": True, "preferred_date": "2026-11-18"},
        "result": {
            "status": "validated",
            "summary": "Customer agreed to a service visit on 18 November.",
            "confidence": 0.92,
            "needs_review": False,
            "data": {"service_booked": True, "preferred_date": "2026-11-18", "needs_followup": False},
        },
    }


async def _call_payload(session: AsyncSession, call: Call) -> dict[str, Any]:
    campaign = await session.get(Campaign, call.campaign_id) if call.campaign_id else None
    contact = await session.get(Contact, call.contact_id) if call.contact_id else None
    result = await session.scalar(
        select(ExtractedResult).where(ExtractedResult.call_id == call.id).order_by(ExtractedResult.created_at.desc())
    )
    answers = call.answers or {}
    return {
        "event": "call.completed",
        "call": {
            "id": str(call.id),
            "campaign_id": str(call.campaign_id) if call.campaign_id else None,
            "campaign_name": campaign.name if campaign else None,
            "attempt_no": call.attempt_no,
            "status": str(call.status),
            "outcome": call.outcome,
            "end_reason": call.end_reason,
            "started_at": call.started_at.isoformat() if call.started_at else None,
            "ended_at": call.ended_at.isoformat() if call.ended_at else None,
            "duration_seconds": call.duration_seconds,
            "language": call.language_detected,
            "simulated": call.is_simulated,
        },
        "contact": {
            "id": str(contact.id) if contact else None,
            "name": contact.name if contact else None,
            "company": contact.company if contact else None,
            "phone_masked": call.phone_masked,
            "fields": (contact.custom_fields or {}) if contact else {},
        },
        "items": (call.context or {}).get("items") or [],
        "answers": answers.get("answers", answers) if isinstance(answers, dict) else answers,
        "result": (
            {
                "status": str(result.status),
                "summary": result.summary,
                "confidence": result.confidence,
                "needs_review": str(result.status) == "needs_review",
                "data": result.corrected or result.validated or (result.raw or {}).get("result", result.raw),
            }
            if result
            else None
        ),
    }


async def _post(row: IntegrationConfig, payload: dict[str, Any]) -> tuple[int, str]:
    """One delivery attempt. Returns (status code, message); raises RemoteError when the server can't be reached."""
    body = json.dumps({**payload, "delivery_id": str(uuid.uuid4())}, ensure_ascii=False, default=str).encode()
    headers, auth = _request_auth(row)
    timestamp = str(int(time.time()))
    headers.update({"Content-Type": "application/json", "X-BullCall-Event": payload["event"]})
    if signing := _secrets(row).get("signing_secret"):
        headers.update({"X-BullCall-Timestamp": timestamp, "X-BullCall-Signature": _sign(signing, timestamp, body)})
    status_code, _ = await _send("POST", row.config["url"], headers=headers, auth=auth, content=body, max_bytes=65536)
    return status_code, _status_problem(status_code) or f"Delivered (HTTP {status_code})"


async def _deliver(connection_id: uuid.UUID, payload: dict[str, Any]) -> None:
    settings = get_settings()
    waits = settings.integration_retry_seconds
    ok, status_code, message = False, None, ""
    for attempt in range(settings.integration_send_attempts):
        async with get_sessionmaker()() as session:
            row = await session.get(IntegrationConfig, connection_id)
            if row is None or not row.is_active:
                return
            try:
                status_code, message = await _post(row, payload)
                ok = 200 <= status_code < 300
            except RemoteError as exc:
                status_code, message = exc.status_code, exc.message
            # Retry only what may succeed later: no answer, rate limits and server errors.
            retry = not ok and (status_code is None or status_code in (408, 429) or status_code >= 500)
            last = attempt + 1 >= settings.integration_send_attempts or not retry
            if last:
                _remember(row, ok, message if ok else f"{message} (call {payload['call']['id']})", status_code)
                await session.commit()
        if last:
            break
        await asyncio.sleep(waits[min(attempt, len(waits) - 1)])
    if not ok:
        log.warning("Sending call %s to connection %s failed: %s", payload["call"]["id"], connection_id, message)


async def deliver_call_results(call_id: uuid.UUID) -> None:
    """Sends a finished call's result to every active send_results connection of its department."""
    async with get_sessionmaker()() as session:
        call = await session.get(Call, call_id)
        if call is None:
            return
        rows = await session.scalars(
            select(IntegrationConfig).where(
                IntegrationConfig.key.startswith(KEY_PREFIX),
                IntegrationConfig.department_id == call.department_id,
                IntegrationConfig.is_active.is_(True),
            )
        )
        targets = [
            r.id
            for r in rows
            if r.config.get("kind") == "send_results"
            and (not r.config.get("campaign_ids") or str(call.campaign_id) in r.config["campaign_ids"])
        ]
        if not targets:
            return
        payload = await _call_payload(session, call)
    await asyncio.gather(*(_deliver(t, payload) for t in targets))


# ---- Test ----


async def test(session: AsyncSession, actor: User, connection_id: uuid.UUID) -> ConnectionTestResult:
    row = await _get(session, actor, connection_id)
    try:
        if row.config["kind"] == "fetch_contacts":
            status_code, rows = await _fetch_rows(row)
            columns = columns_of(rows)
            preview = [{k: v[:80] for k, v in r.items()} for r in rows[:3]]
            result = ConnectionTestResult(
                ok=True,
                status_code=status_code,
                message=f"Connected. Found {len(rows)} records with {len(columns)} fields.",
                records=len(rows),
                columns=columns[:50],
                preview=preview,
            )
        else:
            status_code, message = await _post(row, sample_payload())
            ok = 200 <= status_code < 300
            result = ConnectionTestResult(
                ok=ok, status_code=status_code, message="Connected. A test result was delivered." if ok else message
            )
    except RemoteError as exc:
        result = ConnectionTestResult(ok=False, status_code=exc.status_code, message=exc.message)
    _remember(row, result.ok, result.message, result.status_code)
    await session.commit()
    return result
