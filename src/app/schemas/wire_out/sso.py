import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator


class SSOConfigResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    provider: str
    client_id: str
    client_secret: str = "***"  # always "***" — set by route, never from ORM
    issuer_url: str
    allowed_domains: list | None
    group_to_team_mapping: dict | None
    auto_create_user: bool
    default_role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _mask_secret(cls, data: object) -> object:
        """Map ORM client_secret_encrypted to masked client_secret."""
        if hasattr(data, "client_secret_encrypted"):
            # ORM model — always mask
            return {
                "id": data.id,
                "org_id": data.org_id,
                "provider": data.provider,
                "client_id": data.client_id,
                "client_secret": "***",
                "issuer_url": data.issuer_url,
                "allowed_domains": data.allowed_domains,
                "group_to_team_mapping": data.group_to_team_mapping,
                "auto_create_user": data.auto_create_user,
                "default_role": data.default_role,
                "is_active": data.is_active,
                "created_at": data.created_at,
            }
        return data
