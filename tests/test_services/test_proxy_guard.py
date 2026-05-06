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
from app.services.proxy_guard import map_sdk_error


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
