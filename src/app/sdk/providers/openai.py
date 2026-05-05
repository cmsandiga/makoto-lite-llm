import os
import time
import uuid

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
)
from app.sdk.providers.base import BaseProvider, register_provider
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

DEFAULT_API_BASE = "https://api.openai.com/v1"

_FORWARDED_PARAMS = {
    "temperature",
    "top_p",
    "max_tokens",
    "stream",
    "stop",
    "user",
    "tools",
    "tool_choice",
    "n",
    "seed",
    "logprobs",
    "top_logprobs",
    "response_format",
    "presence_penalty",
    "frequency_penalty",
    "logit_bias",
    "stream_options",
}


class OpenAIProvider(BaseProvider):
    name = "openai"

    def get_api_base(self, model: str, api_base: str | None) -> str:
        return (api_base or os.environ.get("OPENAI_API_BASE") or DEFAULT_API_BASE).rstrip("/")

    def get_headers(self, api_key: str, extra_headers: dict | None) -> dict:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def transform_request(self, model: str, messages: list[dict], params: dict) -> dict:
        body: dict = {"model": model, "messages": messages}
        for k, v in params.items():
            if k in _FORWARDED_PARAMS and v is not None:
                body[k] = v
        return body

    def transform_response(self, raw: dict, model: str) -> ModelResponse:
        choices = [
            Choice(
                index=c["index"],
                message=Message(
                    role=c["message"]["role"],
                    content=c["message"].get("content"),
                    tool_calls=[
                        ToolCall(
                            id=tc["id"],
                            type=tc["type"],
                            function=FunctionCall(
                                name=tc["function"]["name"],
                                arguments=tc["function"]["arguments"],
                            ),
                        )
                        for tc in c["message"].get("tool_calls") or []
                    ]
                    or None,
                ),
                finish_reason=c.get("finish_reason"),
            )
            for c in raw["choices"]
        ]
        usage = None
        if raw.get("usage"):
            u = raw["usage"]
            usage = Usage(
                prompt_tokens=u["prompt_tokens"],
                completion_tokens=u["completion_tokens"],
                total_tokens=u["total_tokens"],
            )
        return ModelResponse(
            id=raw.get("id") or f"chatcmpl-{uuid.uuid4().hex}",
            created=raw.get("created") or int(time.time()),
            model=raw.get("model", model),
            choices=choices,
            usage=usage,
        )

    def transform_stream_chunk(
        self, chunk: dict, model: str
    ) -> ModelResponseStream | None:
        if not chunk or "choices" not in chunk:
            return None
        choices = [
            StreamChoice(
                index=c["index"],
                delta=Delta(
                    role=c["delta"].get("role"),
                    content=c["delta"].get("content"),
                    tool_calls=[
                        ToolCall(
                            id=tc.get("id", ""),
                            type=tc.get("type", "function"),
                            function=FunctionCall(
                                name=tc["function"].get("name", ""),
                                arguments=tc["function"].get("arguments", ""),
                            ),
                        )
                        for tc in c["delta"].get("tool_calls") or []
                    ]
                    or None,
                ),
                finish_reason=c.get("finish_reason"),
            )
            for c in chunk["choices"]
        ]
        usage = None
        if chunk.get("usage"):
            u = chunk["usage"]
            usage = Usage(
                prompt_tokens=u["prompt_tokens"],
                completion_tokens=u["completion_tokens"],
                total_tokens=u["total_tokens"],
            )
        return ModelResponseStream(
            id=chunk["id"],
            created=chunk["created"],
            model=chunk.get("model", model),
            choices=choices,
            usage=usage,
        )

    def get_error_class(self, status_code: int, body: dict) -> Exception:
        msg = (body.get("error") or {}).get("message", str(body))
        code = (body.get("error") or {}).get("code", "")
        if status_code == 401:
            return AuthenticationError(status_code, msg)
        if status_code == 404:
            return NotFoundError(status_code, msg)
        if status_code == 408:
            return TimeoutError(status_code, msg)
        if status_code == 429:
            return RateLimitError(status_code, msg)
        if status_code == 400:
            if code == "context_length_exceeded":
                return ContextWindowExceededError(status_code, msg)
            if code == "content_filter":
                return ContentPolicyViolationError(status_code, msg)
            return BadRequestError(status_code, msg)
        if status_code == 503:
            return ServiceUnavailableError(status_code, msg)
        if 500 <= status_code < 600:
            return InternalServerError(status_code, msg)
        return LiteLLMError(status_code, msg)


register_provider("openai", OpenAIProvider)
