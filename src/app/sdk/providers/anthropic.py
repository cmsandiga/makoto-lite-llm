import json
import os
import time
import uuid

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

_STOP_REASON_MAP = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "stop_sequence": "stop",
}

DEFAULT_API_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096

_FORWARDED_PARAMS = {
    "temperature",
    "top_p",
    "top_k",
    "max_tokens",
    "stream",
    "stop_sequences",
    "tools",
    "tool_choice",
    "metadata",
    "service_tier",
}


def _translate_tools(openai_tools: list[dict]) -> list[dict]:
    """OpenAI tool shape → Anthropic tool shape."""
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"].get("description", ""),
            "input_schema": t["function"]["parameters"],
        }
        for t in openai_tools
    ]


def _translate_tool_choice(value):
    """OpenAI tool_choice → Anthropic tool_choice. Returns None to omit."""
    if value == "auto":
        return {"type": "auto"}
    if value == "none":
        return None  # signal to caller: omit from body
    if isinstance(value, dict) and "function" in value:
        # OpenAI shape
        return {"type": "tool", "name": value["function"]["name"]}
    # Anthropic-shaped dict or anything else — pass through
    return value


def _extract_system_messages(messages: list[dict]) -> tuple[str | None, list[dict]]:
    """Walk messages; pull out role==system entries; concat their content with '\\n\\n'."""
    system_parts: list[str] = []
    remaining: list[dict] = []
    for m in messages:
        if m.get("role") == "system":
            content = m.get("content")
            if isinstance(content, str):
                system_parts.append(content)
        else:
            remaining.append(m)
    system_text = "\n\n".join(system_parts) if system_parts else None
    return system_text, remaining


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def get_api_base(self, model: str, api_base: str | None) -> str:
        return (
            api_base
            or os.environ.get("ANTHROPIC_API_BASE")
            or DEFAULT_API_BASE
        ).rstrip("/")

    def get_headers(self, api_key: str, extra_headers: dict | None) -> dict:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def transform_request(
        self, model: str, messages: list[dict], params: dict
    ) -> dict:
        system_text, filtered_messages = _extract_system_messages(messages)

        # Build allowlisted body fields
        allowlisted: dict = {}
        for k, v in params.items():
            if v is None:
                continue
            if k == "stop":
                # Translate to stop_sequences; coerce string to list
                seqs = [v] if isinstance(v, str) else list(v)
                allowlisted["stop_sequences"] = seqs
                continue
            if k == "tools":
                allowlisted["tools"] = _translate_tools(v)
                continue
            if k == "tool_choice":
                translated = _translate_tool_choice(v)
                if translated is not None:
                    allowlisted["tool_choice"] = translated
                continue
            if k in _FORWARDED_PARAMS:
                allowlisted[k] = v

        max_tokens = allowlisted.pop("max_tokens", None) or DEFAULT_MAX_TOKENS

        body: dict = {"model": model, "messages": filtered_messages}
        if system_text:
            body["system"] = system_text
        body["max_tokens"] = max_tokens
        body.update(allowlisted)
        return body

    def transform_response(self, raw: dict, model: str) -> ModelResponse:
        # Collapse content blocks
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in raw.get("content", []):
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block["id"],
                        type="function",
                        function=FunctionCall(
                            name=block["name"],
                            arguments=json.dumps(block.get("input", {})),
                        ),
                    )
                )
        content = "".join(text_parts) if text_parts else None

        # Map stop_reason; passthrough unknown values
        anthropic_reason = raw.get("stop_reason")
        finish_reason = (
            _STOP_REASON_MAP.get(anthropic_reason, anthropic_reason)
            if anthropic_reason is not None
            else None
        )

        # Build Usage
        u = raw.get("usage") or {}
        prompt_tokens = u.get("input_tokens", 0)
        completion_tokens = u.get("output_tokens", 0)
        usage = Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

        choice = Choice(
            index=0,
            message=Message(
                role="assistant",
                content=content,
                tool_calls=tool_calls or None,
            ),
            finish_reason=finish_reason,
        )

        return ModelResponse(
            id=raw["id"],
            created=int(time.time()),
            model=raw.get("model", model),
            choices=[choice],
            usage=usage,
        )

    def transform_stream_chunk(
        self, chunk: dict, model: str
    ) -> ModelResponseStream | None:
        chunk_type = chunk.get("type")
        if chunk_type is None:
            return None

        if chunk_type == "content_block_delta":
            delta_obj = chunk.get("delta") or {}
            delta_type = delta_obj.get("type")
            if delta_type == "text_delta":
                return self._build_stream_chunk(
                    model,
                    delta=Delta(content=delta_obj.get("text", "")),
                )
            if delta_type == "input_json_delta":
                tool_call = ToolCall(
                    id="",
                    type="function",
                    function=FunctionCall(
                        name="",
                        arguments=delta_obj.get("partial_json", ""),
                    ),
                )
                return self._build_stream_chunk(
                    model,
                    delta=Delta(tool_calls=[tool_call]),
                )
            return None

        if chunk_type == "message_delta":
            delta_obj = chunk.get("delta") or {}
            anthropic_reason = delta_obj.get("stop_reason")
            finish_reason = (
                _STOP_REASON_MAP.get(anthropic_reason, anthropic_reason)
                if anthropic_reason is not None
                else None
            )
            u = chunk.get("usage") or {}
            usage = Usage(
                prompt_tokens=u.get("input_tokens", 0),
                completion_tokens=u.get("output_tokens", 0),
                total_tokens=(
                    u.get("input_tokens", 0) + u.get("output_tokens", 0)
                ),
            )
            return self._build_stream_chunk(
                model,
                delta=Delta(),
                finish_reason=finish_reason,
                usage=usage,
            )

        # message_start, content_block_start, content_block_stop, message_stop, ping
        return None

    def _build_stream_chunk(
        self,
        model: str,
        delta: Delta,
        finish_reason: str | None = None,
        usage: Usage | None = None,
    ) -> ModelResponseStream:
        return ModelResponseStream(
            id=f"chatcmpl-{uuid.uuid4().hex}",
            created=int(time.time()),
            model=model,
            choices=[
                StreamChoice(index=0, delta=delta, finish_reason=finish_reason)
            ],
            usage=usage,
        )

    def get_error_class(self, status_code: int, body: dict) -> Exception:
        raise NotImplementedError  # implemented in Task 4


register_provider("anthropic", AnthropicProvider)
