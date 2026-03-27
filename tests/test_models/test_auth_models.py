import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.api_key import ApiKey
from app.models.audit import AuditLog
from app.models.refresh_token import RefreshToken
from app.models.user import User


async def test_create_api_key(db_session):
    user = User(email="alice@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    key = ApiKey(
        api_key_hash="sha256_hash_here",
        key_prefix="sk-abcd12",
        user_id=user.id,
        allowed_models=["gpt-4", "claude-*"],
    )
    db_session.add(key)
    await db_session.commit()

    result = await db_session.execute(select(ApiKey).where(ApiKey.user_id == user.id))
    fetched = result.scalar_one()
    assert fetched.key_prefix == "sk-abcd12"
    assert fetched.spend == 0.0
    assert fetched.is_blocked is False
    assert fetched.allowed_models == ["gpt-4", "claude-*"]


async def test_create_refresh_token(db_session):
    user = User(email="bob@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    token = RefreshToken(
        token_hash="sha256_token_hash",
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(token)
    await db_session.commit()

    result = await db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )
    fetched = result.scalar_one()
    assert fetched.is_revoked is False


async def test_create_audit_log(db_session):
    log = AuditLog(
        actor_id=uuid.uuid4(),
        actor_type="user",
        action="create",
        resource_type="team",
        resource_id=str(uuid.uuid4()),
        ip_address="127.0.0.1",
        user_agent="test",
    )
    db_session.add(log)
    await db_session.commit()

    result = await db_session.execute(select(AuditLog).where(AuditLog.action == "create"))
    fetched = result.scalar_one()
    assert fetched.actor_type == "user"
