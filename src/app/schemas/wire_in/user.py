from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str | None = None
    name: str | None = None
    role: str = "member"
    max_budget: float | None = None
    metadata: dict | None = None


class UserUpdateProfile(BaseModel):
    """Partial update: name, role, metadata."""
    name: str | None = None
    role: str | None = None
    metadata: dict | None = None


class UserUpdateBudget(BaseModel):
    """Partial update: spending limits."""
    max_budget: float | None = None


class UserBlockRequest(BaseModel):
    blocked: bool
