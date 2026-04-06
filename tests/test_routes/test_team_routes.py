from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.models.api_key import ApiKey
from app.models.user import User


def _admin_headers(user_id):
    token = create_access_token(user_id=user_id, role="proxy_admin")
    return {"Authorization": f"Bearer {token}"}


async def _create_admin(db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()
    return admin


# ========== POST /teams — create ==========


async def test_create_team(client, db_session):
    admin = await _create_admin(db_session)
    response = await client.post(
        "/teams",
        json={"name": "Backend", "allowed_models": ["gpt-4", "claude-*"]},
        headers=_admin_headers(admin.id),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Backend"
    assert data["allowed_models"] == ["gpt-4", "claude-*"]


# ========== GET /teams — list ==========


async def test_list_teams(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    await client.post("/teams", json={"name": "T1"}, headers=headers)
    await client.post("/teams", json={"name": "T2"}, headers=headers)

    response = await client.get("/teams", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) >= 2


# ========== GET /teams/{team_id} — read one ==========


async def test_get_team(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post("/teams", json={"name": "GetMe"}, headers=headers)
    team_id = create_resp.json()["id"]

    response = await client.get(f"/teams/{team_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "GetMe"


# ========== PATCH /teams/{team_id} — update ==========


async def test_update_team(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post("/teams", json={"name": "Old"}, headers=headers)
    team_id = create_resp.json()["id"]

    response = await client.patch(
        f"/teams/{team_id}",
        json={"name": "New", "max_budget": 100.0},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "New"
    assert response.json()["max_budget"] == 100.0


# ========== DELETE /teams/{team_id} — cascade ==========


async def test_delete_team(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post("/teams", json={"name": "Del"}, headers=headers)
    team_id = create_resp.json()["id"]

    response = await client.delete(f"/teams/{team_id}", headers=headers)
    assert response.status_code == 204

    response = await client.get(f"/teams/{team_id}", headers=headers)
    assert response.status_code == 404


async def test_delete_team_cascades_keys(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post("/teams", json={"name": "CascadeTeam"}, headers=headers)
    team_id = create_resp.json()["id"]

    # Add a key scoped to this team
    from app.auth.api_key_auth import generate_api_key, get_key_prefix, hash_api_key

    raw_key = generate_api_key()
    key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=admin.id,
        team_id=team_id,
    )
    db_session.add(key)
    await db_session.commit()
    key_id = key.id

    # Delete team
    response = await client.delete(f"/teams/{team_id}", headers=headers)
    assert response.status_code == 204

    # Verify key is gone
    from sqlalchemy import select
    result = await db_session.execute(select(ApiKey).where(ApiKey.id == key_id))
    assert result.scalar_one_or_none() is None


# ========== Member operations ==========


async def test_add_and_remove_team_member(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)

    create_resp = await client.post("/teams", json={"name": "MemberTeam"}, headers=headers)
    team_id = create_resp.json()["id"]

    user_resp = await client.post(
        "/users", json={"email": "teammember@test.com", "role": "member"}, headers=headers
    )
    member_id = user_resp.json()["id"]

    # Add member
    response = await client.post(
        f"/teams/{team_id}/members",
        json={"user_id": member_id, "role": "member"},
        headers=headers,
    )
    assert response.status_code == 201

    # Update role
    response = await client.patch(
        f"/teams/{team_id}/members",
        json={"user_id": member_id, "role": "team_admin"},
        headers=headers,
    )
    assert response.status_code == 200

    # Remove
    response = await client.request(
        "DELETE",
        f"/teams/{team_id}/members",
        json={"user_id": member_id},
        headers=headers,
    )
    assert response.status_code == 204


async def test_add_duplicate_team_member(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)

    create_resp = await client.post("/teams", json={"name": "DupTeam"}, headers=headers)
    team_id = create_resp.json()["id"]

    user_resp = await client.post(
        "/users", json={"email": "dupmember@test.com", "role": "member"}, headers=headers
    )
    member_id = user_resp.json()["id"]

    response = await client.post(
        f"/teams/{team_id}/members",
        json={"user_id": member_id, "role": "member"},
        headers=headers,
    )
    assert response.status_code == 201

    # Duplicate — conflict
    response = await client.post(
        f"/teams/{team_id}/members",
        json={"user_id": member_id, "role": "member"},
        headers=headers,
    )
    assert response.status_code == 409


# ========== PATCH /teams/{team_id}/block ==========


async def test_block_team(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post("/teams", json={"name": "BlockMe"}, headers=headers)
    team_id = create_resp.json()["id"]

    response = await client.patch(f"/teams/{team_id}/block?blocked=true", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_blocked"] is True

    response = await client.patch(f"/teams/{team_id}/block?blocked=false", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_blocked"] is False
