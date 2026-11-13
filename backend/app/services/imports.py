"""Bulk contact import from CSV/Excel, with a user-chosen column mapping.

1. upload:  the file is stored encrypted; headers, a preview and a suggested mapping are returned.
2. process: rows are validated with the confirmed mapping. `dry_run` reports without saving. By default a single
            invalid row stops the whole import; `skip_invalid_rows` saves the valid rows instead.

Into a campaign, rows with the same phone number become one campaign contact with several items (for SCM, one
call per supplier covering all its open POs). Without a campaign, a repeated number is an error.
"""

import csv
import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import phone
from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.security import decrypt_bytes, encrypt_bytes
from app.core.storage import get_storage
from app.models.campaigns import Campaign, CampaignContact, CampaignImport
from app.models.contacts import Contact, DoNotCall
from app.models.enums import CampaignStatus, ImportStatus
from app.models.org import User
from app.models.scripts import ScriptVersion
from app.rbac.permissions import can_see, resolve_department, visible_departments
from app.schemas.common import PageParams
from app.schemas.imports import DuplicatePolicy, ImportProcess, ImportReport, ImportUploadOut, RowIssue
from app.services import audit
from app.services.scripts import context_problems
from app.services.spreadsheet import FileError, read_sheet, suggest_mapping

_LANGUAGE_CODE = re.compile(r"^[a-z]{2,3}-[A-Z]{2}$")
_MAX_ISSUES_STORED = 2000
_MAX_ISSUES_RETURNED = 500
_PREVIEW_ROWS = 5


@dataclass
class _Row:
    number: int
    name: str
    phone_number: phone.NormalisedPhone
    company: str | None
    language: str | None
    contact_fields: dict[str, str]
    item: dict[str, str]


@dataclass
class _Group:
    """All rows of the file that share one phone number."""

    rows: list[_Row] = field(default_factory=list)

    @property
    def first(self) -> _Row:
        return self.rows[0]


def _safe_file_name(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]).strip("._")
    return (base or "upload")[:120]


def _language(raw: str) -> str | None:
    if not raw:
        return None
    settings = get_settings()
    code = raw if _LANGUAGE_CODE.match(raw) else settings.language_aliases.get(raw.strip().lower())
    if code is None or code not in settings.supported_languages:
        raise ValueError(f"unsupported language {raw!r}; use one of {', '.join(settings.supported_languages)}")
    return code


async def _get_import(session: AsyncSession, actor: User, import_id: uuid.UUID, *, for_update: bool = False):
    record = await session.get(CampaignImport, import_id, with_for_update=for_update)
    if record is None or not can_see(actor, record.department_id):
        raise NotFound("Import not found")
    return record


# ---- upload ----


async def upload(
    session: AsyncSession, actor: User, file: UploadFile, department_id: uuid.UUID | None, ctx: RequestContext
) -> ImportUploadOut:
    settings = get_settings()
    department_id = resolve_department(actor, department_id)
    data = await file.read(settings.import_max_bytes + 1)
    if len(data) > settings.import_max_bytes:
        raise ValidationFailed(f"File is larger than {settings.import_max_bytes // (1024 * 1024)} MB")
    return await store_upload(session, actor, department_id, file.filename or "upload", data, ctx)


async def store_upload(
    session: AsyncSession,
    actor: User,
    department_id: uuid.UUID,
    file_name: str,
    data: bytes,
    ctx: RequestContext,
    source: dict | None = None,
) -> ImportUploadOut:
    """Reads, stores and records an upload whose department is already resolved. Also used for data fetched
    from a connected app (`source` names the connection), so it gets the same mapping and checks as a file."""
    settings = get_settings()
    file_name = _safe_file_name(file_name)
    try:
        sheet = read_sheet(file_name, data, settings.import_max_rows)
    except FileError as exc:
        raise ValidationFailed(str(exc))

    record = CampaignImport(
        department_id=department_id,
        file_name=file_name,
        file_size_bytes=len(data),
        headers=sheet.headers,
        total_rows=len(sheet.rows),
        uploaded_by_id=actor.id,
    )
    session.add(record)
    await session.flush()
    record.object_key = f"imports/{department_id}/{record.id}/{file_name}.enc"
    await get_storage().put(record.object_key, encrypt_bytes(data))
    audit.record(
        session,
        ctx,
        "import.upload",
        actor=actor,
        entity_type="import",
        entity_id=record.id,
        department_id=department_id,
        changes={"file_name": file_name, "rows": len(sheet.rows), **({"source": source} if source else {})},
    )
    await session.commit()
    return ImportUploadOut(
        id=record.id,
        file_name=file_name,
        headers=sheet.headers,
        total_rows=len(sheet.rows),
        preview=[values for _, values in sheet.rows[:_PREVIEW_ROWS]],
        suggested_mapping=suggest_mapping(sheet.headers),
    )


# ---- process ----


def _parse_rows(sheet_rows, request: ImportProcess) -> tuple[list[_Row], list[RowIssue]]:
    mapping = request.mapping
    rows: list[_Row] = []
    errors: list[RowIssue] = []
    for number, values in sheet_rows:
        row_errors: list[RowIssue] = []
        name = values[mapping.name][:200]
        if not name:
            row_errors.append(RowIssue(row=number, field=mapping.name, message="Name is empty"))
        try:
            normalised = phone.normalise(values[mapping.phone])
        except phone.InvalidPhoneNumber:
            normalised = None
            shown = values[mapping.phone] or "(empty)"
            row_errors.append(RowIssue(row=number, field=mapping.phone, message=f"Invalid phone number: {shown}"))
        language = None
        if mapping.language:
            try:
                language = _language(values[mapping.language])
            except ValueError as exc:
                row_errors.append(RowIssue(row=number, field=mapping.language, message=str(exc)))
        if row_errors:
            errors.extend(row_errors)
            continue
        rows.append(
            _Row(
                number=number,
                name=name,
                phone_number=normalised,
                company=(values[mapping.company][:200] or None) if mapping.company else None,
                language=language,
                contact_fields={k: values[h][:1000] for k, h in mapping.contact_fields.items() if values[h]},
                item={k: values[h][:1000] for k, h in mapping.campaign_fields.items() if values[h]},
            )
        )
    return rows, errors


async def process(
    session: AsyncSession, actor: User, import_id: uuid.UUID, request: ImportProcess, ctx: RequestContext
) -> ImportReport:
    record = await _get_import(session, actor, import_id, for_update=True)
    record_id = record.id  # a dry run rolls back, which expires `record`
    if record.status != ImportStatus.UPLOADED:
        raise Conflict(f"This import is already {record.status}; upload the file again to re-import")
    unknown = sorted(set(request.mapping.headers_used()) - set(record.headers))
    if unknown:
        raise ValidationFailed("The mapping names columns that are not in the file", details={"columns": unknown})
    keys = list(request.mapping.contact_fields) + list(request.mapping.campaign_fields)
    if len(set(request.mapping.contact_fields)) + len(set(request.mapping.campaign_fields)) != len(set(keys)):
        raise ValidationFailed("A field key is used both as a contact field and a campaign field")

    campaign, script_config = None, None
    if request.campaign_id:
        campaign = await session.get(Campaign, request.campaign_id, with_for_update=True)
        if campaign is None or campaign.department_id != record.department_id:
            raise ValidationFailed("Campaign not found in this import's department")
        if campaign.status != CampaignStatus.DRAFT:
            raise Conflict(f"Contacts can only be added to a draft campaign; this one is {campaign.status}")
        if campaign.script_version_id:
            script_config = (await session.get(ScriptVersion, campaign.script_version_id)).config

    try:
        sheet = read_sheet(
            record.file_name, decrypt_bytes(await get_storage().get(record.object_key)), get_settings().import_max_rows
        )
    except FileError as exc:  # the stored file was readable at upload, so this is unexpected
        raise ValidationFailed(str(exc))

    rows, errors = _parse_rows(sheet.rows, request)
    warnings: list[RowIssue] = []

    # Group rows by phone number.
    groups: dict[str, _Group] = {}
    for row in rows:
        group = groups.setdefault(row.phone_number.hash, _Group())
        if group.rows and campaign is None:
            errors.append(
                RowIssue(
                    row=row.number,
                    field=request.mapping.phone,
                    message=f"Same phone number as row {group.first.number}",
                )
            )
            continue
        if group.rows and row.name != group.first.name:
            warnings.append(
                RowIssue(
                    row=row.number,
                    field=request.mapping.name,
                    level="warning",
                    message=f"Same number as row {group.first.number} but a different name; "
                    f"the name from row {group.first.number} is used",
                )
            )
        group.rows.append(row)

    # Campaign data must satisfy the script's context fields, row by row.
    if script_config:
        for group in groups.values():
            for row in group.rows:
                for problem in context_problems(script_config, {"items": [row.item]}):
                    errors.append(RowIssue(row=row.number, message=problem.removeprefix("item 1: ")))

    error_row_numbers = {e.row for e in errors}
    valid_groups = {h: g for h, g in groups.items() if not any(r.number in error_row_numbers for r in g.rows)}

    hashes = list(valid_groups)
    existing = (
        {
            c.phone_hash: c
            for c in await session.scalars(
                select(Contact).where(
                    Contact.department_id == record.department_id,
                    Contact.phone_hash.in_(hashes),
                    Contact.deleted_at.is_(None),
                )
            )
        }
        if hashes
        else {}
    )
    suppressed = (
        set(
            await session.scalars(
                select(DoNotCall.phone_hash).where(
                    DoNotCall.phone_hash.in_(hashes),
                    (DoNotCall.department_id.is_(None)) | (DoNotCall.department_id == record.department_id),
                    (DoNotCall.expires_at.is_(None)) | (DoNotCall.expires_at > func.now()),
                )
            )
        )
        if hashes
        else set()
    )
    for phone_hash in suppressed:
        warnings.append(
            RowIssue(
                row=valid_groups[phone_hash].first.number,
                field=request.mapping.phone,
                level="warning",
                message="Number is on the do-not-call list and will not be called",
            )
        )

    total = len(sheet.rows)
    error_rows = len(error_row_numbers)
    blocked = bool(errors) and not request.skip_invalid_rows
    new_count = updated_count = campaign_count = 0
    # Rows whose number already belongs to a contact in this department.
    duplicate_count = sum(len(g.rows) for h, g in valid_groups.items() if h in existing)

    if not request.dry_run and not blocked:
        contact_ids: dict[str, uuid.UUID] = {}
        for phone_hash, group in valid_groups.items():
            row = group.first
            contact = existing.get(phone_hash)
            if contact is None:
                contact = Contact(
                    id=uuid.uuid7(),
                    department_id=record.department_id,
                    name=row.name,
                    company=row.company,
                    phone_encrypted=row.phone_number.encrypted,
                    phone_hash=phone_hash,
                    phone_masked=row.phone_number.masked,
                    language=row.language,
                    custom_fields=row.contact_fields,
                    created_by_id=actor.id,
                )
                session.add(contact)
                new_count += 1
            elif request.duplicate_policy == DuplicatePolicy.UPDATE:
                contact.name = row.name
                contact.company = row.company or contact.company
                contact.language = row.language or contact.language
                contact.custom_fields = {**contact.custom_fields, **row.contact_fields}
                updated_count += 1
            contact_ids[phone_hash] = contact.id
        await session.flush()

        if campaign is not None:
            members = {
                m.contact_id: m
                for m in await session.scalars(
                    select(CampaignContact).where(
                        CampaignContact.campaign_id == campaign.id,
                        CampaignContact.contact_id.in_(list(contact_ids.values())),
                    )
                )
            }
            for phone_hash, group in valid_groups.items():
                context = {"items": [r.item for r in group.rows]}
                member = members.get(contact_ids[phone_hash])
                if member is None:
                    session.add(
                        CampaignContact(campaign_id=campaign.id, contact_id=contact_ids[phone_hash], context=context)
                    )
                else:
                    member.context = context
                    warnings.append(
                        RowIssue(
                            row=group.first.number,
                            level="warning",
                            message="Contact was already in the campaign; its campaign data was replaced",
                        )
                    )
                campaign_count += 1

    issues = [*errors, *warnings]
    status = record.status
    if not request.dry_run:
        status = ImportStatus.FAILED if blocked else ImportStatus.COMPLETED
        record.status = status
        record.campaign_id = campaign.id if campaign else None
        record.column_mapping = request.mapping.model_dump()
        record.options = request.model_dump(mode="json", exclude={"mapping"})
        record.valid_rows = total - error_rows
        record.error_rows = error_rows
        record.duplicate_rows = duplicate_count
        record.new_contacts = new_count
        record.updated_contacts = updated_count
        record.campaign_contacts = campaign_count
        record.errors = [i.model_dump() for i in sorted(issues, key=lambda i: i.row)[:_MAX_ISSUES_STORED]]
        record.completed_at = datetime.now(UTC)
        audit.record(
            session,
            ctx,
            "import.process",
            actor=actor,
            entity_type="import",
            entity_id=record.id,
            department_id=record.department_id,
            changes={
                "status": status,
                "campaign_id": record.campaign_id,
                "new_contacts": new_count,
                "updated_contacts": updated_count,
                "campaign_contacts": campaign_count,
                "error_rows": error_rows,
            },
        )
        await session.commit()
    else:
        await session.rollback()

    return ImportReport(
        id=record_id,
        status=status,
        dry_run=request.dry_run,
        total_rows=total,
        valid_rows=total - error_rows,
        error_rows=error_rows,
        duplicate_rows=duplicate_count,
        new_contacts=new_count,
        updated_contacts=updated_count,
        campaign_contacts=campaign_count,
        errors=sorted(errors, key=lambda i: i.row)[:_MAX_ISSUES_RETURNED],
        warnings=sorted(warnings, key=lambda i: i.row)[:_MAX_ISSUES_RETURNED],
    )


# ---- history ----


async def list_imports(
    session: AsyncSession, actor: User, params: PageParams, campaign_id: uuid.UUID | None = None
) -> tuple[list[CampaignImport], int]:
    query = select(CampaignImport)
    if (scope := visible_departments(actor)) is not None:
        query = query.where(CampaignImport.department_id.in_(scope))
    if campaign_id:
        query = query.where(CampaignImport.campaign_id == campaign_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(CampaignImport.created_at.desc()).offset(params.offset).limit(params.page_size)
    )
    return list(rows), total or 0


async def get_import(session: AsyncSession, actor: User, import_id: uuid.UUID) -> CampaignImport:
    return await _get_import(session, actor, import_id)


async def error_report_csv(session: AsyncSession, actor: User, import_id: uuid.UUID) -> tuple[str, str]:
    record = await _get_import(session, actor, import_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Row", "Level", "Column", "Problem"])
    for issue in record.errors:
        writer.writerow([issue["row"], issue["level"], issue.get("field") or "", issue["message"]])
    return f"{record.file_name.rsplit('.', 1)[0]}_errors.csv", buffer.getvalue()
