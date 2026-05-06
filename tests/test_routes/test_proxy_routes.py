from datetime import date

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7

from app.auth.api_key_auth import generate_api_key, get_key_prefix, hash_api_key
from app.auth.dependencies import _api_key_cache
from app.config import settings
from app.models.api_key import ApiKey
from app.models.spend import DailyKeySpend, SpendLog
from app.models.user import User
from app.sdk import http_client as sdk_http_client


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset SDK pooled client + rate limiter singletons + auth cache between tests."""
    sdk_http_client._default_client = None
    _api_key_cache.clear()
    from app.services import proxy_guard
    from app.services.rate_limiter import SlidingWindowRateLimiter

    proxy_guard._rate_limiter = SlidingWindowRateLimiter()
    yield
    sdk_http_client._default_client = None
    _api_key_cache.clear()
    proxy_guard._rate_limiter = SlidingWindowRateLimiter()


@pytest.fixture
async def proxy_user(db_session: AsyncSession):
    user = User(email="proxy-tester@test.com", role="member")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def proxy_key(db_session: AsyncSession, proxy_user: User):
    """An ApiKey with no rate-limit/budget restrictions."""
    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=proxy_user.id,
    )
    db_session.add(api_key)
    await db_session.commit()
    return raw_key, api_key


@pytest.fixture
def openai_key_set(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-openai")


@respx.mock
async def test_chat_completion_happy_path_openai(
    client, proxy_key, openai_key_set, db_session
):
    raw_key, api_key = proxy_key
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

    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "ok"
    assert body["usage"]["prompt_tokens"] == 10
    assert body["usage"]["cost"] is not None
    assert body["usage"]["cost"] > 0

    result = await db_session.execute(
        select(SpendLog).where(SpendLog.api_key_hash == api_key.api_key_hash)
    )
    log = result.scalar_one()
    assert log.status == "completed"
    assert log.input_tokens == 10
    assert log.output_tokens == 1
    assert log.spend > 0


async def test_chat_completion_missing_authorization(client):
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["type"] == "api_error"


async def test_chat_completion_invalid_api_key(client):
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": "Bearer sk-not-a-real-key"},
    )
    assert resp.status_code == 401


async def test_chat_completion_blocked_key(client, db_session, proxy_user):
    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=proxy_user.id,
        is_blocked=True,
    )
    db_session.add(api_key)
    await db_session.commit()

    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 401


async def test_chat_completion_model_not_in_allowlist(
    client, db_session, proxy_user, openai_key_set
):
    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=proxy_user.id,
        allowed_models=["openai/gpt-4o-mini"],
    )
    db_session.add(api_key)
    await db_session.commit()

    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403
    assert "openai/gpt-4o" in resp.json()["error"]["message"]


@respx.mock
async def test_chat_completion_rpm_exceeded(
    client, db_session, proxy_user, openai_key_set
):
    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=proxy_user.id,
        rpm_limit=1,
    )
    db_session.add(api_key)
    await db_session.commit()

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "x",
                "created": 1,
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )
    )
    # First call passes
    resp1 = await client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp1.status_code == 200
    # Second call same minute -> 429
    resp2 = await client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp2.status_code == 429
    assert "Retry-After" in resp2.headers


async def test_chat_completion_budget_exceeded(
    client, db_session, proxy_user, openai_key_set
):
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)
    api_key = ApiKey(
        api_key_hash=key_hash,
        key_prefix=get_key_prefix(raw_key),
        user_id=proxy_user.id,
        max_budget=0.01,
    )
    db_session.add(api_key)
    spend_row = DailyKeySpend(
        id=uuid7(),
        api_key_hash=key_hash,
        date=date.today(),
        model="openai/gpt-4o-mini",
        total_spend=0.015,
        total_input_tokens=0,
        total_output_tokens=0,
        request_count=1,
    )
    db_session.add(spend_row)
    await db_session.commit()

    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 429
    assert "budget" in resp.json()["error"]["message"].lower()


async def test_chat_completion_provider_key_missing(
    client, proxy_key, monkeypatch
):
    """Anthropic key not configured -> 503."""
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    raw_key, _ = proxy_key
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "anthropic/claude-haiku-4-5-20251001",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 503


async def test_chat_completion_empty_messages_422(client, proxy_key, openai_key_set):
    raw_key, _ = proxy_key
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "openai/gpt-4o-mini", "messages": []},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


async def test_chat_completion_missing_model_422(client, proxy_key, openai_key_set):
    raw_key, _ = proxy_key
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


@respx.mock
async def test_chat_completion_anthropic_happy_path(
    client, proxy_key, monkeypatch, db_session
):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    raw_key, _ = proxy_key
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-4-5-20251001",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 1},
            },
        )
    )
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "anthropic/claude-haiku-4-5-20251001",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "ok"
    assert body["usage"]["prompt_tokens"] == 10


@respx.mock
async def test_chat_completion_request_id_header(
    client, proxy_key, openai_key_set, db_session
):
    raw_key, _ = proxy_key
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "x",
                "created": 1,
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )
    )
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    request_id = resp.headers.get("X-Request-Id")
    assert request_id is not None

    result = await db_session.execute(
        select(SpendLog).where(SpendLog.request_id == request_id)
    )
    assert result.scalar_one() is not None


@respx.mock
async def test_chat_completion_streaming_openai(
    client, proxy_key, openai_key_set, db_session
):
    """Stream from OpenAI: assert SSE chunks are emitted and spend logged."""
    raw_key, api_key = proxy_key
    body_bytes = (
        b'data: {"id":"c1","created":1,"model":"gpt-4o-mini","choices":'
        b'[{"index":0,"delta":{"role":"assistant","content":"He"}}]}\n\n'
        b'data: {"id":"c1","created":1,"model":"gpt-4o-mini","choices":'
        b'[{"index":0,"delta":{"content":"llo"},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":5,"completion_tokens":2,"total_tokens":7}}\n\n'
        b'data: [DONE]\n\n'
    )
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body_bytes, headers={"content-type": "text/event-stream"}
        )
    )

    async with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        events = [line async for line in resp.aiter_lines()]

    data_lines = [e for e in events if e.startswith("data:")]
    assert len(data_lines) >= 3
    assert data_lines[-1].strip() == "data: [DONE]"

    result = await db_session.execute(
        select(SpendLog).where(SpendLog.api_key_hash == api_key.api_key_hash)
    )
    log = result.scalar_one()
    assert log.input_tokens == 5
    assert log.output_tokens == 2
    assert log.status == "completed"


@respx.mock
async def test_chat_completion_streaming_anthropic(
    client, proxy_key, monkeypatch, db_session
):
    """Stream from Anthropic: SSE events with both 'event:' and 'data:' lines."""
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    raw_key, _ = proxy_key
    body_bytes = (
        b'event: message_start\n'
        b'data: {"type":"message_start","message":'
        b'{"id":"msg_1","model":"claude-haiku-4-5-20251001",'
        b'"usage":{"input_tokens":5,"output_tokens":0}}}\n\n'
        b'event: content_block_delta\n'
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":"He"}}\n\n'
        b'event: content_block_delta\n'
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":"llo"}}\n\n'
        b'event: message_delta\n'
        b'data: {"type":"message_delta",'
        b'"delta":{"stop_reason":"end_turn"},'
        b'"usage":{"output_tokens":3}}\n\n'
        b'event: message_stop\n'
        b'data: {"type":"message_stop"}\n\n'
    )
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200, content=body_bytes, headers={"content-type": "text/event-stream"}
        )
    )

    async with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "anthropic/claude-haiku-4-5-20251001",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    ) as resp:
        assert resp.status_code == 200
        events = [line async for line in resp.aiter_lines()]

    data_lines = [e for e in events if e.startswith("data:")]
    assert len(data_lines) >= 3
    assert data_lines[-1].strip() == "data: [DONE]"


@respx.mock
async def test_chat_completion_streaming_partial_log_on_no_finish(
    client, proxy_key, openai_key_set, db_session
):
    """No finish_reason in chunks → spend log status='partial'."""
    raw_key, api_key = proxy_key
    body_bytes = (
        b'data: {"id":"c1","created":1,"model":"gpt-4o-mini","choices":'
        b'[{"index":0,"delta":{"content":"He"}}]}\n\n'
        b'data: [DONE]\n\n'
    )
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body_bytes, headers={"content-type": "text/event-stream"}
        )
    )

    async with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    ) as resp:
        async for _ in resp.aiter_lines():
            pass

    result = await db_session.execute(
        select(SpendLog).where(SpendLog.api_key_hash == api_key.api_key_hash)
    )
    log = result.scalar_one()
    assert log.status == "partial"


# ============================================================================
# Upstream error → OpenAI-shape error response (integration tests)
# ============================================================================


@respx.mock
async def test_upstream_401_maps_to_401(client, proxy_key, openai_key_set):
    raw_key, _ = proxy_key
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            401, json={"error": {"message": "bad upstream key"}}
        )
    )
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["code"] == "invalid_api_key"


@respx.mock
async def test_upstream_429_maps_to_429(client, proxy_key, openai_key_set):
    raw_key, _ = proxy_key
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            429, json={"error": {"message": "slow down"}}
        )
    )
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 429
    body = resp.json()
    assert body["error"]["type"] == "rate_limit_error"


@respx.mock
async def test_upstream_400_context_maps_to_400_context(
    client, proxy_key, openai_key_set
):
    raw_key, _ = proxy_key
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "message": "context too long",
                    "code": "context_length_exceeded",
                }
            },
        )
    )
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "context_length_exceeded"


@respx.mock
async def test_upstream_500_maps_to_502_upstream_error(
    client, proxy_key, openai_key_set
):
    """Upstream 5xx → we return 502 'upstream_error' to clients."""
    raw_key, _ = proxy_key
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            500, json={"error": {"message": "boom"}}
        )
    )
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["code"] == "upstream_error"


@respx.mock
async def test_upstream_503_maps_to_503(client, proxy_key, openai_key_set):
    raw_key, _ = proxy_key
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            503, json={"error": {"message": "down"}}
        )
    )
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"]["code"] == "service_unavailable"
