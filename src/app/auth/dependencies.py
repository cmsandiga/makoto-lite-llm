import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from cachetools import TTLCache
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key_auth import hash_api_key
from app.auth.jwt_handler import decode_token
from app.config import settings
from app.database import get_db
from app.models.api_key import ApiKey
from app.models.organization import Organization
from app.models.team import Team
from app.models.user import User
from app.services.permission_service import resolve_model_access

# In-memory TTL cache for API key auth (spec section 2.1: 5s TTL).
# Key: api_key_hash -> (ApiKey, User) tuple.
_api_key_cache: TTLCache = TTLCache(
    maxsize=4096, ttl=settings.api_key_cache_ttl_seconds
)


def invalidate_api_key_cache(key_hash: str) -> None:
    """Remove a key from the auth cache. Call on update/delete/block."""
    _api_key_cache.pop(key_hash, None)


async def _lookup_api_key(db: AsyncSession, key_hash: str) -> ApiKey | None:
    """Look up an API key by current hash OR previous hash (grace period)."""
    result = await db.execute(
        select(ApiKey).where(
            (ApiKey.api_key_hash == key_hash)
            | (
                (ApiKey.previous_key_hash == key_hash)
                & (ApiKey.grace_period_expires_at > datetime.now(timezone.utc))
            )
        )
    )
    return result.scalar_one_or_none()


async def _authenticate_api_key(db: AsyncSession, raw_key: str) -> User:
    """Authenticate via API key hash lookup with TTL cache."""
    key_hash = hash_api_key(raw_key)

    cached = _api_key_cache.get(key_hash)
    if cached is not None:
        api_key, user = cached
    else:
        api_key = await _lookup_api_key(db, key_hash)
        if api_key is None:
            raise HTTPException(status_code=401, detail="Invalid API key")

        user_result = await db.execute(select(User).where(User.id == api_key.user_id))
        user = user_result.scalar_one_or_none()

        _api_key_cache[key_hash] = (api_key, user)

    if api_key.is_blocked:
        raise HTTPException(status_code=401, detail="API key is blocked")
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="API key has expired")
    if user is None or user.is_blocked:
        raise HTTPException(status_code=401, detail="Key owner not found or blocked")

    return user


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """Extract and validate auth from the Authorization header.

    Supports both JWT tokens and API keys (sk- prefix).
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid authorization header"
        )

    token = auth_header.split(" ", 1)[1]

    if token.startswith("sk-"):
        return await _authenticate_api_key(db, token)

    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = uuid.UUID(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.is_blocked:
        raise HTTPException(status_code=401, detail="User not found or blocked")

    return user


def require_role(*roles: str) -> Callable:
    """Factory that returns a FastAPI dependency enforcing role membership."""

    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return dependency


def require_model_access(path_param: str = "model") -> Callable:
    """Factory returning a dependency that checks model access for the current auth.

    Reads the model name from the path parameter specified by `path_param`.
    proxy_admin users bypass the check. JWT users without an API key have no restrictions.
    """

    async def dependency(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        model_name = request.path_params.get(path_param)
        if model_name is None:
            return user

        # proxy_admin bypasses model access checks
        if user.role == "proxy_admin":
            return user

        # Get the auth token to look up the API key
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.split(" ", 1)[1] if " " in auth_header else ""

        # JWT users without an API key — no model restrictions
        if not token.startswith("sk-"):
            return user

        api_key = await _lookup_api_key(db, hash_api_key(token))

        key_models = api_key.allowed_models if api_key else None
        team_models = None
        org_models = None

        if api_key and api_key.team_id:
            team_result = await db.execute(select(Team).where(Team.id == api_key.team_id))
            team = team_result.scalar_one_or_none()
            if team:
                team_models = team.allowed_models

        if api_key and api_key.org_id:
            org_result = await db.execute(
                select(Organization).where(Organization.id == api_key.org_id)
            )
            org = org_result.scalar_one_or_none()
            if org:
                org_models = org.allowed_models

        if not resolve_model_access(model_name, key_models, team_models, org_models):
            raise HTTPException(
                status_code=403,
                detail=f"Model '{model_name}' is not allowed for this key",
            )

        return user

    return dependency
