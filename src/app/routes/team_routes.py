import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.exceptions import DuplicateError
from app.models.user import User
from app.schemas.wire_in.team import (
    TeamCreate,
    TeamMemberAdd,
    TeamMemberRemove,
    TeamMemberUpdate,
    TeamUpdate,
)
from app.schemas.wire_out.common import StatusResponse
from app.schemas.wire_out.team import TeamResponse
from app.services.team_service import (
    add_member,
    block_team,
    create_team,
    delete_team,
    get_team,
    list_teams,
    remove_member,
    update_member,
    update_team,
)

router = APIRouter(prefix="/teams", tags=["teams"])


# ========== POST /teams — create ==========


@router.post("", status_code=201)
async def create(
    body: TeamCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin", "org_admin")),
) -> TeamResponse:
    team = await create_team(
        db,
        name=body.name,
        org_id=body.org_id,
        allowed_models=body.allowed_models,
        max_budget=body.max_budget,
        tpm_limit=body.tpm_limit,
        rpm_limit=body.rpm_limit,
        metadata=body.metadata,
    )
    return TeamResponse.model_validate(team)


# ========== GET /teams — list ==========


@router.get("")
async def list_all(
    org_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
) -> list[TeamResponse]:
    teams = await list_teams(db, org_id=org_id, page=page, page_size=page_size)
    return [TeamResponse.model_validate(t) for t in teams]


# ========== GET /teams/{team_id} — read one ==========


@router.get("/{team_id}")
async def get_one(
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
) -> TeamResponse:
    team = await get_team(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return TeamResponse.model_validate(team)


# ========== PATCH /teams/{team_id} — update ==========


@router.patch("/{team_id}")
async def update(
    team_id: uuid.UUID,
    body: TeamUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin", "org_admin", "team_admin")),
) -> TeamResponse:
    team = await update_team(
        db,
        team_id,
        name=body.name,
        allowed_models=body.allowed_models,
        max_budget=body.max_budget,
        tpm_limit=body.tpm_limit,
        rpm_limit=body.rpm_limit,
        metadata_json=body.metadata,
    )
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return TeamResponse.model_validate(team)


# ========== DELETE /teams/{team_id} — delete + cascade ==========


@router.delete("/{team_id}", status_code=204)
async def delete(
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin", "org_admin")),
):
    success = await delete_team(db, team_id)
    if not success:
        raise HTTPException(status_code=404, detail="Team not found")


# ========== PATCH /teams/{team_id}/block — block/unblock ==========


@router.patch("/{team_id}/block")
async def block(
    team_id: uuid.UUID,
    blocked: bool = True,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin", "org_admin")),
) -> TeamResponse:
    team = await block_team(db, team_id, blocked)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return TeamResponse.model_validate(team)


# ========== POST /teams/{team_id}/members — add member ==========


@router.post("/{team_id}/members", status_code=201)
async def member_add(
    team_id: uuid.UUID,
    body: TeamMemberAdd,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin", "org_admin", "team_admin")),
) -> StatusResponse:
    try:
        await add_member(db, team_id=team_id, user_id=body.user_id, role=body.role)
    except DuplicateError as e:
        raise HTTPException(status_code=409, detail=e.detail)
    return StatusResponse()


# ========== PATCH /teams/{team_id}/members — update member ==========


@router.patch("/{team_id}/members")
async def member_update(
    team_id: uuid.UUID,
    body: TeamMemberUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin", "org_admin", "team_admin")),
) -> StatusResponse:
    membership = await update_member(db, team_id=team_id, user_id=body.user_id, role=body.role)
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    return StatusResponse()


# ========== DELETE /teams/{team_id}/members — remove member ==========


@router.delete("/{team_id}/members", status_code=204)
async def member_remove(
    team_id: uuid.UUID,
    body: TeamMemberRemove,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin", "org_admin", "team_admin")),
):
    success = await remove_member(db, team_id=team_id, user_id=body.user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Membership not found")
