"""Live integration test against real OpenAI.

Skipped unless OPENAI_API_KEY is set AND `-m live` is passed.
Run: `OPENAI_API_KEY=sk-... uv run pytest -m live`
Cost: ~$0.0001 per run (gpt-4o-mini, ~5 output tokens).
"""

import os

import pytest

from app.sdk import acompletion
from app.sdk.types import ModelResponse


@pytest.mark.live
async def test_openai_chat_happy_path():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set")

    response = await acompletion(
        model="openai/gpt-4o-mini",
        messages=[
            {"role": "user", "content": 'Say "ok" and nothing else.'}
        ],
        max_tokens=5,
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
