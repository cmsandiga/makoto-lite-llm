import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class AuditLog(Base, UUIDMixin):
    __tablename__ = "audit_log"

    # ========== Actor ==========
    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
    )
    actor_type: Mapped[str] = mapped_column(
        String(50),
    )

    # ========== Action ==========
    action: Mapped[str] = mapped_column(
        String(50),
    )
    resource_type: Mapped[str] = mapped_column(
        String(50),
    )
    resource_id: Mapped[str] = mapped_column(
        String(255),
    )

    # ========== Snapshot ==========
    before_value: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    after_value: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # ========== Context ==========
    ip_address: Mapped[str] = mapped_column(
        String(45),
    )
    user_agent: Mapped[str] = mapped_column(
        String(500),
    )

    # ========== Timestamp ==========
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class DeletedUser(Base, UUIDMixin):
    __tablename__ = "deleted_users"

    # ========== Reference ==========
    original_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
    )
    email: Mapped[str] = mapped_column(
        String(320),
    )

    # ========== Deletion ==========
    deleted_by: Mapped[uuid.UUID] = mapped_column(
        Uuid,
    )
    reason: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
    snapshot: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # ========== Timestamp ==========
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class DeletedTeam(Base, UUIDMixin):
    __tablename__ = "deleted_teams"

    # ========== Reference ==========
    original_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
    )
    name: Mapped[str] = mapped_column(
        String(255),
    )

    # ========== Deletion ==========
    deleted_by: Mapped[uuid.UUID] = mapped_column(
        Uuid,
    )
    snapshot: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # ========== Timestamp ==========
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class DeletedKey(Base, UUIDMixin):
    __tablename__ = "deleted_keys"

    # ========== Reference ==========
    original_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
    )
    key_prefix: Mapped[str] = mapped_column(
        String(16),
    )

    # ========== Deletion ==========
    deleted_by: Mapped[uuid.UUID] = mapped_column(
        Uuid,
    )
    snapshot: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # ========== Timestamp ==========
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class ErrorLog(Base, UUIDMixin):
    __tablename__ = "error_logs"

    # ========== Error ==========
    error_type: Mapped[str] = mapped_column(
        String(100),
    )
    message: Mapped[str] = mapped_column(
        String(2000),
    )

    # ========== Context ==========
    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
    )
    user_agent: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # ========== Extra ==========
    metadata_json: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )

    # ========== Timestamp ==========
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
