# src/app/services/audit_service.py
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog, DeletedKey, DeletedTeam, DeletedUser


async def log_action(
    db: AsyncSession,
    actor_id: uuid.UUID,
    actor_type: str,
    action: str,
    resource_type: str,
    resource_id: str,
    ip_address: str,
    user_agent: str,
    before_value: dict | None = None,
    after_value: dict | None = None,
) -> AuditLog:
    """Record an action in the audit log."""
    log = AuditLog(
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before_value=before_value,
        after_value=after_value,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(log)
    await db.flush()
    return log


async def log_deletion(
    db: AsyncSession,
    resource_type: str,
    original_id: uuid.UUID,
    deleted_by: uuid.UUID,
    snapshot: dict | None = None,
    **kwargs,
) -> None:
    """Record entity deletion in the appropriate deleted_* table.

    Args:
        resource_type: "user", "team", or "key"
        original_id: The UUID of the deleted entity
        deleted_by: The UUID of the actor who deleted it
        snapshot: JSON snapshot of the entity before deletion
        **kwargs: Additional fields required by the specific table
            - user: email (required)
            - team: name (required)
            - key: key_prefix (required)
    """
    if resource_type == "user":
        db.add(DeletedUser(
            original_id=original_id,
            email=kwargs["email"],
            deleted_by=deleted_by,
            snapshot=snapshot,
        ))
    elif resource_type == "team":
        db.add(DeletedTeam(
            original_id=original_id,
            name=kwargs["name"],
            deleted_by=deleted_by,
            snapshot=snapshot,
        ))
    elif resource_type == "key":
        db.add(DeletedKey(
            original_id=original_id,
            key_prefix=kwargs["key_prefix"],
            deleted_by=deleted_by,
            snapshot=snapshot,
        ))
    else:
        raise ValueError(f"Unknown resource_type: {resource_type}")

    await db.flush()
