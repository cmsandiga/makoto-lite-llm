import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.user import User
from app.schemas.wire_in.user import (
    UserBlockRequest,
    UserCreate,
    UserUpdateBudget,
    UserUpdateProfile,
)
from app.schemas.wire_out.user import UserResponse
from app.services.user_service import (
    block_user,
    create_user,
    delete_user,
    get_user,
    list_users,
    update_user_budget,
    update_user_profile,
)

router = APIRouter(prefix="/users", tags=["users"])


# ========== POST /users — create ==========


@router.post("", status_code=201)
async def create(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> UserResponse:
    try:
        user = await create_user(
            db,
            email=body.email,
            password=body.password,
            name=body.name,
            role=body.role,
            max_budget=body.max_budget,
            metadata=body.metadata,
        )
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Email already exists")
    return UserResponse.model_validate(user)


# ========== GET /users — list ==========


@router.get("")
async def list_all(
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> list[UserResponse]:
    users = await list_users(db, page, page_size)
    return [UserResponse.model_validate(u) for u in users]


# ========== GET /users/{user_id} — read one ==========


@router.get("/{user_id}")
async def get_one(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
) -> UserResponse:
    user = await get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user)


# ========== PATCH /users/{user_id}/profile — update profile ==========


@router.patch("/{user_id}/profile")
async def update_profile(
    user_id: uuid.UUID,
    body: UserUpdateProfile,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> UserResponse:
    user = await update_user_profile(
        db,
        user_id,
        name=body.name,
        role=body.role,
        metadata_json=body.metadata,
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user)


# ========== PATCH /users/{user_id}/budget — update budget ==========


@router.patch("/{user_id}/budget")
async def update_budget(
    user_id: uuid.UUID,
    body: UserUpdateBudget,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> UserResponse:
    user = await update_user_budget(
        db,
        user_id,
        max_budget=body.max_budget,
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user)


# ========== PATCH /users/{user_id}/block — block/unblock ==========


@router.patch("/{user_id}/block")
async def block(
    user_id: uuid.UUID,
    body: UserBlockRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> UserResponse:
    user = await block_user(db, user_id, body.blocked)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user)


# ========== DELETE /users/{user_id} — delete ==========


@router.delete("/{user_id}", status_code=204)
async def delete(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
):
    success = await delete_user(db, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
