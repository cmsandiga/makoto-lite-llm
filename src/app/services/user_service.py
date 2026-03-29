import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.models.user import User


# ========== Create ==========


async def create_user(
    db: AsyncSession,
    email: str,
    password: str | None = None,
    name: str | None = None,
    role: str = "member",
    max_budget: float | None = None,
    metadata: dict | None = None,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password) if password else None,
        name=name,
        role=role,
        max_budget=max_budget,
        metadata_json=metadata,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ========== Read ==========


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def list_users(
    db: AsyncSession, page: int = 1, page_size: int = 50
) -> list[User]:
    offset = (page - 1) * page_size
    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(offset).limit(page_size)
    )
    return list(result.scalars().all())


# ========== Update Profile ==========


async def update_user_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str | None = None,
    role: str | None = None,
    metadata_json: dict | None = None,
) -> User | None:
    user = await get_user(db, user_id)
    if user is None:
        return None
    if name is not None:
        user.name = name
    if role is not None:
        user.role = role
    if metadata_json is not None:
        user.metadata_json = metadata_json
    await db.commit()
    await db.refresh(user)
    return user


# ========== Update Budget ==========


async def update_user_budget(
    db: AsyncSession,
    user_id: uuid.UUID,
    max_budget: float | None = None,
) -> User | None:
    user = await get_user(db, user_id)
    if user is None:
        return None
    if max_budget is not None:
        user.max_budget = max_budget
    await db.commit()
    await db.refresh(user)
    return user


# ========== Block ==========


async def block_user(db: AsyncSession, user_id: uuid.UUID, blocked: bool) -> User | None:
    user = await get_user(db, user_id)
    if user is None:
        return None
    user.is_blocked = blocked
    await db.commit()
    await db.refresh(user)
    return user


# ========== Delete ==========


async def delete_user(db: AsyncSession, user_id: uuid.UUID) -> bool:
    user = await get_user(db, user_id)
    if user is None:
        return False
    await db.delete(user)
    await db.commit()
    return True
