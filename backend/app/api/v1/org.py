import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import ContextDep, CurrentUser, SessionDep, require
from app.models.org import User
from app.rbac.permissions import Permission
from app.schemas.common import Page, PageParams
from app.schemas.org import (
    DepartmentCreate,
    DepartmentOut,
    DepartmentUpdate,
    PasswordReset,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services import org

router = APIRouter(tags=["departments and users"])

ManageDepartments = Annotated[User, Depends(require(Permission.DEPARTMENTS_MANAGE))]
ReadUsers = Annotated[User, Depends(require(Permission.USERS_READ))]
ManageUsers = Annotated[User, Depends(require(Permission.USERS_MANAGE))]


@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(user: CurrentUser, session: SessionDep):
    return await org.list_departments(session, user)


@router.post("/departments", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
async def create_department(body: DepartmentCreate, user: ManageDepartments, session: SessionDep, ctx: ContextDep):
    return await org.create_department(session, user, body, ctx)


@router.get("/departments/{department_id}", response_model=DepartmentOut)
async def get_department(department_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    return await org.get_department(session, user, department_id)


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
async def update_department(
    department_id: uuid.UUID, body: DepartmentUpdate, user: ManageDepartments, session: SessionDep, ctx: ContextDep
):
    return await org.update_department(session, user, department_id, body, ctx)


@router.get("/users", response_model=Page[UserOut])
async def list_users(user: ReadUsers, session: SessionDep, params: Annotated[PageParams, Query()]):
    items, total = await org.list_users(session, user, params)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, user: ManageUsers, session: SessionDep, ctx: ContextDep):
    return await org.create_user(session, user, body, ctx)


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: uuid.UUID, user: ReadUsers, session: SessionDep):
    return await org.get_user(session, user, user_id)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, body: UserUpdate, user: ManageUsers, session: SessionDep, ctx: ContextDep):
    return await org.update_user(session, user, user_id, body, ctx)


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: uuid.UUID, body: PasswordReset, user: ManageUsers, session: SessionDep, ctx: ContextDep
) -> None:
    await org.reset_password(session, user, user_id, body.new_password, ctx)
