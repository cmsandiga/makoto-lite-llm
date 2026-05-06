"""Public response shape for /v1/chat/completions.

The SDK's ModelResponse is already OpenAI-shaped (intentional design),
so we re-export it under its OpenAI name. Same for streaming chunks
via ModelResponseStream. No translation layer needed at the route boundary.
"""

# Re-exports — kept here so callers don't reach into app.sdk internals
from pydantic import BaseModel

from app.sdk.types import (
    ModelResponse as ChatCompletionResponse,  # noqa: F401
)
from app.sdk.types import (
    ModelResponseStream as ChatCompletionChunk,  # noqa: F401
)


class ChatCompletionErrorBody(BaseModel):
    message: str
    type: str
    code: str | None = None


class ChatCompletionErrorResponse(BaseModel):
    error: ChatCompletionErrorBody
