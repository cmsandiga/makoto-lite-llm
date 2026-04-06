# tests/test_services/test_audit_service.py
import uuid

from sqlalchemy import select

from app.models.audit import AuditLog, DeletedKey, DeletedTeam, DeletedUser
from app.services.audit_service import log_action, log_deletion


async def test_log_action(db_session):
    """log_action creates an AuditLog row."""
    actor_id = uuid.uuid4()
    await log_action(
        db=db_session,
        actor_id=actor_id,
        actor_type="user",
        action="create",
        resource_type="team",
        resource_id=str(uuid.uuid4()),
        ip_address="127.0.0.1",
        user_agent="test-agent",
    )

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.actor_id == actor_id)
    )
    log = result.scalar_one()
    assert log.action == "create"
    assert log.resource_type == "team"
    assert log.ip_address == "127.0.0.1"


async def test_log_action_with_snapshots(db_session):
    """log_action can record before/after values."""
    actor_id = uuid.uuid4()
    await log_action(
        db=db_session,
        actor_id=actor_id,
        actor_type="user",
        action="update",
        resource_type="user",
        resource_id="user-123",
        ip_address="10.0.0.1",
        user_agent="admin-ui",
        before_value={"role": "member"},
        after_value={"role": "proxy_admin"},
    )

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.actor_id == actor_id)
    )
    log = result.scalar_one()
    assert log.before_value == {"role": "member"}
    assert log.after_value == {"role": "proxy_admin"}


async def test_log_deletion_user(db_session):
    """log_deletion records a deleted user."""
    original_id = uuid.uuid4()
    deleted_by = uuid.uuid4()
    await log_deletion(
        db=db_session,
        resource_type="user",
        original_id=original_id,
        deleted_by=deleted_by,
        snapshot={"email": "gone@test.com", "role": "member"},
        email="gone@test.com",
    )

    result = await db_session.execute(
        select(DeletedUser).where(DeletedUser.original_id == original_id)
    )
    row = result.scalar_one()
    assert row.email == "gone@test.com"
    assert row.deleted_by == deleted_by


async def test_log_deletion_team(db_session):
    """log_deletion records a deleted team."""
    original_id = uuid.uuid4()
    deleted_by = uuid.uuid4()
    await log_deletion(
        db=db_session,
        resource_type="team",
        original_id=original_id,
        deleted_by=deleted_by,
        snapshot={"name": "Gone Team"},
        name="Gone Team",
    )

    result = await db_session.execute(
        select(DeletedTeam).where(DeletedTeam.original_id == original_id)
    )
    row = result.scalar_one()
    assert row.name == "Gone Team"


async def test_log_deletion_key(db_session):
    """log_deletion records a deleted key."""
    original_id = uuid.uuid4()
    deleted_by = uuid.uuid4()
    await log_deletion(
        db=db_session,
        resource_type="key",
        original_id=original_id,
        deleted_by=deleted_by,
        snapshot={"key_prefix": "sk-abc123"},
        key_prefix="sk-abc123",
    )

    result = await db_session.execute(
        select(DeletedKey).where(DeletedKey.original_id == original_id)
    )
    row = result.scalar_one()
    assert row.key_prefix == "sk-abc123"
