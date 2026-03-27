import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class SSOConfig(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "sso_configs"

    # ========== Organization ==========
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organizations.id"),
        unique=True,
    )

    # ========== Provider ==========
    provider: Mapped[str] = mapped_column(
        String(50),
    )
    client_id: Mapped[str] = mapped_column(
        String(255),
    )
    client_secret_encrypted: Mapped[str] = mapped_column(
        String(1000),
    )
    issuer_url: Mapped[str] = mapped_column(
        String(1000),
    )

    # ========== Mapping ==========
    allowed_domains: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
    )
    group_to_team_mapping: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # ========== Provisioning ==========
    auto_create_user: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )
    default_role: Mapped[str] = mapped_column(
        String(50),
        default="member",
    )

    # ========== Status ==========
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )
