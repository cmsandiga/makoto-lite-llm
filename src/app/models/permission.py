import uuid

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ObjectPermission(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "object_permissions"
    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity_id",
            "resource_type",
            "resource_id",
            "action",
            name="uq_object_permission",
        ),
    )

    # ========== Entity (who) ==========
    entity_type: Mapped[str] = mapped_column(
        String(50),
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
    )

    # ========== Resource (what) ==========
    resource_type: Mapped[str] = mapped_column(
        String(50),
    )
    resource_id: Mapped[str] = mapped_column(
        String(255),
    )

    # ========== Action ==========
    action: Mapped[str] = mapped_column(
        String(10),
    )


class AccessGroup(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "access_groups"

    # ========== Identity ==========
    name: Mapped[str] = mapped_column(
        String(255),
        unique=True,
    )
    description: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    # ========== Resources ==========
    resources: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
    )


class AccessGroupAssignment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "access_group_assignments"
    __table_args__ = (
        UniqueConstraint(
            "access_group_id",
            "entity_type",
            "entity_id",
            name="uq_access_group_assignment",
        ),
    )

    # ========== References ==========
    access_group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("access_groups.id"),
    )
    entity_type: Mapped[str] = mapped_column(
        String(50),
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
    )
