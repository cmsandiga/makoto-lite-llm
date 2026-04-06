# src/app/services/spend_service.py
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.spend import (
    DailyKeySpend,
    DailyOrgSpend,
    DailyTeamSpend,
    DailyUserSpend,
    SpendLog,
)


async def log_spend(
    db: AsyncSession,
    request_id: str,
    api_key_hash: str,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    spend: float,
    status: str,
    response_time_ms: int,
    user_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    cache_hit: bool = False,
) -> SpendLog:
    """Log a single LLM request and update daily aggregates.

    Creates a SpendLog row and upserts the relevant daily aggregate tables.
    """
    # Create spend log
    log = SpendLog(
        request_id=request_id,
        api_key_hash=api_key_hash,
        user_id=user_id,
        team_id=team_id,
        org_id=org_id,
        project_id=project_id,
        model=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        spend=spend,
        cache_hit=cache_hit,
        status=status,
        response_time_ms=response_time_ms,
    )
    db.add(log)

    today = date.today()

    # Upsert daily aggregates for each relevant entity
    await _upsert_daily_key(db, api_key_hash, model, today, spend, input_tokens, output_tokens)

    if user_id:
        await _upsert_daily_user(db, user_id, model, today, spend, input_tokens, output_tokens)

    if team_id:
        await _upsert_daily_team(db, team_id, model, today, spend, input_tokens, output_tokens)

    if org_id:
        await _upsert_daily_org(db, org_id, model, today, spend, input_tokens, output_tokens)

    await db.commit()
    await db.refresh(log)
    return log


async def _upsert_daily_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    model: str,
    today: date,
    spend: float,
    input_tokens: int,
    output_tokens: int,
) -> None:
    result = await db.execute(
        select(DailyUserSpend).where(
            DailyUserSpend.user_id == user_id,
            DailyUserSpend.model == model,
            DailyUserSpend.date == today,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        row.total_spend += spend
        row.total_input_tokens += input_tokens
        row.total_output_tokens += output_tokens
        row.request_count += 1
    else:
        db.add(DailyUserSpend(
            user_id=user_id, model=model, date=today,
            total_spend=spend, total_input_tokens=input_tokens,
            total_output_tokens=output_tokens, request_count=1,
        ))


async def _upsert_daily_team(
    db: AsyncSession,
    team_id: uuid.UUID,
    model: str,
    today: date,
    spend: float,
    input_tokens: int,
    output_tokens: int,
) -> None:
    result = await db.execute(
        select(DailyTeamSpend).where(
            DailyTeamSpend.team_id == team_id,
            DailyTeamSpend.model == model,
            DailyTeamSpend.date == today,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        row.total_spend += spend
        row.total_input_tokens += input_tokens
        row.total_output_tokens += output_tokens
        row.request_count += 1
    else:
        db.add(DailyTeamSpend(
            team_id=team_id, model=model, date=today,
            total_spend=spend, total_input_tokens=input_tokens,
            total_output_tokens=output_tokens, request_count=1,
        ))


async def _upsert_daily_org(
    db: AsyncSession,
    org_id: uuid.UUID,
    model: str,
    today: date,
    spend: float,
    input_tokens: int,
    output_tokens: int,
) -> None:
    result = await db.execute(
        select(DailyOrgSpend).where(
            DailyOrgSpend.org_id == org_id,
            DailyOrgSpend.model == model,
            DailyOrgSpend.date == today,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        row.total_spend += spend
        row.total_input_tokens += input_tokens
        row.total_output_tokens += output_tokens
        row.request_count += 1
    else:
        db.add(DailyOrgSpend(
            org_id=org_id, model=model, date=today,
            total_spend=spend, total_input_tokens=input_tokens,
            total_output_tokens=output_tokens, request_count=1,
        ))


async def _upsert_daily_key(
    db: AsyncSession,
    api_key_hash: str,
    model: str,
    today: date,
    spend: float,
    input_tokens: int,
    output_tokens: int,
) -> None:
    result = await db.execute(
        select(DailyKeySpend).where(
            DailyKeySpend.api_key_hash == api_key_hash,
            DailyKeySpend.model == model,
            DailyKeySpend.date == today,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        row.total_spend += spend
        row.total_input_tokens += input_tokens
        row.total_output_tokens += output_tokens
        row.request_count += 1
    else:
        db.add(DailyKeySpend(
            api_key_hash=api_key_hash, model=model, date=today,
            total_spend=spend, total_input_tokens=input_tokens,
            total_output_tokens=output_tokens, request_count=1,
        ))
