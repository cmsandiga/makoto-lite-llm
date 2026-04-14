import base64
import hashlib
import secrets
import uuid
from urllib.parse import urlencode

from cachetools import TTLCache
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import encrypt
from app.exceptions import DuplicateError
from app.models.membership import OrgMembership, TeamMembership
from app.models.sso_config import SSOConfig
from app.models.user import User

# In-memory state store with 10-minute TTL for CSRF protection.
# Key: state token, Value: {"verifier": str, "org_id": UUID}.
_state_store: TTLCache = TTLCache(maxsize=1024, ttl=600)


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge (S256)."""
    verifier = secrets.token_urlsafe(64)  # 86 chars
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


async def create_sso_config(
    db: AsyncSession,
    org_id: uuid.UUID,
    provider: str,
    client_id: str,
    client_secret: str,
    issuer_url: str,
    allowed_domains: list[str] | None = None,
    group_to_team_mapping: dict | None = None,
    auto_create_user: bool = True,
    default_role: str = "member",
) -> SSOConfig:
    """Create an SSO config. Encrypts client_secret before storage.

    Raises DuplicateError if the org already has a config.
    """
    config = SSOConfig(
        org_id=org_id,
        provider=provider,
        client_id=client_id,
        client_secret_encrypted=encrypt(client_secret),
        issuer_url=issuer_url,
        allowed_domains=allowed_domains,
        group_to_team_mapping=group_to_team_mapping,
        auto_create_user=auto_create_user,
        default_role=default_role,
    )
    db.add(config)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise DuplicateError(
            "SSO config already exists for this organization"
        ) from None
    await db.commit()
    await db.refresh(config)
    return config


async def get_sso_config(db: AsyncSession, org_id: uuid.UUID) -> SSOConfig | None:
    """Return the SSO config for an org, or None."""
    result = await db.execute(
        select(SSOConfig).where(SSOConfig.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def delete_sso_config(db: AsyncSession, org_id: uuid.UUID) -> bool:
    """Delete the SSO config for an org. Returns True if deleted, False if not found."""
    result = await db.execute(
        delete(SSOConfig).where(SSOConfig.org_id == org_id)
    )
    await db.commit()
    return result.rowcount > 0


async def build_authorize_url(
    db: AsyncSession,
    org_id: uuid.UUID,
    callback_url: str,
) -> tuple[str, str] | None:
    """Build the OAuth2 authorize redirect URL for an org's SSO config.

    Returns (url, state) or None if no config found.
    Stores code_verifier + org_id in state store for callback.
    """
    config = await get_sso_config(db, org_id)
    if config is None:
        return None

    state = secrets.token_urlsafe(32)
    verifier, challenge = generate_pkce_pair()
    _state_store[state] = {"verifier": verifier, "org_id": org_id}

    params = urlencode({
        "client_id": config.client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    url = f"{config.issuer_url}/authorize?{params}"
    return url, state


def validate_and_consume_state(state: str) -> dict | None:
    """Validate and consume an OAuth2 state token.

    Returns {"verifier": str, "org_id": UUID} if valid, None if invalid/expired.
    """
    return _state_store.pop(state, None)


async def provision_sso_user(
    db: AsyncSession,
    email: str,
    name: str | None,
    sso_provider: str,
    sso_subject: str,
    org_id: uuid.UUID,
    default_role: str = "member",
) -> User:
    """Find or create a user from SSO claims, and ensure org membership."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            email=email,
            name=name,
            role=default_role,
            sso_provider=sso_provider,
            sso_subject=sso_subject,
        )
        db.add(user)
        await db.flush()
    else:
        user.sso_provider = sso_provider
        user.sso_subject = sso_subject
        if name and not user.name:
            user.name = name

    membership = OrgMembership(
        user_id=user.id,
        org_id=org_id,
        role=default_role,
    )
    db.add(membership)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one()

    await db.commit()
    await db.refresh(user)
    return user


async def map_groups_to_teams(
    db: AsyncSession,
    user_id: uuid.UUID,
    idp_groups: list[str] | None,
    group_to_team_mapping: dict | None,
) -> None:
    """Map IdP groups to team memberships using the SSO config's mapping."""
    if not group_to_team_mapping or not idp_groups:
        return

    for group_name in idp_groups:
        team_id_str = group_to_team_mapping.get(group_name)
        if team_id_str is None:
            continue
        team_id = uuid.UUID(team_id_str)
        membership = TeamMembership(user_id=user_id, team_id=team_id, role="member")
        db.add(membership)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()

    await db.commit()


