import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.user import User
from app.schemas.wire_in.key import (
    KeyBlockRequest,
    KeyBulkUpdate,
    KeyGenerate,
    KeyRotateRequest,
    KeyUpdate,
)
from app.schemas.wire_out.common import StatusResponse
from app.schemas.wire_out.key import KeyGenerateResponse, KeyResponse
from app.services.key_service import (
    block_key,
    bulk_update_keys,
    delete_key,
    generate_key,
    get_key,
    list_keys,
    reactivate_key,
    reset_spend,
    rotate_key,
    update_key,
)

router = APIRouter(prefix="/keys", tags=["keys"])


# ========== POST /keys — generate ==========


@router.post("", status_code=201)
async def generate(
    body: KeyGenerate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KeyGenerateResponse:
    raw_key, api_key = await generate_key(
        db,
        user_id=current_user.id,
        key_alias=body.key_alias,
        team_id=body.team_id,
        org_id=body.org_id,
        allowed_models=body.allowed_models,
        max_budget=body.max_budget,
        tpm_limit=body.tpm_limit,
        rpm_limit=body.rpm_limit,
        max_parallel_requests=body.max_parallel_requests,
        expires_at=body.expires_at,
        metadata=body.metadata,
    )
    return KeyGenerateResponse(
        key=raw_key,
        key_id=api_key.id,
        key_prefix=api_key.key_prefix,
        expires_at=api_key.expires_at,
    )


# ========== GET /keys — list ==========


@router.get("")
async def list_all(
    user_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
) -> list[KeyResponse]:
    keys = await list_keys(db, user_id=user_id, team_id=team_id, org_id=org_id, page=page, page_size=page_size)
    return [KeyResponse.model_validate(k) for k in keys]


# ========== GET /keys/{key_id} — read one ==========


@router.get("/{key_id}")
async def get_one(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
) -> KeyResponse:
    key = await get_key(db, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return KeyResponse.model_validate(key)


# ========== PATCH /keys/{key_id} — update ==========


@router.patch("/{key_id}")
async def update(
    key_id: uuid.UUID,
    body: KeyUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> KeyResponse:
    key = await update_key(
        db,
        key_id,
        key_alias=body.key_alias,
        allowed_models=body.allowed_models,
        max_budget=body.max_budget,
        tpm_limit=body.tpm_limit,
        rpm_limit=body.rpm_limit,
        metadata_json=body.metadata,
    )
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return KeyResponse.model_validate(key)


# ========== POST /keys/{key_id}/rotate — rotate ==========


@router.post("/{key_id}/rotate")
async def rotate(
    key_id: uuid.UUID,
    body: KeyRotateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> KeyGenerateResponse:
    result = await rotate_key(db, key_id, grace_period_hours=body.grace_period_hours)
    if result is None:
        raise HTTPException(status_code=404, detail="Key not found")
    raw_key, api_key = result
    return KeyGenerateResponse(
        key=raw_key,
        key_id=api_key.id,
        key_prefix=api_key.key_prefix,
        expires_at=api_key.expires_at,
    )


# ========== PATCH /keys/{key_id}/block — block/unblock ==========


@router.patch("/{key_id}/block")
async def block(
    key_id: uuid.UUID,
    body: KeyBlockRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> KeyResponse:
    key = await block_key(db, key_id, body.blocked)
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return KeyResponse.model_validate(key)


# ========== POST /keys/{key_id}/reactivate — reactivate ==========


@router.post("/{key_id}/reactivate")
async def reactivate(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> KeyResponse:
    key = await reactivate_key(db, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return KeyResponse.model_validate(key)


# ========== POST /keys/{key_id}/reset-spend — reset spend ==========


@router.post("/{key_id}/reset-spend")
async def reset_key_spend(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> KeyResponse:
    key = await reset_spend(db, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return KeyResponse.model_validate(key)


# ========== POST /keys/bulk-update — bulk update ==========


@router.post("/bulk-update")
async def bulk_update(
    body: KeyBulkUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> StatusResponse:
    await bulk_update_keys(
        db,
        key_ids=body.key_ids,
        allowed_models=body.allowed_models,
        max_budget=body.max_budget,
    )
    return StatusResponse()


# ========== DELETE /keys/{key_id} — delete ==========


@router.delete("/{key_id}", status_code=204)
async def delete(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
):
    success = await delete_key(db, key_id)
    if not success:
        raise HTTPException(status_code=404, detail="Key not found")
