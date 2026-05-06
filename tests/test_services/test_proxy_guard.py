import pytest
from fastapi import HTTPException

from app.config import Settings
from app.schemas.wire_in.chat import ChatMessage
from app.sdk.exceptions import (
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    LiteLLMError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    UnknownProviderError,
)
from app.sdk.exceptions import (
    TimeoutError as SdkTimeoutError,
)
from app.services.proxy_guard import (
    check_rate_limit,
    enforce_model_access,
    estimate_input_tokens,
    map_sdk_error,
    resolve_provider_api_key,
)
from app.services.rate_limiter import SlidingWindowRateLimiter

# ============================================================================
# map_sdk_error
# ============================================================================


def _assert_mapped(exc, expected_status, expected_type, expected_code):
    status, body = map_sdk_error(exc)
    assert status == expected_status
    assert body["error"]["message"] == exc.message
    assert body["error"]["type"] == expected_type
    assert body["error"]["code"] == expected_code


def test_map_authentication_error():
    _assert_mapped(
        AuthenticationError(401, "bad key"),
        401, "invalid_request_error", "invalid_api_key",
    )


def test_map_rate_limit_error():
    _assert_mapped(
        RateLimitError(429, "slow down"),
        429, "rate_limit_error", "rate_limit_exceeded",
    )


def test_map_bad_request_error():
    _assert_mapped(
        BadRequestError(400, "missing field"),
        400, "invalid_request_error", "bad_request",
    )


def test_map_not_found_error():
    _assert_mapped(
        NotFoundError(404, "no such model"),
        404, "invalid_request_error", "model_not_found",
    )


def test_map_context_window_exceeded():
    _assert_mapped(
        ContextWindowExceededError(400, "too long"),
        400, "invalid_request_error", "context_length_exceeded",
    )


def test_map_content_policy_violation():
    _assert_mapped(
        ContentPolicyViolationError(400, "blocked"),
        400, "invalid_request_error", "content_filter",
    )


def test_map_internal_server_error():
    _assert_mapped(
        InternalServerError(500, "boom"),
        502, "api_error", "upstream_error",
    )


def test_map_service_unavailable_error():
    _assert_mapped(
        ServiceUnavailableError(503, "down"),
        503, "api_error", "service_unavailable",
    )


def test_map_timeout_error():
    _assert_mapped(
        SdkTimeoutError(408, "slow"),
        504, "api_error", "timeout",
    )


def test_map_unknown_provider_error():
    _assert_mapped(
        UnknownProviderError(400, "unknown provider 'foo'"),
        400, "invalid_request_error", "model_not_found",
    )


def test_map_litellm_error_fallback():
    """Direct LiteLLMError instances (not subclasses) → 500 unknown_error."""
    _assert_mapped(
        LiteLLMError(418, "teapot"),
        500, "api_error", "unknown_error",
    )


# ============================================================================
# enforce_model_access
# ============================================================================


class _Stub:
    """Minimal stand-in for ApiKey/Team/Org with allowed_models."""

    def __init__(self, allowed_models=None):
        self.allowed_models = allowed_models


def test_enforce_model_access_allowed():
    api_key = _Stub(allowed_models=["openai/gpt-4o-mini"])
    enforce_model_access("openai/gpt-4o-mini", api_key, None, None)


def test_enforce_model_access_denied_raises_403():
    api_key = _Stub(allowed_models=["openai/gpt-4o-mini"])
    with pytest.raises(HTTPException) as exc_info:
        enforce_model_access("openai/gpt-4o", api_key, None, None)
    assert exc_info.value.status_code == 403
    assert "openai/gpt-4o" in exc_info.value.detail


# ============================================================================
# resolve_provider_api_key
# ============================================================================


def test_resolve_openai_key():
    s = Settings(openai_api_key="sk-test-openai")
    assert resolve_provider_api_key("openai", s) == "sk-test-openai"


def test_resolve_anthropic_key():
    s = Settings(anthropic_api_key="sk-ant-test")
    assert resolve_provider_api_key("anthropic", s) == "sk-ant-test"


def test_resolve_missing_key_raises_503():
    s = Settings(openai_api_key=None, anthropic_api_key=None)
    with pytest.raises(HTTPException) as exc_info:
        resolve_provider_api_key("openai", s)
    assert exc_info.value.status_code == 503
    assert "openai" in exc_info.value.detail.lower()


# ============================================================================
# estimate_input_tokens
# ============================================================================


def test_estimate_input_tokens_basic():
    short = [ChatMessage(role="user", content="hi")]
    long = [ChatMessage(role="user", content="x" * 4000)]
    short_estimate = estimate_input_tokens(short)
    long_estimate = estimate_input_tokens(long)
    assert short_estimate >= 1
    assert long_estimate > short_estimate
    # Order of magnitude: ~4000 chars ≈ ~1000 tokens (chars/4 heuristic)
    assert long_estimate >= 800


# ============================================================================
# check_rate_limit
# ============================================================================


class _ApiKeyStub:
    def __init__(self, api_key_hash="hash1", rpm_limit=None, tpm_limit=None):
        self.api_key_hash = api_key_hash
        self.rpm_limit = rpm_limit
        self.tpm_limit = tpm_limit


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Each test gets a fresh limiter so windows don't bleed across tests."""
    from app.services import proxy_guard

    proxy_guard._rate_limiter = SlidingWindowRateLimiter()
    yield
    proxy_guard._rate_limiter = SlidingWindowRateLimiter()


async def test_check_rate_limit_no_limits_no_op():
    """ApiKey with rpm_limit=None and tpm_limit=None passes immediately."""
    api_key = _ApiKeyStub(rpm_limit=None, tpm_limit=None)
    await check_rate_limit(api_key, estimated_tokens=100)


async def test_check_rate_limit_rpm_allows():
    api_key = _ApiKeyStub(rpm_limit=5, tpm_limit=None)
    await check_rate_limit(api_key, estimated_tokens=10)


async def test_check_rate_limit_rpm_exceeded_raises_429():
    api_key = _ApiKeyStub(rpm_limit=2, tpm_limit=None)
    await check_rate_limit(api_key, estimated_tokens=1)
    await check_rate_limit(api_key, estimated_tokens=1)
    with pytest.raises(HTTPException) as exc_info:
        await check_rate_limit(api_key, estimated_tokens=1)
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


async def test_check_rate_limit_tpm_exceeded_raises_429():
    api_key = _ApiKeyStub(rpm_limit=None, tpm_limit=100)
    await check_rate_limit(api_key, estimated_tokens=50)
    with pytest.raises(HTTPException) as exc_info:
        await check_rate_limit(api_key, estimated_tokens=60)
    assert exc_info.value.status_code == 429


# ============================================================================
# check_budget (requires running Postgres testcontainer — Docker/Colima)
# ============================================================================

from datetime import date  # noqa: E402

from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402
from uuid_extensions import uuid7  # noqa: E402

from app.models.spend import DailyKeySpend  # noqa: E402
from app.services.proxy_guard import check_budget  # noqa: E402


class _ApiKeyWithBudget:
    """Lightweight fake of ApiKey that exposes only the fields check_budget reads."""

    def __init__(self, api_key_hash="hash1", max_budget=None):
        self.api_key_hash = api_key_hash
        self.max_budget = max_budget


async def _seed_daily_spend(
    db: AsyncSession, api_key_hash: str, spent: float, model: str = "openai/gpt-4o-mini"
):
    row = DailyKeySpend(
        id=uuid7(),
        api_key_hash=api_key_hash,
        date=date.today(),
        model=model,
        total_spend=spent,
        total_input_tokens=0,
        total_output_tokens=0,
        request_count=1,
    )
    db.add(row)
    await db.commit()


async def test_check_budget_no_max_budget_no_op(db_session: AsyncSession):
    api_key = _ApiKeyWithBudget(max_budget=None)
    await check_budget(db_session, api_key)


async def test_check_budget_under_budget_allows(db_session: AsyncSession):
    api_key = _ApiKeyWithBudget(api_key_hash="hashU", max_budget=0.10)
    await _seed_daily_spend(db_session, "hashU", spent=0.05)
    await check_budget(db_session, api_key)


async def test_check_budget_over_budget_raises_429(db_session: AsyncSession):
    api_key = _ApiKeyWithBudget(api_key_hash="hashO", max_budget=0.10)
    await _seed_daily_spend(db_session, "hashO", spent=0.15)
    with pytest.raises(HTTPException) as exc_info:
        await check_budget(db_session, api_key)
    assert exc_info.value.status_code == 429
    assert "0.15" in exc_info.value.detail or "0.1500" in exc_info.value.detail
