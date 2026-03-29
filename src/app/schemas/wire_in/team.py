import uuid

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
    name: str | None = None
    allowed_models: list[str] | None = None
    max_budget: float | None = None
    tpm_limit: int | None = None
    rpm_limit: int | None = None
    metadata: dict | None = None


class TeamMemberAdd(BaseModel):
    user_id: uuid.UUID
    role: str = "member"


class TeamMemberUpdate(BaseModel):
    user_id: uuid.UUID
    role: str


class TeamMemberRemove(BaseModel):
    user_id: uuid.UUID
