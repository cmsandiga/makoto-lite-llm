import uuid
from datetime import datetime

from pydantic import BaseModel


class OrgResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    max_budget: float | None
    is_blocked: bool
    created_at: datetime

    model_config = {"from_attributes": True}
