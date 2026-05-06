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
