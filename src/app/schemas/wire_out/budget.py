import uuid
from datetime import datetime

from pydantic import BaseModel


class BudgetResponse(BaseModel):
    id: uuid.UUID
    name: str
    max_budget: float | None
    soft_budget: float | None
    tpm_limit: int | None
    rpm_limit: int | None
    max_parallel_requests: int | None
    budget_reset_period: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
