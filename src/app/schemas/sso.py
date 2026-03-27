import uuid

from pydantic import BaseModel


class SSOConfigCreate(BaseModel):
    org_id: uuid.UUID
    provider: str
    client_id: str
    client_secret: str
    issuer_url: str
    allowed_domains: list[str] | None = None
    group_to_team_mapping: dict | None = None
    auto_create_user: bool = True
    default_role: str = "member"


class SSOConfigResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    provider: str
    client_id: str
    issuer_url: str
    allowed_domains: list | None
    auto_create_user: bool
    is_active: bool

    model_config = {"from_attributes": True}
