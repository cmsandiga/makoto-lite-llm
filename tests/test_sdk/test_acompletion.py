import httpx
import pytest
import respx

from app.sdk import http_client as http_client_module
from app.sdk.exceptions import AuthenticationError, RateLimitError
from app.sdk.main import acompletion
from app.sdk.types import ModelResponse, ModelResponseStream, StreamWrapper


@pytest.fixture(autouse=True)
def _reset_http_client_singleton():
    """Each test gets a fresh LLMHttpClient so respx mocks don't bleed."""
    http_client_module._default_client = None
    yield
    http_client_module._default_client = None


@respx.mock
async def test_acompletion_happy_path():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "created": 1700000000,
                "model": "gpt-4o-mini-2024-07-18",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 1,
                    "total_tokens": 11,
                },
            },
        )
    )

    resp = await acompletion(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-test",
    )
    assert isinstance(resp, ModelResponse)
    assert resp.choices[0].message.content == "ok"
    assert resp.usage.cost is not None
    assert resp.usage.cost == pytest.approx(
        10 * 1.5e-7 + 1 * 6.0e-7, rel=1e-9
    )


@respx.mock
async def test_acompletion_unknown_model_cost_is_none():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-2",
                "created": 1700000000,
                "model": "openai/imaginary",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 1,
                    "total_tokens": 6,
                },
            },
        )
    )
    resp = await acompletion(
        model="openai/imaginary",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-test",
    )
    assert resp.usage.cost is None


async def test_acompletion_missing_api_key_and_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(AuthenticationError, match="No api_key"):
        await acompletion(
            model="openai/gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        )


async def test_acompletion_uses_env_key_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "x",
                    "created": 1,
                    "model": "gpt-4o",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        )
        await acompletion(
            model="openai/gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        )
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-from-env"


@respx.mock
async def test_acompletion_429_maps_to_rate_limit_error():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            429, json={"error": {"message": "slow down"}}
        )
    )
    with pytest.raises(RateLimitError):
        await acompletion(
            model="openai/gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            api_key="sk-test",
        )


@respx.mock
async def test_acompletion_stream_returns_wrapper():
    body = (
        b'data: {"id":"c1","created":1,"model":"gpt-4o",'
        b'"choices":[{"index":0,"delta":'
        b'{"role":"assistant","content":"He"}}]}\n\n'
        b'data: {"id":"c1","created":1,"model":"gpt-4o",'
        b'"choices":[{"index":0,"delta":{"content":"llo"},'
        b'"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )
    )

    result = await acompletion(
        model="openai/gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-test",
        stream=True,
    )
    assert isinstance(result, StreamWrapper)

    chunks: list[ModelResponseStream] = []
    async for chunk in result:
        chunks.append(chunk)
    assert len(chunks) == 2
    assert chunks[0].choices[0].delta.content == "He"
    assert chunks[1].choices[0].delta.content == "llo"
    assert chunks[1].choices[0].finish_reason == "stop"


@respx.mock
async def test_acompletion_stream_429_raises_on_first_anext():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            429, json={"error": {"message": "slow"}}
        )
    )

    result = await acompletion(
        model="openai/gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-test",
        stream=True,
    )
    with pytest.raises(RateLimitError):
        async for _ in result:
            pass
