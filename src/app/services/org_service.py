import uuid

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import DuplicateError
from app.models.api_key import ApiKey
from app.models.membership import OrgMembership, TeamMembership
from app.models.organization import Organization
from app.models.project import Project
from app.models.team import Team


# ========== Create ==========


async def create_org(
    db: AsyncSession,
    name: str,
    slug: str,
    max_budget: float | None = None,
    metadata: dict | None = None,
) -> Organization:
    """Create an org. Raises DuplicateError if slug already exists."""
    org = Organization(
        name=name,
        slug=slug,
        max_budget=max_budget,
        metadata_json=metadata,
    )
    db.add(org)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise DuplicateError("Slug already exists")
    await db.commit()
    await db.refresh(org)
    return org


# ========== Read ==========


async def get_org(db: AsyncSession, org_id: uuid.UUID) -> Organization | None:
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    return result.scalar_one_or_none()


async def list_orgs(
    db: AsyncSession, page: int = 1, page_size: int = 50
) -> list[Organization]:
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Organization).order_by(Organization.created_at.desc()).offset(offset).limit(page_size)
    )
    return list(result.scalars().all())


# ========== Update ==========


async def update_org(
    db: AsyncSession,
    org_id: uuid.UUID,
    name: str | None = None,
    max_budget: float | None = None,
    metadata_json: dict | None = None,
) -> Organization | None:
    org = await get_org(db, org_id)
    if org is None:
        return None
    if name is not None:
        org.name = name
    if max_budget is not None:
        org.max_budget = max_budget
    if metadata_json is not None:
        org.metadata_json = metadata_json
    await db.commit()
    await db.refresh(org)
    return org


# ========== Delete (cascade) ==========


async def delete_org(db: AsyncSession, org_id: uuid.UUID) -> bool:
    """Delete org and cascade: teams → projects → keys, memberships."""
    org = await get_org(db, org_id)
    if org is None:
        return False

    # Find all teams in this org
    team_result = await db.execute(select(Team.id).where(Team.org_id == org_id))
    team_ids = [row[0] for row in team_result.all()]

    if team_ids:
        # Delete API keys scoped to these teams
        await db.execute(delete(ApiKey).where(ApiKey.team_id.in_(team_ids)))
        # Delete projects in these teams
        await db.execute(delete(Project).where(Project.team_id.in_(team_ids)))
        # Delete team memberships
        await db.execute(delete(TeamMembership).where(TeamMembership.team_id.in_(team_ids)))
        # Delete teams
        await db.execute(delete(Team).where(Team.id.in_(team_ids)))

    # Delete API keys scoped directly to org
    await db.execute(delete(ApiKey).where(ApiKey.org_id == org_id))
    # Delete org memberships
    await db.execute(delete(OrgMembership).where(OrgMembership.org_id == org_id))
    # Delete org
    await db.delete(org)
    await db.commit()
    return True


# ========== Member Operations ==========


async def add_member(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str = "member",
) -> OrgMembership:
    """Add a member to an org. Raises DuplicateError if already a member."""
    membership = OrgMembership(
        org_id=org_id,
        user_id=user_id,
        role=role,
    )
    db.add(membership)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise DuplicateError("User is already a member of this organization")
    await db.commit()
    await db.refresh(membership)
    return membership


async def update_member(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
) -> OrgMembership | None:
    result = await db.execute(
        select(OrgMembership).where(
            OrgMembership.org_id == org_id,
            OrgMembership.user_id == user_id,
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
    org_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(OrgMembership).where(
            OrgMembership.org_id == org_id,
            OrgMembership.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        return False
    await db.delete(membership)
    await db.commit()
    return True
