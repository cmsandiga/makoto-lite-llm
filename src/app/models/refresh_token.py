import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class RefreshToken(Base, UUIDMixin):
    __tablename__ = "refresh_tokens"

    # ========== Token ==========
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id"),
        index=True,
    )

    # ========== Lifecycle ==========
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
    )
    is_revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("refresh_tokens.id"),
        nullable=True,
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

    # ========== Timestamp ==========
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
