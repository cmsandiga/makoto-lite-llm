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
