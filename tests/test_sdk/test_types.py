import pytest
from pydantic import ValidationError

from app.sdk.types import (
    Choice,
    Delta,
    FunctionCall,
    Message,
    ModelResponse,
    ModelResponseStream,
    StreamChoice,
    ToolCall,
    Usage,
)


def test_message_with_content():
    m = Message(role="assistant", content="hello")
    assert m.role == "assistant"
    assert m.content == "hello"
    assert m.tool_calls is None


def test_message_with_tool_calls():
    m = Message(
        role="assistant",
        content=None,
        tool_calls=[
            ToolCall(
                id="call_1",
                type="function",
                function=FunctionCall(name="get_weather", arguments='{"city":"sf"}'),
            )
        ],
    )
    assert m.content is None
    assert len(m.tool_calls) == 1
    assert m.tool_calls[0].function.name == "get_weather"


def test_usage_cost_defaults_none():
    u = Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    assert u.cost is None


def test_model_response_allows_extra_fields():
    """OpenAI ships new fields constantly; we tolerate them."""
    resp = ModelResponse(
        id="chatcmpl-1",
        created=1700000000,
        model="gpt-4o",
        choices=[
            Choice(
                index=0,
                message=Message(role="assistant", content="ok"),
                finish_reason="stop",
            )
        ],
        usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        system_fingerprint="fp_xyz",  # extra field — should not raise
        service_tier="default",
    )
    assert resp.id == "chatcmpl-1"


def test_choice_strict_on_required_fields():
    """Inner types are strict — missing required fields raise."""
    with pytest.raises(ValidationError):
        Choice(index=0)  # missing message


def test_delta_all_fields_optional():
    d = Delta()
    assert d.role is None
    assert d.content is None
    assert d.tool_calls is None


def test_delta_partial_content():
    d = Delta(content="hel")
    assert d.content == "hel"


def test_model_response_stream_extra_allowed():
    chunk = ModelResponseStream(
        id="chatcmpl-1",
        created=1700000000,
        model="gpt-4o",
        choices=[StreamChoice(index=0, delta=Delta(content="ok"))],
        system_fingerprint="fp_xyz",  # extra
    )
    assert chunk.choices[0].delta.content == "ok"


class _FakeProvider:
    """Minimal stand-in for BaseProvider — we only need transform_stream_chunk
    and get_error_class for these tests."""

    def __init__(self):
        self.errors_raised: list = []

    def transform_stream_chunk(self, chunk, model):
        if chunk == {"skip": True}:
            return None
        return ModelResponseStream(
            id=chunk["id"],
            created=chunk["created"],
            model=model,
            choices=[StreamChoice(index=0, delta=Delta(content=chunk.get("content", "")))],
        )

    def get_error_class(self, status_code, body):
        return RuntimeError(f"{status_code}: {body}")


async def _gen(items):
    for x in items:
        yield x


async def test_stream_wrapper_iterates_chunks():
    from app.sdk.types import StreamWrapper

    provider = _FakeProvider()
    chunks = [
        {"id": "c1", "created": 1, "content": "Hel"},
        {"id": "c2", "created": 2, "content": "lo"},
    ]
    wrapper = StreamWrapper(_gen(chunks), provider, "gpt-4o")
    out = []
    async for chunk in wrapper:
        out.append(chunk)
    assert len(out) == 2
    assert out[0].choices[0].delta.content == "Hel"
    assert out[1].choices[0].delta.content == "lo"


async def test_stream_wrapper_skips_none_returns_from_provider():
    from app.sdk.types import StreamWrapper

    provider = _FakeProvider()
    chunks = [
        {"id": "c1", "created": 1, "content": "a"},
        {"skip": True},
        {"id": "c2", "created": 2, "content": "b"},
    ]
    wrapper = StreamWrapper(_gen(chunks), provider, "gpt-4o")
    out = [c async for c in wrapper]
    assert len(out) == 2


async def test_stream_wrapper_aclose_calls_underlying():
    from app.sdk.types import StreamWrapper

    closed = {"v": False}

    async def gen():
        try:
            yield {"id": "c1", "created": 1, "content": "x"}
        finally:
            closed["v"] = True

    g = gen()
    wrapper = StreamWrapper(g, _FakeProvider(), "gpt-4o")
    # consume one then close
    await wrapper.__anext__()
    await wrapper.aclose()
    assert closed["v"] is True
