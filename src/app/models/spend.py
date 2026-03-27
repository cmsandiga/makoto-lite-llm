import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class SpendLog(Base, UUIDMixin):
    __tablename__ = "spend_logs"

    # ========== Request ==========
    request_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
    )

    # ========== References ==========
    api_key_hash: Mapped[str] = mapped_column(
        String(64),
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )

    # ========== Model ==========
    model: Mapped[str] = mapped_column(
        String(255),
    )
    provider: Mapped[str] = mapped_column(
        String(100),
    )

    # ========== Usage ==========
    input_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )
    spend: Mapped[float] = mapped_column(
        Float,
        default=0.0,
    )

    # ========== Status ==========
    cache_hit: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
    )
    response_time_ms: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    # ========== Timestamp ==========
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


# ========== Daily Aggregate Tables ==========
# All 6 tables have the same structure, grouped by different entity.


class DailyUserSpend(Base, UUIDMixin):
    __tablename__ = "daily_user_spend"
    __table_args__ = (
        UniqueConstraint("user_id", "model", "date", name="uq_daily_user_spend"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    model: Mapped[str] = mapped_column(String(255))
    date: Mapped[date] = mapped_column(Date)
    total_spend: Mapped[float] = mapped_column(Float, default=0.0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)


class DailyTeamSpend(Base, UUIDMixin):
    __tablename__ = "daily_team_spend"
    __table_args__ = (
        UniqueConstraint("team_id", "model", "date", name="uq_daily_team_spend"),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    model: Mapped[str] = mapped_column(String(255))
    date: Mapped[date] = mapped_column(Date)
    total_spend: Mapped[float] = mapped_column(Float, default=0.0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)


class DailyOrgSpend(Base, UUIDMixin):
    __tablename__ = "daily_org_spend"
    __table_args__ = (
        UniqueConstraint("org_id", "model", "date", name="uq_daily_org_spend"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    model: Mapped[str] = mapped_column(String(255))
    date: Mapped[date] = mapped_column(Date)
    total_spend: Mapped[float] = mapped_column(Float, default=0.0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)


class DailyKeySpend(Base, UUIDMixin):
    __tablename__ = "daily_key_spend"
    __table_args__ = (
        UniqueConstraint("api_key_hash", "model", "date", name="uq_daily_key_spend"),
    )

    api_key_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(255))
    date: Mapped[date] = mapped_column(Date)
    total_spend: Mapped[float] = mapped_column(Float, default=0.0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)


class DailyEndUserSpend(Base, UUIDMixin):
    __tablename__ = "daily_end_user_spend"
    __table_args__ = (
        UniqueConstraint("end_user", "model", "date", name="uq_daily_end_user_spend"),
    )

    end_user: Mapped[str] = mapped_column(String(255))
    model: Mapped[str] = mapped_column(String(255))
    date: Mapped[date] = mapped_column(Date)
    total_spend: Mapped[float] = mapped_column(Float, default=0.0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)


class DailyTagSpend(Base, UUIDMixin):
    __tablename__ = "daily_tag_spend"
    __table_args__ = (
        UniqueConstraint("tag", "model", "date", name="uq_daily_tag_spend"),
    )

    tag: Mapped[str] = mapped_column(String(255))
    model: Mapped[str] = mapped_column(String(255))
    date: Mapped[date] = mapped_column(Date)
    total_spend: Mapped[float] = mapped_column(Float, default=0.0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
