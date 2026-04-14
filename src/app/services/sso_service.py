import uuid

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import encrypt
from app.exceptions import DuplicateError
from app.models.sso_config import SSOConfig


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
        raise DuplicateError("SSO config already exists for this organization")
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
