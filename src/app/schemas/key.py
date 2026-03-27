import uuid
from datetime import datetime

from pydantic import BaseModel


class KeyGenerate(BaseModel):
    key_alias: str | None = None
    team_id: uuid.UUID | None = None
    org_id: uuid.UUID | None = None
    allowed_models: list[str] | None = None
    max_budget: float | None = None
    tpm_limit: int | None = None
    rpm_limit: int | None = None
    max_parallel_requests: int | None = None
    expires_at: datetime | None = None
    metadata: dict | None = None


class KeyGenerateResponse(BaseModel):
    key: str  # plaintext — only returned once
    key_id: uuid.UUID
    key_prefix: str
    expires_at: datetime | None


class KeyUpdate(BaseModel):
    key_id: uuid.UUID
    key_alias: str | None = None
    allowed_models: list[str] | None = None
    max_budget: float | None = None
    tpm_limit: int | None = None
    rpm_limit: int | None = None
    metadata: dict | None = None


class KeyResponse(BaseModel):
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


class KeyRotateRequest(BaseModel):
    key_id: uuid.UUID
    grace_period_hours: int = 24


class KeyBlockRequest(BaseModel):
    key_id: uuid.UUID
    blocked: bool


class KeyBulkUpdate(BaseModel):
    key_ids: list[uuid.UUID]
    allowed_models: list[str] | None = None
    max_budget: float | None = None
