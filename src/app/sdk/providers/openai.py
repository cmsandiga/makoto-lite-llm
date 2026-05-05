import os

from app.sdk.providers.base import BaseProvider, register_provider
from app.sdk.types import ModelResponse, ModelResponseStream

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
        raise NotImplementedError  # implemented in Task 8

    def transform_stream_chunk(self, chunk: dict, model: str) -> ModelResponseStream | None:
        raise NotImplementedError  # implemented in Task 8

    def get_error_class(self, status_code: int, body: dict) -> Exception:
        raise NotImplementedError  # implemented in Task 8


register_provider("openai", OpenAIProvider)
