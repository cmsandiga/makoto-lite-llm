from uuid_extensions import uuid7

from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.models.organization import Organization
from app.models.user import User
from app.services.sso_service import _state_store


def _admin_headers(user_id):
    token = create_access_token(user_id=user_id, role="proxy_admin")
    return {"Authorization": f"Bearer {token}"}


def _member_headers(user_id):
    token = create_access_token(user_id=user_id, role="member")
    return {"Authorization": f"Bearer {token}"}


async def _setup(db_session):
    """Create an admin user and an org. Returns (admin, org)."""
    admin = User(
        email=f"admin-{uuid7()}@test.com",
        password_hash=hash_password("pass"),
        role="proxy_admin",
    )
    db_session.add(admin)
    org = Organization(name="SSO Org", slug=f"sso-{uuid7()}")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(admin)
    await db_session.refresh(org)
    return admin, org


# ========== POST /sso/config ==========


async def test_create_sso_config_route(client, db_session):
    admin, org = await _setup(db_session)
    response = await client.post(
        "/sso/config",
        json={
            "org_id": str(org.id),
            "provider": "google",
            "client_id": "goog-123",
            "client_secret": "my-secret",
            "issuer_url": "https://accounts.google.com",
            "allowed_domains": ["acme.com"],
        },
        headers=_admin_headers(admin.id),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["org_id"] == str(org.id)
    assert data["provider"] == "google"
    assert data["client_id"] == "goog-123"
    assert data["client_secret"] == "***"  # masked
    assert data["issuer_url"] == "https://accounts.google.com"
    assert data["allowed_domains"] == ["acme.com"]
    assert data["is_active"] is True


async def test_create_sso_config_duplicate(client, db_session):
    admin, org = await _setup(db_session)
    headers = _admin_headers(admin.id)
    payload = {
        "org_id": str(org.id),
        "provider": "google",
        "client_id": "id1",
        "client_secret": "secret1",
        "issuer_url": "https://accounts.google.com",
    }
    await client.post("/sso/config", json=payload, headers=headers)
    response = await client.post("/sso/config", json=payload, headers=headers)
    assert response.status_code == 409


async def test_create_sso_config_non_admin(client, db_session):
    member = User(
        email=f"member-{uuid7()}@test.com",
        password_hash=hash_password("pass"),
        role="member",
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    response = await client.post(
        "/sso/config",
        json={
            "org_id": str(uuid7()),
            "provider": "google",
            "client_id": "id",
            "client_secret": "secret",
            "issuer_url": "https://example.com",
        },
        headers=_member_headers(member.id),
    )
    assert response.status_code == 403


# ========== GET /sso/config/{org_id} ==========


async def test_get_sso_config_route(client, db_session):
    admin, org = await _setup(db_session)
    headers = _admin_headers(admin.id)
    await client.post(
        "/sso/config",
        json={
            "org_id": str(org.id),
            "provider": "okta",
            "client_id": "okta-id",
            "client_secret": "okta-secret",
            "issuer_url": "https://okta.example.com",
        },
        headers=headers,
    )
    response = await client.get(f"/sso/config/{org.id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "okta"
    assert data["client_secret"] == "***"


async def test_get_sso_config_not_found(client, db_session):
    admin, _ = await _setup(db_session)
    response = await client.get(
        f"/sso/config/{uuid7()}", headers=_admin_headers(admin.id)
    )
    assert response.status_code == 404


# ========== DELETE /sso/config/{org_id} ==========


async def test_delete_sso_config_route(client, db_session):
    admin, org = await _setup(db_session)
    headers = _admin_headers(admin.id)
    await client.post(
        "/sso/config",
        json={
            "org_id": str(org.id),
            "provider": "google",
            "client_id": "gid",
            "client_secret": "gsecret",
            "issuer_url": "https://accounts.google.com",
        },
        headers=headers,
    )
    response = await client.delete(f"/sso/config/{org.id}", headers=headers)
    assert response.status_code == 204

    # Verify it's gone
    get_resp = await client.get(f"/sso/config/{org.id}", headers=headers)
    assert get_resp.status_code == 404


async def test_delete_sso_config_not_found(client, db_session):
    admin, _ = await _setup(db_session)
    response = await client.delete(
        f"/sso/config/{uuid7()}", headers=_admin_headers(admin.id)
    )
    assert response.status_code == 404


# ========== GET /sso/authorize ==========


async def test_authorize_redirect(client, db_session):
    admin, org = await _setup(db_session)
    headers = _admin_headers(admin.id)
    await client.post(
        "/sso/config",
        json={
            "org_id": str(org.id),
            "provider": "google",
            "client_id": "goog-123",
            "client_secret": "secret",
            "issuer_url": "https://accounts.google.com",
        },
        headers=headers,
    )
    # authorize is public — no auth header needed
    response = await client.get(
        f"/sso/authorize?org_id={org.id}",
        follow_redirects=False,
    )
    assert response.status_code == 307
    location = response.headers["location"]
    assert "https://accounts.google.com/authorize" in location
    assert "client_id=goog-123" in location
    assert "response_type=code" in location


async def test_authorize_org_not_found(client, db_session):
    response = await client.get(
        f"/sso/authorize?org_id={uuid7()}",
        follow_redirects=False,
    )
    assert response.status_code == 404


# ========== GET /sso/callback ==========


async def test_callback_valid_state(client, db_session):
    # Manually add a state to simulate an authorize flow
    _state_store["valid-test-state"] = True
    response = await client.get("/sso/callback?code=authcode123&state=valid-test-state")
    assert response.status_code == 501
    assert "not yet implemented" in response.json()["detail"].lower()


async def test_callback_invalid_state(client, db_session):
    response = await client.get("/sso/callback?code=authcode123&state=bogus-state")
    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()


async def test_callback_missing_params(client, db_session):
    response = await client.get("/sso/callback")
    assert response.status_code == 422  # FastAPI validation error
