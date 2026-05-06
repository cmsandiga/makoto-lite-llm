import json

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
from app.services.permission_service import resolve_model_access


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
