"""Live integration test against real Anthropic.

Skipped unless ANTHROPIC_API_KEY is set AND `-m live` is passed.
Run: `ANTHROPIC_API_KEY=sk-ant-... uv run pytest -m live`
Cost: ~$0.0001 per run (claude-haiku-4-5-20251001, ~5 output tokens).
"""

import os

import pytest

from app.sdk import acompletion
from app.sdk.types import ModelResponse


@pytest.mark.live
async def test_anthropic_chat_happy_path():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")

    response = await acompletion(
        model="anthropic/claude-haiku-4-5-20251001",
        messages=[
            {"role": "user", "content": 'Say "ok" and nothing else.'}
        ],
        max_tokens=10,
        api_key=api_key,
    )

    assert isinstance(response, ModelResponse)
    assert len(response.choices) == 1
    assert response.choices[0].message.role == "assistant"
    assert response.choices[0].message.content
    assert response.choices[0].finish_reason in ("stop", "length")

    assert response.usage is not None
    assert response.usage.prompt_tokens > 0
    assert response.usage.completion_tokens > 0
    assert response.usage.total_tokens == (
        response.usage.prompt_tokens + response.usage.completion_tokens
    )
    assert response.usage.cost is not None
    assert response.usage.cost > 0
