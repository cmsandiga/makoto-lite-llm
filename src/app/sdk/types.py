from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.sdk.providers.base import BaseProvider


class FunctionCall(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    id: str
    type: str
    function: FunctionCall


class Message(BaseModel):
    role: str
    content: str | None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float | None = None


class Choice(BaseModel):
    index: int
    message: Message
    finish_reason: str | None


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage | None = None


class Delta(BaseModel):
    role: str | None = None
    content: str | None = None
    tool_calls: list[ToolCall] | None = None


class StreamChoice(BaseModel):
    index: int
    delta: Delta
    finish_reason: str | None = None


class ModelResponseStream(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[StreamChoice]
    usage: Usage | None = None


class StreamWrapper:
    """Async iterator wrapping a parsed-chunk source. Owns the response lifecycle.

    The underlying source yields parsed dicts (already SSE-decoded by
    LLMHttpClient.post_stream). Each dict is passed through the provider's
    transform_stream_chunk, which returns a ModelResponseStream or None
    (skip).
    """

    def __init__(
        self,
        chunk_iter: "AsyncIterator[dict]",
        provider: "BaseProvider",
        model: str,
    ):
        self._chunk_iter = chunk_iter
        self._provider = provider
        self._model = model

    def __aiter__(self) -> "StreamWrapper":
        return self

    async def __anext__(self) -> ModelResponseStream:
        from app.sdk.http_client import _StreamingHTTPError

        while True:
            try:
                chunk = await self._chunk_iter.__anext__()
            except _StreamingHTTPError as e:
                raise self._provider.get_error_class(e.status_code, e.body) from None
            result = self._provider.transform_stream_chunk(chunk, self._model)
            if result is not None:
                return result

    async def aclose(self) -> None:
        if hasattr(self._chunk_iter, "aclose"):
            await self._chunk_iter.aclose()
