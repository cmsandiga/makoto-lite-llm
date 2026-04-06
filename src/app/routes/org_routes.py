import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.exceptions import DuplicateError
from app.models.user import User
from app.schemas.wire_in.org import (
    OrgCreate,
    OrgMemberAdd,
    OrgMemberRemove,
    OrgMemberUpdate,
    OrgUpdate,
)
from app.schemas.wire_out.common import StatusResponse
from app.schemas.wire_out.org import OrgResponse
from app.services.org_service import (
    add_member,
    create_org,
    delete_org,
    get_org,
    list_orgs,
    remove_member,
    update_member,
    update_org,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


# ========== POST /organizations — create ==========


@router.post("", status_code=201)
async def create(
    body: OrgCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> OrgResponse:
    try:
        org = await create_org(
            db,
            name=body.name,
            slug=body.slug,
            max_budget=body.max_budget,
            metadata=body.metadata,
        )
    except DuplicateError as e:
        raise HTTPException(status_code=409, detail=e.detail)
    return OrgResponse.model_validate(org)


# ========== GET /organizations — list ==========


@router.get("")
async def list_all(
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> list[OrgResponse]:
    orgs = await list_orgs(db, page, page_size)
    return [OrgResponse.model_validate(o) for o in orgs]


# ========== GET /organizations/{org_id} — read one ==========


@router.get("/{org_id}")
async def get_one(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
) -> OrgResponse:
    org = await get_org(db, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrgResponse.model_validate(org)


# ========== PATCH /organizations/{org_id} — update ==========


@router.patch("/{org_id}")
async def update(
    org_id: uuid.UUID,
    body: OrgUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> OrgResponse:
    org = await update_org(
        db,
        org_id,
        name=body.name,
        max_budget=body.max_budget,
        metadata_json=body.metadata,
    )
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrgResponse.model_validate(org)


# ========== DELETE /organizations/{org_id} — delete + cascade ==========


@router.delete("/{org_id}", status_code=204)
async def delete(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
):
    success = await delete_org(db, org_id)
    if not success:
        raise HTTPException(status_code=404, detail="Organization not found")


# ========== POST /organizations/{org_id}/members — add member ==========


@router.post("/{org_id}/members", status_code=201)
async def member_add(
    org_id: uuid.UUID,
    body: OrgMemberAdd,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> StatusResponse:
    try:
        await add_member(db, org_id=org_id, user_id=body.user_id, role=body.role)
    except DuplicateError as e:
        raise HTTPException(status_code=409, detail=e.detail)
    return StatusResponse()


# ========== PATCH /organizations/{org_id}/members — update member ==========


@router.patch("/{org_id}/members")
async def member_update(
    org_id: uuid.UUID,
    body: OrgMemberUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> StatusResponse:
    membership = await update_member(db, org_id=org_id, user_id=body.user_id, role=body.role)
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    return StatusResponse()


# ========== DELETE /organizations/{org_id}/members — remove member ==========


@router.delete("/{org_id}/members", status_code=204)
async def member_remove(
    org_id: uuid.UUID,
    body: OrgMemberRemove,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
):
    success = await remove_member(db, org_id=org_id, user_id=body.user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Membership not found")
