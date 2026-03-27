import uuid
from datetime import datetime

from pydantic import BaseModel


class TeamCreate(BaseModel):
    name: str
    org_id: uuid.UUID | None = None
    allowed_models: list[str] | None = None
    max_budget: float | None = None
    tpm_limit: int | None = None
    rpm_limit: int | None = None
    metadata: dict | None = None


class TeamUpdate(BaseModel):
    team_id: uuid.UUID
    name: str | None = None
    allowed_models: list[str] | None = None
    max_budget: float | None = None
    tpm_limit: int | None = None
    rpm_limit: int | None = None
    metadata: dict | None = None


class TeamResponse(BaseModel):
    id: uuid.UUID
    name: str
    org_id: uuid.UUID | None
    allowed_models: list | None
    max_budget: float | None
    is_blocked: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TeamMemberAdd(BaseModel):
    team_id: uuid.UUID
    user_id: uuid.UUID
    role: str = "member"


class TeamMemberUpdate(BaseModel):
    team_id: uuid.UUID
    user_id: uuid.UUID
    role: str


class TeamMemberDelete(BaseModel):
    team_id: uuid.UUID
    user_id: uuid.UUID
