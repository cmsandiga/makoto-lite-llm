# Core SDK — OpenAI (ola-12) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the provider-abstraction layer for the LLM proxy, with OpenAI chat completions as the first and only provider. Validate the architecture (BaseProvider ABC, registry, resolver, pooled HTTP client, streaming wrapper, cost calc, error mapping) end-to-end.

**Architecture:** Single async public function `acompletion()` dispatches to a registered provider resolved from the `"provider/model"` string. Providers are stateless and implement six abstract methods that transform between OpenAI-shaped requests/responses and our Pydantic types. A pooled `httpx.AsyncClient` (one per `(api_base, api_key)`) is owned by an `LLMHttpClient` singleton; SSE parsing happens in the client so providers stay pure dict-in/Pydantic-out.

**Tech Stack:** Python 3.11+, Pydantic, httpx (async), pytest + pytest-asyncio, respx (HTTP mocking).

**Spec:** `docs/superpowers/specs/2026-04-30-core-sdk-openai-design.md`

---

## File Structure

```
src/app/sdk/
├── __init__.py            # Public re-exports: acompletion, types, errors
├── main.py                # acompletion() — top-level dispatcher
├── types.py               # Pydantic models + StreamWrapper class
├── exceptions.py          # LiteLLMError + 10 subclasses
├── http_client.py         # LLMHttpClient + _StreamingHTTPError + get_http_client
├── cost.py                # calculate_cost() — reads model_prices.json
├── model_prices.json      # 4-model OpenAI chat catalog
├── resolver.py            # resolve_provider("provider/model")
└── providers/
    ├── __init__.py        # Side-effect import of openai (registers it)
    ├── base.py            # BaseProvider ABC + register_provider()
    └── openai.py          # OpenAIProvider — register_provider("openai", ...)

tests/test_sdk/
├── __init__.py
├── test_resolver.py
├── test_types.py
├── test_cost.py
├── test_http_client.py
├── test_exceptions.py
├── test_acompletion.py        # respx-mocked dispatcher tests
├── test_openai_live.py        # 1 test, @pytest.mark.live
└── providers/
    ├── __init__.py
    └── test_openai.py
```

**`pyproject.toml`** gains a `live` marker + updated `addopts`.

---

### Task 1: Package scaffold + exceptions

**Files:**
- Create: `src/app/sdk/__init__.py`
- Create: `src/app/sdk/exceptions.py`
- Create: `tests/test_sdk/__init__.py`
- Create: `tests/test_sdk/test_exceptions.py`

- [ ] **Step 1: Create empty package files**

```bash
mkdir -p src/app/sdk tests/test_sdk
touch src/app/sdk/__init__.py
touch tests/test_sdk/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_sdk/test_exceptions.py`:

```python
import pytest

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


def test_litellm_error_str_format():
    err = LiteLLMError(401, "bad key")
    assert str(err) == "[401] bad key"
    assert err.status_code == 401
    assert err.message == "bad key"


@pytest.mark.parametrize(
    "cls",
    [
        AuthenticationError,
        RateLimitError,
        BadRequestError,
        NotFoundError,
        ContentPolicyViolationError,
        ContextWindowExceededError,
        InternalServerError,
        TimeoutError,
        ServiceUnavailableError,
        UnknownProviderError,
    ],
)
def test_subclasses_inherit_from_litellm_error(cls):
    err = cls(400, "x")
    assert isinstance(err, LiteLLMError)
    assert err.status_code == 400
    assert err.message == "x"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest tests/test_sdk/test_exceptions.py -v 2>&1 | tail -5
```

Expected: ImportError — `app.sdk.exceptions` does not exist.

- [ ] **Step 4: Implement `exceptions.py`**

Create `src/app/sdk/exceptions.py`:

```python
class LiteLLMError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"[{status_code}] {message}")


class AuthenticationError(LiteLLMError): ...
class RateLimitError(LiteLLMError): ...
class BadRequestError(LiteLLMError): ...
class NotFoundError(LiteLLMError): ...
class ContentPolicyViolationError(LiteLLMError): ...
class ContextWindowExceededError(LiteLLMError): ...
class InternalServerError(LiteLLMError): ...
class TimeoutError(LiteLLMError): ...
class ServiceUnavailableError(LiteLLMError): ...
class UnknownProviderError(LiteLLMError): ...
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/test_sdk/test_exceptions.py -v 2>&1 | tail -5
```

Expected: 11 passed.

- [ ] **Step 6: Commit**

```bash
git add src/app/sdk/__init__.py src/app/sdk/exceptions.py tests/test_sdk/__init__.py tests/test_sdk/test_exceptions.py
git commit -m "feat(sdk): add exception hierarchy (LiteLLMError + 10 subclasses)"
```

---

### Task 2: Response Pydantic types (non-streaming)

**Files:**
- Create: `src/app/sdk/types.py`
- Create: `tests/test_sdk/test_types.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_sdk/test_types.py`:

```python
import pytest
from pydantic import ValidationError

from app.sdk.types import (
    Choice,
    FunctionCall,
    Message,
    ModelResponse,
    ToolCall,
    Usage,
)


def test_message_with_content():
    m = Message(role="assistant", content="hello")
    assert m.role == "assistant"
    assert m.content == "hello"
    assert m.tool_calls is None


def test_message_with_tool_calls():
    m = Message(
        role="assistant",
        content=None,
        tool_calls=[
            ToolCall(
                id="call_1",
                type="function",
                function=FunctionCall(name="get_weather", arguments='{"city":"sf"}'),
            )
        ],
    )
    assert m.content is None
    assert len(m.tool_calls) == 1
    assert m.tool_calls[0].function.name == "get_weather"


def test_usage_cost_defaults_none():
    u = Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    assert u.cost is None


def test_model_response_allows_extra_fields():
    """OpenAI ships new fields constantly; we tolerate them."""
    resp = ModelResponse(
        id="chatcmpl-1",
        created=1700000000,
        model="gpt-4o",
        choices=[Choice(index=0, message=Message(role="assistant", content="ok"), finish_reason="stop")],
        usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        system_fingerprint="fp_xyz",  # extra field — should not raise
        service_tier="default",
    )
    assert resp.id == "chatcmpl-1"


def test_choice_strict_on_required_fields():
    """Inner types are strict — missing required fields raise."""
    with pytest.raises(ValidationError):
        Choice(index=0)  # missing message
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_sdk/test_types.py -v 2>&1 | tail -5
```

Expected: ImportError on `app.sdk.types`.

- [ ] **Step 3: Implement `types.py` (non-streaming portion)**

Create `src/app/sdk/types.py`:

```python
from pydantic import BaseModel, ConfigDict


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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_sdk/test_types.py -v 2>&1 | tail -5
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/app/sdk/types.py tests/test_sdk/test_types.py
git commit -m "feat(sdk): add response Pydantic types (Message, Choice, ModelResponse, Usage)"
```

---

### Task 3: Streaming Pydantic types

**Files:**
- Modify: `src/app/sdk/types.py`
- Modify: `tests/test_sdk/test_types.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sdk/test_types.py`:

```python
from app.sdk.types import Delta, ModelResponseStream, StreamChoice


def test_delta_all_fields_optional():
    d = Delta()
    assert d.role is None
    assert d.content is None
    assert d.tool_calls is None


def test_delta_partial_content():
    d = Delta(content="hel")
    assert d.content == "hel"


def test_model_response_stream_extra_allowed():
    chunk = ModelResponseStream(
        id="chatcmpl-1",
        created=1700000000,
        model="gpt-4o",
        choices=[StreamChoice(index=0, delta=Delta(content="ok"))],
        system_fingerprint="fp_xyz",  # extra
    )
    assert chunk.choices[0].delta.content == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_sdk/test_types.py::test_delta_all_fields_optional -v 2>&1 | tail -5
```

Expected: ImportError on `Delta`.

- [ ] **Step 3: Append streaming types to `types.py`**

Append to `src/app/sdk/types.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_sdk/test_types.py -v 2>&1 | tail -5
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/app/sdk/types.py tests/test_sdk/test_types.py
git commit -m "feat(sdk): add streaming Pydantic types (Delta, StreamChoice, ModelResponseStream)"
```

---

### Task 4: BaseProvider ABC + registry

**Files:**
- Create: `src/app/sdk/providers/__init__.py`
- Create: `src/app/sdk/providers/base.py`
- Create: `tests/test_sdk/providers/__init__.py`
- Create: `tests/test_sdk/providers/test_base.py`

- [ ] **Step 1: Create the package skeletons**

```bash
mkdir -p src/app/sdk/providers tests/test_sdk/providers
touch src/app/sdk/providers/__init__.py
touch tests/test_sdk/providers/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_sdk/providers/test_base.py`:

```python
from app.sdk.providers.base import (
    PROVIDER_REGISTRY,
    BaseProvider,
    register_provider,
)


class _DummyProvider(BaseProvider):
    name = "dummy"

    def get_api_base(self, model, api_base):
        return api_base or "https://dummy.example.com"

    def get_headers(self, api_key, extra_headers):
        return {"Authorization": f"Bearer {api_key}"}

    def transform_request(self, model, messages, params):
        return {"model": model, "messages": messages}

    def transform_response(self, raw, model):
        raise NotImplementedError

    def transform_stream_chunk(self, chunk, model):
        return None

    def get_error_class(self, status_code, body):
        return RuntimeError(f"{status_code}: {body}")


def test_register_and_lookup():
    register_provider("dummy", _DummyProvider)
    assert PROVIDER_REGISTRY["dummy"] is _DummyProvider
    # Can construct an instance
    inst = _DummyProvider()
    assert inst.name == "dummy"
    assert inst.get_api_base("foo", None) == "https://dummy.example.com"


def test_baseprovider_is_abstract():
    """Cannot instantiate BaseProvider directly — abstract methods unimplemented."""
    import pytest

    with pytest.raises(TypeError):
        BaseProvider()
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest tests/test_sdk/providers/test_base.py -v 2>&1 | tail -5
```

Expected: ImportError on `app.sdk.providers.base`.

- [ ] **Step 4: Implement `base.py`**

Create `src/app/sdk/providers/base.py`:

```python
from abc import ABC, abstractmethod

from app.sdk.types import ModelResponse, ModelResponseStream


class BaseProvider(ABC):
    """All providers implement this interface.

    Stateless. Receives bare model names ('gpt-4o'), not 'openai/gpt-4o'.
    """

    name: str

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
    ) -> ModelResponseStream | None: ...

    @abstractmethod
    def get_error_class(self, status_code: int, response_body: dict) -> Exception: ...


PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {}


def register_provider(name: str, provider_class: type[BaseProvider]) -> None:
    PROVIDER_REGISTRY[name] = provider_class
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/test_sdk/providers/test_base.py -v 2>&1 | tail -5
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/app/sdk/providers/__init__.py src/app/sdk/providers/base.py tests/test_sdk/providers/__init__.py tests/test_sdk/providers/test_base.py
git commit -m "feat(sdk): add BaseProvider ABC + registry"
```

---

### Task 5: Resolver

**Files:**
- Create: `src/app/sdk/resolver.py`
- Create: `tests/test_sdk/test_resolver.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_sdk/test_resolver.py`:

```python
import pytest

from app.sdk.exceptions import UnknownProviderError
from app.sdk.providers.base import BaseProvider, register_provider
from app.sdk.resolver import resolve_provider


class _StubProvider(BaseProvider):
    name = "stub"

    def get_api_base(self, model, api_base): return "https://stub"
    def get_headers(self, api_key, extra_headers): return {}
    def transform_request(self, model, messages, params): return {}
    def transform_response(self, raw, model): raise NotImplementedError
    def transform_stream_chunk(self, chunk, model): return None
    def get_error_class(self, status_code, body): return RuntimeError()


def test_resolve_strict_prefix_returns_provider():
    register_provider("stub", _StubProvider)
    name, model, inst = resolve_provider("stub/super-model-v1")
    assert name == "stub"
    assert model == "super-model-v1"
    assert isinstance(inst, _StubProvider)


def test_resolve_bare_name_raises():
    with pytest.raises(UnknownProviderError, match="Model string must be"):
        resolve_provider("gpt-4o")


def test_resolve_unknown_provider_raises():
    with pytest.raises(UnknownProviderError, match="Unknown provider 'nope'"):
        resolve_provider("nope/some-model")


def test_resolve_preserves_slashes_in_model_name():
    """Provider is split on the FIRST slash only."""
    register_provider("stub", _StubProvider)
    name, model, _ = resolve_provider("stub/org/some-model:v2")
    assert name == "stub"
    assert model == "org/some-model:v2"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_sdk/test_resolver.py -v 2>&1 | tail -5
```

Expected: ImportError on `app.sdk.resolver`.

- [ ] **Step 3: Implement `resolver.py`**

Create `src/app/sdk/resolver.py`:

```python
from app.sdk.exceptions import UnknownProviderError
from app.sdk.providers.base import PROVIDER_REGISTRY, BaseProvider


def resolve_provider(model: str) -> tuple[str, str, BaseProvider]:
    """Parse 'provider/model' and return (provider_name, bare_model, provider_instance).

    Strict: model MUST contain '/'. Bare names raise UnknownProviderError.
    """
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

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_sdk/test_resolver.py -v 2>&1 | tail -5
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/app/sdk/resolver.py tests/test_sdk/test_resolver.py
git commit -m "feat(sdk): add resolve_provider() with strict 'provider/model' parsing"
```

---

### Task 6: HTTP client

**Files:**
- Create: `src/app/sdk/http_client.py`
- Create: `tests/test_sdk/test_http_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_sdk/test_http_client.py`:

```python
import httpx
import pytest
import respx

from app.sdk.http_client import (
    LLMHttpClient,
    _StreamingHTTPError,
    get_http_client,
)


@pytest.fixture
def client():
    return LLMHttpClient(default_timeout=5.0)


@respx.mock
async def test_post_returns_status_and_body(client):
    respx.post("https://api.example.com/v1/foo").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    status, body = await client.post(
        "https://api.example.com/v1",
        "sk-test",
        "/foo",
        {"Authorization": "Bearer sk-test"},
        {"input": "x"},
    )
    assert status == 200
    assert body == {"ok": True}


@respx.mock
async def test_post_returns_text_when_not_json(client):
    respx.post("https://api.example.com/v1/foo").mock(
        return_value=httpx.Response(500, text="upstream broke")
    )
    status, body = await client.post(
        "https://api.example.com/v1", "k", "/foo", {}, {}
    )
    assert status == 500
    assert body == {"error": {"message": "upstream broke"}}


async def test_get_client_reuses_per_base_and_key(client):
    c1 = await client._get_client("https://api.example.com", "key1")
    c2 = await client._get_client("https://api.example.com", "key1")
    assert c1 is c2


async def test_get_client_different_keys_get_different_clients(client):
    c1 = await client._get_client("https://api.example.com", "key1")
    c2 = await client._get_client("https://api.example.com", "key2")
    assert c1 is not c2


@respx.mock
async def test_post_stream_filters_done_and_blanks(client):
    body = (
        b'data: {"id":"1","created":1,"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"a"}}]}\n\n'
        b"\n"
        b'data: {"id":"1","created":1,"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"b"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
    )

    chunks = []
    async for chunk in client.post_stream(
        "https://api.example.com/v1", "k", "/chat/completions", {}, {}
    ):
        chunks.append(chunk)
    assert len(chunks) == 2
    assert chunks[0]["choices"][0]["delta"]["content"] == "a"
    assert chunks[1]["choices"][0]["delta"]["content"] == "b"


@respx.mock
async def test_post_stream_4xx_raises_streaming_http_error(client):
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": {"message": "too fast", "code": "rate_limit_exceeded"}})
    )

    with pytest.raises(_StreamingHTTPError) as exc_info:
        async for _ in client.post_stream(
            "https://api.example.com/v1", "k", "/chat/completions", {}, {}
        ):
            pass
    assert exc_info.value.status_code == 429
    assert exc_info.value.body["error"]["message"] == "too fast"


def test_get_http_client_returns_singleton():
    a = get_http_client()
    b = get_http_client()
    assert a is b
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_sdk/test_http_client.py -v 2>&1 | tail -5
```

Expected: ImportError on `app.sdk.http_client`.

- [ ] **Step 3: Implement `http_client.py`**

Create `src/app/sdk/http_client.py`:

```python
import asyncio
import json
from typing import AsyncIterator

import httpx


class _StreamingHTTPError(Exception):
    """Raised internally when post_stream sees a 4xx/5xx before yielding."""

    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.body = body


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
        self,
        api_base: str,
        api_key: str,
        path: str,
        headers: dict,
        json_body: dict,
        timeout: float | None = None,
    ) -> tuple[int, dict]:
        client = await self._get_client(api_base, api_key)
        resp = await client.post(
            path,
            headers=headers,
            json=json_body,
            timeout=timeout or self._default_timeout,
        )
        try:
            body = resp.json()
        except json.JSONDecodeError:
            body = {"error": {"message": resp.text}}
        return resp.status_code, body

    async def post_stream(
        self,
        api_base: str,
        api_key: str,
        path: str,
        headers: dict,
        json_body: dict,
        timeout: float | None = None,
    ) -> AsyncIterator[dict]:
        """Yield parsed JSON dicts from an SSE stream.

        Filters '[DONE]' sentinels and blank/non-data lines.
        """
        client = await self._get_client(api_base, api_key)
        async with client.stream(
            "POST",
            path,
            headers=headers,
            json=json_body,
            timeout=timeout or self._default_timeout,
        ) as resp:
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
                payload = line[len("data: ") :].strip()
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


_default_client: LLMHttpClient | None = None


def get_http_client() -> LLMHttpClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMHttpClient()
    return _default_client
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_sdk/test_http_client.py -v 2>&1 | tail -10
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/app/sdk/http_client.py tests/test_sdk/test_http_client.py
git commit -m "feat(sdk): add LLMHttpClient (pooled httpx) with SSE streaming + error mapping"
```

---

### Task 7: OpenAI provider — request side (headers, api_base, transform_request)

**Files:**
- Create: `src/app/sdk/providers/openai.py`
- Modify: `src/app/sdk/providers/__init__.py`
- Create: `tests/test_sdk/providers/test_openai.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_sdk/providers/test_openai.py`:

```python
import os

from app.sdk.providers.openai import DEFAULT_API_BASE, OpenAIProvider


def test_get_api_base_default():
    p = OpenAIProvider()
    assert p.get_api_base("gpt-4o", None) == DEFAULT_API_BASE


def test_get_api_base_explicit_override():
    p = OpenAIProvider()
    assert p.get_api_base("gpt-4o", "https://my-proxy/v1") == "https://my-proxy/v1"


def test_get_api_base_strips_trailing_slash():
    p = OpenAIProvider()
    assert p.get_api_base("gpt-4o", "https://my-proxy/v1/") == "https://my-proxy/v1"


def test_get_api_base_env_var(monkeypatch):
    monkeypatch.setenv("OPENAI_API_BASE", "https://env-proxy/v1")
    p = OpenAIProvider()
    assert p.get_api_base("gpt-4o", None) == "https://env-proxy/v1"


def test_get_headers_includes_bearer():
    p = OpenAIProvider()
    headers = p.get_headers("sk-secret", None)
    assert headers["Authorization"] == "Bearer sk-secret"
    assert headers["Content-Type"] == "application/json"


def test_get_headers_merges_extra():
    p = OpenAIProvider()
    headers = p.get_headers("sk-secret", {"X-Trace-Id": "abc"})
    assert headers["X-Trace-Id"] == "abc"
    assert headers["Authorization"] == "Bearer sk-secret"


def test_transform_request_includes_model_and_messages():
    p = OpenAIProvider()
    body = p.transform_request(
        "gpt-4o",
        [{"role": "user", "content": "hi"}],
        {},
    )
    assert body["model"] == "gpt-4o"
    assert body["messages"] == [{"role": "user", "content": "hi"}]


def test_transform_request_forwards_allowlisted_params():
    p = OpenAIProvider()
    body = p.transform_request(
        "gpt-4o",
        [],
        {"temperature": 0.7, "max_tokens": 100, "stream": True},
    )
    assert body["temperature"] == 0.7
    assert body["max_tokens"] == 100
    assert body["stream"] is True


def test_transform_request_drops_none_values():
    p = OpenAIProvider()
    body = p.transform_request(
        "gpt-4o",
        [],
        {"temperature": None, "max_tokens": 10},
    )
    assert "temperature" not in body
    assert body["max_tokens"] == 10


def test_transform_request_drops_unknown_keys():
    p = OpenAIProvider()
    body = p.transform_request(
        "gpt-4o",
        [],
        {"temperature": 0.5, "made_up_param": "x", "cache": True},
    )
    assert "made_up_param" not in body
    assert "cache" not in body
    assert body["temperature"] == 0.5


def test_provider_is_registered():
    """Importing the module side-effects register_provider('openai', ...)."""
    from app.sdk.providers.base import PROVIDER_REGISTRY

    assert PROVIDER_REGISTRY["openai"] is OpenAIProvider
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_sdk/providers/test_openai.py -v 2>&1 | tail -5
```

Expected: ImportError on `app.sdk.providers.openai`.

- [ ] **Step 3: Implement the request side of `openai.py`**

Create `src/app/sdk/providers/openai.py`:

```python
import os

from app.sdk.providers.base import BaseProvider, register_provider
from app.sdk.types import ModelResponse, ModelResponseStream

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
        return (
            api_base
            or os.environ.get("OPENAI_API_BASE")
            or DEFAULT_API_BASE
        ).rstrip("/")

    def get_headers(self, api_key: str, extra_headers: dict | None) -> dict:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def transform_request(
        self, model: str, messages: list[dict], params: dict
    ) -> dict:
        body: dict = {"model": model, "messages": messages}
        for k, v in params.items():
            if k in _FORWARDED_PARAMS and v is not None:
                body[k] = v
        return body

    def transform_response(self, raw: dict, model: str) -> ModelResponse:
        raise NotImplementedError  # implemented in Task 8

    def transform_stream_chunk(
        self, chunk: dict, model: str
    ) -> ModelResponseStream | None:
        raise NotImplementedError  # implemented in Task 8

    def get_error_class(self, status_code: int, body: dict) -> Exception:
        raise NotImplementedError  # implemented in Task 8


register_provider("openai", OpenAIProvider)
```

- [ ] **Step 4: Update `providers/__init__.py` to trigger registration**

Replace `src/app/sdk/providers/__init__.py` with:

```python
"""Side-effect import: registers each provider into PROVIDER_REGISTRY."""
from app.sdk.providers import openai  # noqa: F401  registers "openai"
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_sdk/providers/test_openai.py -v 2>&1 | tail -15
```

Expected: 11 passed.

- [ ] **Step 6: Commit**

```bash
git add src/app/sdk/providers/openai.py src/app/sdk/providers/__init__.py tests/test_sdk/providers/test_openai.py
git commit -m "feat(sdk): OpenAI provider — headers, api_base, transform_request"
```

---

### Task 8: OpenAI provider — response side + error mapping

**Files:**
- Modify: `src/app/sdk/providers/openai.py`
- Modify: `tests/test_sdk/providers/test_openai.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sdk/providers/test_openai.py`:

```python
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
    TimeoutError as SdkTimeoutError,
)


# ---- transform_response ----

def test_transform_response_basic():
    raw = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "gpt-4o-2024-08-06",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }
    p = OpenAIProvider()
    resp = p.transform_response(raw, "gpt-4o")
    assert resp.id == "chatcmpl-1"
    assert resp.created == 1700000000
    assert resp.model == "gpt-4o-2024-08-06"
    assert resp.choices[0].message.content == "ok"
    assert resp.choices[0].finish_reason == "stop"
    assert resp.usage.prompt_tokens == 10
    assert resp.usage.cost is None  # populated by dispatcher, not provider


def test_transform_response_with_tool_calls():
    raw = {
        "id": "chatcmpl-2",
        "created": 1700000001,
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"city":"sf"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }
    p = OpenAIProvider()
    resp = p.transform_response(raw, "gpt-4o")
    msg = resp.choices[0].message
    assert msg.content is None
    assert msg.tool_calls[0].function.name == "get_weather"
    assert msg.tool_calls[0].function.arguments == '{"city":"sf"}'
    assert resp.choices[0].finish_reason == "tool_calls"
    assert resp.usage is None  # absent in raw


def test_transform_response_synthesizes_id_if_missing():
    raw = {
        "created": 1700000000,
        "model": "gpt-4o",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "x"}, "finish_reason": "stop"}
        ],
    }
    p = OpenAIProvider()
    resp = p.transform_response(raw, "gpt-4o")
    assert resp.id.startswith("chatcmpl-")


# ---- transform_stream_chunk ----

def test_transform_stream_chunk_content_delta():
    chunk = {
        "id": "chatcmpl-1",
        "created": 1700000000,
        "model": "gpt-4o",
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hel"}}],
    }
    p = OpenAIProvider()
    parsed = p.transform_stream_chunk(chunk, "gpt-4o")
    assert parsed.choices[0].delta.role == "assistant"
    assert parsed.choices[0].delta.content == "Hel"


def test_transform_stream_chunk_tool_call_delta():
    chunk = {
        "id": "chatcmpl-1",
        "created": 1700000000,
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"ci'},
                        }
                    ]
                },
            }
        ],
    }
    p = OpenAIProvider()
    parsed = p.transform_stream_chunk(chunk, "gpt-4o")
    tc = parsed.choices[0].delta.tool_calls[0]
    assert tc.id == "call_1"
    assert tc.function.name == "get_weather"
    assert tc.function.arguments == '{"ci'  # partial — passthrough


def test_transform_stream_chunk_returns_none_when_no_choices():
    p = OpenAIProvider()
    assert p.transform_stream_chunk({}, "gpt-4o") is None
    assert p.transform_stream_chunk({"id": "x"}, "gpt-4o") is None


def test_transform_stream_chunk_final_chunk_includes_usage():
    chunk = {
        "id": "chatcmpl-1",
        "created": 1700000000,
        "model": "gpt-4o",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }
    p = OpenAIProvider()
    parsed = p.transform_stream_chunk(chunk, "gpt-4o")
    assert parsed.usage.total_tokens == 13


# ---- get_error_class ----

def test_error_401_authentication():
    p = OpenAIProvider()
    err = p.get_error_class(401, {"error": {"message": "bad key"}})
    assert isinstance(err, AuthenticationError)
    assert err.status_code == 401


def test_error_404_not_found():
    p = OpenAIProvider()
    assert isinstance(
        p.get_error_class(404, {"error": {"message": "no such model"}}),
        NotFoundError,
    )


def test_error_408_timeout():
    p = OpenAIProvider()
    assert isinstance(
        p.get_error_class(408, {"error": {"message": "slow"}}),
        SdkTimeoutError,
    )


def test_error_429_rate_limit():
    p = OpenAIProvider()
    assert isinstance(
        p.get_error_class(429, {"error": {"message": "too fast"}}),
        RateLimitError,
    )


def test_error_400_context_length_exceeded():
    p = OpenAIProvider()
    err = p.get_error_class(
        400,
        {"error": {"message": "too long", "code": "context_length_exceeded"}},
    )
    assert isinstance(err, ContextWindowExceededError)


def test_error_400_content_filter():
    p = OpenAIProvider()
    err = p.get_error_class(
        400, {"error": {"message": "bad", "code": "content_filter"}}
    )
    assert isinstance(err, ContentPolicyViolationError)


def test_error_400_generic_bad_request():
    p = OpenAIProvider()
    assert isinstance(
        p.get_error_class(400, {"error": {"message": "nope"}}),
        BadRequestError,
    )


def test_error_503_service_unavailable():
    p = OpenAIProvider()
    assert isinstance(
        p.get_error_class(503, {"error": {"message": "down"}}),
        ServiceUnavailableError,
    )


def test_error_500_internal():
    p = OpenAIProvider()
    assert isinstance(
        p.get_error_class(500, {"error": {"message": "boom"}}),
        InternalServerError,
    )


def test_error_unknown_status_falls_back_to_litellm_error():
    p = OpenAIProvider()
    err = p.get_error_class(418, {"error": {"message": "teapot"}})
    assert type(err) is LiteLLMError
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_sdk/providers/test_openai.py -v 2>&1 | tail -10
```

Expected: NotImplementedError raised by the stub methods.

- [ ] **Step 3: Implement `transform_response`, `transform_stream_chunk`, and `get_error_class`**

Replace the three `raise NotImplementedError` methods in `src/app/sdk/providers/openai.py` with full implementations. Also update the imports.

Replace this block at the top of the file:

```python
import os

from app.sdk.providers.base import BaseProvider, register_provider
from app.sdk.types import ModelResponse, ModelResponseStream
```

with:

```python
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
```

Replace the three stub methods with these implementations:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_sdk/providers/test_openai.py -v 2>&1 | tail -15
```

Expected: 28 passed (11 from Task 7 + 17 new).

- [ ] **Step 5: Commit**

```bash
git add src/app/sdk/providers/openai.py tests/test_sdk/providers/test_openai.py
git commit -m "feat(sdk): OpenAI provider — transform_response, transform_stream_chunk, error mapping"
```

---

### Task 9: model_prices.json + cost calculator

**Files:**
- Create: `src/app/sdk/model_prices.json`
- Create: `src/app/sdk/cost.py`
- Create: `tests/test_sdk/test_cost.py`

- [ ] **Step 1: Create the price catalog**

Create `src/app/sdk/model_prices.json` with exactly this content (USD per token):

```json
{
  "openai/gpt-4o": {
    "input_cost_per_token": 2.5e-6,
    "output_cost_per_token": 1.0e-5,
    "max_input_tokens": 128000,
    "max_output_tokens": 16384,
    "supports_tools": true,
    "supports_vision": true,
    "mode": "chat"
  },
  "openai/gpt-4o-mini": {
    "input_cost_per_token": 1.5e-7,
    "output_cost_per_token": 6.0e-7,
    "max_input_tokens": 128000,
    "max_output_tokens": 16384,
    "supports_tools": true,
    "supports_vision": true,
    "mode": "chat"
  },
  "openai/gpt-4-turbo": {
    "input_cost_per_token": 1.0e-5,
    "output_cost_per_token": 3.0e-5,
    "max_input_tokens": 128000,
    "max_output_tokens": 4096,
    "supports_tools": true,
    "supports_vision": true,
    "mode": "chat"
  },
  "openai/gpt-3.5-turbo": {
    "input_cost_per_token": 5.0e-7,
    "output_cost_per_token": 1.5e-6,
    "max_input_tokens": 16385,
    "max_output_tokens": 4096,
    "supports_tools": true,
    "supports_vision": false,
    "mode": "chat"
  }
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_sdk/test_cost.py`:

```python
import pytest

from app.sdk import cost as cost_module
from app.sdk.cost import calculate_cost
from app.sdk.types import Usage


def _reset_cache():
    cost_module._prices = None


def test_known_model_returns_usd():
    _reset_cache()
    usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    c = calculate_cost("openai/gpt-4o-mini", usage)
    # 1000 * 1.5e-7 + 500 * 6.0e-7 = 0.00015 + 0.0003 = 0.00045
    assert c == pytest.approx(0.00045, rel=1e-9)


def test_unknown_model_returns_none():
    _reset_cache()
    usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    assert calculate_cost("openai/imaginary-model", usage) is None


def test_zero_tokens_returns_zero():
    _reset_cache()
    usage = Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    assert calculate_cost("openai/gpt-4o", usage) == 0.0


def test_loads_json_only_once():
    _reset_cache()
    usage = Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    calculate_cost("openai/gpt-4o", usage)
    cached = cost_module._prices
    assert cached is not None
    calculate_cost("openai/gpt-4o-mini", usage)
    assert cost_module._prices is cached  # same object, no re-read


def test_catalog_locked_to_known_prices():
    """Pin the catalog so a typo in JSON fails CI loudly."""
    _reset_cache()
    prices = cost_module._load()
    assert prices["openai/gpt-4o"]["input_cost_per_token"] == 2.5e-6
    assert prices["openai/gpt-4o-mini"]["output_cost_per_token"] == 6.0e-7
    assert prices["openai/gpt-3.5-turbo"]["input_cost_per_token"] == 5.0e-7
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest tests/test_sdk/test_cost.py -v 2>&1 | tail -5
```

Expected: ImportError on `app.sdk.cost`.

- [ ] **Step 4: Implement `cost.py`**

Create `src/app/sdk/cost.py`:

```python
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
    """Compute USD cost for a usage record. Returns None if model is unknown.

    `model` is the full 'provider/bare' string, matching JSON keys.
    """
    info = _load().get(model)
    if not info:
        return None
    return (
        usage.prompt_tokens * info.get("input_cost_per_token", 0.0)
        + usage.completion_tokens * info.get("output_cost_per_token", 0.0)
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_sdk/test_cost.py -v 2>&1 | tail -10
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/app/sdk/cost.py src/app/sdk/model_prices.json tests/test_sdk/test_cost.py
git commit -m "feat(sdk): add cost calculator + 4-model OpenAI price catalog"
```

---

### Task 10: StreamWrapper class

**Files:**
- Modify: `src/app/sdk/types.py`
- Modify: `tests/test_sdk/test_types.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sdk/test_types.py`:

```python
class _FakeProvider:
    """Minimal stand-in for BaseProvider — we only need transform_stream_chunk
    and get_error_class for these tests."""

    def __init__(self):
        self.errors_raised: list = []

    def transform_stream_chunk(self, chunk, model):
        if chunk == {"skip": True}:
            return None
        return ModelResponseStream(
            id=chunk["id"],
            created=chunk["created"],
            model=model,
            choices=[StreamChoice(index=0, delta=Delta(content=chunk.get("content", "")))],
        )

    def get_error_class(self, status_code, body):
        return RuntimeError(f"{status_code}: {body}")


async def _gen(items):
    for x in items:
        yield x


async def test_stream_wrapper_iterates_chunks():
    from app.sdk.types import StreamWrapper

    provider = _FakeProvider()
    chunks = [
        {"id": "c1", "created": 1, "content": "Hel"},
        {"id": "c2", "created": 2, "content": "lo"},
    ]
    wrapper = StreamWrapper(_gen(chunks), provider, "gpt-4o")
    out = []
    async for chunk in wrapper:
        out.append(chunk)
    assert len(out) == 2
    assert out[0].choices[0].delta.content == "Hel"
    assert out[1].choices[0].delta.content == "lo"


async def test_stream_wrapper_skips_none_returns_from_provider():
    from app.sdk.types import StreamWrapper

    provider = _FakeProvider()
    chunks = [
        {"id": "c1", "created": 1, "content": "a"},
        {"skip": True},
        {"id": "c2", "created": 2, "content": "b"},
    ]
    wrapper = StreamWrapper(_gen(chunks), provider, "gpt-4o")
    out = [c async for c in wrapper]
    assert len(out) == 2


async def test_stream_wrapper_aclose_calls_underlying():
    from app.sdk.types import StreamWrapper

    closed = {"v": False}

    async def gen():
        try:
            yield {"id": "c1", "created": 1, "content": "x"}
        finally:
            closed["v"] = True

    g = gen()
    wrapper = StreamWrapper(g, _FakeProvider(), "gpt-4o")
    # consume one then close
    await wrapper.__anext__()
    await wrapper.aclose()
    assert closed["v"] is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_sdk/test_types.py::test_stream_wrapper_iterates_chunks -v 2>&1 | tail -5
```

Expected: ImportError on `StreamWrapper`.

- [ ] **Step 3: Append `StreamWrapper` to `types.py`**

Append to `src/app/sdk/types.py`:

```python
class StreamWrapper:
    """Async iterator wrapping a parsed-chunk source. Owns the response lifecycle.

    The underlying source yields parsed dicts (already SSE-decoded by
    LLMHttpClient.post_stream). Each dict is passed through the provider's
    transform_stream_chunk, which returns a ModelResponseStream or None
    (skip).
    """

    def __init__(self, chunk_iter, provider, model: str):
        self._chunk_iter = chunk_iter
        self._provider = provider
        self._model = model

    def __aiter__(self) -> "StreamWrapper":
        return self

    async def __anext__(self) -> ModelResponseStream:
        from app.sdk.http_client import _StreamingHTTPError

        try:
            chunk = await self._chunk_iter.__anext__()
        except _StreamingHTTPError as e:
            raise self._provider.get_error_class(e.status_code, e.body) from None
        result = self._provider.transform_stream_chunk(chunk, self._model)
        if result is None:
            return await self.__anext__()
        return result

    async def aclose(self) -> None:
        if hasattr(self._chunk_iter, "aclose"):
            await self._chunk_iter.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_sdk/test_types.py -v 2>&1 | tail -10
```

Expected: 11 passed (8 from Tasks 2+3, plus 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/app/sdk/types.py tests/test_sdk/test_types.py
git commit -m "feat(sdk): add StreamWrapper async iterator"
```

---

### Task 11: acompletion dispatcher (non-streaming)

**Files:**
- Create: `src/app/sdk/main.py`
- Create: `tests/test_sdk/test_acompletion.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_sdk/test_acompletion.py`:

```python
import httpx
import pytest
import respx

from app.sdk import http_client as http_client_module
from app.sdk.exceptions import AuthenticationError, RateLimitError
from app.sdk.main import acompletion
from app.sdk.types import ModelResponse


@pytest.fixture(autouse=True)
def _reset_http_client_singleton():
    """Each test gets a fresh LLMHttpClient so respx mocks don't bleed."""
    http_client_module._default_client = None
    yield
    http_client_module._default_client = None


@respx.mock
async def test_acompletion_happy_path():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "created": 1700000000,
                "model": "gpt-4o-mini-2024-07-18",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 1,
                    "total_tokens": 11,
                },
            },
        )
    )

    resp = await acompletion(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-test",
    )
    assert isinstance(resp, ModelResponse)
    assert resp.choices[0].message.content == "ok"
    assert resp.usage.cost is not None
    assert resp.usage.cost == pytest.approx(
        10 * 1.5e-7 + 1 * 6.0e-7, rel=1e-9
    )


@respx.mock
async def test_acompletion_unknown_model_cost_is_none():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-2",
                "created": 1700000000,
                "model": "openai/imaginary",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 1,
                    "total_tokens": 6,
                },
            },
        )
    )
    resp = await acompletion(
        model="openai/imaginary",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-test",
    )
    assert resp.usage.cost is None


async def test_acompletion_missing_api_key_and_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(AuthenticationError, match="No api_key"):
        await acompletion(
            model="openai/gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        )


async def test_acompletion_uses_env_key_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "x",
                    "created": 1,
                    "model": "gpt-4o",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        )
        await acompletion(
            model="openai/gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        )
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-from-env"


@respx.mock
async def test_acompletion_429_maps_to_rate_limit_error():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            429, json={"error": {"message": "slow down"}}
        )
    )
    with pytest.raises(RateLimitError):
        await acompletion(
            model="openai/gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            api_key="sk-test",
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_sdk/test_acompletion.py -v 2>&1 | tail -5
```

Expected: ImportError on `app.sdk.main`.

- [ ] **Step 3: Implement non-streaming `acompletion`**

Create `src/app/sdk/main.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_sdk/test_acompletion.py -v 2>&1 | tail -10
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/app/sdk/main.py tests/test_sdk/test_acompletion.py
git commit -m "feat(sdk): acompletion() non-streaming dispatcher with cost patching"
```

---

### Task 12: acompletion dispatcher (streaming)

**Files:**
- Modify: `src/app/sdk/main.py`
- Modify: `tests/test_sdk/test_acompletion.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sdk/test_acompletion.py`:

```python
from app.sdk.types import ModelResponseStream, StreamWrapper


@respx.mock
async def test_acompletion_stream_returns_wrapper():
    body = (
        b'data: {"id":"c1","created":1,"model":"gpt-4o","choices":[{"index":0,"delta":{"role":"assistant","content":"He"}}]}\n\n'
        b'data: {"id":"c1","created":1,"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"llo"},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )
    )

    result = await acompletion(
        model="openai/gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-test",
        stream=True,
    )
    assert isinstance(result, StreamWrapper)

    chunks: list[ModelResponseStream] = []
    async for chunk in result:
        chunks.append(chunk)
    assert len(chunks) == 2
    assert chunks[0].choices[0].delta.content == "He"
    assert chunks[1].choices[0].delta.content == "llo"
    assert chunks[1].choices[0].finish_reason == "stop"


@respx.mock
async def test_acompletion_stream_429_raises_on_first_anext():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            429, json={"error": {"message": "slow"}}
        )
    )

    result = await acompletion(
        model="openai/gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-test",
        stream=True,
    )
    with pytest.raises(RateLimitError):
        async for _ in result:
            pass
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_sdk/test_acompletion.py::test_acompletion_stream_returns_wrapper -v 2>&1 | tail -5
```

Expected: NotImplementedError raised by the stub stream branch.

- [ ] **Step 3: Replace the streaming stub in `main.py`**

In `src/app/sdk/main.py`, replace:

```python
    if stream:
        raise NotImplementedError("streaming wired up in next task")
```

with:

```python
    if stream:
        chunk_iter = client.post_stream(
            base, resolved_key, path, headers, body, timeout=timeout
        )
        return StreamWrapper(chunk_iter, provider, bare_model)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_sdk/test_acompletion.py -v 2>&1 | tail -10
```

Expected: 7 passed (5 from Task 11 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/app/sdk/main.py tests/test_sdk/test_acompletion.py
git commit -m "feat(sdk): acompletion() streaming branch via StreamWrapper"
```

---

### Task 13: Public re-exports

**Files:**
- Modify: `src/app/sdk/__init__.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sdk/test_acompletion.py`:

```python
def test_public_imports():
    """The public surface — what callers should be able to import."""
    from app.sdk import (
        AuthenticationError,
        BadRequestError,
        Choice,
        ContentPolicyViolationError,
        ContextWindowExceededError,
        Delta,
        FunctionCall,
        InternalServerError,
        LiteLLMError,
        Message,
        ModelResponse,
        ModelResponseStream,
        NotFoundError,
        RateLimitError,
        ServiceUnavailableError,
        StreamChoice,
        StreamWrapper,
        ToolCall,
        UnknownProviderError,
        Usage,
        acompletion,
    )

    # Sanity: callable, types are types
    assert callable(acompletion)
    assert isinstance(ModelResponse, type)
    assert issubclass(AuthenticationError, LiteLLMError)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_sdk/test_acompletion.py::test_public_imports -v 2>&1 | tail -5
```

Expected: ImportError on most names.

- [ ] **Step 3: Replace `src/app/sdk/__init__.py`**

Replace `src/app/sdk/__init__.py` with:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_sdk/test_acompletion.py::test_public_imports -v 2>&1 | tail -5
```

Expected: 1 passed.

- [ ] **Step 5: Run the full SDK suite to confirm nothing regressed**

```bash
uv run pytest tests/test_sdk/ -v 2>&1 | tail -3
```

Expected: ~46 tests passed (1 + 5 + 8 + 11 + 4 + 2 + 4 + 7 + 28 = depends on exact counts; the key is "all pass").

- [ ] **Step 6: Commit**

```bash
git add src/app/sdk/__init__.py
git commit -m "feat(sdk): public re-exports — acompletion + types + exceptions"
```

---

### Task 14: Register `live` pytest marker

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update the `[tool.pytest.ini_options]` block**

Open `pyproject.toml`. Replace the existing `[tool.pytest.ini_options]` block with:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
addopts = "-m 'not e2e and not live'"
markers = [
    "e2e: full end-to-end tests that boot containers and a browser; run with `pytest -m e2e`",
    "live: tests that hit real third-party APIs and need credentials; run with `pytest -m live`",
]
filterwarnings = [
    "ignore::DeprecationWarning:testcontainers",
]
```

- [ ] **Step 2: Verify the default suite still excludes everything that should be excluded**

```bash
uv run pytest --collect-only -q 2>&1 | tail -3
```

Expected: collected count matches the previous green baseline (152 default + ~46 SDK = ~198) + " deselected" if e2e is on disk.

```bash
uv run pytest -v 2>&1 | tail -3
```

Expected: all default tests pass (152 + ~46 ≈ ~198 passed, 1 e2e deselected).

- [ ] **Step 3: Verify `-m live` selects nothing yet (no live tests written)**

```bash
uv run pytest -m live -v 2>&1 | tail -3
```

Expected: `0 passed` or `no tests ran`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: register 'live' pytest marker for real-API integration tests"
```

---

### Task 15: Live test against real OpenAI

**Files:**
- Create: `tests/test_sdk/test_openai_live.py`

- [ ] **Step 1: Write the live test**

Create `tests/test_sdk/test_openai_live.py`:

```python
"""Live integration test against real OpenAI.

Skipped unless OPENAI_API_KEY is set AND `-m live` is passed.
Run: `OPENAI_API_KEY=sk-... uv run pytest -m live`
Cost: ~$0.0001 per run (gpt-4o-mini, ~5 output tokens).
"""

import os

import pytest

from app.sdk import acompletion
from app.sdk.types import ModelResponse


@pytest.mark.live
async def test_openai_chat_happy_path():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set")

    response = await acompletion(
        model="openai/gpt-4o-mini",
        messages=[
            {"role": "user", "content": 'Say "ok" and nothing else.'}
        ],
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

- [ ] **Step 2: Confirm the live test does NOT run by default**

```bash
uv run pytest -v 2>&1 | tail -3
```

Expected: same passing count as Task 14, with 1 more deselected (the live test).

- [ ] **Step 3: Confirm `-m live` SKIPS when no key is set**

```bash
unset OPENAI_API_KEY  # ensure not set
uv run pytest -m live -v 2>&1 | tail -5
```

Expected: 1 skipped, reason "OPENAI_API_KEY not set". Do NOT proceed to step 4 unless this is green.

- [ ] **Step 4: STOP — request user runs the live test with their key**

The live test calls real OpenAI and costs ~$0.0001. Do NOT run with a key from a subagent context. Surface the command to the user:

```bash
OPENAI_API_KEY=sk-... uv run pytest -m live -v
```

Expected (when the user runs it): 1 passed in ~1-3s.

- [ ] **Step 5: Commit**

```bash
git add tests/test_sdk/test_openai_live.py
git commit -m "test(sdk): add gated live test against real OpenAI gpt-4o-mini"
```

---

### Task 16: Update progress notes

**Files:**
- Modify: `/Users/makoto.sandiga/.claude/projects/-Users-makoto-sandiga-dev-me-makoto-lite-llm/memory/project_progress.md`
- Modify: `/Users/makoto.sandiga/.claude/projects/-Users-makoto-sandiga-dev-me-makoto-lite-llm/memory/MEMORY.md`

- [ ] **Step 1: Update `project_progress.md`**

Edit the file. Replace the "Auth System Progress" header with two sections — keep the auth tracker, add a Core SDK tracker:

Replace:

```markdown
## Auth System Progress (as of 2026-04-29)
```

with:

```markdown
## Auth System Progress (as of 2026-04-29)

(unchanged below)

---

## Core SDK Progress (as of <today>)
```

Then append after the auth "Remaining Work" section:

```markdown
### Completed Olas (Core SDK)

| Ola | What | PR | Tests Added |
|-----|------|----|-------------|
| 12 | OpenAI chat completions: BaseProvider ABC, registry, resolver, pooled httpx, cost calc, error mapping, streaming wrapper | #16 | ~46 unit + 1 live |

### Core SDK — Remaining Work

1. **Anthropic provider** — separate ola; same BaseProvider interface.
2. **Google Gemini provider** — separate ola.
3. **Embeddings** (OpenAI + Gemini) — separate ola.
4. **Images, audio (STT/TTS), rerank** — separate olas.
5. **Sync `completion()` wrappers** — add when a sync caller appears.
6. **`tiktoken` for pre-call estimation** — add when a caller (e.g., Router) needs it.
7. **Map `httpx.TimeoutException` → `TimeoutError`** — one-line follow-up.
8. **Replace `model_prices.json` with upstream LiteLLM export** — when more providers land.
9. **Wire `aclose_all()` to FastAPI lifespan** — when proxy routes land.
```

- [ ] **Step 2: Update `MEMORY.md`**

Replace the line:

```
- [Project Progress](project_progress.md) — Auth system done incl. Keycloak e2e, 153 tests, 15 PRs, next: Core SDK
```

with:

```
- [Project Progress](project_progress.md) — Auth done; Core SDK ola-12 (OpenAI chat) done, ~199 tests, 16 PRs, next: Anthropic provider
```

- [ ] **Step 3: No git commit needed — memory files are outside the repo.**

---

## Task Summary

| Task | Component | Tests |
|------|-----------|-------|
| 1 | Exception hierarchy | 11 |
| 2 | Response Pydantic types | 5 |
| 3 | Streaming Pydantic types | 3 |
| 4 | BaseProvider ABC + registry | 2 |
| 5 | Resolver | 4 |
| 6 | LLMHttpClient | 7 |
| 7 | OpenAI provider — request side | 11 |
| 8 | OpenAI provider — response side + errors | 17 |
| 9 | Cost calc + price catalog | 5 |
| 10 | StreamWrapper | 3 |
| 11 | acompletion (non-stream) | 5 |
| 12 | acompletion (stream) | 2 |
| 13 | Public re-exports | 1 |
| 14 | `live` pytest marker | — |
| 15 | Live test | 1 (gated) |
| 16 | Memory update | — |

**Total: ~76 SDK tests (75 default + 1 live), 16 tasks**

---

## Self-Review

**Spec coverage:** Every section of the spec has at least one task that implements it.
- §1 Scope — Tasks 11+12 (acompletion async-only, OpenAI only, stream + tools)
- §2 Public API — Task 11 (signature), Task 13 (re-exports)
- §3 Layout — file paths in every task
- §4 Types — Tasks 2, 3, 10
- §5 BaseProvider/registry/resolver — Tasks 4, 5
- §6 OpenAI provider — Tasks 7, 8
- §7 HTTP client — Task 6
- §8 Dispatcher / cost / exceptions — Tasks 1, 9, 11, 12
- §9 Testing — every task has TDD; Tasks 14, 15 add the `live` marker + live test

**Placeholder scan:** No "TBD/TODO/implement later/add error handling" anywhere except deliberate "implemented in Task 8" stubs in Task 7 (which are filled in by Task 8 in the same plan).

**Type consistency:** `_FORWARDED_PARAMS`, `DEFAULT_API_BASE`, `_StreamingHTTPError`, `_default_client`, `register_provider`, `PROVIDER_REGISTRY`, `resolve_provider`, `calculate_cost`, `get_http_client`, `acompletion` — all defined in their introducing task and used identically in subsequent tasks.
