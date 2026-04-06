from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.models.user import User


def _admin_headers(user_id):
    token = create_access_token(user_id=user_id, role="proxy_admin")
    return {"Authorization": f"Bearer {token}"}


async def _create_admin(db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()
    return admin


# ========== POST /keys — generate ==========


async def test_generate_key(client, db_session):
    admin = await _create_admin(db_session)
    response = await client.post(
        "/keys",
        json={"key_alias": "my-prod-key", "allowed_models": ["gpt-4", "claude-*"], "max_budget": 50.0},
        headers=_admin_headers(admin.id),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["key"].startswith("sk-")
    assert data["key_prefix"]
    assert data["key_id"]


# ========== GET /keys — list ==========


async def test_list_keys(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    await client.post("/keys", json={"key_alias": "k1"}, headers=headers)
    await client.post("/keys", json={"key_alias": "k2"}, headers=headers)

    response = await client.get("/keys", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) >= 2


# ========== GET /keys/{key_id} — read one ==========


async def test_get_key(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post("/keys", json={"key_alias": "getme"}, headers=headers)
    key_id = create_resp.json()["key_id"]

    response = await client.get(f"/keys/{key_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["key_alias"] == "getme"
    # Full key should NOT be in the info response
    assert "key" not in response.json() or not response.json().get("key", "").startswith("sk-")


# ========== PATCH /keys/{key_id} — update ==========


async def test_update_key(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post("/keys", json={"key_alias": "old"}, headers=headers)
    key_id = create_resp.json()["key_id"]

    response = await client.patch(
        f"/keys/{key_id}",
        json={"key_alias": "new", "max_budget": 100.0},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["key_alias"] == "new"
    assert response.json()["max_budget"] == 100.0


# ========== POST /keys/{key_id}/rotate ==========


async def test_rotate_key(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post("/keys", json={"key_alias": "rotate-me"}, headers=headers)
    key_id = create_resp.json()["key_id"]
    original_key = create_resp.json()["key"]

    response = await client.post(
        f"/keys/{key_id}/rotate",
        json={"grace_period_hours": 2},
        headers=headers,
    )
    assert response.status_code == 200
    new_key = response.json()["key"]
    assert new_key.startswith("sk-")
    assert new_key != original_key


# ========== PATCH /keys/{key_id}/block ==========


async def test_block_key(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post("/keys", json={}, headers=headers)
    key_id = create_resp.json()["key_id"]

    response = await client.patch(
        f"/keys/{key_id}/block",
        json={"blocked": True},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["is_blocked"] is True


# ========== POST /keys/{key_id}/reactivate ==========


async def test_reactivate_key(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)

    # Create expired key
    create_resp = await client.post(
        "/keys",
        json={"expires_at": "2020-01-01T00:00:00Z"},
        headers=headers,
    )
    key_id = create_resp.json()["key_id"]

    # Block it too
    await client.patch(f"/keys/{key_id}/block", json={"blocked": True}, headers=headers)

    # Reactivate
    response = await client.post(f"/keys/{key_id}/reactivate", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_blocked"] is False
    assert response.json()["expires_at"] is None


# ========== POST /keys/{key_id}/reset-spend ==========


async def test_reset_spend(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post("/keys", json={}, headers=headers)
    key_id = create_resp.json()["key_id"]

    # Manually set spend on the key
    from app.models.api_key import ApiKey
    from sqlalchemy import select

    result = await db_session.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one()
    key.spend = 42.5
    await db_session.commit()

    response = await client.post(f"/keys/{key_id}/reset-spend", headers=headers)
    assert response.status_code == 200
    assert response.json()["spend"] == 0.0


# ========== POST /keys/bulk-update ==========


async def test_bulk_update(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)

    r1 = await client.post("/keys", json={"key_alias": "bulk1"}, headers=headers)
    r2 = await client.post("/keys", json={"key_alias": "bulk2"}, headers=headers)
    key_ids = [r1.json()["key_id"], r2.json()["key_id"]]

    response = await client.post(
        "/keys/bulk-update",
        json={"key_ids": key_ids, "max_budget": 200.0},
        headers=headers,
    )
    assert response.status_code == 200

    # Verify both keys updated
    for kid in key_ids:
        info = await client.get(f"/keys/{kid}", headers=headers)
        assert info.json()["max_budget"] == 200.0


# ========== DELETE /keys/{key_id} ==========


async def test_delete_key(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post("/keys", json={}, headers=headers)
    key_id = create_resp.json()["key_id"]

    response = await client.delete(f"/keys/{key_id}", headers=headers)
    assert response.status_code == 204

    response = await client.get(f"/keys/{key_id}", headers=headers)
    assert response.status_code == 404
