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
