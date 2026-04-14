import pytest
from uuid_extensions import uuid7

from app.auth.crypto import decrypt
from app.exceptions import DuplicateError
from app.models.organization import Organization
from app.models.user import User
from app.services.sso_service import (
    _state_store,
    build_authorize_url,
    create_sso_config,
    delete_sso_config,
    generate_pkce_pair,
    get_sso_config,
    provision_sso_user,
    validate_and_consume_state,
)


async def _create_org(db_session) -> Organization:
    org = Organization(name="TestOrg", slug=f"test-{uuid7()}")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


async def test_create_sso_config(db_session):
    org = await _create_org(db_session)
    config = await create_sso_config(
        db_session,
        org_id=org.id,
        provider="google",
        client_id="google-client-123",
        client_secret="super-secret-value",
        issuer_url="https://accounts.google.com",
        allowed_domains=["acme.com"],
    )
    assert config.org_id == org.id
    assert config.provider == "google"
    assert config.client_id == "google-client-123"
    # client_secret_encrypted is NOT the plaintext
    assert config.client_secret_encrypted != "super-secret-value"
    # but it decrypts back to the original
    assert decrypt(config.client_secret_encrypted) == "super-secret-value"
    assert config.allowed_domains == ["acme.com"]
    assert config.auto_create_user is True
    assert config.default_role == "member"
    assert config.is_active is True


async def test_create_sso_config_duplicate_org(db_session):
    org = await _create_org(db_session)
    await create_sso_config(
        db_session,
        org_id=org.id,
        provider="google",
        client_id="id1",
        client_secret="secret1",
        issuer_url="https://accounts.google.com",
    )
    with pytest.raises(DuplicateError):
        await create_sso_config(
            db_session,
            org_id=org.id,
            provider="okta",
            client_id="id2",
            client_secret="secret2",
            issuer_url="https://okta.example.com",
        )


async def test_get_sso_config(db_session):
    org = await _create_org(db_session)
    await create_sso_config(
        db_session,
        org_id=org.id,
        provider="okta",
        client_id="okta-id",
        client_secret="okta-secret",
        issuer_url="https://okta.example.com",
    )
    config = await get_sso_config(db_session, org.id)
    assert config is not None
    assert config.provider == "okta"
    assert config.client_id == "okta-id"


async def test_get_sso_config_not_found(db_session):
    config = await get_sso_config(db_session, uuid7())
    assert config is None


async def test_delete_sso_config(db_session):
    org = await _create_org(db_session)
    await create_sso_config(
        db_session,
        org_id=org.id,
        provider="google",
        client_id="gid",
        client_secret="gsecret",
        issuer_url="https://accounts.google.com",
    )
    result = await delete_sso_config(db_session, org.id)
    assert result is True
    # Verify it's gone
    config = await get_sso_config(db_session, org.id)
    assert config is None


async def test_delete_sso_config_not_found(db_session):
    result = await delete_sso_config(db_session, uuid7())
    assert result is False


async def test_build_authorize_url(db_session):
    org = await _create_org(db_session)
    await create_sso_config(
        db_session,
        org_id=org.id,
        provider="google",
        client_id="goog-123",
        client_secret="secret",
        issuer_url="https://accounts.google.com",
    )
    url, state = await build_authorize_url(
        db_session,
        org_id=org.id,
        callback_url="http://localhost:8000/sso/callback",
    )
    assert "https://accounts.google.com/authorize" in url
    assert "client_id=goog-123" in url
    assert "redirect_uri=http" in url
    assert "response_type=code" in url
    assert "scope=openid+email+profile" in url or "scope=openid%20email%20profile" in url
    assert f"state={state}" in url
    assert len(state) > 16
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url


async def test_build_authorize_url_org_not_found(db_session):
    result = await build_authorize_url(
        db_session,
        org_id=uuid7(),
        callback_url="http://localhost:8000/sso/callback",
    )
    assert result is None


def test_generate_pkce_pair():
    verifier, challenge = generate_pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert len(challenge) > 0
    assert "=" not in challenge  # no padding
    v2, c2 = generate_pkce_pair()
    assert verifier != v2


async def test_validate_state_valid():
    test_org_id = uuid7()
    _state_store["test-state-123"] = {"verifier": "test-verifier-abc", "org_id": test_org_id}
    result = validate_and_consume_state("test-state-123")
    assert result["verifier"] == "test-verifier-abc"
    assert result["org_id"] == test_org_id
    # Second call should fail — state is consumed
    assert validate_and_consume_state("test-state-123") is None


async def test_validate_state_invalid():
    assert validate_and_consume_state("nonexistent-state") is None


# ---------------------------------------------------------------------------
# Task 6: provision_sso_user
# ---------------------------------------------------------------------------


async def test_provision_sso_user_creates_new(db_session):
    org = await _create_org(db_session)
    user = await provision_sso_user(
        db_session,
        email="new@acme.com",
        name="New User",
        sso_provider="google",
        sso_subject="google-sub-123",
        org_id=org.id,
        default_role="member",
    )
    assert user.email == "new@acme.com"
    assert user.name == "New User"
    assert user.sso_provider == "google"
    assert user.sso_subject == "google-sub-123"
    assert user.role == "member"
    assert user.password_hash is None


async def test_provision_sso_user_links_existing(db_session):
    org = await _create_org(db_session)
    existing = User(
        email="existing@acme.com",
        password_hash="some-hash",
        role="member",
    )
    db_session.add(existing)
    await db_session.commit()
    await db_session.refresh(existing)

    user = await provision_sso_user(
        db_session,
        email="existing@acme.com",
        name="Existing User",
        sso_provider="google",
        sso_subject="google-sub-456",
        org_id=org.id,
        default_role="member",
    )
    assert user.id == existing.id
    assert user.sso_provider == "google"
    assert user.sso_subject == "google-sub-456"
    assert user.password_hash == "some-hash"


async def test_provision_sso_user_creates_org_membership(db_session):
    from sqlalchemy import select as sa_select

    from app.models.membership import OrgMembership

    org = await _create_org(db_session)
    user = await provision_sso_user(
        db_session,
        email="member@acme.com",
        name="Member",
        sso_provider="okta",
        sso_subject="okta-sub-789",
        org_id=org.id,
        default_role="member",
    )
    result = await db_session.execute(
        sa_select(OrgMembership).where(
            OrgMembership.user_id == user.id,
            OrgMembership.org_id == org.id,
        )
    )
    membership = result.scalar_one_or_none()
    assert membership is not None
    assert membership.role == "member"


