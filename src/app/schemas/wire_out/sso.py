import uuid
from datetime import datetime

from pydantic import BaseModel


class SSOConfigResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    provider: str
    client_id: str
    client_secret: str  # always "***" — set by route, never from ORM
    issuer_url: str
    allowed_domains: list | None
    group_to_team_mapping: dict | None
    auto_create_user: bool
    default_role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
