import uuid
from datetime import datetime

from pydantic import BaseModel


class TeamResponse(BaseModel):
    id: uuid.UUID
    name: str
    org_id: uuid.UUID | None
    allowed_models: list | None
    max_budget: float | None
    is_blocked: bool
    created_at: datetime

    model_config = {"from_attributes": True}
