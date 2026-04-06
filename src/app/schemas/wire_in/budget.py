from pydantic import BaseModel


class BudgetCreate(BaseModel):
    name: str
    max_budget: float | None = None
    soft_budget: float | None = None
    tpm_limit: int | None = None
    rpm_limit: int | None = None
    max_parallel_requests: int | None = None
    budget_reset_period: str | None = None


class BudgetUpdate(BaseModel):
    name: str | None = None
    max_budget: float | None = None
    soft_budget: float | None = None
    tpm_limit: int | None = None
    rpm_limit: int | None = None
    max_parallel_requests: int | None = None
    budget_reset_period: str | None = None
