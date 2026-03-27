import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class PasswordResetToken(Base, UUIDMixin):
    __tablename__ = "password_reset_tokens"

    # ========== Token ==========
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id"),
    )

    # ========== Lifecycle ==========
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
    )
    is_used: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    # ========== Timestamp ==========
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
