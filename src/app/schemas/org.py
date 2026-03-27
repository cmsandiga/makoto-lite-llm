import uuid
from datetime import datetime

from pydantic import BaseModel


class OrgCreate(BaseModel):
    name: str
    slug: str
    max_budget: float | None = None
    metadata: dict | None = None


class OrgUpdate(BaseModel):
    org_id: uuid.UUID
    name: str | None = None
    max_budget: float | None = None
    metadata: dict | None = None


class OrgResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    max_budget: float | None
    is_blocked: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgMemberAdd(BaseModel):
    org_id: uuid.UUID
    user_id: uuid.UUID
    role: str = "member"


class OrgMemberUpdate(BaseModel):
    org_id: uuid.UUID
    user_id: uuid.UUID
    role: str


class OrgMemberDelete(BaseModel):
    org_id: uuid.UUID
    user_id: uuid.UUID
