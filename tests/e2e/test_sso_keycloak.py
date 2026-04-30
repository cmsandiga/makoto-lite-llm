"""E2E: real OIDC flow against Keycloak, driven by Playwright."""

import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select

from app.models.membership import OrgMembership
from app.models.user import User


@pytest.mark.e2e
async def test_oidc_happy_path(app_server, sso_org, e2e_db_session):
    """End-to-end: start authorize, log in at Keycloak, land on dashboard
    redirect with JWT tokens, verify user+membership in DB.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        # 1. Kick off SSO flow — follows redirect to Keycloak login page.
        await page.goto(
            f"{app_server}/sso/authorize?org_id={sso_org.id}"
        )

        # 2. Fill Keycloak login form. Keycloak 24 field names: username, password.
        await page.fill("input[name=username]", "alice")
        await page.fill("input[name=password]", "alice-password")
        await page.click("input[type=submit]")

        # 3. Wait until the browser lands on the dashboard redirect URL
        #    (which contains access_token in its query string).
        await page.wait_for_url(
            lambda url: "access_token=" in url, timeout=30_000
        )

        final_url = page.url
        assert "access_token=" in final_url
        assert "refresh_token=" in final_url

        await browser.close()

    # 4. Assert DB state — user provisioned, membership created.
    user_result = await e2e_db_session.execute(
        select(User).where(User.email == "alice@example.com")
    )
    user = user_result.scalar_one()
    assert user.sso_provider == "keycloak"
    assert user.sso_subject  # non-empty subject from the IdP
    assert user.name in ("Alice Example", "alice")

    membership_result = await e2e_db_session.execute(
        select(OrgMembership).where(OrgMembership.user_id == user.id)
    )
    membership = membership_result.scalar_one()
    assert membership.org_id == sso_org.id
