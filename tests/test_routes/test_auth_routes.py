from app.auth.password import hash_password
from app.models.user import User


async def test_login_success(client, db_session):
    user = User(
        email="alice@test.com",
        password_hash=hash_password("secret123"),
        role="member",
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post("/auth/login", json={
        "email": "alice@test.com",
        "password": "secret123",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(client, db_session):
    user = User(
        email="bob@test.com",
        password_hash=hash_password("correct"),
        role="member",
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post("/auth/login", json={
        "email": "bob@test.com",
        "password": "wrong",
    })
    assert response.status_code == 401


async def test_login_nonexistent_email(client):
    response = await client.post("/auth/login", json={
        "email": "nobody@test.com",
        "password": "anything",
    })
    assert response.status_code == 401


async def test_login_blocked_user(client, db_session):
    user = User(
        email="blocked@test.com",
        password_hash=hash_password("pass"),
        role="member",
        is_blocked=True,
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post("/auth/login", json={
        "email": "blocked@test.com",
        "password": "pass",
    })
    assert response.status_code == 403


async def test_refresh_token_flow(client, db_session):
    user = User(
        email="refresh@test.com",
        password_hash=hash_password("pass"),
        role="member",
    )
    db_session.add(user)
    await db_session.commit()

    # Login first to get tokens
    login = await client.post("/auth/login", json={
        "email": "refresh@test.com",
        "password": "pass",
    })
    refresh_token = login.json()["refresh_token"]

    # Use the refresh token to get a new pair
    response = await client.post("/auth/refresh", json={
        "refresh_token": refresh_token,
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    # The new refresh token should be different (rotation)
    assert data["refresh_token"] != refresh_token


async def test_refresh_with_revoked_token(client, db_session):
    user = User(
        email="revoked@test.com",
        password_hash=hash_password("pass"),
        role="member",
    )
    db_session.add(user)
    await db_session.commit()

    login = await client.post("/auth/login", json={
        "email": "revoked@test.com",
        "password": "pass",
    })
    refresh_token = login.json()["refresh_token"]

    # Use it once (this revokes the original)
    await client.post("/auth/refresh", json={"refresh_token": refresh_token})

    # Try to reuse the old token — should fail
    response = await client.post("/auth/refresh", json={
        "refresh_token": refresh_token,
    })
    assert response.status_code == 401


async def test_logout(client, db_session):
    user = User(
        email="logout@test.com",
        password_hash=hash_password("pass"),
        role="member",
    )
    db_session.add(user)
    await db_session.commit()

    login = await client.post("/auth/login", json={
        "email": "logout@test.com",
        "password": "pass",
    })
    tokens = login.json()

    # Logout (requires Bearer token)
    response = await client.post(
        "/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == 200

    # Refresh should now fail (token was revoked)
    response = await client.post("/auth/refresh", json={
        "refresh_token": tokens["refresh_token"],
    })
    assert response.status_code == 401


async def test_logout_requires_auth(client):
    response = await client.post(
        "/auth/logout",
        json={"refresh_token": "fake-token"},
    )
    assert response.status_code == 401


async def test_logout_all(client, db_session):
    user = User(
        email="logoutall@test.com",
        password_hash=hash_password("pass"),
        role="member",
    )
    db_session.add(user)
    await db_session.commit()

    # Login twice to create two refresh tokens
    login1 = await client.post("/auth/login", json={
        "email": "logoutall@test.com",
        "password": "pass",
    })
    login2 = await client.post("/auth/login", json={
        "email": "logoutall@test.com",
        "password": "pass",
    })
    tokens1 = login1.json()

    # Logout all sessions
    response = await client.post(
        "/auth/logout-all",
        headers={"Authorization": f"Bearer {tokens1['access_token']}"},
    )
    assert response.status_code == 200
    assert response.json()["revoked_count"] == 2

    # Both refresh tokens should be dead
    r1 = await client.post("/auth/refresh", json={
        "refresh_token": tokens1["refresh_token"],
    })
    r2 = await client.post("/auth/refresh", json={
        "refresh_token": login2.json()["refresh_token"],
    })
    assert r1.status_code == 401
    assert r2.status_code == 401
