# tests/test_services/test_spend_service.py
import pytest
from uuid_extensions import uuid7
from sqlalchemy import select

from app.models.spend import DailyKeySpend, DailyUserSpend, SpendLog
from app.services.spend_service import log_spend


async def test_log_spend_creates_spend_log(db_session):
    """log_spend creates a SpendLog row."""
    await log_spend(
        db=db_session,
        request_id="req-001",
        api_key_hash="abc123",
        user_id=uuid7(),
        model="gpt-4",
        provider="openai",
        input_tokens=100,
        output_tokens=50,
        spend=0.05,
        status="success",
        response_time_ms=200,
    )

    result = await db_session.execute(
        select(SpendLog).where(SpendLog.request_id == "req-001")
    )
    log = result.scalar_one()
    assert log.model == "gpt-4"
    assert log.spend == 0.05
    assert log.input_tokens == 100


async def test_log_spend_upserts_daily_user(db_session):
    """log_spend upserts the daily_user_spend aggregate."""
    user_id = uuid7()
    await log_spend(
        db=db_session,
        request_id="req-002",
        api_key_hash="abc123",
        user_id=user_id,
        model="gpt-4",
        provider="openai",
        input_tokens=100,
        output_tokens=50,
        spend=0.05,
        status="success",
        response_time_ms=200,
    )
    await log_spend(
        db=db_session,
        request_id="req-003",
        api_key_hash="abc123",
        user_id=user_id,
        model="gpt-4",
        provider="openai",
        input_tokens=200,
        output_tokens=100,
        spend=0.10,
        status="success",
        response_time_ms=300,
    )

    result = await db_session.execute(
        select(DailyUserSpend).where(DailyUserSpend.user_id == user_id)
    )
    daily = result.scalar_one()
    assert daily.total_spend == pytest.approx(0.15)
    assert daily.total_input_tokens == 300
    assert daily.total_output_tokens == 150
    assert daily.request_count == 2


async def test_log_spend_upserts_daily_key(db_session):
    """log_spend upserts the daily_key_spend aggregate."""
    key_hash = "keyhash123"
    await log_spend(
        db=db_session,
        request_id="req-004",
        api_key_hash=key_hash,
        model="claude-3",
        provider="anthropic",
        input_tokens=50,
        output_tokens=25,
        spend=0.02,
        status="success",
        response_time_ms=150,
    )

    result = await db_session.execute(
        select(DailyKeySpend).where(DailyKeySpend.api_key_hash == key_hash)
    )
    daily = result.scalar_one()
    assert daily.total_spend == 0.02
    assert daily.request_count == 1


async def test_log_spend_optional_fields(db_session):
    """log_spend works with minimal required fields (no user_id/team_id/org_id)."""
    await log_spend(
        db=db_session,
        request_id="req-005",
        api_key_hash="min123",
        model="gpt-4",
        provider="openai",
        input_tokens=10,
        output_tokens=5,
        spend=0.001,
        status="success",
        response_time_ms=100,
    )

    result = await db_session.execute(
        select(SpendLog).where(SpendLog.request_id == "req-005")
    )
    log = result.scalar_one()
    assert log.user_id is None
    assert log.team_id is None
