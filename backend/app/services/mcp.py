"""MCP tools: what an AI assistant can do in Bull AI Calling, over the same rules as the app.

Each tool needs one permission. The caller (a person, or an API key acting as one) only sees the tools it is
allowed to use, and every tool goes through the normal services, so department scoping, do-not-call checks,
calling hours and approvals apply unchanged. Nothing here approves anything: a person does that in the app.
"""

import csv
import io
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.errors import NotFound, ValidationFailed
from app.models.enums import CallStatus, CampaignStatus, ScriptVersionStatus
from app.models.org import Department, User
from app.models.scripts import Script, ScriptVersion
from app.rbac.permissions import Permission, is_admin, visible_departments
from app.schemas.campaigns import CampaignCreate
from app.schemas.common import PageParams
from app.schemas.imports import ColumnMapping, ImportProcess
from app.services import calls, campaigns, imports

FieldKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


@dataclass
class Caller:
    session: AsyncSession
    user: User
    ctx: RequestContext


@dataclass
class Tool:
    name: str
    title: str
    description: str
    permission: Permission
    args: type[BaseModel]
    run: Callable[[Caller, Any], Awaitable[Any]]
    read_only: bool = True


# ---- Argument models (their JSON schema is what the assistant sees) ----


class NoArgs(BaseModel):
    pass


class ListCampaignsArgs(BaseModel):
    status: CampaignStatus | None = Field(None, description="Only campaigns in this state")
    limit: int = Field(20, ge=1, le=100)


class CampaignRef(BaseModel):
    campaign_id: uuid.UUID


class CreateCampaignArgs(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = Field(
        description='What the team will see, e.g. "Service due reminder - November"'
    )
    script_version_id: uuid.UUID = Field(description="A published script version, from list_scripts")
    start_date: date | None = None
    end_date: date | None = None
    department_code: str | None = Field(None, description="Admins only: the department, e.g. SCM")


class Person(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    phone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=32)] = Field(
        description="Mobile number, e.g. 9876543210 or +91 98765 43210"
    )
    company: str | None = None
    language: str | None = Field(None, description="Tamil, English or Hindi (or ta-IN, en-IN, hi-IN)")
    items: list[dict[FieldKey, str | int | float | None]] = Field(
        default_factory=list,
        description="The script's upload fields for this person, one entry per line (e.g. per PO or machine). "
        "Keys are the field keys from list_scripts, e.g. po_number.",
        max_length=50,
    )


class AddContactsArgs(BaseModel):
    campaign_id: uuid.UUID
    contacts: list[Person] = Field(min_length=1, max_length=1000)
    skip_invalid: bool = Field(False, description="Add the valid people even if some rows have problems")
    dry_run: bool = Field(False, description="Only check; save nothing")


class ControlCampaignArgs(BaseModel):
    campaign_id: uuid.UUID
    action: Literal["start", "pause", "resume"]


class ListCallsArgs(BaseModel):
    campaign_id: uuid.UUID | None = None
    status: CallStatus | None = None
    limit: int = Field(20, ge=1, le=100)


class CallRef(BaseModel):
    call_id: uuid.UUID
    include_transcript: bool = False


# ---- Tools ----


def _campaign(c) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "name": c.name,
        "status": c.status,
        "script_version_id": str(c.script_version_id) if c.script_version_id else None,
        "contacts": c.contact_count,
        "progress": c.progress,
        "start_date": c.start_date,
        "end_date": c.end_date,
        "calling_window": c.calling_window,
    }


async def list_scripts(caller: Caller, _: NoArgs) -> dict[str, Any]:
    query = (
        select(ScriptVersion, Script)
        .join(Script, Script.id == ScriptVersion.script_id)
        .where(ScriptVersion.status == ScriptVersionStatus.PUBLISHED, Script.is_archived.is_(False))
        .order_by(Script.name)
    )
    if (scope := visible_departments(caller.user)) is not None:
        query = query.where(Script.department_id.in_(scope))
    rows = (await caller.session.execute(query)).all()
    return {
        "scripts": [
            {
                "script_version_id": str(v.id),
                "name": s.name,
                "version": v.version_no,
                "description": s.description,
                "purpose": v.config.get("objective"),
                "languages": v.config.get("languages", {}).get("allowed"),
                "upload_fields": [
                    {"key": f["key"], "label": f.get("label"), "type": f.get("type"), "required": f.get("required")}
                    for f in v.config.get("context_fields", [])
                ],
                "questions": [q.get("prompt") for q in v.config.get("questions", [])],
            }
            for v, s in rows
        ]
    }


async def list_campaigns(caller: Caller, args: ListCampaignsArgs) -> dict[str, Any]:
    items, total = await campaigns.list_campaigns(
        caller.session, caller.user, PageParams(page=1, page_size=args.limit), args.status
    )
    return {"total": total, "campaigns": [_campaign(c) for c in items]}


async def get_campaign(caller: Caller, args: CampaignRef) -> dict[str, Any]:
    return _campaign(await campaigns.get_campaign(caller.session, caller.user, args.campaign_id))


async def create_campaign(caller: Caller, args: CreateCampaignArgs) -> dict[str, Any]:
    department_id = None
    if args.department_code:
        if not is_admin(caller.user):
            raise ValidationFailed("Only admins choose the department; your campaigns are in your own department")
        department_id = await caller.session.scalar(
            select(Department.id).where(Department.code == args.department_code.upper())
        )
        if department_id is None:
            raise NotFound(f"No department {args.department_code}")
    body = CampaignCreate(
        name=args.name,
        script_version_id=args.script_version_id,
        start_date=args.start_date,
        end_date=args.end_date,
        department_id=department_id,
    )
    created = await campaigns.create_campaign(caller.session, caller.user, body, caller.ctx)
    return {**_campaign(created), "next": "Add people with add_contacts, then submit_campaign for approval."}


async def add_contacts(caller: Caller, args: AddContactsArgs) -> dict[str, Any]:
    campaign = await campaigns.get_campaign(caller.session, caller.user, args.campaign_id)
    keys = list(dict.fromkeys(k for p in args.contacts for item in p.items for k in item))
    if clash := {"name", "phone", "company", "language"} & set(keys):
        raise ValidationFailed(f"Item fields cannot be named {', '.join(sorted(clash))}")
    has = {f: any(getattr(p, f) for p in args.contacts) for f in ("company", "language")}
    headers = ["name", "phone", *(f for f in ("company", "language") if has[f]), *keys]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for person in args.contacts:
        base = [person.name, person.phone] + [getattr(person, f) or "" for f in ("company", "language") if has[f]]
        for item in person.items or [{}]:
            writer.writerow(base + ["" if item.get(k) is None else str(item[k]) for k in keys])
    upload = await imports.store_upload(
        caller.session,
        caller.user,
        campaign.department_id,
        "mcp-contacts.csv",
        buffer.getvalue().encode(),
        caller.ctx,
        source={"via": "mcp"},
    )
    mapping = ColumnMapping(
        name="name",
        phone="phone",
        company="company" if has["company"] else None,
        language="language" if has["language"] else None,
        campaign_fields={k: k for k in keys},
    )
    request = ImportProcess(
        mapping=mapping, campaign_id=campaign.id, skip_invalid_rows=args.skip_invalid, dry_run=args.dry_run
    )
    report = await imports.process(caller.session, caller.user, upload.id, request, caller.ctx)
    problems = [{"row": i.row, "field": i.field, "problem": i.message} for i in [*report.errors, *report.warnings]]
    return {
        "checked_only": report.dry_run,
        "saved": not report.dry_run and report.status == "completed",
        "rows": report.total_rows,
        "valid_rows": report.valid_rows,
        "rows_with_errors": report.error_rows,
        "new_contacts": report.new_contacts,
        "added_to_campaign": report.campaign_contacts,
        "problems": problems[:50],
        "note": "Rows are numbered from 2 (row 1 is the header). Same phone number = one call covering all its items.",
    }


async def submit_campaign(caller: Caller, args: CampaignRef) -> dict[str, Any]:
    submitted = await campaigns.submit(caller.session, caller.user, args.campaign_id, caller.ctx)
    return {**_campaign(submitted), "next": "A person approves it in the app; then control_campaign can start it."}


async def control_campaign(caller: Caller, args: ControlCampaignArgs) -> dict[str, Any]:
    return _campaign(
        await campaigns.set_running(caller.session, caller.user, args.campaign_id, args.action, caller.ctx)
    )


def _call(c) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "campaign_id": str(c.campaign_id) if c.campaign_id else None,
        "contact": c.contact_name,
        "phone": c.phone_masked,
        "status": c.status,
        "outcome": c.outcome,
        "end_reason": c.end_reason,
        "attempt": c.attempt_no,
        "started_at": c.started_at,
        "duration_seconds": c.duration_seconds,
        "simulated": c.is_simulated,
    }


async def list_calls(caller: Caller, args: ListCallsArgs) -> dict[str, Any]:
    items, total = await calls.list_calls(
        caller.session, caller.user, PageParams(page=1, page_size=args.limit), args.status, None, args.campaign_id
    )
    return {"total": total, "calls": [_call(c) for c in items]}


async def get_call_result(caller: Caller, args: CallRef) -> dict[str, Any]:
    detail = await calls.get_call(caller.session, caller.user, args.call_id)
    extraction = detail.extraction
    result = {
        **_call(detail),
        "items": (detail.context or {}).get("items") or [],
        "answers": detail.answers,
        "result": (
            {
                "status": extraction.status,
                "summary": extraction.summary,
                "confidence": extraction.confidence,
                "data": extraction.validated or extraction.raw.get("result", extraction.raw),
            }
            if extraction
            else None
        ),
    }
    if args.include_transcript:
        result["transcript"] = detail.transcript
    return result


TOOLS: list[Tool] = [
    Tool(
        "list_scripts",
        "List published scripts",
        "Published call scripts you can use for a campaign: purpose, questions, and the upload fields each "
        "person needs (use those keys in add_contacts items).",
        Permission.SCRIPTS_READ,
        NoArgs,
        list_scripts,
    ),
    Tool(
        "list_campaigns",
        "List campaigns",
        "Campaigns with status (draft, pending_approval, approved, running, paused, completed, cancelled), "
        "number of people and progress.",
        Permission.CAMPAIGNS_READ,
        ListCampaignsArgs,
        list_campaigns,
    ),
    Tool(
        "get_campaign",
        "Get a campaign",
        "One campaign's status, settings and progress.",
        Permission.CAMPAIGNS_READ,
        CampaignRef,
        get_campaign,
    ),
    Tool(
        "create_campaign",
        "Create a campaign",
        "Creates a draft campaign with a published script. Nobody is called until people are added, a person "
        "approves it in the app, and it is started.",
        Permission.CAMPAIGNS_WRITE,
        CreateCampaignArgs,
        create_campaign,
        read_only=False,
    ),
    Tool(
        "add_contacts",
        "Add people to a campaign",
        "Adds people to call to a draft campaign, with the same checks as an Excel upload (valid phone numbers, "
        "do-not-call list, duplicates, the script's required fields). Use dry_run first to see problems.",
        Permission.IMPORTS_WRITE,
        AddContactsArgs,
        add_contacts,
        read_only=False,
    ),
    Tool(
        "submit_campaign",
        "Send a campaign for approval",
        "Sends a draft campaign for approval. A person must approve it in the app before calling can start.",
        Permission.CAMPAIGNS_WRITE,
        CampaignRef,
        submit_campaign,
        read_only=False,
    ),
    Tool(
        "control_campaign",
        "Start, pause or resume calling",
        "start: an approved campaign begins calling (within its calling hours). pause: no new calls. resume.",
        Permission.CAMPAIGNS_WRITE,
        ControlCampaignArgs,
        control_campaign,
        read_only=False,
    ),
    Tool(
        "list_calls",
        "List calls",
        "Recent calls, newest first, optionally for one campaign: who, outcome and duration.",
        Permission.CALLS_READ,
        ListCallsArgs,
        list_calls,
    ),
    Tool(
        "get_call_result",
        "Get a call's result",
        "What was said and recorded on one call: the answers, a summary, the structured result and, if asked, "
        "the transcript.",
        Permission.CALLS_READ,
        CallRef,
        get_call_result,
    ),
]

TOOLS_BY_NAME = {t.name: t for t in TOOLS}
