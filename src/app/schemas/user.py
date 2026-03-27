import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str | None = None
    name: str | None = None
    role: str = "member"
    max_budget: float | None = None
    metadata: dict | None = None


class UserUpdate(BaseModel):
    user_id: uuid.UUID
    role: str | None = None
    name: str | None = None
    max_budget: float | None = None
    is_blocked: bool | None = None
    metadata: dict | None = None


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    role: str
    max_budget: float | None
    spend: float
    is_blocked: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserBlockRequest(BaseModel):
    user_id: uuid.UUID
    blocked: bool
