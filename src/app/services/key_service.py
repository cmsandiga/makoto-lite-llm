import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key_auth import generate_api_key, get_key_prefix, hash_api_key
from app.auth.dependencies import invalidate_api_key_cache
from app.models.api_key import ApiKey


# ========== Generate ==========


async def generate_key(
    db: AsyncSession,
    user_id: uuid.UUID,
    key_alias: str | None = None,
    team_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    allowed_models: list[str] | None = None,
    max_budget: float | None = None,
    tpm_limit: int | None = None,
    rpm_limit: int | None = None,
    max_parallel_requests: int | None = None,
    expires_at: datetime | None = None,
    metadata: dict | None = None,
) -> tuple[str, ApiKey]:
    """Generate a new API key. Returns (plaintext_key, api_key_record).

    The plaintext key is only available at creation time.
    """
    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        key_alias=key_alias,
        user_id=user_id,
        team_id=team_id,
        org_id=org_id,
        allowed_models=allowed_models,
        max_budget=max_budget,
        tpm_limit=tpm_limit,
        rpm_limit=rpm_limit,
        max_parallel_requests=max_parallel_requests,
        expires_at=expires_at,
        metadata_json=metadata,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return raw_key, api_key


# ========== Read ==========


async def get_key(db: AsyncSession, key_id: uuid.UUID) -> ApiKey | None:
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    return result.scalar_one_or_none()


async def list_keys(
    db: AsyncSession,
    user_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[ApiKey]:
    offset = (page - 1) * page_size
    query = select(ApiKey).order_by(ApiKey.created_at.desc())
    if user_id is not None:
        query = query.where(ApiKey.user_id == user_id)
    if team_id is not None:
        query = query.where(ApiKey.team_id == team_id)
    if org_id is not None:
        query = query.where(ApiKey.org_id == org_id)
    result = await db.execute(query.offset(offset).limit(page_size))
    return list(result.scalars().all())


# ========== Update ==========


async def update_key(
    db: AsyncSession,
    key_id: uuid.UUID,
    key_alias: str | None = None,
    allowed_models: list[str] | None = None,
    max_budget: float | None = None,
    tpm_limit: int | None = None,
    rpm_limit: int | None = None,
    metadata_json: dict | None = None,
) -> ApiKey | None:
    key = await get_key(db, key_id)
    if key is None:
        return None
    if key_alias is not None:
        key.key_alias = key_alias
    if allowed_models is not None:
        key.allowed_models = allowed_models
    if max_budget is not None:
        key.max_budget = max_budget
    if tpm_limit is not None:
        key.tpm_limit = tpm_limit
    if rpm_limit is not None:
        key.rpm_limit = rpm_limit
    if metadata_json is not None:
        key.metadata_json = metadata_json
    await db.commit()
    await db.refresh(key)
    return key


# ========== Rotate ==========


async def rotate_key(
    db: AsyncSession,
    key_id: uuid.UUID,
    grace_period_hours: int = 24,
) -> tuple[str, ApiKey] | None:
    """Rotate a key: generate new one, keep old hash during grace period."""
    key = await get_key(db, key_id)
    if key is None:
        return None

    # Invalidate cache for the old key hash before rotation
    invalidate_api_key_cache(key.api_key_hash)

    # Store current hash as previous
    key.previous_key_hash = key.api_key_hash
    key.grace_period_expires_at = datetime.now(timezone.utc) + timedelta(hours=grace_period_hours)

    # Generate new key
    raw_key = generate_api_key()
    key.api_key_hash = hash_api_key(raw_key)
    key.key_prefix = get_key_prefix(raw_key)
    key.last_rotated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(key)
    return raw_key, key


# ========== Block ==========


async def block_key(db: AsyncSession, key_id: uuid.UUID, blocked: bool) -> ApiKey | None:
    key = await get_key(db, key_id)
    if key is None:
        return None
    key.is_blocked = blocked
    await db.commit()
    await db.refresh(key)
    invalidate_api_key_cache(key.api_key_hash)
    return key


# ========== Reactivate ==========


async def reactivate_key(db: AsyncSession, key_id: uuid.UUID) -> ApiKey | None:
    """Clear expiration and unblock a key."""
    key = await get_key(db, key_id)
    if key is None:
        return None
    key.expires_at = None
    key.is_blocked = False
    await db.commit()
    await db.refresh(key)
    return key


# ========== Reset Spend ==========


async def reset_spend(db: AsyncSession, key_id: uuid.UUID) -> ApiKey | None:
    key = await get_key(db, key_id)
    if key is None:
        return None
    key.spend = 0.0
    await db.commit()
    await db.refresh(key)
    return key


# ========== Bulk Update ==========


async def bulk_update_keys(
    db: AsyncSession,
    key_ids: list[uuid.UUID],
    allowed_models: list[str] | None = None,
    max_budget: float | None = None,
) -> int:
    """Batch update multiple keys. Returns count of updated rows."""
    values: dict = {}
    if allowed_models is not None:
        values["allowed_models"] = allowed_models
    if max_budget is not None:
        values["max_budget"] = max_budget
    if not values:
        return 0
    result = await db.execute(
        update(ApiKey).where(ApiKey.id.in_(key_ids)).values(**values)
    )
    await db.commit()
    return result.rowcount  # type: ignore[return-value]


# ========== Delete ==========


async def delete_key(db: AsyncSession, key_id: uuid.UUID) -> bool:
    key = await get_key(db, key_id)
    if key is None:
        return False
    await db.delete(key)
    await db.commit()
    return True
