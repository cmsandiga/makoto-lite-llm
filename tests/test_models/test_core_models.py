from sqlalchemy import select

from app.models.budget import Budget
from app.models.membership import OrgMembership
from app.models.organization import Organization
from app.models.team import Team
from app.models.user import User


async def test_create_organization(db_session):
    org = Organization(name="Acme Corp", slug="acme-corp")
    db_session.add(org)
    await db_session.commit()

    result = await db_session.execute(select(Organization).where(Organization.slug == "acme-corp"))
    fetched = result.scalar_one()
    assert fetched.name == "Acme Corp"
    assert fetched.id is not None
    assert fetched.is_blocked is False


async def test_create_team_with_org(db_session):
    org = Organization(name="Acme", slug="acme")
    db_session.add(org)
    await db_session.flush()

    team = Team(name="Engineering", org_id=org.id)
    db_session.add(team)
    await db_session.commit()

    result = await db_session.execute(select(Team).where(Team.name == "Engineering"))
    fetched = result.scalar_one()
    assert fetched.org_id == org.id


async def test_create_user(db_session):
    user = User(email="alice@example.com", role="proxy_admin")
    db_session.add(user)
    await db_session.commit()

    result = await db_session.execute(select(User).where(User.email == "alice@example.com"))
    fetched = result.scalar_one()
    assert fetched.role == "proxy_admin"
    assert fetched.spend == 0.0
    assert fetched.is_blocked is False


async def test_org_membership(db_session):
    org = Organization(name="Acme", slug="acme-mb")
    user = User(email="bob@example.com", role="member")
    db_session.add_all([org, user])
    await db_session.flush()

    membership = OrgMembership(user_id=user.id, org_id=org.id, role="org_admin")
    db_session.add(membership)
    await db_session.commit()

    result = await db_session.execute(
        select(OrgMembership).where(OrgMembership.user_id == user.id)
    )
    fetched = result.scalar_one()
    assert fetched.role == "org_admin"


async def test_create_budget(db_session):
    budget = Budget(name="Standard", max_budget=100.0, rpm_limit=60)
    db_session.add(budget)
    await db_session.commit()

    result = await db_session.execute(select(Budget).where(Budget.name == "Standard"))
    fetched = result.scalar_one()
    assert fetched.max_budget == 100.0
    assert fetched.rpm_limit == 60
