import os
from typing import Any

from app.sdk.cost import calculate_cost
from app.sdk.exceptions import AuthenticationError
from app.sdk.http_client import get_http_client
from app.sdk.providers import openai as _openai  # noqa: F401  registers "openai"
from app.sdk.resolver import resolve_provider
from app.sdk.types import ModelResponse, StreamWrapper


async def acompletion(
    model: str,
    messages: list[dict],
    *,
    api_key: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    stream: bool = False,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
    stop: str | list[str] | None = None,
    user: str | None = None,
    timeout: float = 600.0,
    api_base: str | None = None,
    extra_headers: dict | None = None,
    **kwargs: Any,
) -> ModelResponse | StreamWrapper:
    provider_name, bare_model, provider = resolve_provider(model)

    resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not resolved_key:
        raise AuthenticationError(
            401, "No api_key passed and OPENAI_API_KEY env var is not set"
        )

    params = {
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "stream": stream,
        "tools": tools,
        "tool_choice": tool_choice,
        "stop": stop,
        "user": user,
        **kwargs,
    }
    body = provider.transform_request(bare_model, messages, params)
    headers = provider.get_headers(resolved_key, extra_headers)
    base = provider.get_api_base(bare_model, api_base)
    path = "/chat/completions"

    client = get_http_client()

    if stream:
        raise NotImplementedError("streaming wired up in next task")

    status, raw = await client.post(
        base, resolved_key, path, headers, body, timeout=timeout
    )
    if status >= 400:
        raise provider.get_error_class(status, raw)

    response = provider.transform_response(raw, bare_model)
    if response.usage is not None:
        response.usage.cost = calculate_cost(
            f"{provider_name}/{bare_model}", response.usage
        )
    return response
