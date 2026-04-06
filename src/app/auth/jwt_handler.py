import uuid
from datetime import datetime, timedelta, timezone

import jwt
from uuid_extensions import uuid7

from app.config import settings


def create_access_token(
    user_id: uuid.UUID,
    role: str,
    org_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "org_id": str(org_id) if org_id else None,
        "team_id": str(team_id) if team_id else None,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc)
        + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: uuid.UUID) -> str:
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": str(uuid7()),
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc)
        + timedelta(days=settings.refresh_token_expire_days),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return None
