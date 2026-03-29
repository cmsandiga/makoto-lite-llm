import uuid
from datetime import datetime

from pydantic import BaseModel


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
