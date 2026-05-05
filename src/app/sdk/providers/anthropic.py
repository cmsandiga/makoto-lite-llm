import os

from app.sdk.providers.base import BaseProvider, register_provider
from app.sdk.types import ModelResponse, ModelResponseStream

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
        raise NotImplementedError  # implemented in Task 2

    def transform_stream_chunk(
        self, chunk: dict, model: str
    ) -> ModelResponseStream | None:
        raise NotImplementedError  # implemented in Task 3

    def get_error_class(self, status_code: int, body: dict) -> Exception:
        raise NotImplementedError  # implemented in Task 4


register_provider("anthropic", AnthropicProvider)
