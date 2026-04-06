from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.models.organization import Organization
from app.models.team import Team
from app.models.user import User


def _admin_headers(user_id):
    token = create_access_token(user_id=user_id, role="proxy_admin")
    return {"Authorization": f"Bearer {token}"}


async def _create_admin(db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()
    return admin


# ========== POST /organizations — create ==========


async def test_create_org(client, db_session):
    admin = await _create_admin(db_session)
    response = await client.post(
        "/organizations",
        json={"name": "Acme Corp", "slug": "acme"},
        headers=_admin_headers(admin.id),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Acme Corp"
    assert data["slug"] == "acme"


async def test_create_org_duplicate_slug(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    await client.post("/organizations", json={"name": "A", "slug": "dupe"}, headers=headers)
    response = await client.post("/organizations", json={"name": "B", "slug": "dupe"}, headers=headers)
    assert response.status_code == 409


# ========== GET /organizations — list ==========


async def test_list_orgs(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    await client.post("/organizations", json={"name": "Org1", "slug": "org1"}, headers=headers)
    await client.post("/organizations", json={"name": "Org2", "slug": "org2"}, headers=headers)

    response = await client.get("/organizations", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) >= 2


# ========== GET /organizations/{org_id} — read one ==========


async def test_get_org(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post(
        "/organizations", json={"name": "GetMe", "slug": "getme"}, headers=headers
    )
    org_id = create_resp.json()["id"]

    response = await client.get(f"/organizations/{org_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "GetMe"


async def test_get_org_not_found(client, db_session):
    admin = await _create_admin(db_session)
    response = await client.get(
        "/organizations/00000000-0000-0000-0000-000000000000",
        headers=_admin_headers(admin.id),
    )
    assert response.status_code == 404


# ========== PATCH /organizations/{org_id} — update ==========


async def test_update_org(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post(
        "/organizations", json={"name": "Old", "slug": "upd"}, headers=headers
    )
    org_id = create_resp.json()["id"]

    response = await client.patch(
        f"/organizations/{org_id}",
        json={"name": "New"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "New"


# ========== DELETE /organizations/{org_id} — cascade ==========


async def test_delete_org(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post(
        "/organizations", json={"name": "Del", "slug": "del"}, headers=headers
    )
    org_id = create_resp.json()["id"]

    response = await client.delete(f"/organizations/{org_id}", headers=headers)
    assert response.status_code == 204

    # Verify gone
    response = await client.get(f"/organizations/{org_id}", headers=headers)
    assert response.status_code == 404


async def test_delete_org_cascades_teams(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)

    # Create org
    create_resp = await client.post(
        "/organizations", json={"name": "Cascade", "slug": "cascade"}, headers=headers
    )
    org_id = create_resp.json()["id"]

    # Create a team in that org directly in DB
    team = Team(name="TeamA", org_id=org_id)
    db_session.add(team)
    await db_session.commit()

    # Delete org
    response = await client.delete(f"/organizations/{org_id}", headers=headers)
    assert response.status_code == 204

    # Verify team is gone
    from sqlalchemy import select
    result = await db_session.execute(select(Team).where(Team.id == team.id))
    assert result.scalar_one_or_none() is None


# ========== Member operations ==========


async def test_add_and_remove_member(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)

    # Create org
    create_resp = await client.post(
        "/organizations", json={"name": "Members", "slug": "members"}, headers=headers
    )
    org_id = create_resp.json()["id"]

    # Create a user to add via API
    user_resp = await client.post(
        "/users",
        json={"email": "member@test.com", "role": "member"},
        headers=headers,
    )
    member_id = user_resp.json()["id"]

    # Add member
    response = await client.post(
        f"/organizations/{org_id}/members",
        json={"user_id": member_id, "role": "member"},
        headers=headers,
    )
    assert response.status_code == 201

    # Update member role
    response = await client.patch(
        f"/organizations/{org_id}/members",
        json={"user_id": member_id, "role": "org_admin"},
        headers=headers,
    )
    assert response.status_code == 200

    # Remove member
    response = await client.request(
        "DELETE",
        f"/organizations/{org_id}/members",
        json={"user_id": member_id},
        headers=headers,
    )
    assert response.status_code == 204


async def test_add_duplicate_member(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)

    create_resp = await client.post(
        "/organizations", json={"name": "DupMembers", "slug": "dupmembers"}, headers=headers
    )
    org_id = create_resp.json()["id"]

    user_resp = await client.post(
        "/users", json={"email": "dup-member@test.com", "role": "member"}, headers=headers
    )
    member_id = user_resp.json()["id"]

    # Add member
    response = await client.post(
        f"/organizations/{org_id}/members",
        json={"user_id": member_id, "role": "member"},
        headers=headers,
    )
    assert response.status_code == 201

    # Add same member again — conflict
    response = await client.post(
        f"/organizations/{org_id}/members",
        json={"user_id": member_id, "role": "member"},
        headers=headers,
    )
    assert response.status_code == 409


# ========== Auth — non-admin cannot create ==========


async def test_non_admin_cannot_create_org(client, db_session):
    user = User(email="normie@test.com", password_hash=hash_password("pass"), role="member")
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(user_id=user.id, role="member")
    response = await client.post(
        "/organizations",
        json={"name": "Nope", "slug": "nope"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
