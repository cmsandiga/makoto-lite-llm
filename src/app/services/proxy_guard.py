import json
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.spend import DailyKeySpend
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
from app.services.permission_service import resolve_model_access
from app.services.rate_limiter import SlidingWindowRateLimiter

_rate_limiter: SlidingWindowRateLimiter = SlidingWindowRateLimiter()


def get_rate_limiter() -> SlidingWindowRateLimiter:
    """Return the singleton sliding-window rate limiter.

    Tests reset _rate_limiter directly to isolate windows.
    """
    return _rate_limiter


def map_sdk_error(exc: LiteLLMError) -> tuple[int, dict]:
    """Translate an SDK exception into (HTTP status, OpenAI-shape error body).

    The route catches LiteLLMError, calls this, and raises HTTPException
    with the mapped status + body. The exception handler in main.py wraps
    the detail in {"error": ...} for /v1/* paths.
    """
    cls = type(exc)
    if cls is AuthenticationError:
        status, etype, code = 401, "invalid_request_error", "invalid_api_key"
    elif cls is RateLimitError:
        status, etype, code = 429, "rate_limit_error", "rate_limit_exceeded"
    elif cls is BadRequestError:
        status, etype, code = 400, "invalid_request_error", "bad_request"
    elif cls is NotFoundError:
        status, etype, code = 404, "invalid_request_error", "model_not_found"
    elif cls is ContextWindowExceededError:
        status, etype, code = 400, "invalid_request_error", "context_length_exceeded"
    elif cls is ContentPolicyViolationError:
        status, etype, code = 400, "invalid_request_error", "content_filter"
    elif cls is InternalServerError:
        status, etype, code = 502, "api_error", "upstream_error"
    elif cls is ServiceUnavailableError:
        status, etype, code = 503, "api_error", "service_unavailable"
    elif cls is SdkTimeoutError:
        status, etype, code = 504, "api_error", "timeout"
    elif cls is UnknownProviderError:
        status, etype, code = 400, "invalid_request_error", "model_not_found"
    else:
        # LiteLLMError or any other subclass — fallback
        status, etype, code = 500, "api_error", "unknown_error"

    return status, {
        "error": {
            "message": exc.message,
            "type": etype,
            "code": code,
        }
    }


def enforce_model_access(model: str, api_key, team, org) -> None:
    """Raise HTTPException(403) if the model is not in any allowlist.

    Empty allowlists (None) are treated as "no restriction" by
    resolve_model_access. proxy_admin bypass is handled by the route's
    auth dep, not here — this function purely checks the allowlists.
    """
    key_models = api_key.allowed_models if api_key else None
    team_models = team.allowed_models if team else None
    org_models = org.allowed_models if org else None

    if not resolve_model_access(model, key_models, team_models, org_models):
        raise HTTPException(
            status_code=403,
            detail=f"Model '{model}' is not allowed for this key",
        )


def resolve_provider_api_key(provider_name: str, settings: Settings) -> str:
    """Read the upstream provider's API key from server config.

    Per ola-14 design, provider keys live in env vars only (no per-org keys
    in this ola). Raises 503 if the env var for this provider is unset —
    a configuration error on the proxy, not the client's fault.
    """
    if provider_name == "openai":
        key = settings.openai_api_key
    elif provider_name == "anthropic":
        key = settings.anthropic_api_key
    else:
        raise HTTPException(
            status_code=503,
            detail=f"Provider '{provider_name}' is not configured on this proxy",
        )

    if key is None:
        raise HTTPException(
            status_code=503,
            detail=f"Provider '{provider_name}' is not configured on this proxy",
        )
    return key


def estimate_input_tokens(messages: list[ChatMessage]) -> int:
    """Coarse pre-call estimate: roughly chars/4.

    Used only for TPM rate-limit reservation — the real token count from
    the upstream response replaces this estimate when log_spend writes
    the SpendLog row. Under-estimates for code/non-Latin text.

    TODO(future-ola): replace with tiktoken-based counting for accuracy.
    """
    serialized = json.dumps([m.model_dump() for m in messages])
    return max(1, len(serialized) // 4)


async def check_rate_limit(api_key, estimated_tokens: int) -> None:
    """Enforce RPM and TPM limits on the given ApiKey.

    Raises HTTPException(429) with Retry-After header on the first
    exceeded limit. Order: RPM check, then TPM check.

    Scope: key-level only. Team and org limits are documented on the model
    but not enforced here; precedence rule is a future-ola decision.
    """
    limiter = get_rate_limiter()

    if api_key.rpm_limit is not None:
        result = await limiter.check_rate_limit(
            f"rpm:{api_key.api_key_hash}",
            api_key.rpm_limit,
            window_seconds=60,
        )
        if not result.allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded (RPM)",
                headers={"Retry-After": str(int(result.retry_after) + 1)},
            )

    if api_key.tpm_limit is not None:
        result = await limiter.check_rate_limit(
            f"tpm:{api_key.api_key_hash}",
            api_key.tpm_limit,
            window_seconds=60,
            increment=estimated_tokens,
        )
        if not result.allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded (TPM)",
                headers={"Retry-After": str(int(result.retry_after) + 1)},
            )


async def check_budget(db: AsyncSession, api_key) -> None:
    """Enforce daily budget against spend recorded in DailyKeySpend.

    Reads the sum of today's spend rows for this API key (across models)
    and compares to api_key.max_budget. Raises HTTPException(429) on exceed.

    Scope: key-level only. Team/org budgets deferred to a future ola.
    Race condition: spend updates lag the request, so a key can briefly
    overspend by one or two requests under concurrency. Documented in spec.
    """
    if api_key.max_budget is None:
        return

    today = date.today()
    result = await db.execute(
        select(DailyKeySpend.total_spend).where(
            DailyKeySpend.api_key_hash == api_key.api_key_hash,
            DailyKeySpend.date == today,
        )
    )
    rows = result.scalars().all()
    spent_today = sum(rows) if rows else 0.0

    if spent_today >= api_key.max_budget:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily budget exceeded: ${spent_today:.4f} / ${api_key.max_budget}"
            ),
        )
