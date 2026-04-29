import httpx
import pytest


@pytest.mark.e2e
def test_keycloak_discovery_doc(keycloak_issuer_url):
    resp = httpx.get(
        f"{keycloak_issuer_url}/.well-known/openid-configuration",
        timeout=10,
    )
    assert resp.status_code == 200
    doc = resp.json()
    assert doc["issuer"].endswith("/realms/litellm")
    assert "token_endpoint" in doc
    assert "userinfo_endpoint" in doc


@pytest.mark.e2e
def test_app_server_health(app_server):
    resp = httpx.get(f"{app_server}/health", timeout=5)
    assert resp.status_code == 200


from sqlalchemy import select


@pytest.mark.e2e
async def test_db_session_round_trip(e2e_db_session):
    from app.models.budget import Budget
    from app.models.organization import Organization

    budget = Budget(name="e2e-budget", max_budget=100)
    e2e_db_session.add(budget)
    await e2e_db_session.flush()

    org = Organization(name="Test Org", slug="test-org-e2e", budget_id=budget.id)
    e2e_db_session.add(org)
    await e2e_db_session.commit()

    result = await e2e_db_session.execute(
        select(Organization).where(Organization.slug == "test-org-e2e")
    )
    assert result.scalar_one().name == "Test Org"


@pytest.mark.e2e
async def test_db_cleanup_between_tests(e2e_db_session):
    from app.models.organization import Organization

    result = await e2e_db_session.execute(
        select(Organization).where(Organization.slug == "test-org-e2e")
    )
    assert result.scalar_one_or_none() is None, (
        "Truncate cleanup should have removed the previous test's org"
    )
