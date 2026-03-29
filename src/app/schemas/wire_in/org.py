import uuid

from pydantic import BaseModel


class OrgCreate(BaseModel):
    name: str
    slug: str
    max_budget: float | None = None
    metadata: dict | None = None


class OrgUpdate(BaseModel):
    name: str | None = None
    max_budget: float | None = None
    metadata: dict | None = None


class OrgMemberAdd(BaseModel):
    user_id: uuid.UUID
    role: str = "member"


class OrgMemberUpdate(BaseModel):
    user_id: uuid.UUID
    role: str


class OrgMemberRemove(BaseModel):
    user_id: uuid.UUID
