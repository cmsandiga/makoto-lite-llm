import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import Budget


# ========== Create ==========


async def create_budget(
    db: AsyncSession,
    name: str,
    max_budget: float | None = None,
    soft_budget: float | None = None,
    tpm_limit: int | None = None,
    rpm_limit: int | None = None,
    max_parallel_requests: int | None = None,
    budget_reset_period: str | None = None,
) -> Budget:
    budget = Budget(
        name=name,
        max_budget=max_budget,
        soft_budget=soft_budget,
        tpm_limit=tpm_limit,
        rpm_limit=rpm_limit,
        max_parallel_requests=max_parallel_requests,
        budget_reset_period=budget_reset_period,
    )
    db.add(budget)
    await db.commit()
    await db.refresh(budget)
    return budget


# ========== Read ==========


async def get_budget(db: AsyncSession, budget_id: uuid.UUID) -> Budget | None:
    result = await db.execute(select(Budget).where(Budget.id == budget_id))
    return result.scalar_one_or_none()


async def list_budgets(
    db: AsyncSession, page: int = 1, page_size: int = 50
) -> list[Budget]:
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Budget).order_by(Budget.created_at.desc()).offset(offset).limit(page_size)
    )
    return list(result.scalars().all())


# ========== Update ==========


async def update_budget(
    db: AsyncSession,
    budget_id: uuid.UUID,
    name: str | None = None,
    max_budget: float | None = None,
    soft_budget: float | None = None,
    tpm_limit: int | None = None,
    rpm_limit: int | None = None,
    max_parallel_requests: int | None = None,
    budget_reset_period: str | None = None,
) -> Budget | None:
    budget = await get_budget(db, budget_id)
    if budget is None:
        return None
    if name is not None:
        budget.name = name
    if max_budget is not None:
        budget.max_budget = max_budget
    if soft_budget is not None:
        budget.soft_budget = soft_budget
    if tpm_limit is not None:
        budget.tpm_limit = tpm_limit
    if rpm_limit is not None:
        budget.rpm_limit = rpm_limit
    if max_parallel_requests is not None:
        budget.max_parallel_requests = max_parallel_requests
    if budget_reset_period is not None:
        budget.budget_reset_period = budget_reset_period
    await db.commit()
    await db.refresh(budget)
    return budget


# ========== Delete ==========


async def delete_budget(db: AsyncSession, budget_id: uuid.UUID) -> bool:
    budget = await get_budget(db, budget_id)
    if budget is None:
        return False
    await db.delete(budget)
    await db.commit()
    return True
