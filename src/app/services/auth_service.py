import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key_auth import hash_api_key
from app.auth.jwt_handler import create_access_token, create_refresh_token, decode_token
from app.auth.password import hash_password, verify_password
from app.config import settings
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User


# ========== Login ==========


async def authenticate_user(
    db: AsyncSession, email: str, password: str
) -> User | None:
    """Validate credentials and return the User, or None on failure.

    Tracks failed attempts and enforces lockout (brute-force protection).
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None or user.password_hash is None:
        return None

    # ---- Brute-force protection: still locked out? ----
    if user.lockout_until and user.lockout_until > datetime.now(timezone.utc):
        return None

    # ---- Wrong password ----
    if not verify_password(password, user.password_hash):
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= settings.max_login_attempts:
            user.lockout_until = datetime.now(timezone.utc) + timedelta(
                minutes=settings.lockout_duration_minutes
            )
        await db.commit()
        return None

    # ---- Success: reset counters ----
    user.failed_login_attempts = 0
    user.lockout_until = None
    await db.commit()
    return user


# ========== Token Creation ==========


async def create_tokens(
    db: AsyncSession,
    user: User,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, str]:
    """Create an access + refresh token pair and persist the refresh token."""
    access_token = create_access_token(user_id=user.id, role=user.role)
    refresh_token_str = create_refresh_token(user_id=user.id)

    # Store a SHA-256 hash of the refresh token (never store the raw value)
    token_hash = hash_api_key(refresh_token_str)
    refresh_record = RefreshToken(
        token_hash=token_hash,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.refresh_token_expire_days),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(refresh_record)
    await db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
    }


# ========== Refresh ==========


async def refresh_tokens(
    db: AsyncSession, refresh_token_str: str
) -> dict[str, str] | None:
    """Rotate a refresh token: revoke the old one, issue a new pair."""
    token_hash = hash_api_key(refresh_token_str)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.is_revoked == False,  # noqa: E712  (SQLAlchemy needs ==)
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    old_token = result.scalar_one_or_none()
    if old_token is None:
        return None

    # Revoke old token
    old_token.is_revoked = True

    # Fetch the user to build a fresh access token
    user_result = await db.execute(select(User).where(User.id == old_token.user_id))
    user = user_result.scalar_one()

    # Issue new pair
    access_token = create_access_token(user_id=user.id, role=user.role)
    new_refresh_str = create_refresh_token(user_id=user.id)
    new_token_hash = hash_api_key(new_refresh_str)

    new_record = RefreshToken(
        token_hash=new_token_hash,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(new_record)
    await db.flush()  # sends INSERT → new_record.id is now available, but no commit yet

    # Link old → new (for audit trail)
    old_token.replaced_by = new_record.id
    await db.commit()  # single atomic commit: INSERT + UPDATE together

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_str,
        "token_type": "bearer",
    }


# ========== Logout ==========


async def revoke_refresh_token(db: AsyncSession, refresh_token_str: str) -> bool:
    """Revoke a single refresh token (logout from one device)."""
    token_hash = hash_api_key(refresh_token_str)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    token = result.scalar_one_or_none()
    if token is None:
        return False
    token.is_revoked = True
    await db.commit()
    return True


async def revoke_all_user_tokens(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Revoke every active refresh token for a user (logout from all devices)."""
    result = await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.is_revoked == False,  # noqa: E712
        )
        .values(is_revoked=True)
    )
    await db.commit()
    return result.rowcount


# ========== Password Reset ==========


async def create_password_reset_token(db: AsyncSession, email: str) -> str | None:
    """Generate a password-reset token. Returns the raw token (to be emailed)."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        return None

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    reset_record = PasswordResetToken(
        token_hash=token_hash,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(reset_record)
    await db.commit()
    return token


async def reset_password_with_token(
    db: AsyncSession, token: str, new_password: str
) -> bool:
    """Consume a reset token and update the user's password."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.is_used == False,  # noqa: E712
            PasswordResetToken.expires_at > datetime.now(timezone.utc),
        )
    )
    reset_token = result.scalar_one_or_none()
    if reset_token is None:
        return False

    reset_token.is_used = True

    user_result = await db.execute(
        select(User).where(User.id == reset_token.user_id)
    )
    user = user_result.scalar_one()
    user.password_hash = hash_password(new_password)
    await db.commit()
    return True
