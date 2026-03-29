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


class KeyUpdate(BaseModel):
    key_alias: str | None = None
    allowed_models: list[str] | None = None
    max_budget: float | None = None
    tpm_limit: int | None = None
    rpm_limit: int | None = None
    metadata: dict | None = None


class KeyRotateRequest(BaseModel):
    grace_period_hours: int = 24


class KeyBlockRequest(BaseModel):
    blocked: bool


class KeyBulkUpdate(BaseModel):
    key_ids: list[uuid.UUID]
    allowed_models: list[str] | None = None
    max_budget: float | None = None
