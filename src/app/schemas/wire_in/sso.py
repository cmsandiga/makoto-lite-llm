import uuid

from pydantic import BaseModel


class SSOConfigCreate(BaseModel):
    org_id: uuid.UUID
    provider: str  # "google", "azure_ad", "okta", "oidc"
    client_id: str
    client_secret: str  # plaintext — service encrypts before storage
    issuer_url: str
    allowed_domains: list[str] | None = None
    group_to_team_mapping: dict | None = None
    auto_create_user: bool = True
    default_role: str = "member"
