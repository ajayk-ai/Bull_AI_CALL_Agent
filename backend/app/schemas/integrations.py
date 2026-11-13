"""Connected apps: a department's own CRM, ERP or HR system, reached over HTTP.

Two kinds today:
- fetch_contacts: the app GETs a JSON list of people from the department's system and imports it like a file.
- send_results:   after each call, the app POSTs the call's result as JSON to the department's system.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AnyHttpUrl, BaseModel, Field, StringConstraints, field_validator

ConnectionKind = Literal["fetch_contacts", "send_results"]
AuthType = Literal["none", "bearer", "api_key", "basic"]

HeaderName = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9-]{1,64}$")]
ConnectionName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# Dot path to the list of records in the JSON reply, e.g. "data.items". Empty: the reply itself is the list.
RecordsPath = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200, pattern=r"^[A-Za-z0-9_.-]*$")]

QueryKey = Annotated[str, StringConstraints(max_length=100)]
QueryValue = Annotated[str, StringConstraints(max_length=500)]

# Headers the app sets itself, or that would carry credentials outside the encrypted secret.
_RESERVED_HEADERS = {"authorization", "content-type", "content-length", "host", "cookie", "proxy-authorization"}


class ConnectionIn(BaseModel):
    name: ConnectionName
    kind: ConnectionKind
    url: AnyHttpUrl
    department_id: uuid.UUID | None = None
    is_active: bool = True

    auth_type: AuthType = "none"
    api_key_header: HeaderName = "X-API-Key"
    username: Annotated[str, StringConstraints(max_length=200)] | None = None
    # Token, API key or password. Write-only. On update: None keeps the stored one, "" removes it.
    secret: Annotated[str, StringConstraints(max_length=4000)] | None = None
    # send_results: results are signed with HMAC-SHA256 when set. Same update rule as `secret`.
    signing_secret: Annotated[str, StringConstraints(max_length=200)] | None = None

    headers: dict[HeaderName, Annotated[str, StringConstraints(max_length=500)]] = Field(default_factory=dict)
    # fetch_contacts
    records_path: RecordsPath = ""
    query: dict[QueryKey, QueryValue] = Field(default_factory=dict)
    # send_results: only calls of these campaigns. Empty: every campaign of the department.
    campaign_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)

    @field_validator("headers")
    @classmethod
    def _no_reserved_headers(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 10:
            raise ValueError("at most 10 extra headers")
        bad = sorted(h for h in value if h.lower() in _RESERVED_HEADERS)
        if bad:
            raise ValueError(f"set these through the sign-in options instead: {', '.join(bad)}")
        return value

    @field_validator("query")
    @classmethod
    def _query_size(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 20:
            raise ValueError("at most 20 query parameters")
        return value


class ConnectionOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: ConnectionKind
    url: str
    department_id: uuid.UUID | None
    is_active: bool
    auth_type: AuthType
    api_key_header: str
    username: str | None
    has_secret: bool
    has_signing_secret: bool
    headers: dict[str, str]
    records_path: str
    query: dict[str, str]
    campaign_ids: list[uuid.UUID]
    # The last test, fetch or delivery: {"at", "ok", "status_code", "message"}.
    last_result: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class ConnectionTestResult(BaseModel):
    ok: bool
    status_code: int | None = None
    message: str
    # fetch_contacts: what the reply looks like.
    records: int | None = None
    columns: list[str] = Field(default_factory=list)
    preview: list[dict[str, str]] = Field(default_factory=list)


class FetchRequest(BaseModel):
    campaign_id: uuid.UUID | None = None
