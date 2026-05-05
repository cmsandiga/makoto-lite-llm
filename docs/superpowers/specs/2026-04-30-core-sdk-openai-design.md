# Core SDK — OpenAI (ola-12) Design Spec

**Date:** 2026-04-30
**Sub-project:** #2 (Core SDK), first slice
**Dependencies:** None — standalone library, no Auth System or proxy coupling
**Parent spec:** `docs/specs/2026-03-22-core-sdk-design.md` (full multi-provider vision)

---

## 1. Goal & Scope

Stand up the provider-abstraction layer with **OpenAI chat completions** as the first and only provider. Validate the architecture (BaseProvider ABC, registry, resolver, HTTP client, streaming wrapper, cost calc, error mapping) end-to-end with a single provider. Anthropic, Gemini, embeddings, images, audio, and rerank land in later olas; the architecture they plug into is what this ola delivers.

### In scope (ola-12)

- `acompletion()` — async chat completion against OpenAI
- Streaming + non-streaming
- Tools / function calling (delta pass-through, no reassembly)
- Strict `"openai/<model>"` model strings
- Pydantic response types (`ModelResponse`, `Choice`, `Message`, `ToolCall`, `Usage`, streaming variants)
- `BaseProvider` ABC + registry + resolver
- `LLMHttpClient` (pooled async httpx, one client per `(api_base, api_key)`, never closes on cache eviction)
- Standard exception hierarchy + OpenAI error → standard error mapping
- Cost calculation from `model_prices.json` (4-model OpenAI seed)
- `respx`-mocked unit tests + 1 gated live test against real OpenAI

### Out of scope (later olas)

- Sync `completion()` wrappers
- Anthropic, Gemini providers
- Embeddings, images, audio, rerank
- `tiktoken` token counter (rely on OpenAI's returned `usage`)
- Proxy HTTP routes (`POST /v1/chat/completions`)
- Auth/middleware integration
- Retries, fallbacks, routing — belong to Router (sub-project #3)
- `drop_params` / strict-param toggle — fixed allow-list for now
- Mapping `httpx.TimeoutException` → our `TimeoutError` — explicit gap, one-line fix later

---

## 2. Public API

```python
from app.sdk import acompletion, ModelResponse  # the only things callers need

async def acompletion(
    model: str,                                  # MUST be "openai/<model>"
    messages: list[dict],                        # OpenAI message format
    *,
    api_key: str | None = None,                  # falls back to OPENAI_API_KEY env
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    stream: bool = False,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
    stop: str | list[str] | None = None,
    user: str | None = None,
    timeout: float = 600.0,
    api_base: str | None = None,                 # override OpenAI base URL
    extra_headers: dict | None = None,
    **kwargs,                                    # forwarded to provider (allow-listed)
) -> ModelResponse | StreamWrapper: ...
```

### Decisions

- **Required kwargs after `*`** — every parameter named at the call site.
- **`api_key` keyword-only**: explicit > `OPENAI_API_KEY` env var > `AuthenticationError`.
- **`stream: bool` toggles return type**. Same function, two return shapes.
- **`**kwargs`** absorbed and passed to the provider. The provider applies an allow-list (see §6); unknown OpenAI params silently dropped.
- **Async-only for ola-12.** No `completion()` (sync). FastAPI is async, tests are async, httpx is async.

### Public re-exports from `app.sdk`

`acompletion`, `ModelResponse`, `Choice`, `Message`, `ToolCall`, `FunctionCall`, `Usage`, `ModelResponseStream`, `StreamChoice`, `Delta`, `StreamWrapper`, and all 10 exception classes.

Internal (test imports only): `BaseProvider`, `register_provider`, `PROVIDER_REGISTRY`, `resolve_provider`, `LLMHttpClient`, `get_http_client`, `calculate_cost`.

---

## 3. Package layout

```
src/app/sdk/
├── __init__.py            # Public surface: acompletion, types, errors
├── main.py                # acompletion() — top-level entry, resolves provider, dispatches
├── types.py               # Pydantic models + StreamWrapper
├── exceptions.py          # LiteLLMError + 9 subclasses
├── http_client.py         # LLMHttpClient (pooled async httpx) + _StreamingHTTPError
├── cost.py                # calculate_cost() — reads model_prices.json
├── model_prices.json      # OpenAI catalog (gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo)
├── resolver.py            # resolve_provider("provider/model")
└── providers/
    ├── __init__.py        # Imports openai to trigger registration
    ├── base.py            # BaseProvider ABC + register_provider()
    └── openai.py          # OpenAIProvider — register_provider("openai", OpenAIProvider)

tests/test_sdk/
├── __init__.py
├── test_resolver.py
├── test_types.py
├── test_cost.py
├── test_http_client.py
├── test_exceptions.py
├── test_acompletion.py        # respx-mocked dispatcher integration
├── test_openai_live.py        # 1 test, @pytest.mark.live, hits real OpenAI
└── providers/
    ├── __init__.py
    └── test_openai.py
```

### Decisions

- Mirrors existing `src/app/{auth,services,routes,...}` shape — each domain in its own module.
- `providers/` as a sub-package — adding `anthropic.py`/`gemini.py` later is one file + one import.
- `model_prices.json` as a data file (not Python) so it can be regenerated from upstream LiteLLM without code changes.
- `__init__.py` re-exports the small public surface — internal modules stay private.

---

## 4. Response types

```python
# src/app/sdk/types.py
from pydantic import BaseModel, ConfigDict


class FunctionCall(BaseModel):
    name: str
    arguments: str  # JSON-encoded string per OpenAI contract


class ToolCall(BaseModel):
    id: str
    type: str  # always "function" for now
    function: FunctionCall


class Message(BaseModel):
    role: str
    content: str | None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None  # only on role="tool" messages


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float | None = None  # USD; populated post-construction by dispatcher


class Choice(BaseModel):
    index: int
    message: Message
    finish_reason: str | None  # "stop" | "length" | "tool_calls" | "content_filter"


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="allow")  # forward-compat for new OpenAI fields

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage | None = None


# ---- Streaming ----

class Delta(BaseModel):
    role: str | None = None
    content: str | None = None
    tool_calls: list[ToolCall] | None = None  # partial deltas, pass-through


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
    usage: Usage | None = None  # OpenAI emits this in the final chunk when requested


class StreamWrapper:
    """Async iterator wrapping a parsed-chunk stream. Owns the httpx response lifecycle."""

    def __init__(self, chunk_iter, provider, model: str): ...
    def __aiter__(self) -> "StreamWrapper": ...
    async def __anext__(self) -> ModelResponseStream: ...
    async def aclose(self) -> None: ...
```

### Decisions

- **`ConfigDict(extra="allow")`** on response containers (`ModelResponse`, `ModelResponseStream`) — OpenAI ships new fields constantly (`system_fingerprint`, `service_tier`, …); we don't break when they do.
- **Strict containers on inner types** (`Choice`, `Message`, `Usage`, `ToolCall`) — material field changes break loudly, as they should.
- **`Usage.cost` is post-construction**. The provider returns `prompt_tokens`/`completion_tokens`; the dispatcher computes `cost` and writes it back.
- **`StreamWrapper` is plain class**, not Pydantic — it manages a streaming HTTP response and needs `aclose()`.
- **`Delta.tool_calls`** carries OpenAI's *partial* tool-call deltas verbatim. We do not reassemble — that's a caller concern.

---

## 5. BaseProvider, registry, resolver

```python
# src/app/sdk/providers/base.py
from abc import ABC, abstractmethod

from app.sdk.types import ModelResponse, ModelResponseStream


class BaseProvider(ABC):
    """Stateless. Receives bare model names ('gpt-4o'), not 'openai/gpt-4o'."""

    name: str  # class attribute, e.g., "openai"

    @abstractmethod
    def get_api_base(self, model: str, api_base: str | None) -> str: ...

    @abstractmethod
    def get_headers(self, api_key: str, extra_headers: dict | None) -> dict: ...

    @abstractmethod
    def transform_request(
        self, model: str, messages: list[dict], params: dict
    ) -> dict: ...

    @abstractmethod
    def transform_response(self, raw: dict, model: str) -> ModelResponse: ...

    @abstractmethod
    def transform_stream_chunk(
        self, chunk: dict, model: str
    ) -> ModelResponseStream | None:
        """Return None to skip the chunk."""

    @abstractmethod
    def get_error_class(self, status_code: int, response_body: dict) -> Exception: ...


PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {}


def register_provider(name: str, provider_class: type[BaseProvider]) -> None:
    PROVIDER_REGISTRY[name] = provider_class
```

```python
# src/app/sdk/resolver.py
from app.sdk.exceptions import UnknownProviderError
from app.sdk.providers.base import PROVIDER_REGISTRY, BaseProvider


def resolve_provider(model: str) -> tuple[str, str, BaseProvider]:
    if "/" not in model:
        raise UnknownProviderError(
            400,
            f"Model string must be 'provider/model', got '{model}'. "
            f"Known providers: {sorted(PROVIDER_REGISTRY)}",
        )
    provider_name, _, bare_model = model.partition("/")
    cls = PROVIDER_REGISTRY.get(provider_name)
    if cls is None:
        raise UnknownProviderError(
            400,
            f"Unknown provider '{provider_name}'. Known: {sorted(PROVIDER_REGISTRY)}",
        )
    return provider_name, bare_model, cls()
```

```python
# src/app/sdk/providers/__init__.py
"""Side-effect import: registers each provider into PROVIDER_REGISTRY."""
from app.sdk.providers import openai  # noqa: F401
```

### Decisions

- **Side-effect registration via package import.** Simplest pattern that works without entry-point machinery.
- **Provider instances constructed per-call.** Stateless — cost is negligible. Avoids global mutable state in providers. The stateful piece (HTTP client / connection pool) lives at the dispatcher level.
- **Bare model names downstream.** Resolver strips the `provider/` prefix once; providers never see it. Removes a class of "did I include the prefix?" bugs.
- **`transform_stream_chunk` may return `None`** — providers can filter SSE non-data lines without the dispatcher knowing SSE shape.
- **`get_error_class` returns an *instance***, not a class — lets the provider include the response body without callers needing to know each exception's constructor.
- **No separate `get_supported_params` / `map_params`** — folded into `transform_request`. Add the split back when callers actually need to introspect supported params (Router-level decisions, probably).

---

## 6. OpenAI provider

```python
# src/app/sdk/providers/openai.py
import os
import time
import uuid

from app.sdk.exceptions import (
    AuthenticationError, BadRequestError, ContentPolicyViolationError,
    ContextWindowExceededError, InternalServerError, LiteLLMError,
    NotFoundError, RateLimitError, ServiceUnavailableError, TimeoutError,
)
from app.sdk.providers.base import BaseProvider, register_provider
from app.sdk.types import (
    Choice, Delta, FunctionCall, Message, ModelResponse,
    ModelResponseStream, StreamChoice, ToolCall, Usage,
)

DEFAULT_API_BASE = "https://api.openai.com/v1"

_FORWARDED_PARAMS = {
    "temperature", "top_p", "max_tokens", "stream", "stop", "user",
    "tools", "tool_choice", "n", "seed", "logprobs", "top_logprobs",
    "response_format", "presence_penalty", "frequency_penalty",
    "logit_bias", "stream_options",
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
                    ] or None,
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

    def transform_stream_chunk(self, chunk: dict, model: str) -> ModelResponseStream | None:
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
                    ] or None,
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
        if status_code == 401: return AuthenticationError(status_code, msg)
        if status_code == 404: return NotFoundError(status_code, msg)
        if status_code == 408: return TimeoutError(status_code, msg)
        if status_code == 429: return RateLimitError(status_code, msg)
        if status_code == 400:
            if code == "context_length_exceeded":
                return ContextWindowExceededError(status_code, msg)
            if code == "content_filter":
                return ContentPolicyViolationError(status_code, msg)
            return BadRequestError(status_code, msg)
        if status_code == 503: return ServiceUnavailableError(status_code, msg)
        if 500 <= status_code < 600: return InternalServerError(status_code, msg)
        return LiteLLMError(status_code, msg)


register_provider("openai", OpenAIProvider)
```

### Decisions

- **`_FORWARDED_PARAMS` is an allow-list, not a deny-list.** Anything not in the set is silently dropped. Adding a new OpenAI param is a one-line append. Trade-off: we won't auto-forward random new OpenAI params — we also won't accidentally forward library-level kwargs (`cache=True`, etc.) to the API.
- **Error mapping reads OpenAI's `error.code`** for the two 400s with semantic meaning to us (`context_length_exceeded`, `content_filter`). Everything else under 400 → `BadRequestError`.
- **SSE `[DONE]` filtering happens in `LLMHttpClient.post_stream`**, not in the provider. The HTTP client returns parsed JSON dicts; `[DONE]` never reaches `transform_stream_chunk`. Keeps the provider pure (dict-in / Pydantic-out) and avoids per-provider SSE parsing.
- **Module-level `register_provider("openai", OpenAIProvider)`** at the bottom triggers registration on import.
- **No `tiktoken`.** We trust OpenAI's `usage` field. If absent, `response.usage` stays `None` and `Usage.cost` never populates.

---

## 7. HTTP client

```python
# src/app/sdk/http_client.py
import asyncio
import json
from typing import AsyncIterator

import httpx


class LLMHttpClient:
    """Pooled async httpx wrapper. One client per (api_base, api_key) tuple.

    Clients are never closed on cache eviction — there may be in-flight
    requests using them. Cleanup is process-shutdown only via aclose_all().
    """

    def __init__(self, default_timeout: float = 600.0):
        self._clients: dict[tuple[str, str], httpx.AsyncClient] = {}
        self._lock = asyncio.Lock()
        self._default_timeout = default_timeout

    async def _get_client(self, api_base: str, api_key: str) -> httpx.AsyncClient:
        key = (api_base, api_key)
        client = self._clients.get(key)
        if client is not None:
            return client
        async with self._lock:
            client = self._clients.get(key)  # double-checked
            if client is None:
                client = httpx.AsyncClient(
                    base_url=api_base,
                    timeout=httpx.Timeout(self._default_timeout, connect=10.0),
                    limits=httpx.Limits(
                        max_keepalive_connections=20,
                        max_connections=100,
                    ),
                )
                self._clients[key] = client
        return client

    async def post(
        self, api_base, api_key, path, headers, json_body,
        timeout: float | None = None,
    ) -> tuple[int, dict]:
        client = await self._get_client(api_base, api_key)
        resp = await client.post(path, headers=headers, json=json_body,
                                  timeout=timeout or self._default_timeout)
        try:
            body = resp.json()
        except json.JSONDecodeError:
            body = {"error": {"message": resp.text}}
        return resp.status_code, body

    async def post_stream(
        self, api_base, api_key, path, headers, json_body,
        timeout: float | None = None,
    ) -> AsyncIterator[dict]:
        """Yields parsed JSON dicts from an SSE stream. Filters [DONE] + blanks."""
        client = await self._get_client(api_base, api_key)
        async with client.stream("POST", path, headers=headers, json=json_body,
                                  timeout=timeout or self._default_timeout) as resp:
            if resp.status_code >= 400:
                body_bytes = await resp.aread()
                try:
                    body = json.loads(body_bytes)
                except json.JSONDecodeError:
                    body = {"error": {"message": body_bytes.decode("utf-8", "replace")}}
                raise _StreamingHTTPError(resp.status_code, body)

            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[len("data: "):].strip()
                if payload == "[DONE]":
                    return
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    continue  # malformed chunk; skip rather than abort the stream

    async def aclose_all(self) -> None:
        for c in list(self._clients.values()):
            await c.aclose()
        self._clients.clear()


class _StreamingHTTPError(Exception):
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.body = body


_default_client: LLMHttpClient | None = None


def get_http_client() -> LLMHttpClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMHttpClient()
    return _default_client
```

### Decisions

- **Pool key is `(api_base, api_key)`.** Different keys to the same base get separate clients — keys are tied to per-tenant rate limits; we don't want one tenant's traffic shape blocking another's. Trade-off: many tenants → many clients. Acceptable for ola-12; revisit under load.
- **Lazy + double-checked lock** so concurrent first-calls don't race.
- **`max_keepalive_connections=20, max_connections=100`** — sensible defaults, not tuned.
- **Never close on cache eviction.** The only valid close is process-shutdown via `aclose_all()`. Will wire to FastAPI lifespan when the proxy lands; for ola-12 it's a hook for tests.
- **`post_stream` parses SSE inside the client.** Filters `[DONE]` and blanks; yields parsed dicts. Provider methods stay pure and dict-fixture-testable.
- **Streaming errors raise `_StreamingHTTPError`** (private) which the dispatcher catches and re-raises through provider error mapping. Avoids two error-mapping paths in providers.
- **Malformed mid-stream chunks are skipped, not raised.** Caller may already have valid content; we don't poison the rest of the stream over a single bad chunk.
- **Module-level singleton** `get_http_client()`. Tests can construct their own `LLMHttpClient()` for isolation.

---

## 8. Dispatcher, cost, exceptions

```python
# src/app/sdk/main.py
import os

from app.sdk.cost import calculate_cost
from app.sdk.exceptions import AuthenticationError
from app.sdk.http_client import get_http_client
from app.sdk.providers import openai as _  # noqa: F401  registers "openai"
from app.sdk.resolver import resolve_provider
from app.sdk.types import ModelResponse, StreamWrapper


async def acompletion(
    model, messages, *, api_key=None, temperature=None, top_p=None,
    max_tokens=None, stream=False, tools=None, tool_choice=None, stop=None,
    user=None, timeout=600.0, api_base=None, extra_headers=None, **kwargs,
):
    provider_name, bare_model, provider = resolve_provider(model)

    resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not resolved_key:
        raise AuthenticationError(
            401, "No api_key passed and OPENAI_API_KEY env var is not set"
        )

    params = {
        "temperature": temperature, "top_p": top_p, "max_tokens": max_tokens,
        "stream": stream, "tools": tools, "tool_choice": tool_choice,
        "stop": stop, "user": user, **kwargs,
    }
    body = provider.transform_request(bare_model, messages, params)
    headers = provider.get_headers(resolved_key, extra_headers)
    base = provider.get_api_base(bare_model, api_base)
    path = "/chat/completions"

    client = get_http_client()

    if stream:
        chunk_iter = client.post_stream(base, resolved_key, path, headers, body, timeout=timeout)
        return StreamWrapper(chunk_iter, provider, bare_model)

    status, raw = await client.post(base, resolved_key, path, headers, body, timeout=timeout)
    if status >= 400:
        raise provider.get_error_class(status, raw)

    response = provider.transform_response(raw, bare_model)
    if response.usage is not None:
        response.usage.cost = calculate_cost(f"{provider_name}/{bare_model}", response.usage)
    return response
```

```python
# src/app/sdk/cost.py
import json
from pathlib import Path

from app.sdk.types import Usage

_PRICES_PATH = Path(__file__).parent / "model_prices.json"
_prices: dict[str, dict] | None = None


def _load() -> dict[str, dict]:
    global _prices
    if _prices is None:
        _prices = json.loads(_PRICES_PATH.read_text())
    return _prices


def calculate_cost(model: str, usage: Usage) -> float | None:
    info = _load().get(model)
    if not info:
        return None
    return (
        usage.prompt_tokens * info.get("input_cost_per_token", 0.0)
        + usage.completion_tokens * info.get("output_cost_per_token", 0.0)
    )
```

```jsonc
// src/app/sdk/model_prices.json
{
  "openai/gpt-4o":        {"input_cost_per_token": 2.50e-6,  "output_cost_per_token": 10.00e-6, "max_input_tokens": 128000, "max_output_tokens": 16384, "supports_tools": true, "supports_vision": true,  "mode": "chat"},
  "openai/gpt-4o-mini":   {"input_cost_per_token": 0.15e-6,  "output_cost_per_token":  0.60e-6, "max_input_tokens": 128000, "max_output_tokens": 16384, "supports_tools": true, "supports_vision": true,  "mode": "chat"},
  "openai/gpt-4-turbo":   {"input_cost_per_token": 10.00e-6, "output_cost_per_token": 30.00e-6, "max_input_tokens": 128000, "max_output_tokens": 4096,  "supports_tools": true, "supports_vision": true,  "mode": "chat"},
  "openai/gpt-3.5-turbo": {"input_cost_per_token": 0.50e-6,  "output_cost_per_token":  1.50e-6, "max_input_tokens": 16385,  "max_output_tokens": 4096,  "supports_tools": true, "supports_vision": false, "mode": "chat"}
}
```

```python
# src/app/sdk/exceptions.py
class LiteLLMError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"[{status_code}] {message}")


class AuthenticationError(LiteLLMError):          ...  # 401
class RateLimitError(LiteLLMError):                ...  # 429
class BadRequestError(LiteLLMError):               ...  # 400
class NotFoundError(LiteLLMError):                 ...  # 404
class ContentPolicyViolationError(LiteLLMError):   ...  # 400 with code=content_filter
class ContextWindowExceededError(LiteLLMError):    ...  # 400 with code=context_length_exceeded
class InternalServerError(LiteLLMError):           ...  # 5xx
class TimeoutError(LiteLLMError):                  ...  # 408
class ServiceUnavailableError(LiteLLMError):       ...  # 503
class UnknownProviderError(LiteLLMError):          ...  # 400
```

### StreamWrapper implementation note

```python
# in src/app/sdk/types.py
class StreamWrapper:
    def __init__(self, chunk_iter, provider, model: str):
        self._chunk_iter = chunk_iter
        self._provider = provider
        self._model = model

    def __aiter__(self): return self

    async def __anext__(self) -> "ModelResponseStream":
        from app.sdk.http_client import _StreamingHTTPError
        try:
            chunk = await self._chunk_iter.__anext__()
        except _StreamingHTTPError as e:
            raise self._provider.get_error_class(e.status_code, e.body) from None
        result = self._provider.transform_stream_chunk(chunk, self._model)
        if result is None:
            return await self.__anext__()  # skip and recurse
        return result

    async def aclose(self):
        if hasattr(self._chunk_iter, "aclose"):
            await self._chunk_iter.aclose()
```

### Decisions

- **Dispatcher does only border work.** Resolve provider → resolve key → assemble params → call HTTP → patch cost → return. No transformation logic.
- **None-valued kwargs forwarded to providers**, not filtered in dispatcher. The provider's allow-list does the filtering. One filter wins.
- **Cost is patched onto the response.** Providers return tokens; dispatcher computes USD and writes back. Providers stay ignorant of pricing.
- **Streaming errors surface on first `__anext__()`**, not at dispatch. Matches `httpx.AsyncClient.stream`'s lazy semantics.
- **Pricing seed is 4 OpenAI chat models.** JSON shape matches upstream LiteLLM's `model_prices_and_context_window.json` so we can later replace it with their export wholesale. Unknown models → `cost=None`.
- **`httpx.TimeoutException` not mapped in ola-12.** Explicit gap; one-line addition later.

---

## 9. Testing

### Unit tests (default suite)

```
tests/test_sdk/
├── test_resolver.py        # 4 tests
├── test_types.py           # 3 tests
├── test_cost.py            # 4 tests
├── test_http_client.py     # 5 tests
├── test_exceptions.py      # 1 test
├── test_acompletion.py     # 6 tests — dispatcher integration via respx
└── providers/test_openai.py # 8 tests — provider transforms
```

| File | Coverage |
|------|----------|
| `test_resolver.py` | strict prefix accepts `openai/x`; bare name raises; unknown provider raises; registry exposes `openai` |
| `test_types.py` | `ModelResponse` extra fields tolerated; `Choice` strict; `StreamWrapper.aclose()` calls underlying generator |
| `test_cost.py` | known model returns USD; unknown returns `None`; zero tokens → 0.0; JSON loaded once (cache) |
| `test_http_client.py` | client reuse by `(base, key)`; different keys → different clients; `post` returns `(status, body)`; `post_stream` filters `[DONE]` + blanks; 4xx in stream raises `_StreamingHTTPError` |
| `test_exceptions.py` | `str(LiteLLMError(401, "x"))` formats as `"[401] x"` |
| `test_openai.py` | headers include `Authorization: Bearer …`; `transform_request` forwards allow-listed params + drops unknown; `transform_response` parses choice + usage; tool_calls round-trip; `transform_stream_chunk` parses delta + tool-call delta; error mapping (401, 429, 400+context_length_exceeded → ContextWindow, 400+content_filter → ContentPolicy, 400 → BadRequest, 503, 500) |
| `test_acompletion.py` | non-stream happy path with respx; `usage.cost` populated when model in catalog; `usage.cost` None when not; missing api_key + missing env → `AuthenticationError`; 429 from OpenAI → `RateLimitError`; stream returns `StreamWrapper` and yields `ModelResponseStream` chunks |

### Live test (gated)

```
tests/test_sdk/test_openai_live.py    # 1 test, @pytest.mark.live
```

```python
@pytest.mark.live
async def test_openai_chat_happy_path():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set")

    response = await acompletion(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "Say \"ok\" and nothing else."}],
        max_tokens=5,
        api_key=api_key,
    )

    assert isinstance(response, ModelResponse)
    assert len(response.choices) == 1
    assert response.choices[0].message.role == "assistant"
    assert response.choices[0].message.content
    assert response.choices[0].finish_reason in ("stop", "length")

    assert response.usage is not None
    assert response.usage.prompt_tokens > 0
    assert response.usage.completion_tokens > 0
    assert response.usage.total_tokens == (
        response.usage.prompt_tokens + response.usage.completion_tokens
    )
    assert response.usage.cost is not None
    assert response.usage.cost > 0
```

### `pyproject.toml` changes

```toml
[tool.pytest.ini_options]
markers = [
    "e2e: full end-to-end tests that boot containers and a browser; run with `pytest -m e2e`",
    "live: tests that hit real third-party APIs and need credentials; run with `pytest -m live`",
]
addopts = "-m 'not e2e and not live'"
```

### Operational notes

- Default `pytest` excludes both `e2e` and `live`.
- Local: `OPENAI_API_KEY=sk-... uv run pytest -m live`.
- CI: separate workflow with the secret. Can be a scheduled job (e.g., daily) so PRs don't burn budget.
- `pytest.skip()` inside the test makes `-m live` without a key a no-op rather than a failure.
- Cost: one run ≈ $0.0001 (gpt-4o-mini, ~5 output tokens).

### Decisions

- **respx everywhere for HTTP mocks.** Same library as the OIDC tests.
- **Pool isolation per test.** Dispatcher tests reset `_default_client = None` via autouse fixture so each test gets a fresh pool. `test_http_client.py` constructs its own `LLMHttpClient()`.
- **No `app` fixtures needed.** SDK is pure library — no DB, Redis, or FastAPI.
- **Cost catalog locked.** `test_cost.py` asserts on exact prices in `model_prices.json` so a typo fails CI.
- **Updates default suite from 152 → ~183 tests** (+ 1 e2e + 1 live, both gated).

---

## 10. Anti-goals (deliberately NOT in this spec)

- Anthropic + Gemini providers — separate olas, will exercise the same `BaseProvider` interface.
- Embeddings, images, audio, rerank — separate endpoints, separate olas.
- Sync `completion()` — add when a sync caller appears.
- `tiktoken` — add when a caller needs pre-call estimation.
- Proxy HTTP route (`POST /v1/chat/completions`) — the surface from the proxy into the SDK is a separate design decision (auth integration, tenant resolution, request_tags routing).
- Retries / fallbacks / circuit breakers — sub-project #3 (Router).
- Caching — sub-project #4.
- Spend tracking — sub-project #5; consumes `Usage.cost` from this layer.
- Observability callbacks — sub-project #6.
- Guardrails — sub-project #7.

---

## 11. Open follow-ups

- `httpx.TimeoutException` → our `TimeoutError` mapping (1 line, defer to next ola).
- `aclose_all()` wired to FastAPI lifespan (when the proxy route lands).
- Replace handcrafted `model_prices.json` with an export from upstream LiteLLM (when more providers/models land — for ola-12 the 4-model seed is enough).
- Whether per-tenant pool keys cause memory pressure — revisit during load testing once the proxy is wired up.
