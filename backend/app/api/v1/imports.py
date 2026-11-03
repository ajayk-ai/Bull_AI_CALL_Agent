import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import Response

from app.api.deps import ContextDep, SessionDep, require
from app.models.org import User
from app.rbac.permissions import Permission
from app.schemas.common import Page, PageParams
from app.schemas.imports import ImportOut, ImportProcess, ImportReport, ImportUploadOut
from app.services import imports

router = APIRouter(prefix="/imports", tags=["contact imports"])

ReadImports = Annotated[User, Depends(require(Permission.CONTACTS_READ))]
WriteImports = Annotated[User, Depends(require(Permission.IMPORTS_WRITE))]


@router.post("", response_model=ImportUploadOut, status_code=status.HTTP_201_CREATED)
async def upload(
    user: WriteImports,
    session: SessionDep,
    ctx: ContextDep,
    file: Annotated[UploadFile, File(description=".csv or .xlsx; first non-empty row is the header")],
    department_id: Annotated[uuid.UUID | None, Form()] = None,
):
    """Step 1: upload. Returns the column headers, a preview and a suggested mapping to confirm."""
    return await imports.upload(session, user, file, department_id, ctx)


@router.post("/{import_id}/process", response_model=ImportReport)
async def process(import_id: uuid.UUID, body: ImportProcess, user: WriteImports, session: SessionDep, ctx: ContextDep):
    """Step 2: validate with the confirmed mapping. Use `dry_run` first to see problems without saving."""
    return await imports.process(session, user, import_id, body, ctx)


@router.get("", response_model=Page[ImportOut])
async def list_imports(
    user: ReadImports,
    session: SessionDep,
    params: Annotated[PageParams, Query()],
    campaign_id: uuid.UUID | None = None,
):
    items, total = await imports.list_imports(session, user, params, campaign_id)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.get("/{import_id}", response_model=ImportOut)
async def get_import(import_id: uuid.UUID, user: ReadImports, session: SessionDep):
    return await imports.get_import(session, user, import_id)


@router.get("/{import_id}/errors.csv", response_class=Response)
async def error_report(import_id: uuid.UUID, user: ReadImports, session: SessionDep) -> Response:
    file_name, content = await imports.error_report_csv(session, user, import_id)
    return Response(
        content="﻿" + content,  # BOM so Excel opens it as UTF-8
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )
