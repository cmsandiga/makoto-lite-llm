"""Live integration test for the proxy.

Skipped unless `-m live` is passed AND the env vars are set.
Run: `OPENAI_API_KEY=sk-... uv run pytest -m live tests/test_proxy/`
Cost: ~$0.0001 per run (gpt-4o-mini, ~5 output tokens).

Boots the FastAPI app via uvicorn in a background thread, creates a
proxy ApiKey in a real DB (testcontainer Postgres), then posts to
/v1/chat/completions with that key.
"""

import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key_auth import generate_api_key, get_key_prefix, hash_api_key
from app.models.api_key import ApiKey
from app.models.spend import SpendLog
from app.models.user import User


def _free_port() -> int:
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def app_server():
    """Boot the FastAPI app in a uvicorn thread on a free port."""
    from app.main import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        try:
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
            break
        except (httpx.ConnectError, httpx.ReadTimeout):
            time.sleep(0.1)
    else:
        pytest.fail("uvicorn did not start within 5s")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.live
async def test_proxy_chat_completion_live(app_server, db_session: AsyncSession):
    """End-to-end: real proxy key + real OpenAI call + spend log row written."""
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")

    user = User(email="proxy-live-test@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)
    api_key = ApiKey(
        api_key_hash=key_hash,
        key_prefix=get_key_prefix(raw_key),
        user_id=user.id,
    )
    db_session.add(api_key)
    await db_session.commit()

    response = httpx.post(
        f"{app_server}/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": 'Say "ok" and nothing else.'}],
            "max_tokens": 5,
        },
        headers={"Authorization": f"Bearer {raw_key}"},
        timeout=30.0,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"]
    assert body["usage"]["prompt_tokens"] > 0
    assert body["usage"]["completion_tokens"] > 0
    assert body["usage"]["cost"] > 0

    result = await db_session.execute(
        select(SpendLog).where(SpendLog.api_key_hash == key_hash)
    )
    log = result.scalar_one()
    assert log.status == "completed"
    assert log.input_tokens == body["usage"]["prompt_tokens"]
