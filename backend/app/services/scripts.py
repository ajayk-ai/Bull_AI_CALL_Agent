"""AI scripts and their versions.

Lifecycle of a version: draft -> pending_approval -> published (-> retired when a newer version is published).
A rejected version goes back to draft. Only drafts can be edited; published versions never change, so campaigns
and calls that reference one always see the exact configuration that was approved.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.errors import Conflict, Forbidden, NotFound
from app.models.enums import ScriptVersionStatus
from app.models.org import User
from app.models.scripts import Script, ScriptVersion
from app.rbac.permissions import can_see, is_admin, resolve_department, visible_departments
from app.schemas.scripts import ScriptCreate, ScriptOut, ScriptUpdate, ScriptVersionBody, ScriptVersionSummary
from app.services import audit

_OPEN = (ScriptVersionStatus.DRAFT, ScriptVersionStatus.PENDING_APPROVAL)


async def _get_script(session: AsyncSession, actor: User, script_id: uuid.UUID) -> Script:
    script = await session.get(Script, script_id)
    if script is None or not can_see(actor, script.department_id):
        raise NotFound("Script not found")
    return script


async def _versions(session: AsyncSession, script_id: uuid.UUID) -> list[ScriptVersion]:
    rows = await session.scalars(
        select(ScriptVersion).where(ScriptVersion.script_id == script_id).order_by(ScriptVersion.version_no.desc())
    )
    return list(rows)


async def _out(session: AsyncSession, script: Script) -> ScriptOut:
    out = ScriptOut.model_validate(script)
    out.versions = [ScriptVersionSummary.model_validate(v) for v in await _versions(session, script.id)]
    return out


async def get_version(
    session: AsyncSession, actor: User, version_id: uuid.UUID, *, for_update: bool = False
) -> tuple[ScriptVersion, Script]:
    version = await session.get(ScriptVersion, version_id, with_for_update=for_update)
    if version is None:
        raise NotFound("Script version not found")
    script = await _get_script(session, actor, version.script_id)
    return version, script


async def create_script(session: AsyncSession, actor: User, data: ScriptCreate, ctx: RequestContext) -> ScriptOut:
    department_id = resolve_department(actor, data.department_id)
    script = Script(department_id=department_id, name=data.name, description=data.description, created_by_id=actor.id)
    session.add(script)
    await session.flush()
    version = ScriptVersion(
        script_id=script.id,
        version_no=1,
        config=data.config.model_dump(mode="json"),
        extraction_schema=data.extraction_schema,
        created_by_id=actor.id,
    )
    session.add(version)
    await session.flush()
    audit.record(
        session,
        ctx,
        "script.create",
        actor=actor,
        entity_type="script",
        entity_id=script.id,
        department_id=department_id,
        changes={"name": script.name, "version_id": version.id},
    )
    await session.commit()
    return await _out(session, script)


async def list_scripts(
    session: AsyncSession, actor: User, include_archived: bool = False, department_id: uuid.UUID | None = None
) -> list[ScriptOut]:
    query = select(Script).order_by(Script.name)
    if (scope := visible_departments(actor)) is not None:
        query = query.where(Script.department_id.in_(scope))
    if department_id:
        query = query.where(Script.department_id == department_id)
    if not include_archived:
        query = query.where(Script.is_archived.is_(False))
    return [await _out(session, s) for s in await session.scalars(query)]


async def get_script(session: AsyncSession, actor: User, script_id: uuid.UUID) -> ScriptOut:
    return await _out(session, await _get_script(session, actor, script_id))


async def update_script(
    session: AsyncSession, actor: User, script_id: uuid.UUID, data: ScriptUpdate, ctx: RequestContext
) -> ScriptOut:
    script = await _get_script(session, actor, script_id)
    updates = data.model_dump(exclude_unset=True)
    changes = audit.diff({k: getattr(script, k) for k in updates}, updates)
    for key, value in updates.items():
        setattr(script, key, value)
    audit.record(
        session,
        ctx,
        "script.update",
        actor=actor,
        entity_type="script",
        entity_id=script.id,
        department_id=script.department_id,
        changes=changes,
    )
    await session.commit()
    return await _out(session, script)


async def create_version(
    session: AsyncSession, actor: User, script_id: uuid.UUID, data: ScriptVersionBody, ctx: RequestContext
) -> ScriptVersion:
    script = await _get_script(session, actor, script_id)
    # Lock the script row so two concurrent requests cannot take the same version number.
    await session.execute(select(Script.id).where(Script.id == script.id).with_for_update())
    if script.is_archived:
        raise Conflict("Script is archived")
    open_version = await session.scalar(
        select(ScriptVersion).where(ScriptVersion.script_id == script.id, ScriptVersion.status.in_(_OPEN))
    )
    if open_version:
        raise Conflict(
            f"Version {open_version.version_no} is still {open_version.status}; finish or edit it first",
            details={"version_id": str(open_version.id)},
        )
    latest = await session.scalar(
        select(func.max(ScriptVersion.version_no)).where(ScriptVersion.script_id == script.id)
    )
    version = ScriptVersion(
        script_id=script.id,
        version_no=(latest or 0) + 1,
        config=data.config.model_dump(mode="json"),
        extraction_schema=data.extraction_schema,
        created_by_id=actor.id,
    )
    session.add(version)
    await session.flush()
    audit.record(
        session,
        ctx,
        "script_version.create",
        actor=actor,
        entity_type="script_version",
        entity_id=version.id,
        department_id=script.department_id,
        changes={"script_id": script.id, "version_no": version.version_no},
    )
    await session.commit()
    return version


async def update_version(
    session: AsyncSession, actor: User, version_id: uuid.UUID, data: ScriptVersionBody, ctx: RequestContext
) -> ScriptVersion:
    version, script = await get_version(session, actor, version_id, for_update=True)
    if version.status != ScriptVersionStatus.DRAFT:
        raise Conflict(f"Only drafts can be edited; this version is {version.status}")
    version.config = data.config.model_dump(mode="json")
    version.extraction_schema = data.extraction_schema
    audit.record(
        session,
        ctx,
        "script_version.update",
        actor=actor,
        entity_type="script_version",
        entity_id=version.id,
        department_id=script.department_id,
    )
    await session.commit()
    return version


async def _transition(
    session: AsyncSession,
    actor: User,
    version_id: uuid.UUID,
    expected: ScriptVersionStatus,
    action: str,
    ctx: RequestContext,
    comments: str | None = None,
) -> tuple[ScriptVersion, Script]:
    version, script = await get_version(session, actor, version_id, for_update=True)
    if version.status != expected:
        raise Conflict(f"Version is {version.status}, expected {expected}")
    audit.record(
        session,
        ctx,
        action,
        actor=actor,
        entity_type="script_version",
        entity_id=version.id,
        department_id=script.department_id,
        changes={"version_no": version.version_no, "comments": comments}
        if comments
        else {"version_no": version.version_no},
    )
    return version, script


async def submit_version(
    session: AsyncSession, actor: User, version_id: uuid.UUID, ctx: RequestContext
) -> ScriptVersion:
    version, _ = await _transition(session, actor, version_id, ScriptVersionStatus.DRAFT, "script_version.submit", ctx)
    version.status = ScriptVersionStatus.PENDING_APPROVAL
    await session.commit()
    return version


async def approve_version(
    session: AsyncSession, actor: User, version_id: uuid.UUID, comments: str | None, ctx: RequestContext
) -> ScriptVersion:
    version, script = await _transition(
        session, actor, version_id, ScriptVersionStatus.PENDING_APPROVAL, "script_version.approve", ctx, comments
    )
    if version.created_by_id == actor.id and not is_admin(actor):
        raise Forbidden("A script version must be approved by someone other than its author")
    now = datetime.now(UTC)
    previous = await session.scalars(
        select(ScriptVersion).where(
            ScriptVersion.script_id == script.id, ScriptVersion.status == ScriptVersionStatus.PUBLISHED
        )
    )
    for old in previous:
        old.status = ScriptVersionStatus.RETIRED
    version.status = ScriptVersionStatus.PUBLISHED
    version.approved_by_id = actor.id
    version.approved_at = now
    version.published_at = now
    await session.commit()
    return version


async def reject_version(
    session: AsyncSession, actor: User, version_id: uuid.UUID, comments: str | None, ctx: RequestContext
) -> ScriptVersion:
    version, _ = await _transition(
        session, actor, version_id, ScriptVersionStatus.PENDING_APPROVAL, "script_version.reject", ctx, comments
    )
    version.status = ScriptVersionStatus.DRAFT
    await session.commit()
    return version


def context_problems(config: dict, context: dict) -> list[str]:
    """Problems with one campaign contact's data against the script's context fields.

    Campaign data is {"items": [{...}, ...]}: one item per line the call covers (for SCM, one per PO), so a
    supplier with three open POs gets one call that covers all three.
    """
    fields = config.get("context_fields") or []
    if not fields:
        return []
    items = context.get("items")
    if not isinstance(items, list) or not items:
        return ["no campaign data (items) for this contact"]
    problems = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            problems.append(f"item {index} is not an object")
            continue
        for field in fields:
            value = item.get(field["key"])
            if value in (None, ""):
                if field.get("required", True):
                    problems.append(f"item {index}: {field['label']} is missing")
                continue
            if field.get("type") == "date":
                try:
                    date.fromisoformat(str(value))
                except ValueError:
                    problems.append(f"item {index}: {field['label']} is not a date (YYYY-MM-DD): {value!r}")
            elif field.get("type") == "number":
                try:
                    float(value)
                except TypeError, ValueError:
                    problems.append(f"item {index}: {field['label']} is not a number: {value!r}")
    return problems
