import pytest
from uuid_extensions import uuid7

from app.auth.crypto import decrypt
from app.exceptions import DuplicateError
from app.models.organization import Organization
from app.services.sso_service import create_sso_config, delete_sso_config, get_sso_config


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
