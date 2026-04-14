import uuid

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Organization(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organizations"

    # ========== Identity ==========
    name: Mapped[str] = mapped_column(
        String(255),
    )
    slug: Mapped[str] = mapped_column(
        String(255),
        unique=True,
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

    # ========== Model Access ==========
    allowed_models: Mapped[list | None] = mapped_column(
        JSON,
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
