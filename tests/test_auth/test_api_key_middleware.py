from datetime import datetime, timedelta, timezone

from app.auth.api_key_auth import generate_api_key, get_key_prefix, hash_api_key
from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.models.api_key import ApiKey
from app.models.user import User


async def test_api_key_auth(client, db_session):
    """A valid sk- key in the Bearer header should authenticate the request."""
    user = User(email="dev@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=user.id,
    )
    db_session.add(api_key)
    await db_session.commit()

    response = await client.get(
        f"/users/{user.id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "dev@test.com"


async def test_api_key_blocked(client, db_session):
    """A blocked API key should return 401."""
    user = User(email="blocked-key@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=user.id,
        is_blocked=True,
    )
    db_session.add(api_key)
    await db_session.commit()

    response = await client.get(
        f"/users/{user.id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 401


async def test_api_key_expired(client, db_session):
    """An expired API key should return 401."""
    user = User(email="expired-key@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=user.id,
        expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(api_key)
    await db_session.commit()

    response = await client.get(
        f"/users/{user.id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 401


async def test_api_key_rotated_grace_period(client, db_session):
    """During grace period, the old key hash (in previous_key_hash) should still work."""
    user = User(email="rotated@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    old_key = generate_api_key()
    new_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(new_key),
        key_prefix=get_key_prefix(new_key),
        user_id=user.id,
        previous_key_hash=hash_api_key(old_key),
        grace_period_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    db_session.add(api_key)
    await db_session.commit()

    # Old key should still work during grace period
    response = await client.get(
        f"/users/{user.id}",
        headers={"Authorization": f"Bearer {old_key}"},
    )
    assert response.status_code == 200


async def test_jwt_still_works(client, db_session):
    """JWT auth should continue working alongside API key auth."""
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()

    token = create_access_token(user_id=admin.id, role="proxy_admin")
    response = await client.get(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
