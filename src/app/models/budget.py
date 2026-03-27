from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Budget(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "budgets"

    # ========== Identity ==========
    name: Mapped[str] = mapped_column(
        String(255),
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

    # ========== Reset ==========
    budget_reset_period: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
