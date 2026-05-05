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
)
from app.sdk.exceptions import (
    TimeoutError as SdkTimeoutError,
)
from app.sdk.providers.openai import DEFAULT_API_BASE, OpenAIProvider


def test_get_api_base_default():
    p = OpenAIProvider()
    assert p.get_api_base("gpt-4o", None) == DEFAULT_API_BASE


def test_get_api_base_explicit_override():
    p = OpenAIProvider()
    assert p.get_api_base("gpt-4o", "https://my-proxy/v1") == "https://my-proxy/v1"


def test_get_api_base_strips_trailing_slash():
    p = OpenAIProvider()
    assert p.get_api_base("gpt-4o", "https://my-proxy/v1/") == "https://my-proxy/v1"


def test_get_api_base_env_var(monkeypatch):
    monkeypatch.setenv("OPENAI_API_BASE", "https://env-proxy/v1")
    p = OpenAIProvider()
    assert p.get_api_base("gpt-4o", None) == "https://env-proxy/v1"


def test_get_headers_includes_bearer():
    p = OpenAIProvider()
    headers = p.get_headers("sk-secret", None)
    assert headers["Authorization"] == "Bearer sk-secret"
    assert headers["Content-Type"] == "application/json"


def test_get_headers_merges_extra():
    p = OpenAIProvider()
    headers = p.get_headers("sk-secret", {"X-Trace-Id": "abc"})
    assert headers["X-Trace-Id"] == "abc"
    assert headers["Authorization"] == "Bearer sk-secret"


def test_transform_request_includes_model_and_messages():
    p = OpenAIProvider()
    body = p.transform_request(
        "gpt-4o",
        [{"role": "user", "content": "hi"}],
        {},
    )
    assert body["model"] == "gpt-4o"
    assert body["messages"] == [{"role": "user", "content": "hi"}]


def test_transform_request_forwards_allowlisted_params():
    p = OpenAIProvider()
    body = p.transform_request(
        "gpt-4o",
        [],
        {"temperature": 0.7, "max_tokens": 100, "stream": True},
    )
    assert body["temperature"] == 0.7
    assert body["max_tokens"] == 100
    assert body["stream"] is True


def test_transform_request_drops_none_values():
    p = OpenAIProvider()
    body = p.transform_request(
        "gpt-4o",
        [],
        {"temperature": None, "max_tokens": 10},
    )
    assert "temperature" not in body
    assert body["max_tokens"] == 10


def test_transform_request_drops_unknown_keys():
    p = OpenAIProvider()
    body = p.transform_request(
        "gpt-4o",
        [],
        {"temperature": 0.5, "made_up_param": "x", "cache": True},
    )
    assert "made_up_param" not in body
    assert "cache" not in body
    assert body["temperature"] == 0.5


def test_provider_is_registered():
    """Importing the module side-effects register_provider('openai', ...)."""
    from app.sdk.providers.base import PROVIDER_REGISTRY

    assert PROVIDER_REGISTRY["openai"] is OpenAIProvider


# ---- transform_response ----

def test_transform_response_basic():
    raw = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "gpt-4o-2024-08-06",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }
    p = OpenAIProvider()
    resp = p.transform_response(raw, "gpt-4o")
    assert resp.id == "chatcmpl-1"
    assert resp.created == 1700000000
    assert resp.model == "gpt-4o-2024-08-06"
    assert resp.choices[0].message.content == "ok"
    assert resp.choices[0].finish_reason == "stop"
    assert resp.usage.prompt_tokens == 10
    assert resp.usage.cost is None  # populated by dispatcher, not provider


def test_transform_response_with_tool_calls():
    raw = {
        "id": "chatcmpl-2",
        "created": 1700000001,
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"city":"sf"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }
    p = OpenAIProvider()
    resp = p.transform_response(raw, "gpt-4o")
    msg = resp.choices[0].message
    assert msg.content is None
    assert msg.tool_calls[0].function.name == "get_weather"
    assert msg.tool_calls[0].function.arguments == '{"city":"sf"}'
    assert resp.choices[0].finish_reason == "tool_calls"
    assert resp.usage is None  # absent in raw


def test_transform_response_synthesizes_id_if_missing():
    raw = {
        "created": 1700000000,
        "model": "gpt-4o",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "x"}, "finish_reason": "stop"}
        ],
    }
    p = OpenAIProvider()
    resp = p.transform_response(raw, "gpt-4o")
    assert resp.id.startswith("chatcmpl-")


# ---- transform_stream_chunk ----

def test_transform_stream_chunk_content_delta():
    chunk = {
        "id": "chatcmpl-1",
        "created": 1700000000,
        "model": "gpt-4o",
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hel"}}],
    }
    p = OpenAIProvider()
    parsed = p.transform_stream_chunk(chunk, "gpt-4o")
    assert parsed.choices[0].delta.role == "assistant"
    assert parsed.choices[0].delta.content == "Hel"


def test_transform_stream_chunk_tool_call_delta():
    chunk = {
        "id": "chatcmpl-1",
        "created": 1700000000,
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"ci'},
                        }
                    ]
                },
            }
        ],
    }
    p = OpenAIProvider()
    parsed = p.transform_stream_chunk(chunk, "gpt-4o")
    tc = parsed.choices[0].delta.tool_calls[0]
    assert tc.id == "call_1"
    assert tc.function.name == "get_weather"
    assert tc.function.arguments == '{"ci'  # partial — passthrough


def test_transform_stream_chunk_returns_none_when_no_choices():
    p = OpenAIProvider()
    assert p.transform_stream_chunk({}, "gpt-4o") is None
    assert p.transform_stream_chunk({"id": "x"}, "gpt-4o") is None


def test_transform_stream_chunk_final_chunk_includes_usage():
    chunk = {
        "id": "chatcmpl-1",
        "created": 1700000000,
        "model": "gpt-4o",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }
    p = OpenAIProvider()
    parsed = p.transform_stream_chunk(chunk, "gpt-4o")
    assert parsed.usage.total_tokens == 13


# ---- get_error_class ----

def test_error_401_authentication():
    p = OpenAIProvider()
    err = p.get_error_class(401, {"error": {"message": "bad key"}})
    assert isinstance(err, AuthenticationError)
    assert err.status_code == 401


def test_error_404_not_found():
    p = OpenAIProvider()
    assert isinstance(
        p.get_error_class(404, {"error": {"message": "no such model"}}),
        NotFoundError,
    )


def test_error_408_timeout():
    p = OpenAIProvider()
    assert isinstance(
        p.get_error_class(408, {"error": {"message": "slow"}}),
        SdkTimeoutError,
    )


def test_error_429_rate_limit():
    p = OpenAIProvider()
    assert isinstance(
        p.get_error_class(429, {"error": {"message": "too fast"}}),
        RateLimitError,
    )


def test_error_400_context_length_exceeded():
    p = OpenAIProvider()
    err = p.get_error_class(
        400,
        {"error": {"message": "too long", "code": "context_length_exceeded"}},
    )
    assert isinstance(err, ContextWindowExceededError)


def test_error_400_content_filter():
    p = OpenAIProvider()
    err = p.get_error_class(
        400, {"error": {"message": "bad", "code": "content_filter"}}
    )
    assert isinstance(err, ContentPolicyViolationError)


def test_error_400_generic_bad_request():
    p = OpenAIProvider()
    assert isinstance(
        p.get_error_class(400, {"error": {"message": "nope"}}),
        BadRequestError,
    )


def test_error_503_service_unavailable():
    p = OpenAIProvider()
    assert isinstance(
        p.get_error_class(503, {"error": {"message": "down"}}),
        ServiceUnavailableError,
    )


def test_error_500_internal():
    p = OpenAIProvider()
    assert isinstance(
        p.get_error_class(500, {"error": {"message": "boom"}}),
        InternalServerError,
    )


def test_error_unknown_status_falls_back_to_litellm_error():
    p = OpenAIProvider()
    err = p.get_error_class(418, {"error": {"message": "teapot"}})
    assert type(err) is LiteLLMError
