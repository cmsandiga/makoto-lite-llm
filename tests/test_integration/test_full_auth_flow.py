from app.auth.dependencies import _api_key_cache
from app.auth.password import hash_password
from app.models.user import User


async def test_full_auth_lifecycle(client, db_session):
    """End-to-end: admin login -> org -> team -> member -> API key -> rotate -> block."""

    # 1. Bootstrap: create admin user directly in DB
    admin = User(email="admin@acme.com", password_hash=hash_password("admin123"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()

    # 2. Login as admin -> get JWT
    login_resp = await client.post("/auth/login", json={"email": "admin@acme.com", "password": "admin123"})
    assert login_resp.status_code == 200
    admin_token = login_resp.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 3. Create organization
    org_resp = await client.post("/organizations", json={"name": "Acme Corp", "slug": "acme"}, headers=admin_headers)
    assert org_resp.status_code == 201
    org_id = org_resp.json()["id"]

    # 4. Create team in org
    team_resp = await client.post(
        "/teams",
        json={"name": "Backend", "org_id": org_id, "allowed_models": ["gpt-4", "claude-*"]},
        headers=admin_headers,
    )
    assert team_resp.status_code == 201
    team_id = team_resp.json()["id"]

    # 5. Create member user
    member_resp = await client.post(
        "/users",
        json={"email": "dev@acme.com", "password": "dev123", "role": "member"},
        headers=admin_headers,
    )
    assert member_resp.status_code == 201
    member_id = member_resp.json()["id"]

    # 6. Add member to team
    add_resp = await client.post(
        f"/teams/{team_id}/members",
        json={"user_id": member_id, "role": "member"},
        headers=admin_headers,
    )
    assert add_resp.status_code == 201

    # 7. Generate API key for member (admin generates on behalf)
    key_resp = await client.post(
        "/keys",
        json={"key_alias": "dev-key", "team_id": team_id, "allowed_models": ["gpt-4"]},
        headers=admin_headers,
    )
    assert key_resp.status_code == 201
    api_key = key_resp.json()["key"]
    key_id = key_resp.json()["key_id"]
    assert api_key.startswith("sk-")

    # 8. Use API key to authenticate
    me_resp = await client.get(f"/users/{member_id}", headers={"Authorization": f"Bearer {api_key}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "dev@acme.com"

    # 9. Rotate API key -> verify new key works
    rotate_resp = await client.post(f"/keys/{key_id}/rotate", json={"grace_period_hours": 1}, headers=admin_headers)
    assert rotate_resp.status_code == 200
    new_key = rotate_resp.json()["key"]
    assert new_key != api_key

    # Clear the in-memory TTL cache so rotated/blocked state is re-fetched from DB
    _api_key_cache.clear()

    # New key works
    new_resp = await client.get(f"/users/{member_id}", headers={"Authorization": f"Bearer {new_key}"})
    assert new_resp.status_code == 200

    # Old key still works during grace period
    _api_key_cache.clear()
    old_resp = await client.get(f"/users/{member_id}", headers={"Authorization": f"Bearer {api_key}"})
    assert old_resp.status_code == 200

    # 10. Block the API key -> verify auth fails
    block_resp = await client.patch(f"/keys/{key_id}/block", json={"blocked": True}, headers=admin_headers)
    assert block_resp.status_code == 200

    _api_key_cache.clear()
    blocked_resp = await client.get(f"/users/{member_id}", headers={"Authorization": f"Bearer {new_key}"})
    assert blocked_resp.status_code == 401

    # 11. Block the member user -> verify JWT login fails
    await client.patch(f"/users/{member_id}/block", json={"blocked": True}, headers=admin_headers)

    member_login = await client.post("/auth/login", json={"email": "dev@acme.com", "password": "dev123"})
    assert member_login.status_code == 403  # blocked user

    # 12. Delete org -> cascade deletes team
    del_resp = await client.delete(f"/organizations/{org_id}", headers=admin_headers)
    assert del_resp.status_code == 204

    # Verify team is gone
    team_check = await client.get(f"/teams/{team_id}", headers=admin_headers)
    assert team_check.status_code == 404
