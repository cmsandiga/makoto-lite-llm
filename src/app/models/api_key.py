import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ApiKey(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "api_keys"

    # ========== Identity ==========
    api_key_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
    )
    key_prefix: Mapped[str] = mapped_column(
        String(16),
    )
    key_alias: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # ========== Ownership ==========
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id"),
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("teams.id"),
        nullable=True,
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("organizations.id"),
        nullable=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("projects.id"),
        nullable=True,
    )

    # ========== Model Access ==========
    allowed_models: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # ========== Spend Limits ==========
    max_budget: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    soft_budget: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    spend: Mapped[float] = mapped_column(
        Float,
        default=0.0,
    )
    budget_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("budgets.id"),
        nullable=True,
    )

    # ========== Rate Limits ==========
    tpm_limit: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    rpm_limit: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    max_parallel_requests: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    budget_reset_period: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    # ========== Expiration ==========
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========== Rotation ==========
    auto_rotate: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    rotation_interval_days: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    last_rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    previous_key_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    grace_period_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========== Status ==========
    is_blocked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    # ========== Extra ==========
    metadata_json: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )
