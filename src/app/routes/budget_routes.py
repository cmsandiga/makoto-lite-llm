import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.user import User
from app.schemas.wire_in.budget import BudgetCreate, BudgetUpdate
from app.schemas.wire_out.budget import BudgetResponse
from app.services.budget_service import (
    create_budget,
    delete_budget,
    get_budget,
    list_budgets,
    update_budget,
)

router = APIRouter(prefix="/budgets", tags=["budgets"])


# ========== POST /budgets — create ==========


@router.post("", status_code=201)
async def create(
    body: BudgetCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> BudgetResponse:
    budget = await create_budget(
        db,
        name=body.name,
        max_budget=body.max_budget,
        soft_budget=body.soft_budget,
        tpm_limit=body.tpm_limit,
        rpm_limit=body.rpm_limit,
        max_parallel_requests=body.max_parallel_requests,
        budget_reset_period=body.budget_reset_period,
    )
    return BudgetResponse.model_validate(budget)


# ========== GET /budgets — list ==========


@router.get("")
async def list_all(
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> list[BudgetResponse]:
    budgets = await list_budgets(db, page, page_size)
    return [BudgetResponse.model_validate(b) for b in budgets]


# ========== PATCH /budgets/{budget_id} — update ==========


@router.patch("/{budget_id}")
async def update(
    budget_id: uuid.UUID,
    body: BudgetUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> BudgetResponse:
    budget = await update_budget(
        db,
        budget_id,
        name=body.name,
        max_budget=body.max_budget,
        soft_budget=body.soft_budget,
        tpm_limit=body.tpm_limit,
        rpm_limit=body.rpm_limit,
        max_parallel_requests=body.max_parallel_requests,
        budget_reset_period=body.budget_reset_period,
    )
    if budget is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    return BudgetResponse.model_validate(budget)


# ========== DELETE /budgets/{budget_id} — delete ==========


@router.delete("/{budget_id}", status_code=204)
async def delete(
    budget_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
):
    success = await delete_budget(db, budget_id)
    if not success:
        raise HTTPException(status_code=404, detail="Budget not found")
