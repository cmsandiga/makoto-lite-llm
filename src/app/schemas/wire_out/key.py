import uuid
from datetime import datetime

from pydantic import BaseModel


class KeyGenerateResponse(BaseModel):
    """Returned only at creation time — contains the plaintext key."""
    key: str
    key_id: uuid.UUID
    key_prefix: str
    expires_at: datetime | None


class KeyResponse(BaseModel):
    """Standard key info — never exposes the full key."""
    id: uuid.UUID
    key_prefix: str
    key_alias: str | None
    user_id: uuid.UUID
    team_id: uuid.UUID | None
    org_id: uuid.UUID | None
    allowed_models: list | None
    max_budget: float | None
    spend: float
    is_blocked: bool
    expires_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
