from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.models.user import User


def _admin_headers(user_id):
    """Build an Authorization header for a proxy_admin."""
    token = create_access_token(user_id=user_id, role="proxy_admin")
    return {"Authorization": f"Bearer {token}"}


# ========== POST /users — create ==========


async def test_create_user(client, db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()

    response = await client.post(
        "/users",
        json={"email": "newuser@test.com", "password": "pass123", "role": "member"},
        headers=_admin_headers(admin.id),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@test.com"
    assert data["role"] == "member"
    assert data["is_blocked"] is False


async def test_create_user_duplicate_email(client, db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()

    await client.post(
        "/users",
        json={"email": "dup@test.com", "role": "member"},
        headers=_admin_headers(admin.id),
    )
    response = await client.post(
        "/users",
        json={"email": "dup@test.com", "role": "member"},
        headers=_admin_headers(admin.id),
    )
    assert response.status_code == 409


# ========== GET /users — list ==========


async def test_list_users(client, db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()

    response = await client.get("/users", headers=_admin_headers(admin.id))
    assert response.status_code == 200
    assert len(response.json()) >= 1


# ========== GET /users/{id} — read one ==========


async def test_get_user(client, db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()

    response = await client.get(
        f"/users/{admin.id}", headers=_admin_headers(admin.id)
    )
    assert response.status_code == 200
    assert response.json()["email"] == "admin@test.com"


async def test_get_user_not_found(client, db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()

    import uuid

    response = await client.get(
        f"/users/{uuid.uuid4()}", headers=_admin_headers(admin.id)
    )
    assert response.status_code == 404


# ========== PATCH /users/{id}/profile — update profile ==========


async def test_update_user_profile(client, db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    target = User(email="target@test.com", role="member")
    db_session.add_all([admin, target])
    await db_session.commit()

    response = await client.patch(
        f"/users/{target.id}/profile",
        json={"name": "Updated Name", "role": "org_admin"},
        headers=_admin_headers(admin.id),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["role"] == "org_admin"


# ========== PATCH /users/{id}/block — block/unblock ==========


async def test_block_user(client, db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    target = User(email="target@test.com", role="member")
    db_session.add_all([admin, target])
    await db_session.commit()

    response = await client.patch(
        f"/users/{target.id}/block",
        json={"blocked": True},
        headers=_admin_headers(admin.id),
    )
    assert response.status_code == 200

    info = await client.get(f"/users/{target.id}", headers=_admin_headers(admin.id))
    assert info.json()["is_blocked"] is True


# ========== DELETE /users/{id} — delete ==========


async def test_delete_user(client, db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    target = User(email="target@test.com", role="member")
    db_session.add_all([admin, target])
    await db_session.commit()

    response = await client.request(
        "DELETE", f"/users/{target.id}", headers=_admin_headers(admin.id)
    )
    assert response.status_code == 204

    # Confirm deleted
    info = await client.get(f"/users/{target.id}", headers=_admin_headers(admin.id))
    assert info.status_code == 404


# ========== RBAC — members can't manage users ==========


async def test_member_cannot_create_user(client, db_session):
    member = User(email="member@test.com", password_hash=hash_password("pass"), role="member")
    db_session.add(member)
    await db_session.commit()

    token = create_access_token(user_id=member.id, role="member")
    response = await client.post(
        "/users",
        json={"email": "other@test.com", "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


async def test_member_cannot_list_users(client, db_session):
    member = User(email="member@test.com", password_hash=hash_password("pass"), role="member")
    db_session.add(member)
    await db_session.commit()

    token = create_access_token(user_id=member.id, role="member")
    response = await client.get(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
