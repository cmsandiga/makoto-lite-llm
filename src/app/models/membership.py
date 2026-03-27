import uuid

from sqlalchemy import Float, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class OrgMembership(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "org_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "org_id", name="uq_user_org"),
    )

    # ========== References ==========
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organizations.id"),
    )

    # ========== Role & Limits ==========
    role: Mapped[str] = mapped_column(
        String(50),
    )
    max_budget: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )


class TeamMembership(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "team_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "team_id", name="uq_user_team"),
    )

    # ========== References ==========
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id"),
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("teams.id"),
    )

    # ========== Role & Limits ==========
    role: Mapped[str] = mapped_column(
        String(50),
    )
    max_budget: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
