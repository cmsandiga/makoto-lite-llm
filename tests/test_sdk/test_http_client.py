import httpx
import pytest
import respx

from app.sdk.http_client import (
    LLMHttpClient,
    _StreamingHTTPError,
    get_http_client,
)


@pytest.fixture
def client():
    return LLMHttpClient(default_timeout=5.0)


@respx.mock
async def test_post_returns_status_and_body(client):
    respx.post("https://api.example.com/v1/foo").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    status, body = await client.post(
        "https://api.example.com/v1",
        "sk-test",
        "/foo",
        {"Authorization": "Bearer sk-test"},
        {"input": "x"},
    )
    assert status == 200
    assert body == {"ok": True}


@respx.mock
async def test_post_returns_text_when_not_json(client):
    respx.post("https://api.example.com/v1/foo").mock(
        return_value=httpx.Response(500, text="upstream broke")
    )
    status, body = await client.post(
        "https://api.example.com/v1", "k", "/foo", {}, {}
    )
    assert status == 500
    assert body == {"error": {"message": "upstream broke"}}


async def test_get_client_reuses_per_base_and_key(client):
    c1 = await client._get_client("https://api.example.com", "key1")
    c2 = await client._get_client("https://api.example.com", "key1")
    assert c1 is c2


async def test_get_client_different_keys_get_different_clients(client):
    c1 = await client._get_client("https://api.example.com", "key1")
    c2 = await client._get_client("https://api.example.com", "key2")
    assert c1 is not c2


@respx.mock
async def test_post_stream_filters_done_and_blanks(client):
    body = (
        b'data: {"id":"1","created":1,"model":"gpt-4o",'
        b'"choices":[{"index":0,"delta":{"content":"a"}}]}\n\n'
        b"\n"
        b'data: {"id":"1","created":1,"model":"gpt-4o",'
        b'"choices":[{"index":0,"delta":{"content":"b"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )
    )

    chunks = []
    async for chunk in client.post_stream(
        "https://api.example.com/v1", "k", "/chat/completions", {}, {}
    ):
        chunks.append(chunk)
    assert len(chunks) == 2
    assert chunks[0]["choices"][0]["delta"]["content"] == "a"
    assert chunks[1]["choices"][0]["delta"]["content"] == "b"


@respx.mock
async def test_post_stream_4xx_raises_streaming_http_error(client):
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            429,
            json={"error": {"message": "too fast", "code": "rate_limit_exceeded"}},
        )
    )

    with pytest.raises(_StreamingHTTPError) as exc_info:
        async for _ in client.post_stream(
            "https://api.example.com/v1", "k", "/chat/completions", {}, {}
        ):
            pass
    assert exc_info.value.status_code == 429
    assert exc_info.value.body["error"]["message"] == "too fast"


def test_get_http_client_returns_singleton():
    a = get_http_client()
    b = get_http_client()
    assert a is b
