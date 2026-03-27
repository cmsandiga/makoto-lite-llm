import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"

    # ========== Identity ==========
    email: Mapped[str] = mapped_column(
        String(320),
        unique=True,
    )
    password_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    role: Mapped[str] = mapped_column(
        String(50),
        default="member",
    )

    # ========== Budget & Limits ==========
    max_budget: Mapped[float | None] = mapped_column(
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

    # ========== SSO ==========
    sso_provider: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    sso_subject: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # ========== Security ==========
    is_blocked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )
    lockout_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========== Extra ==========
    metadata_json: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )
