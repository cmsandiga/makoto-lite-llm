import uuid

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import DuplicateError
from app.models.api_key import ApiKey
from app.models.membership import TeamMembership
from app.models.project import Project
from app.models.team import Team


# ========== Create ==========


async def create_team(
    db: AsyncSession,
    name: str,
    org_id: uuid.UUID | None = None,
    allowed_models: list[str] | None = None,
    max_budget: float | None = None,
    tpm_limit: int | None = None,
    rpm_limit: int | None = None,
    metadata: dict | None = None,
) -> Team:
    team = Team(
        name=name,
        org_id=org_id,
        allowed_models=allowed_models,
        max_budget=max_budget,
        tpm_limit=tpm_limit,
        rpm_limit=rpm_limit,
        metadata_json=metadata,
    )
    db.add(team)
    await db.commit()
    await db.refresh(team)
    return team


# ========== Read ==========


async def get_team(db: AsyncSession, team_id: uuid.UUID) -> Team | None:
    result = await db.execute(select(Team).where(Team.id == team_id))
    return result.scalar_one_or_none()


async def list_teams(
    db: AsyncSession, org_id: uuid.UUID | None = None, page: int = 1, page_size: int = 50
) -> list[Team]:
    offset = (page - 1) * page_size
    query = select(Team).order_by(Team.created_at.desc())
    if org_id is not None:
        query = query.where(Team.org_id == org_id)
    result = await db.execute(query.offset(offset).limit(page_size))
    return list(result.scalars().all())


# ========== Update ==========


async def update_team(
    db: AsyncSession,
    team_id: uuid.UUID,
    name: str | None = None,
    allowed_models: list[str] | None = None,
    max_budget: float | None = None,
    tpm_limit: int | None = None,
    rpm_limit: int | None = None,
    metadata_json: dict | None = None,
) -> Team | None:
    team = await get_team(db, team_id)
    if team is None:
        return None
    if name is not None:
        team.name = name
    if allowed_models is not None:
        team.allowed_models = allowed_models
    if max_budget is not None:
        team.max_budget = max_budget
    if tpm_limit is not None:
        team.tpm_limit = tpm_limit
    if rpm_limit is not None:
        team.rpm_limit = rpm_limit
    if metadata_json is not None:
        team.metadata_json = metadata_json
    await db.commit()
    await db.refresh(team)
    return team


# ========== Delete (cascade) ==========


async def delete_team(db: AsyncSession, team_id: uuid.UUID) -> bool:
    """Delete team and cascade: projects → keys, memberships."""
    team = await get_team(db, team_id)
    if team is None:
        return False

    # Delete API keys scoped to this team
    await db.execute(delete(ApiKey).where(ApiKey.team_id == team_id))
    # Delete projects
    await db.execute(delete(Project).where(Project.team_id == team_id))
    # Delete memberships
    await db.execute(delete(TeamMembership).where(TeamMembership.team_id == team_id))
    # Delete team
    await db.delete(team)
    await db.commit()
    return True


# ========== Block ==========


async def block_team(db: AsyncSession, team_id: uuid.UUID, blocked: bool) -> Team | None:
    team = await get_team(db, team_id)
    if team is None:
        return None
    team.is_blocked = blocked
    await db.commit()
    await db.refresh(team)
    return team


# ========== Member Operations ==========


async def add_member(
    db: AsyncSession,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str = "member",
) -> TeamMembership:
    """Add a member to a team. Raises DuplicateError if already a member."""
    membership = TeamMembership(
        team_id=team_id,
        user_id=user_id,
        role=role,
    )
    db.add(membership)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise DuplicateError("User is already a member of this team")
    await db.commit()
    await db.refresh(membership)
    return membership


async def update_member(
    db: AsyncSession,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
) -> TeamMembership | None:
    result = await db.execute(
        select(TeamMembership).where(
            TeamMembership.team_id == team_id,
            TeamMembership.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        return None
    membership.role = role
    await db.commit()
    await db.refresh(membership)
    return membership


async def remove_member(
    db: AsyncSession,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(TeamMembership).where(
            TeamMembership.team_id == team_id,
            TeamMembership.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        return False
    await db.delete(membership)
    await db.commit()
    return True
