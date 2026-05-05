"""Core SDK — unified provider abstraction.

Public surface:
    acompletion(model, messages, **kwargs) -> ModelResponse | StreamWrapper

Response types:
    ModelResponse, Choice, Message, ToolCall, FunctionCall, Usage
    ModelResponseStream, StreamChoice, Delta, StreamWrapper

Exceptions:
    LiteLLMError + 10 subclasses
"""

from app.sdk.exceptions import (
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    LiteLLMError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    TimeoutError,
    UnknownProviderError,
)
from app.sdk.main import acompletion
from app.sdk.types import (
    Choice,
    Delta,
    FunctionCall,
    Message,
    ModelResponse,
    ModelResponseStream,
    StreamChoice,
    StreamWrapper,
    ToolCall,
    Usage,
)

__all__ = [
    "acompletion",
    "AuthenticationError",
    "BadRequestError",
    "Choice",
    "ContentPolicyViolationError",
    "ContextWindowExceededError",
    "Delta",
    "FunctionCall",
    "InternalServerError",
    "LiteLLMError",
    "Message",
    "ModelResponse",
    "ModelResponseStream",
    "NotFoundError",
    "RateLimitError",
    "ServiceUnavailableError",
    "StreamChoice",
    "StreamWrapper",
    "TimeoutError",
    "ToolCall",
    "UnknownProviderError",
    "Usage",
]
