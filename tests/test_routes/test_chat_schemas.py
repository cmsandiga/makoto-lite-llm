import pytest
from pydantic import ValidationError

from app.schemas.wire_in.chat import ChatCompletionRequest, ChatMessage
from app.schemas.wire_out.chat import (
    ChatCompletionErrorBody,
    ChatCompletionErrorResponse,
)


def test_chat_message_basic():
    m = ChatMessage(role="user", content="hi")
    assert m.role == "user"
    assert m.content == "hi"


def test_chat_message_content_can_be_none():
    """Tool-call assistant messages have content=None."""
    m = ChatMessage(role="assistant", content=None)
    assert m.content is None


def test_chat_message_content_can_be_list_of_dicts():
    """Multimodal/tool-result messages have list content."""
    m = ChatMessage(
        role="tool",
        content=[{"type": "text", "text": "result"}],
    )
    assert m.content == [{"type": "text", "text": "result"}]


def test_chat_message_extra_fields_allowed():
    """OpenAI ships new message fields; we tolerate them."""
    m = ChatMessage(role="assistant", content=None, tool_calls=[{"id": "x"}])
    assert m.tool_calls == [{"id": "x"}]


def test_request_basic():
    req = ChatCompletionRequest(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert req.model == "openai/gpt-4o-mini"
    assert len(req.messages) == 1
    assert req.stream is False  # default


def test_request_rejects_empty_messages():
    with pytest.raises(ValidationError):
        ChatCompletionRequest(model="openai/gpt-4o-mini", messages=[])


def test_request_extra_fields_allowed():
    """Unknown top-level fields pass through; SDK allowlists what's forwarded."""
    req = ChatCompletionRequest(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        future_param_we_dont_know_about=42,
    )
    # Pydantic stores extras; access via model_extra
    assert req.model_extra == {"future_param_we_dont_know_about": 42}


def test_request_does_not_validate_provider_prefix():
    """Bare model names must reach the SDK resolver, which raises UnknownProviderError."""
    # Schema accepts any string for `model`. The route translates the SDK
    # exception to HTTP 400 + model_not_found.
    req = ChatCompletionRequest(
        model="bare-model-name",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert req.model == "bare-model-name"


def test_error_envelope_serializes():
    body = ChatCompletionErrorBody(
        message="bad", type="invalid_request_error", code="bad_request"
    )
    env = ChatCompletionErrorResponse(error=body)
    dumped = env.model_dump()
    assert dumped == {
        "error": {
            "message": "bad",
            "type": "invalid_request_error",
            "code": "bad_request",
        }
    }
