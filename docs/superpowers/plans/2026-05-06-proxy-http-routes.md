# Proxy HTTP Routes (ola-14) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the OpenAI-compatible HTTP route layer that turns the SDK library into an actual proxy server. Authenticated clients post chat requests; the proxy enforces auth + rate-limit + budget + model-access, dispatches via the SDK, logs spend, and returns OpenAI-shape responses (or SSE streams).

**Architecture:** A single new route `POST /v1/chat/completions` in `proxy_routes.py` orchestrates pure helper functions in `proxy_guard.py` (rate-limit, budget, model-access, key resolution, error mapping). The SDK's `acompletion()` is consumed as-is — no changes to `app.sdk`. Streaming wraps the SDK's `StreamWrapper` in a FastAPI `StreamingResponse` with a `finally:` block that logs spend even on client disconnect.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0 async, Pydantic v2, httpx (async), pytest + pytest-asyncio, respx (HTTP mocking), uvicorn (for the live test harness).

**Spec:** `docs/superpowers/specs/2026-05-06-proxy-http-routes-design.md`

---

## File Structure

```
src/app/
├── routes/
│   └── proxy_routes.py           # NEW: POST /v1/chat/completions
├── services/
│   └── proxy_guard.py            # NEW: 6 helper functions (rate-limit, budget, model-access, key, estimate, error map)
├── schemas/
│   ├── wire_in/
│   │   └── chat.py               # NEW: ChatCompletionRequest, ChatMessage
│   └── wire_out/
│       └── chat.py               # NEW: error envelope + re-exports
├── auth/
│   └── dependencies.py           # MODIFY: add get_current_api_key
├── config.py                     # MODIFY: add OPENAI_API_KEY, ANTHROPIC_API_KEY
└── main.py                       # MODIFY: include proxy_router, lifespan aclose_all, OpenAI-shape error handler

tests/
├── test_routes/
│   └── test_proxy_routes.py      # NEW: ~25 route-level tests
├── test_services/
│   └── test_proxy_guard.py       # NEW: ~24 unit tests
└── test_proxy/
    ├── __init__.py               # NEW: empty package marker
    └── test_proxy_live.py        # NEW: 1 @pytest.mark.live test
```

**Untouched:** `app.sdk`, models, all other auth/services/routes/schemas. The proxy is purely additive.

**Validation criterion (from spec):** if any task surfaces a need to change `app.sdk`, stop and decide before continuing. The SDK was designed to be the source of truth for provider behavior; the proxy layer should consume it without leakage.

---

### Task 1: Config additions for provider env vars

**Goal:** Add `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` to the Settings class. Both default to `None`; only required when a request is actually made for that provider.

**Files:**
- Modify: `src/app/config.py`
- Test: existing config tests should not regress (no new test added — this is a 2-line additive change with no behavior to test directly; later tasks exercise the values)

- [ ] **Step 1: Read the existing config**

```bash
cat src/app/config.py | head -40
```

Find the `class Settings(BaseSettings):` definition.

- [ ] **Step 2: Add the two settings**

In `src/app/config.py`, inside the `Settings` class, add after the existing settings (preserve alphabetical or section ordering if the file has it; otherwise append at the end of the class):

```python
    # Upstream LLM provider keys (used by the proxy when dispatching via the SDK)
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
```

- [ ] **Step 3: Verify the app still starts cleanly**

```bash
uv run python -c "from app.config import settings; print(settings.openai_api_key, settings.anthropic_api_key)"
```

Expected output: `None None` (both unset by default).

- [ ] **Step 4: Run the full default suite to confirm no regression**

```bash
uv run pytest tests/test_sdk/ -v 2>&1 | tail -3
```

Expected: same pass count as on `main` (no impact on SDK tests).

- [ ] **Step 5: Run linters**

```bash
uv run ruff check src/app/config.py
uv run mypy src/app/config.py
```

Both must be clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/config.py
git commit -m "feat(config): add OPENAI_API_KEY and ANTHROPIC_API_KEY env settings for the proxy"
```

---

### Task 2: Wire schemas (`ChatCompletionRequest` + error envelope)

**Goal:** Create the request and error response Pydantic models. Permissive on top-level extras (forward-compat for new OpenAI fields), strict on `messages` and `model`.

**Files:**
- Create: `src/app/schemas/wire_in/chat.py`
- Create: `src/app/schemas/wire_out/chat.py`
- Create: `tests/test_routes/test_chat_schemas.py` (small schema-only tests — separate from the full route tests in Task 11)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_routes/test_chat_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from app.schemas.wire_in.chat import ChatCompletionRequest, ChatMessage
from app.schemas.wire_out.chat import (
    ChatCompletionErrorBody,
    ChatCompletionErrorResponse,
)


def test_chat_message_basic():
    m = ChatMessage(role="user", content="hi")
    assert m.role == "user"
    assert m.content == "hi"


def test_chat_message_content_can_be_none():
    """Tool-call assistant messages have content=None."""
    m = ChatMessage(role="assistant", content=None)
    assert m.content is None


def test_chat_message_content_can_be_list_of_dicts():
    """Multimodal/tool-result messages have list content."""
    m = ChatMessage(
        role="tool",
        content=[{"type": "text", "text": "result"}],
    )
    assert m.content == [{"type": "text", "text": "result"}]


def test_chat_message_extra_fields_allowed():
    """OpenAI ships new message fields; we tolerate them."""
    m = ChatMessage(role="assistant", content=None, tool_calls=[{"id": "x"}])
    assert m.tool_calls == [{"id": "x"}]


def test_request_basic():
    req = ChatCompletionRequest(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert req.model == "openai/gpt-4o-mini"
    assert len(req.messages) == 1
    assert req.stream is False  # default


def test_request_rejects_empty_messages():
    with pytest.raises(ValidationError):
        ChatCompletionRequest(model="openai/gpt-4o-mini", messages=[])


def test_request_extra_fields_allowed():
    """Unknown top-level fields pass through; SDK allowlists what's forwarded."""
    req = ChatCompletionRequest(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        future_param_we_dont_know_about=42,
    )
    # Pydantic stores extras; access via model_extra
    assert req.model_extra == {"future_param_we_dont_know_about": 42}


def test_request_does_not_validate_provider_prefix():
    """Bare model names must reach the SDK resolver, which raises UnknownProviderError."""
    # Schema accepts any string for `model`. The route translates the SDK
    # exception to HTTP 400 + model_not_found.
    req = ChatCompletionRequest(
        model="bare-model-name",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert req.model == "bare-model-name"


def test_error_envelope_serializes():
    body = ChatCompletionErrorBody(
        message="bad", type="invalid_request_error", code="bad_request"
    )
    env = ChatCompletionErrorResponse(error=body)
    dumped = env.model_dump()
    assert dumped == {
        "error": {
            "message": "bad",
            "type": "invalid_request_error",
            "code": "bad_request",
        }
    }
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_routes/test_chat_schemas.py -v 2>&1 | tail -5
```

Expected: ImportError on `app.schemas.wire_in.chat`.

- [ ] **Step 3: Implement `wire_in/chat.py`**

Create `src/app/schemas/wire_in/chat.py`:

```python
from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    """One message in the conversation.

    Permissive on extras so tool-result and multimodal shapes pass through;
    the SDK's per-provider transform_request handles the actual wire format.
    """

    model_config = ConfigDict(extra="allow")

    role: str
    content: str | list[dict] | None = None


class ChatCompletionRequest(BaseModel):
    """OpenAI-shape /v1/chat/completions request body.

    Permissive on top-level extras — OpenAI ships new fields constantly,
    and we don't want to fail requests at the proxy boundary. The SDK's
    per-provider _FORWARDED_PARAMS allowlist controls what's actually sent
    upstream.
    """

    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage] = Field(min_length=1)

    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    stop: str | list[str] | None = None
    user: str | None = None

    tools: list[dict] | None = None
    tool_choice: str | dict | None = None

    response_format: dict | None = None
    seed: int | None = None
    n: int | None = None

    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    logit_bias: dict | None = None
    logprobs: bool | None = None
    top_logprobs: int | None = None
    stream_options: dict | None = None
```

- [ ] **Step 4: Implement `wire_out/chat.py`**

Create `src/app/schemas/wire_out/chat.py`:

```python
"""Public response shape for /v1/chat/completions.

The SDK's ModelResponse is already OpenAI-shaped (intentional design),
so we re-export it under its OpenAI name. Same for streaming chunks
via ModelResponseStream. No translation layer needed at the route boundary.
"""

from pydantic import BaseModel

# Re-exports — kept here so callers don't reach into app.sdk internals
from app.sdk.types import (  # noqa: F401
    ModelResponse as ChatCompletionResponse,
    ModelResponseStream as ChatCompletionChunk,
)


class ChatCompletionErrorBody(BaseModel):
    message: str
    type: str
    code: str | None = None


class ChatCompletionErrorResponse(BaseModel):
    error: ChatCompletionErrorBody
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_routes/test_chat_schemas.py -v 2>&1 | tail -10
```

Expected: 9 passed.

- [ ] **Step 6: Run linters**

```bash
uv run ruff check src/app/schemas/wire_in/chat.py src/app/schemas/wire_out/chat.py tests/test_routes/test_chat_schemas.py
uv run mypy src/app/schemas/wire_in/chat.py src/app/schemas/wire_out/chat.py
```

Both must be clean.

- [ ] **Step 7: Commit**

```bash
git add src/app/schemas/wire_in/chat.py src/app/schemas/wire_out/chat.py tests/test_routes/test_chat_schemas.py
git commit -m "feat(schemas): add ChatCompletionRequest + error envelope (OpenAI-shape)"
```

---

### Task 3: `map_sdk_error` — translate SDK exceptions to HTTP

**Goal:** Pure function that maps the 11 SDK exception classes to `(http_status, openai_shape_error_body)`.

**Files:**
- Create: `src/app/services/proxy_guard.py`
- Create: `tests/test_services/test_proxy_guard.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_services/test_proxy_guard.py`:

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
    UnknownProviderError,
)
from app.services.proxy_guard import map_sdk_error


def _assert_mapped(exc, expected_status, expected_type, expected_code):
    status, body = map_sdk_error(exc)
    assert status == expected_status
    assert body["error"]["message"] == exc.message
    assert body["error"]["type"] == expected_type
    assert body["error"]["code"] == expected_code


def test_map_authentication_error():
    _assert_mapped(
        AuthenticationError(401, "bad key"),
        401, "invalid_request_error", "invalid_api_key",
    )


def test_map_rate_limit_error():
    _assert_mapped(
        RateLimitError(429, "slow down"),
        429, "rate_limit_error", "rate_limit_exceeded",
    )


def test_map_bad_request_error():
    _assert_mapped(
        BadRequestError(400, "missing field"),
        400, "invalid_request_error", "bad_request",
    )


def test_map_not_found_error():
    _assert_mapped(
        NotFoundError(404, "no such model"),
        404, "invalid_request_error", "model_not_found",
    )


def test_map_context_window_exceeded():
    _assert_mapped(
        ContextWindowExceededError(400, "too long"),
        400, "invalid_request_error", "context_length_exceeded",
    )


def test_map_content_policy_violation():
    _assert_mapped(
        ContentPolicyViolationError(400, "blocked"),
        400, "invalid_request_error", "content_filter",
    )


def test_map_internal_server_error():
    _assert_mapped(
        InternalServerError(500, "boom"),
        502, "api_error", "upstream_error",
    )


def test_map_service_unavailable_error():
    _assert_mapped(
        ServiceUnavailableError(503, "down"),
        503, "api_error", "service_unavailable",
    )


def test_map_timeout_error():
    _assert_mapped(
        SdkTimeoutError(408, "slow"),
        504, "api_error", "timeout",
    )


def test_map_unknown_provider_error():
    _assert_mapped(
        UnknownProviderError(400, "unknown provider 'foo'"),
        400, "invalid_request_error", "model_not_found",
    )


def test_map_litellm_error_fallback():
    """Direct LiteLLMError instances (not subclasses) → 500 unknown_error."""
    _assert_mapped(
        LiteLLMError(418, "teapot"),
        500, "api_error", "unknown_error",
    )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_services/test_proxy_guard.py -v 2>&1 | tail -5
```

Expected: ImportError on `app.services.proxy_guard`.

- [ ] **Step 3: Implement `proxy_guard.py` (just `map_sdk_error` for now)**

Create `src/app/services/proxy_guard.py`:

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
    UnknownProviderError,
)


def map_sdk_error(exc: LiteLLMError) -> tuple[int, dict]:
    """Translate an SDK exception into (HTTP status, OpenAI-shape error body).

    The route catches LiteLLMError, calls this, and raises HTTPException
    with the mapped status + body. The exception handler in main.py wraps
    the detail in {"error": ...} for /v1/* paths.
    """
    cls = type(exc)
    if cls is AuthenticationError:
        status, etype, code = 401, "invalid_request_error", "invalid_api_key"
    elif cls is RateLimitError:
        status, etype, code = 429, "rate_limit_error", "rate_limit_exceeded"
    elif cls is BadRequestError:
        status, etype, code = 400, "invalid_request_error", "bad_request"
    elif cls is NotFoundError:
        status, etype, code = 404, "invalid_request_error", "model_not_found"
    elif cls is ContextWindowExceededError:
        status, etype, code = 400, "invalid_request_error", "context_length_exceeded"
    elif cls is ContentPolicyViolationError:
        status, etype, code = 400, "invalid_request_error", "content_filter"
    elif cls is InternalServerError:
        status, etype, code = 502, "api_error", "upstream_error"
    elif cls is ServiceUnavailableError:
        status, etype, code = 503, "api_error", "service_unavailable"
    elif cls is SdkTimeoutError:
        status, etype, code = 504, "api_error", "timeout"
    elif cls is UnknownProviderError:
        status, etype, code = 400, "invalid_request_error", "model_not_found"
    else:
        # LiteLLMError or any other subclass — fallback
        status, etype, code = 500, "api_error", "unknown_error"

    return status, {
        "error": {
            "message": exc.message,
            "type": etype,
            "code": code,
        }
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_services/test_proxy_guard.py -v 2>&1 | tail -15
```

Expected: 11 passed.

- [ ] **Step 5: Run linters**

```bash
uv run ruff check src/app/services/proxy_guard.py tests/test_services/test_proxy_guard.py
uv run mypy src/app/services/proxy_guard.py
```

Both must be clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/services/proxy_guard.py tests/test_services/test_proxy_guard.py
git commit -m "feat(proxy): map_sdk_error — translate SDK exceptions to OpenAI-shape errors"
```

---

### Task 4: `enforce_model_access` helper

**Goal:** Wrap the existing `permission_service.resolve_model_access` for use in the proxy route. Raises HTTPException(403) on denial; no-ops for `proxy_admin` users.

**Files:**
- Modify: `src/app/services/proxy_guard.py`
- Modify: `tests/test_services/test_proxy_guard.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_services/test_proxy_guard.py`:

```python
import pytest
from fastapi import HTTPException

from app.services.proxy_guard import enforce_model_access


class _Stub:
    """Minimal stand-in for ApiKey/Team/Org with allowed_models."""
    def __init__(self, allowed_models=None):
        self.allowed_models = allowed_models


def test_enforce_model_access_allowed():
    api_key = _Stub(allowed_models=["openai/gpt-4o-mini"])
    # Should not raise
    enforce_model_access("openai/gpt-4o-mini", api_key, None, None)


def test_enforce_model_access_denied_raises_403():
    api_key = _Stub(allowed_models=["openai/gpt-4o-mini"])
    with pytest.raises(HTTPException) as exc_info:
        enforce_model_access("openai/gpt-4o", api_key, None, None)
    assert exc_info.value.status_code == 403
    assert "openai/gpt-4o" in exc_info.value.detail
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_services/test_proxy_guard.py::test_enforce_model_access_allowed -v 2>&1 | tail -5
```

Expected: ImportError on `enforce_model_access`.

- [ ] **Step 3: Update imports in `proxy_guard.py` + add `enforce_model_access`**

In `src/app/services/proxy_guard.py`, add to the existing imports near the top:

```python
from fastapi import HTTPException

from app.services.permission_service import resolve_model_access
```

Then append (after `map_sdk_error`):

```python
def enforce_model_access(
    model: str,
    api_key,  # ApiKey | None — typing left flexible to accept stubs in tests
    team,     # Team | None
    org,      # Organization | None
) -> None:
    """Raise HTTPException(403) if the model is not in any allowlist.

    Empty allowlists (None) are treated as "no restriction" by
    resolve_model_access. proxy_admin bypass is handled by the route's
    auth dep, not here — this function purely checks the allowlists.
    """
    key_models = api_key.allowed_models if api_key else None
    team_models = team.allowed_models if team else None
    org_models = org.allowed_models if org else None

    if not resolve_model_access(model, key_models, team_models, org_models):
        raise HTTPException(
            status_code=403,
            detail=f"Model '{model}' is not allowed for this key",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_services/test_proxy_guard.py -v 2>&1 | tail -5
```

Expected: 13 passed (11 prior + 2 new).

- [ ] **Step 5: Run linters**

```bash
uv run ruff check src/app/services/proxy_guard.py tests/test_services/test_proxy_guard.py
uv run mypy src/app/services/proxy_guard.py
```

Both must be clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/services/proxy_guard.py tests/test_services/test_proxy_guard.py
git commit -m "feat(proxy): enforce_model_access — raises 403 when model not in allowlist"
```

---

### Task 5: `resolve_provider_api_key` helper

**Goal:** Map a provider name (`"openai"`, `"anthropic"`) to the configured env-var key. Raise 503 if missing.

**Files:**
- Modify: `src/app/services/proxy_guard.py`
- Modify: `tests/test_services/test_proxy_guard.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_services/test_proxy_guard.py`:

```python
from app.config import Settings
from app.services.proxy_guard import resolve_provider_api_key


def test_resolve_openai_key():
    s = Settings(openai_api_key="sk-test-openai")
    assert resolve_provider_api_key("openai", s) == "sk-test-openai"


def test_resolve_anthropic_key():
    s = Settings(anthropic_api_key="sk-ant-test")
    assert resolve_provider_api_key("anthropic", s) == "sk-ant-test"


def test_resolve_missing_key_raises_503():
    s = Settings(openai_api_key=None, anthropic_api_key=None)
    with pytest.raises(HTTPException) as exc_info:
        resolve_provider_api_key("openai", s)
    assert exc_info.value.status_code == 503
    assert "openai" in exc_info.value.detail.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_services/test_proxy_guard.py::test_resolve_openai_key -v 2>&1 | tail -5
```

Expected: ImportError on `resolve_provider_api_key`.

- [ ] **Step 3: Add `resolve_provider_api_key` to `proxy_guard.py`**

In `src/app/services/proxy_guard.py`, add to imports near the top:

```python
from app.config import Settings
```

Then append:

```python
def resolve_provider_api_key(provider_name: str, settings: Settings) -> str:
    """Read the upstream provider's API key from server config.

    Per ola-14 design, provider keys live in env vars only (no per-org keys
    in this ola). Raises 503 if the env var for this provider is unset —
    a configuration error on the proxy, not the client's fault.
    """
    if provider_name == "openai":
        key = settings.openai_api_key
    elif provider_name == "anthropic":
        key = settings.anthropic_api_key
    else:
        # Unknown provider — caller's resolver should have caught this; defensive.
        raise HTTPException(
            status_code=503,
            detail=f"Provider '{provider_name}' is not configured on this proxy",
        )

    if key is None:
        raise HTTPException(
            status_code=503,
            detail=f"Provider '{provider_name}' is not configured on this proxy",
        )
    return key
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_services/test_proxy_guard.py -v 2>&1 | tail -5
```

Expected: 16 passed (13 prior + 3 new).

- [ ] **Step 5: Run linters**

```bash
uv run ruff check src/app/services/proxy_guard.py tests/test_services/test_proxy_guard.py
uv run mypy src/app/services/proxy_guard.py
```

Both must be clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/services/proxy_guard.py tests/test_services/test_proxy_guard.py
git commit -m "feat(proxy): resolve_provider_api_key — read OPENAI/ANTHROPIC keys from settings"
```

---

### Task 6: `estimate_input_tokens` helper

**Goal:** Coarse heuristic for pre-call TPM reservation. Real counts come from `ModelResponse.usage` post-call.

**Files:**
- Modify: `src/app/services/proxy_guard.py`
- Modify: `tests/test_services/test_proxy_guard.py`

- [ ] **Step 1: Append failing test**

Append to `tests/test_services/test_proxy_guard.py`:

```python
from app.schemas.wire_in.chat import ChatMessage
from app.services.proxy_guard import estimate_input_tokens


def test_estimate_input_tokens_basic():
    short = [ChatMessage(role="user", content="hi")]
    long = [ChatMessage(role="user", content="x" * 4000)]
    short_estimate = estimate_input_tokens(short)
    long_estimate = estimate_input_tokens(long)
    assert short_estimate >= 1
    assert long_estimate > short_estimate
    # Order of magnitude check: ~4000 chars ≈ ~1000 tokens (chars/4 heuristic)
    assert long_estimate >= 800
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_services/test_proxy_guard.py::test_estimate_input_tokens_basic -v 2>&1 | tail -5
```

Expected: ImportError on `estimate_input_tokens`.

- [ ] **Step 3: Add `estimate_input_tokens` to `proxy_guard.py`**

In `src/app/services/proxy_guard.py`, add to imports near the top:

```python
import json

from app.schemas.wire_in.chat import ChatMessage
```

Then append:

```python
def estimate_input_tokens(messages: list[ChatMessage]) -> int:
    """Coarse pre-call estimate: roughly chars/4.

    Used only for TPM rate-limit reservation — the real token count from
    the upstream response replaces this estimate when log_spend writes
    the SpendLog row. Under-estimates for code/non-Latin text.

    TODO(future-ola): replace with tiktoken-based counting for accuracy.
    """
    serialized = json.dumps([m.model_dump() for m in messages])
    return max(1, len(serialized) // 4)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_services/test_proxy_guard.py -v 2>&1 | tail -5
```

Expected: 17 passed (16 prior + 1 new).

- [ ] **Step 5: Run linters**

```bash
uv run ruff check src/app/services/proxy_guard.py tests/test_services/test_proxy_guard.py
uv run mypy src/app/services/proxy_guard.py
```

Both must be clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/services/proxy_guard.py tests/test_services/test_proxy_guard.py
git commit -m "feat(proxy): estimate_input_tokens — coarse chars/4 heuristic for TPM reservation"
```

---

### Task 7: `check_rate_limit` helper

**Goal:** Read RPM and TPM limits from the ApiKey, call the singleton SlidingWindowRateLimiter, raise 429 with Retry-After if exceeded.

**Files:**
- Modify: `src/app/services/proxy_guard.py`
- Modify: `tests/test_services/test_proxy_guard.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_services/test_proxy_guard.py`:

```python
from app.services.proxy_guard import check_rate_limit, get_rate_limiter
from app.services.rate_limiter import SlidingWindowRateLimiter


class _ApiKeyStub:
    def __init__(self, api_key_hash="hash1", rpm_limit=None, tpm_limit=None):
        self.api_key_hash = api_key_hash
        self.rpm_limit = rpm_limit
        self.tpm_limit = tpm_limit


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Each test gets a fresh limiter so windows don't bleed across tests."""
    from app.services import proxy_guard
    proxy_guard._rate_limiter = SlidingWindowRateLimiter()
    yield
    proxy_guard._rate_limiter = SlidingWindowRateLimiter()


async def test_check_rate_limit_no_limits_no_op():
    """ApiKey with rpm_limit=None and tpm_limit=None passes immediately."""
    api_key = _ApiKeyStub(rpm_limit=None, tpm_limit=None)
    await check_rate_limit(api_key, estimated_tokens=100)
    # No exception raised


async def test_check_rate_limit_rpm_allows():
    api_key = _ApiKeyStub(rpm_limit=5, tpm_limit=None)
    # First request — should pass
    await check_rate_limit(api_key, estimated_tokens=10)


async def test_check_rate_limit_rpm_exceeded_raises_429():
    api_key = _ApiKeyStub(rpm_limit=2, tpm_limit=None)
    # Burn the budget
    await check_rate_limit(api_key, estimated_tokens=1)
    await check_rate_limit(api_key, estimated_tokens=1)
    with pytest.raises(HTTPException) as exc_info:
        await check_rate_limit(api_key, estimated_tokens=1)
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


async def test_check_rate_limit_tpm_exceeded_raises_429():
    api_key = _ApiKeyStub(rpm_limit=None, tpm_limit=100)
    # First request OK (50 tokens)
    await check_rate_limit(api_key, estimated_tokens=50)
    # Second request would exceed 100 TPM (50 + 60 > 100)
    with pytest.raises(HTTPException) as exc_info:
        await check_rate_limit(api_key, estimated_tokens=60)
    assert exc_info.value.status_code == 429
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_services/test_proxy_guard.py::test_check_rate_limit_no_limits_no_op -v 2>&1 | tail -5
```

Expected: ImportError on `check_rate_limit`.

- [ ] **Step 3: Add the rate limiter singleton + `check_rate_limit` to `proxy_guard.py`**

In `src/app/services/proxy_guard.py`, add the import near the top:

```python
from app.services.rate_limiter import SlidingWindowRateLimiter
```

Then add at module level (above `map_sdk_error` is fine):

```python
_rate_limiter: SlidingWindowRateLimiter = SlidingWindowRateLimiter()


def get_rate_limiter() -> SlidingWindowRateLimiter:
    """Return the singleton sliding-window rate limiter.

    Tests reset _rate_limiter directly to isolate windows.
    """
    return _rate_limiter
```

Then append the function:

```python
async def check_rate_limit(api_key, estimated_tokens: int) -> None:
    """Enforce RPM and TPM limits on the given ApiKey.

    Raises HTTPException(429) with Retry-After header on the first
    exceeded limit. Order: RPM check, then TPM check.

    Scope: key-level only. Team and org limits are documented on the model
    but not enforced here; precedence rule is a future-ola decision.
    """
    limiter = get_rate_limiter()

    if api_key.rpm_limit is not None:
        result = await limiter.check_rate_limit(
            f"rpm:{api_key.api_key_hash}",
            api_key.rpm_limit,
            window_seconds=60,
        )
        if not result.allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded (RPM)",
                headers={"Retry-After": str(int(result.retry_after) + 1)},
            )

    if api_key.tpm_limit is not None:
        result = await limiter.check_rate_limit(
            f"tpm:{api_key.api_key_hash}",
            api_key.tpm_limit,
            window_seconds=60,
            increment=estimated_tokens,
        )
        if not result.allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded (TPM)",
                headers={"Retry-After": str(int(result.retry_after) + 1)},
            )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_services/test_proxy_guard.py -v 2>&1 | tail -10
```

Expected: 21 passed (17 prior + 4 new).

- [ ] **Step 5: Run linters**

```bash
uv run ruff check src/app/services/proxy_guard.py tests/test_services/test_proxy_guard.py
uv run mypy src/app/services/proxy_guard.py
```

Both must be clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/services/proxy_guard.py tests/test_services/test_proxy_guard.py
git commit -m "feat(proxy): check_rate_limit — enforce RPM + TPM via SlidingWindowRateLimiter"
```

---

### Task 8: `check_budget` helper

**Goal:** Read today's spend from `DailyKeySpend`, compare to `api_key.max_budget`, raise 429 if exceeded.

**Files:**
- Modify: `src/app/services/proxy_guard.py`
- Modify: `tests/test_services/test_proxy_guard.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_services/test_proxy_guard.py`:

```python
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7

from app.models.spend import DailyKeySpend
from app.services.proxy_guard import check_budget


class _ApiKeyWithBudget:
    """Lightweight fake of ApiKey that exposes only the fields check_budget reads."""
    def __init__(self, api_key_hash="hash1", max_budget=None):
        self.api_key_hash = api_key_hash
        self.max_budget = max_budget


async def _seed_daily_spend(
    db: AsyncSession, api_key_hash: str, spent: float, model: str = "openai/gpt-4o-mini"
):
    row = DailyKeySpend(
        id=uuid7(),
        api_key_hash=api_key_hash,
        date=date.today(),
        model=model,
        spend=spent,
        input_tokens=0,
        output_tokens=0,
        request_count=1,
    )
    db.add(row)
    await db.commit()


async def test_check_budget_no_max_budget_no_op(db_session: AsyncSession):
    api_key = _ApiKeyWithBudget(max_budget=None)
    # Should not raise
    await check_budget(db_session, api_key)


async def test_check_budget_under_budget_allows(db_session: AsyncSession):
    api_key = _ApiKeyWithBudget(api_key_hash="hashU", max_budget=0.10)
    await _seed_daily_spend(db_session, "hashU", spent=0.05)
    # Should not raise
    await check_budget(db_session, api_key)


async def test_check_budget_over_budget_raises_429(db_session: AsyncSession):
    api_key = _ApiKeyWithBudget(api_key_hash="hashO", max_budget=0.10)
    await _seed_daily_spend(db_session, "hashO", spent=0.15)
    with pytest.raises(HTTPException) as exc_info:
        await check_budget(db_session, api_key)
    assert exc_info.value.status_code == 429
    # Detail mentions both the spend and the budget
    assert "0.15" in exc_info.value.detail or "0.1500" in exc_info.value.detail
    assert "0.10" in exc_info.value.detail or "0.1" in exc_info.value.detail
```

**Note on `db_session` fixture:** the project has `tests/conftest.py` providing async `db_session` for service tests. If it doesn't (verify by `grep -n "db_session" tests/conftest.py`), add a session-scoped fixture using the existing `testcontainer` PostgreSQL pattern from `tests/test_services/test_audit_service.py`. Match whatever pattern the existing service tests use; do not invent a new one.

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_services/test_proxy_guard.py::test_check_budget_no_max_budget_no_op -v 2>&1 | tail -5
```

Expected: ImportError on `check_budget` OR `db_session` fixture not found (depending on conftest state).

- [ ] **Step 3: Implement `check_budget` in `proxy_guard.py`**

In `src/app/services/proxy_guard.py`, add to imports near the top:

```python
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.spend import DailyKeySpend
```

Then append:

```python
async def check_budget(db: AsyncSession, api_key) -> None:
    """Enforce daily budget against spend recorded in DailyKeySpend.

    Reads the sum of today's spend rows for this API key (across models)
    and compares to api_key.max_budget. Raises HTTPException(429) on exceed.

    Scope: key-level only. Team/org budgets deferred to a future ola.
    Race condition: spend updates lag the request, so a key can briefly
    overspend by one or two requests under concurrency. Documented in spec.
    """
    if api_key.max_budget is None:
        return

    today = date.today()
    result = await db.execute(
        select(DailyKeySpend.spend).where(
            DailyKeySpend.api_key_hash == api_key.api_key_hash,
            DailyKeySpend.date == today,
        )
    )
    rows = result.scalars().all()
    spent_today = sum(rows) if rows else 0.0

    if spent_today >= api_key.max_budget:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily budget exceeded: ${spent_today:.4f} / ${api_key.max_budget}"
            ),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_services/test_proxy_guard.py -v 2>&1 | tail -10
```

Expected: 24 passed (21 prior + 3 new).

- [ ] **Step 5: Run linters**

```bash
uv run ruff check src/app/services/proxy_guard.py tests/test_services/test_proxy_guard.py
uv run mypy src/app/services/proxy_guard.py
```

Both must be clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/services/proxy_guard.py tests/test_services/test_proxy_guard.py
git commit -m "feat(proxy): check_budget — enforce daily key budget via DailyKeySpend lookup"
```

---

### Task 9: `get_current_api_key` auth dependency

**Goal:** Add a sibling to `get_current_user` that returns the `ApiKey` (or `None` for JWT auth). Reuses the existing `_api_key_cache`.

**Files:**
- Modify: `src/app/auth/dependencies.py`
- Create: `tests/test_auth/test_get_current_api_key.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_auth/test_get_current_api_key.py`:

```python
import pytest
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key_auth import generate_api_key, hash_api_key
from app.auth.dependencies import _api_key_cache, get_current_api_key
from app.models.api_key import ApiKey
from app.models.user import User


def _make_request(authorization: str | None) -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    return Request({
        "type": "http",
        "headers": headers,
        "method": "GET",
        "path": "/v1/chat/completions",
    })


@pytest.fixture(autouse=True)
def _clear_cache():
    _api_key_cache.clear()
    yield
    _api_key_cache.clear()


async def test_get_current_api_key_returns_apikey_for_sk(
    db_session: AsyncSession, sample_user: User
):
    raw_key, key_hash = generate_api_key()
    api_key = ApiKey(
        api_key_hash=key_hash,
        user_id=sample_user.id,
        name="test",
    )
    db_session.add(api_key)
    await db_session.commit()

    req = _make_request(f"Bearer {raw_key}")
    result = await get_current_api_key(req, db_session)
    assert result is not None
    assert result.api_key_hash == key_hash


async def test_get_current_api_key_returns_none_for_jwt(db_session: AsyncSession):
    """JWT bearer (not sk- prefix) → no associated ApiKey → returns None."""
    req = _make_request("Bearer eyJhbGc.fake.jwt")
    result = await get_current_api_key(req, db_session)
    assert result is None
```

**Note on fixtures:** `db_session` and `sample_user` should already exist in `tests/conftest.py` from earlier auth tasks. If they don't, mirror what `tests/test_auth/test_user_service.py` (or similar) uses.

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_auth/test_get_current_api_key.py -v 2>&1 | tail -5
```

Expected: ImportError on `get_current_api_key`.

- [ ] **Step 3: Add `get_current_api_key` to `dependencies.py`**

In `src/app/auth/dependencies.py`, append at the end of the file:

```python
async def get_current_api_key(
    request: Request, db: AsyncSession = Depends(get_db)
) -> ApiKey | None:
    """Return the ApiKey for the current request, or None for JWT auth.

    Reuses the existing _api_key_cache so this is essentially free when
    paired with get_current_user (which warmed the cache). For JWT users,
    returns None — proxy routes that need limits should treat this as
    "no key-level constraints" (e.g., admins via JWT).
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1]
    if not token.startswith("sk-"):
        return None

    key_hash = hash_api_key(token)
    cached = _api_key_cache.get(key_hash)
    if cached is not None:
        api_key, _user = cached
        return api_key

    return await _lookup_api_key(db, key_hash)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_auth/test_get_current_api_key.py -v 2>&1 | tail -5
```

Expected: 2 passed.

- [ ] **Step 5: Run linters**

```bash
uv run ruff check src/app/auth/dependencies.py tests/test_auth/test_get_current_api_key.py
uv run mypy src/app/auth/dependencies.py
```

Both must be clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/auth/dependencies.py tests/test_auth/test_get_current_api_key.py
git commit -m "feat(auth): get_current_api_key dep — returns ApiKey for sk-, None for JWT"
```

---

### Task 10: Scaffold `proxy_routes.py` + `main.py` wiring

**Goal:** Create the empty router file (so main.py can include it without errors), wire it into the FastAPI app, register the SDK lifespan cleanup, install the OpenAI-shape error handler scoped to `/v1/*` paths.

**Files:**
- Create: `src/app/routes/proxy_routes.py` (router only, no handlers yet)
- Modify: `src/app/main.py`

- [ ] **Step 1: Create the empty router**

Create `src/app/routes/proxy_routes.py`:

```python
from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["proxy"])

# POST /chat/completions handler is implemented in Task 11.
```

- [ ] **Step 2: Update `main.py` — include router + lifespan + error handler**

Read `src/app/main.py`. Replace the file with:

```python
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import fastapi.exception_handlers
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.routes.auth_routes import router as auth_router
from app.routes.budget_routes import router as budget_router
from app.routes.key_routes import router as key_router
from app.routes.org_routes import router as org_router
from app.routes.proxy_routes import router as proxy_router
from app.routes.sso_routes import router as sso_router
from app.routes.team_routes import router as team_router
from app.routes.user_routes import router as user_router
from app.schemas.wire_out.common import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    # Shutdown: close pooled HTTP clients used by the SDK
    from app.sdk.http_client import get_http_client
    await get_http_client().aclose_all()


app = FastAPI(
    title=settings.app_name,
    description="Unified LLM proxy gateway",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(HTTPException)
async def openai_shape_error_handler(request: Request, exc: HTTPException):
    """OpenAI-shape error envelope for /v1/* routes; default for the rest.

    The proxy_guard helpers raise HTTPException with detail set to either
    a string (which we wrap as `{message, type, code: None}`) or a dict
    that already contains the OpenAI-shape error body (from map_sdk_error).
    """
    if not request.url.path.startswith("/v1/"):
        return await fastapi.exception_handlers.http_exception_handler(request, exc)

    if isinstance(exc.detail, dict) and "error" in exc.detail:
        # map_sdk_error produced {"error": {...}}; pass through
        body = exc.detail
    elif isinstance(exc.detail, dict):
        body = {"error": exc.detail}
    else:
        body = {
            "error": {
                "message": str(exc.detail),
                "type": "api_error",
                "code": None,
            }
        }
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=exc.headers or {},
    )


app.include_router(auth_router)
app.include_router(user_router)
app.include_router(org_router)
app.include_router(team_router)
app.include_router(key_router)
app.include_router(budget_router)
app.include_router(sso_router)
app.include_router(proxy_router)


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse()
```

- [ ] **Step 3: Verify the app starts**

```bash
uv run python -c "from app.main import app; print([r.path for r in app.routes if hasattr(r, 'path')])"
```

Expected output: list including `/health` and `/openapi.json` etc. The `/v1/chat/completions` path won't be there yet because Task 11 adds the handler.

- [ ] **Step 4: Run the full default suite to confirm no regression**

```bash
uv run pytest tests/test_sdk/ tests/test_services/ -v 2>&1 | tail -3
```

Expected: same pass count as before this task. The error handler change should not affect existing tests because none of the existing routes are under `/v1/*`.

Note: Docker-dependent service tests (audit, sso, spend) may fail in environments without Docker — that's pre-existing and unrelated.

- [ ] **Step 5: Run linters**

```bash
uv run ruff check src/app/main.py src/app/routes/proxy_routes.py
uv run mypy src/app/main.py
```

Both must be clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/main.py src/app/routes/proxy_routes.py
git commit -m "feat(main): wire proxy router + SDK lifespan cleanup + OpenAI-shape /v1/* error handler"
```

---

### Task 11: Non-streaming `POST /v1/chat/completions`

**Goal:** Implement the full handler for `stream=false` requests. Wires every guard + dispatches via the SDK + logs spend. Streaming branch follows in Task 12.

**Files:**
- Modify: `src/app/routes/proxy_routes.py`
- Create: `tests/test_routes/test_proxy_routes.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_routes/test_proxy_routes.py`:

```python
import time
from datetime import date

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key_auth import generate_api_key, hash_api_key
from app.config import settings
from app.main import app
from app.models.api_key import ApiKey
from app.models.spend import DailyKeySpend, SpendLog
from app.models.user import User
from app.sdk import http_client as sdk_http_client


# Each test resets shared singletons to avoid cross-test bleed.
@pytest.fixture(autouse=True)
def _reset_singletons():
    sdk_http_client._default_client = None
    from app.services import proxy_guard
    from app.services.rate_limiter import SlidingWindowRateLimiter
    proxy_guard._rate_limiter = SlidingWindowRateLimiter()
    yield
    sdk_http_client._default_client = None
    proxy_guard._rate_limiter = SlidingWindowRateLimiter()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
async def proxy_key(db_session: AsyncSession, sample_user: User):
    """An ApiKey with no rate-limit/budget restrictions."""
    raw_key, key_hash = generate_api_key()
    api_key = ApiKey(
        api_key_hash=key_hash,
        user_id=sample_user.id,
        name="test-proxy-key",
    )
    db_session.add(api_key)
    await db_session.commit()
    return raw_key, api_key


@pytest.fixture
def openai_key_set(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-openai")


@respx.mock
async def test_chat_completion_happy_path_openai(
    client, proxy_key, openai_key_set, db_session
):
    raw_key, api_key = proxy_key
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

    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "ok"
    assert body["usage"]["prompt_tokens"] == 10
    # Cost was computed by the dispatcher
    assert body["usage"]["cost"] is not None
    assert body["usage"]["cost"] > 0

    # SpendLog row was written
    result = await db_session.execute(
        select(SpendLog).where(SpendLog.api_key_hash == api_key.api_key_hash)
    )
    log = result.scalar_one()
    assert log.status == "completed"
    assert log.input_tokens == 10
    assert log.output_tokens == 1
    assert log.spend > 0


def test_chat_completion_missing_authorization(client):
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["type"] == "api_error"


def test_chat_completion_invalid_api_key(client):
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": "Bearer sk-not-a-real-key"},
    )
    assert resp.status_code == 401


async def test_chat_completion_blocked_key(client, db_session, sample_user):
    raw_key, key_hash = generate_api_key()
    api_key = ApiKey(
        api_key_hash=key_hash,
        user_id=sample_user.id,
        name="blocked",
        is_blocked=True,
    )
    db_session.add(api_key)
    await db_session.commit()

    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 401


async def test_chat_completion_model_not_in_allowlist(
    client, db_session, sample_user, openai_key_set
):
    raw_key, key_hash = generate_api_key()
    api_key = ApiKey(
        api_key_hash=key_hash,
        user_id=sample_user.id,
        name="restricted",
        allowed_models=["openai/gpt-4o-mini"],
    )
    db_session.add(api_key)
    await db_session.commit()

    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o",  # not in allowlist
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert "openai/gpt-4o" in body["error"]["message"]


async def test_chat_completion_rpm_exceeded(
    client, db_session, sample_user, openai_key_set
):
    raw_key, key_hash = generate_api_key()
    api_key = ApiKey(
        api_key_hash=key_hash,
        user_id=sample_user.id,
        name="rate-limited",
        rpm_limit=1,
    )
    db_session.add(api_key)
    await db_session.commit()

    with respx.mock:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "x",
                    "created": 1,
                    "model": "gpt-4o-mini",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                },
            )
        )
        # First request — allowed
        resp1 = client.post(
            "/v1/chat/completions",
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp1.status_code == 200
        # Second request in the same minute — 429
        resp2 = client.post(
            "/v1/chat/completions",
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp2.status_code == 429
        assert "Retry-After" in resp2.headers


async def test_chat_completion_budget_exceeded(
    client, db_session, sample_user, openai_key_set
):
    from uuid_extensions import uuid7
    raw_key, key_hash = generate_api_key()
    api_key = ApiKey(
        api_key_hash=key_hash,
        user_id=sample_user.id,
        name="budgeted",
        max_budget=0.01,
    )
    db_session.add(api_key)
    # Pre-seed today's spend at $0.015 (over budget)
    spend_row = DailyKeySpend(
        id=uuid7(),
        api_key_hash=key_hash,
        date=date.today(),
        model="openai/gpt-4o-mini",
        spend=0.015,
        input_tokens=0,
        output_tokens=0,
        request_count=1,
    )
    db_session.add(spend_row)
    await db_session.commit()

    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 429
    assert "budget" in resp.json()["error"]["message"].lower()


async def test_chat_completion_provider_key_missing(
    client, proxy_key, monkeypatch
):
    """Anthropic key not configured → 503."""
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    raw_key, _ = proxy_key
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "anthropic/claude-haiku-4-5-20251001",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 503


def test_chat_completion_empty_messages_422(client, proxy_key, openai_key_set):
    raw_key, _ = proxy_key
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


def test_chat_completion_missing_model_422(client, proxy_key, openai_key_set):
    raw_key, _ = proxy_key
    resp = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


@respx.mock
async def test_chat_completion_anthropic_happy_path(
    client, proxy_key, monkeypatch, db_session
):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    raw_key, api_key = proxy_key
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-4-5-20251001",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 1},
            },
        )
    )
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "anthropic/claude-haiku-4-5-20251001",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "ok"
    assert body["usage"]["prompt_tokens"] == 10


@respx.mock
async def test_chat_completion_request_id_header(
    client, proxy_key, openai_key_set, db_session
):
    raw_key, api_key = proxy_key
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "x",
                "created": 1,
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )
    )
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    request_id = resp.headers.get("X-Request-Id")
    assert request_id is not None
    # SpendLog row uses the same request_id
    result = await db_session.execute(
        select(SpendLog).where(SpendLog.request_id == request_id)
    )
    assert result.scalar_one() is not None
```

**Note on fixtures:** the existing `tests/conftest.py` provides `db_session` and `sample_user` fixtures from earlier auth tasks. If `sample_user` doesn't exist, look at `tests/test_routes/test_user_routes.py` for the pattern (typically a User row with role="proxy_admin" inserted in a fixture). The 12 tests above assume both fixtures are available.

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_routes/test_proxy_routes.py -v 2>&1 | tail -10
```

Expected: 422/404 errors because the route handler doesn't exist yet.

- [ ] **Step 3: Implement the handler**

Replace `src/app/routes/proxy_routes.py` with:

```python
import time

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7

from app.auth.dependencies import get_current_api_key, get_current_user
from app.config import settings
from app.database import get_db
from app.models.api_key import ApiKey
from app.models.organization import Organization
from app.models.team import Team
from app.models.user import User
from app.schemas.wire_in.chat import ChatCompletionRequest
from app.sdk import LiteLLMError, ModelResponse, acompletion
from app.sdk.cost import calculate_cost  # noqa: F401  used by streaming generator (Task 12)
from app.services.proxy_guard import (
    check_budget,
    check_rate_limit,
    enforce_model_access,
    estimate_input_tokens,
    map_sdk_error,
    resolve_provider_api_key,
)
from app.services.spend_service import log_spend

router = APIRouter(prefix="/v1", tags=["proxy"])


@router.post("/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    response: Response,
    user: User = Depends(get_current_user),
    api_key: ApiKey | None = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
) -> ModelResponse:
    """OpenAI-compatible chat completion endpoint.

    Pipeline (per CLAUDE.md):
        authenticate → rate limit → budget → model access → dispatch → spend log
    """
    request_id = f"req-{uuid7().hex}"
    response.headers["X-Request-Id"] = request_id
    started_at = time.time()

    if body.stream:
        # Streaming branch is implemented in Task 12; this guard avoids
        # silently returning a non-streaming response for stream=true.
        raise HTTPException(
            status_code=501,
            detail="Streaming not yet implemented in this build",
        )

    # Resolve team/org for the model-access check (lazy: only fetch if api_key has them)
    team: Team | None = None
    org: Organization | None = None
    if api_key:
        if api_key.team_id:
            team = await db.get(Team, api_key.team_id)
        if api_key.org_id:
            org = await db.get(Organization, api_key.org_id)

    # Guard chain (only enforced for sk- API key auth; JWT users bypass key-level checks)
    if api_key:
        # Skip enforcement entirely for proxy_admin
        if user.role != "proxy_admin":
            enforce_model_access(body.model, api_key, team, org)
            estimated = estimate_input_tokens(body.messages)
            await check_rate_limit(api_key, estimated)
            await check_budget(db, api_key)

    # Resolve upstream provider key
    provider_name = body.model.split("/", 1)[0] if "/" in body.model else ""
    upstream_key = resolve_provider_api_key(provider_name, settings)

    # Dispatch via the SDK
    try:
        # Pass model + messages explicitly; forward other params via **kwargs
        forwarded = body.model_dump(
            exclude={"model", "messages", "stream"},
            exclude_none=True,
        )
        sdk_response = await acompletion(
            model=body.model,
            messages=[m.model_dump() for m in body.messages],
            api_key=upstream_key,
            **forwarded,
        )
    except LiteLLMError as exc:
        status, error_body = map_sdk_error(exc)
        raise HTTPException(status_code=status, detail=error_body) from exc

    # Type narrowing: non-streaming returns ModelResponse, not StreamWrapper
    assert isinstance(sdk_response, ModelResponse)

    # Spend log
    elapsed_ms = int((time.time() - started_at) * 1000)
    bare_model = body.model.split("/", 1)[1] if "/" in body.model else body.model
    usage = sdk_response.usage
    cost = usage.cost if usage else None
    await log_spend(
        db,
        request_id=request_id,
        api_key_hash=api_key.api_key_hash if api_key else "",
        model=bare_model,
        provider=provider_name,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
        spend=cost or 0.0,
        status="completed",
        response_time_ms=elapsed_ms,
        user_id=user.id if user else None,
        team_id=api_key.team_id if api_key else None,
        org_id=api_key.org_id if api_key else None,
    )

    return sdk_response
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_routes/test_proxy_routes.py -v 2>&1 | tail -20
```

Expected: 12 passed (the 12 non-streaming tests above).

If Docker isn't running locally, the DB-touching tests will fail with the same Docker errors as other testcontainer-backed tests in the repo. Run them in an environment where Docker (or Colima) is available — OR in CI.

- [ ] **Step 5: Run linters**

```bash
uv run ruff check src/app/routes/proxy_routes.py tests/test_routes/test_proxy_routes.py
uv run mypy src/app/routes/proxy_routes.py
```

Both must be clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/routes/proxy_routes.py tests/test_routes/test_proxy_routes.py
git commit -m "feat(proxy): non-streaming POST /v1/chat/completions with full guard chain + spend log"
```

---

### Task 12: Streaming branch via SSE

**Goal:** Implement the `stream=true` path. Returns `StreamingResponse` wrapping a generator that yields SSE events and logs spend in `finally:`.

**Files:**
- Modify: `src/app/routes/proxy_routes.py`
- Modify: `tests/test_routes/test_proxy_routes.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_routes/test_proxy_routes.py`:

```python
@respx.mock
async def test_chat_completion_streaming_openai(
    client, proxy_key, openai_key_set, db_session
):
    """Stream from OpenAI: assert SSE chunks are emitted and spend logged."""
    raw_key, api_key = proxy_key
    body_bytes = (
        b'data: {"id":"c1","created":1,"model":"gpt-4o-mini","choices":'
        b'[{"index":0,"delta":{"role":"assistant","content":"He"}}]}\n\n'
        b'data: {"id":"c1","created":1,"model":"gpt-4o-mini","choices":'
        b'[{"index":0,"delta":{"content":"llo"},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":5,"completion_tokens":2,"total_tokens":7}}\n\n'
        b'data: [DONE]\n\n'
    )
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body_bytes, headers={"content-type": "text/event-stream"}
        )
    )

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        events = list(resp.iter_lines())

    # Should contain at least: 2 data: lines + [DONE]
    data_lines = [e for e in events if e.startswith("data:")]
    assert len(data_lines) >= 3
    assert data_lines[-1].strip() == "data: [DONE]"

    # Spend log was written via the finally: block
    result = await db_session.execute(
        select(SpendLog).where(SpendLog.api_key_hash == api_key.api_key_hash)
    )
    log = result.scalar_one()
    # Final chunk's usage was captured
    assert log.input_tokens == 5
    assert log.output_tokens == 2
    assert log.status == "completed"


@respx.mock
async def test_chat_completion_streaming_anthropic(
    client, proxy_key, monkeypatch, db_session
):
    """Stream from Anthropic: SSE events with both 'event:' and 'data:' lines."""
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    raw_key, _ = proxy_key
    body_bytes = (
        b'event: message_start\n'
        b'data: {"type":"message_start","message":'
        b'{"id":"msg_1","model":"claude-haiku-4-5-20251001",'
        b'"usage":{"input_tokens":5,"output_tokens":0}}}\n\n'
        b'event: content_block_delta\n'
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":"He"}}\n\n'
        b'event: content_block_delta\n'
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":"llo"}}\n\n'
        b'event: message_delta\n'
        b'data: {"type":"message_delta",'
        b'"delta":{"stop_reason":"end_turn"},'
        b'"usage":{"output_tokens":3}}\n\n'
        b'event: message_stop\n'
        b'data: {"type":"message_stop"}\n\n'
    )
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200, content=body_bytes, headers={"content-type": "text/event-stream"}
        )
    )

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "anthropic/claude-haiku-4-5-20251001",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    ) as resp:
        assert resp.status_code == 200
        events = list(resp.iter_lines())

    data_lines = [e for e in events if e.startswith("data:")]
    assert len(data_lines) >= 3
    assert data_lines[-1].strip() == "data: [DONE]"


@respx.mock
async def test_chat_completion_streaming_partial_log_on_no_finish(
    client, proxy_key, openai_key_set, db_session
):
    """No finish_reason in chunks → spend log status='partial'."""
    raw_key, api_key = proxy_key
    body_bytes = (
        b'data: {"id":"c1","created":1,"model":"gpt-4o-mini","choices":'
        b'[{"index":0,"delta":{"content":"He"}}]}\n\n'
        b'data: [DONE]\n\n'
    )
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body_bytes, headers={"content-type": "text/event-stream"}
        )
    )

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    ) as resp:
        list(resp.iter_lines())

    result = await db_session.execute(
        select(SpendLog).where(SpendLog.api_key_hash == api_key.api_key_hash)
    )
    log = result.scalar_one()
    assert log.status == "partial"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_routes/test_proxy_routes.py::test_chat_completion_streaming_openai -v 2>&1 | tail -10
```

Expected: 501 NotImplemented (the Task 11 stub guard for `stream=true`).

- [ ] **Step 3: Implement the streaming branch**

Replace the streaming-stub in `src/app/routes/proxy_routes.py`:

```python
    if body.stream:
        # Streaming branch is implemented in Task 12; this guard avoids
        # silently returning a non-streaming response for stream=true.
        raise HTTPException(
            status_code=501,
            detail="Streaming not yet implemented in this build",
        )
```

with the actual streaming implementation. First, add imports at the top of the file:

```python
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse

from app.sdk import StreamWrapper
```

Then in the route, replace the stream-501 stub. Insert this block after `upstream_key = resolve_provider_api_key(...)` and before the `try:` non-streaming dispatch:

```python
    if body.stream:
        try:
            forwarded = body.model_dump(
                exclude={"model", "messages", "stream"},
                exclude_none=True,
            )
            wrapper = await acompletion(
                model=body.model,
                messages=[m.model_dump() for m in body.messages],
                api_key=upstream_key,
                stream=True,
                **forwarded,
            )
        except LiteLLMError as exc:
            status, error_body = map_sdk_error(exc)
            raise HTTPException(status_code=status, detail=error_body) from exc

        assert isinstance(wrapper, StreamWrapper)

        async def _sse_generator() -> AsyncIterator[str]:
            last_usage = None
            finish_reason = None
            try:
                async for chunk in wrapper:
                    if chunk.usage:
                        last_usage = chunk.usage
                    if chunk.choices and chunk.choices[0].finish_reason:
                        finish_reason = chunk.choices[0].finish_reason
                    yield f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"
                yield "data: [DONE]\n\n"
            except LiteLLMError as exc:
                # Mid-stream provider error — emit an SSE error event and stop
                _, error_body = map_sdk_error(exc)
                yield f"data: {error_body}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                elapsed_ms = int((time.time() - started_at) * 1000)
                cost = (
                    calculate_cost(body.model, last_usage)
                    if last_usage
                    else None
                )
                await log_spend(
                    db,
                    request_id=request_id,
                    api_key_hash=api_key.api_key_hash if api_key else "",
                    model=bare_model,
                    provider=provider_name,
                    input_tokens=last_usage.prompt_tokens if last_usage else 0,
                    output_tokens=last_usage.completion_tokens if last_usage else 0,
                    spend=cost or 0.0,
                    status="completed" if finish_reason else "partial",
                    response_time_ms=elapsed_ms,
                    user_id=user.id if user else None,
                    team_id=api_key.team_id if api_key else None,
                    org_id=api_key.org_id if api_key else None,
                )

        # Compute bare_model + provider_name once for the closure
        bare_model = body.model.split("/", 1)[1] if "/" in body.model else body.model
        # provider_name was already computed above

        return StreamingResponse(
            _sse_generator(),
            media_type="text/event-stream",
            headers={"X-Request-Id": request_id},
        )
```

**Note:** the `bare_model = ...` line should appear BEFORE the `async def _sse_generator():` so the closure captures it. The block above puts it after for clarity in the diff; reorder when applying. Final code structure inside the route:

```python
    # ... earlier guards ...
    provider_name = body.model.split("/", 1)[0] if "/" in body.model else ""
    bare_model = body.model.split("/", 1)[1] if "/" in body.model else body.model
    upstream_key = resolve_provider_api_key(provider_name, settings)

    if body.stream:
        # streaming dispatch + generator + finally log_spend
        ...
        return StreamingResponse(...)

    # non-streaming dispatch + log_spend (Task 11 code)
    ...
```

So move the `bare_model = ...` computation up to be alongside `provider_name = ...`. Both are needed by both branches.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_routes/test_proxy_routes.py -v 2>&1 | tail -10
```

Expected: 15 passed (12 from Task 11 + 3 new streaming tests).

- [ ] **Step 5: Run linters**

```bash
uv run ruff check src/app/routes/proxy_routes.py tests/test_routes/test_proxy_routes.py
uv run mypy src/app/routes/proxy_routes.py
```

Both must be clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/routes/proxy_routes.py tests/test_routes/test_proxy_routes.py
git commit -m "feat(proxy): streaming POST /v1/chat/completions via SSE + finally spend log"
```

---

### Task 13: Upstream error mapping integration tests

**Goal:** Verify the SDK→HTTP error flow end-to-end through the route. Each test mocks an upstream HTTP error and asserts the proxy translates it correctly.

**Files:**
- Modify: `tests/test_routes/test_proxy_routes.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_routes/test_proxy_routes.py`:

```python
@respx.mock
async def test_upstream_401_maps_to_401(client, proxy_key, openai_key_set):
    raw_key, _ = proxy_key
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            401, json={"error": {"message": "bad upstream key"}}
        )
    )
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["code"] == "invalid_api_key"


@respx.mock
async def test_upstream_429_maps_to_429(client, proxy_key, openai_key_set):
    raw_key, _ = proxy_key
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            429, json={"error": {"message": "slow down"}}
        )
    )
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 429
    body = resp.json()
    assert body["error"]["type"] == "rate_limit_error"


@respx.mock
async def test_upstream_400_context_maps_to_400_context(
    client, proxy_key, openai_key_set
):
    raw_key, _ = proxy_key
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "message": "context too long",
                    "code": "context_length_exceeded",
                }
            },
        )
    )
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "context_length_exceeded"


@respx.mock
async def test_upstream_500_maps_to_502_upstream_error(
    client, proxy_key, openai_key_set
):
    """Upstream 5xx → we return 502 'upstream_error' to clients."""
    raw_key, _ = proxy_key
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            500, json={"error": {"message": "boom"}}
        )
    )
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["code"] == "upstream_error"


@respx.mock
async def test_upstream_503_maps_to_503(client, proxy_key, openai_key_set):
    raw_key, _ = proxy_key
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            503, json={"error": {"message": "down"}}
        )
    )
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"]["code"] == "service_unavailable"
```

- [ ] **Step 2: Run tests to verify they pass**

(They should pass immediately — Task 11/12's `try/except LiteLLMError → map_sdk_error` flow already exists.)

```bash
uv run pytest tests/test_routes/test_proxy_routes.py -v 2>&1 | tail -10
```

Expected: 20 passed (15 prior + 5 new).

- [ ] **Step 3: Run linters**

```bash
uv run ruff check tests/test_routes/test_proxy_routes.py
```

Must be clean.

- [ ] **Step 4: Commit**

```bash
git add tests/test_routes/test_proxy_routes.py
git commit -m "test(proxy): upstream HTTP error → OpenAI-shape error response (5 status codes)"
```

---

### Task 14: Live test against real OpenAI

**Goal:** Single gated end-to-end test that boots the FastAPI app via uvicorn and posts a real request to OpenAI.

**Files:**
- Create: `tests/test_proxy/__init__.py` (empty)
- Create: `tests/test_proxy/test_proxy_live.py`

- [ ] **Step 1: Create the package marker**

```bash
mkdir -p tests/test_proxy
touch tests/test_proxy/__init__.py
```

- [ ] **Step 2: Create the live test**

Create `tests/test_proxy/test_proxy_live.py`:

```python
"""Live integration test for the proxy.

Skipped unless `-m live` is passed AND the env vars are set.
Run: `OPENAI_API_KEY=sk-... uv run pytest -m live tests/test_proxy/`
Cost: ~$0.0001 per run (gpt-4o-mini, ~5 output tokens).

Boots the FastAPI app via uvicorn in a background thread (same harness
pattern as the Keycloak e2e), creates a proxy ApiKey in a real DB, then
posts to /v1/chat/completions with that key.
"""

import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn


def _free_port() -> int:
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def app_server():
    """Boot the FastAPI app in a uvicorn thread on a free port."""
    from app.main import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for the server to start
    for _ in range(50):
        try:
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
            break
        except (httpx.ConnectError, httpx.ReadTimeout):
            time.sleep(0.1)
    else:
        pytest.fail("uvicorn did not start within 5s")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.live
async def test_proxy_chat_completion_live(app_server, db_session, sample_user):
    """End-to-end: real proxy key + real OpenAI call + spend log row written."""
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")

    from app.auth.api_key_auth import generate_api_key
    from app.models.api_key import ApiKey
    from sqlalchemy import select
    from app.models.spend import SpendLog

    raw_key, key_hash = generate_api_key()
    api_key = ApiKey(
        api_key_hash=key_hash,
        user_id=sample_user.id,
        name="live-test",
    )
    db_session.add(api_key)
    await db_session.commit()

    response = httpx.post(
        f"{app_server}/v1/chat/completions",
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": 'Say "ok" and nothing else.'}],
            "max_tokens": 5,
        },
        headers={"Authorization": f"Bearer {raw_key}"},
        timeout=30.0,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"]
    assert body["usage"]["prompt_tokens"] > 0
    assert body["usage"]["completion_tokens"] > 0
    assert body["usage"]["cost"] > 0

    # SpendLog row was written by the proxy
    result = await db_session.execute(
        select(SpendLog).where(SpendLog.api_key_hash == key_hash)
    )
    log = result.scalar_one()
    assert log.status == "completed"
    assert log.input_tokens == body["usage"]["prompt_tokens"]
```

- [ ] **Step 3: Confirm the test is deselected by default**

```bash
uv run pytest tests/test_proxy/ --collect-only -q 2>&1 | tail -3
```

Expected: `1 deselected`.

- [ ] **Step 4: Confirm `-m live` SKIPS without an OpenAI key**

```bash
unset OPENAI_API_KEY
uv run pytest -m live tests/test_proxy/ -v 2>&1 | tail -5
```

Expected: 1 skipped, reason: `OPENAI_API_KEY not set`.

- [ ] **Step 5: STOP — request user runs the live test with their key**

The live test calls real OpenAI and costs ~$0.0001. **Do NOT run from a subagent context.** Surface this command:

```bash
OPENAI_API_KEY=sk-... uv run pytest -m live tests/test_proxy/ -v
```

Expected (when the user runs it): 1 passed in ~1-3s.

- [ ] **Step 6: Run linters**

```bash
uv run ruff check tests/test_proxy/test_proxy_live.py
```

Must be clean.

- [ ] **Step 7: Commit**

```bash
git add tests/test_proxy/__init__.py tests/test_proxy/test_proxy_live.py
git commit -m "test(proxy): gated live test — real OpenAI request through the proxy + spend log"
```

---

### Task 15: Update progress notes

**Goal:** Record ola-14 in the project memory files.

**Files:**
- Modify: `/Users/makoto.sandiga/.claude/projects/-Users-makoto-sandiga-dev-me-makoto-lite-llm/memory/project_progress.md`
- Modify: `/Users/makoto.sandiga/.claude/projects/-Users-makoto-sandiga-dev-me-makoto-lite-llm/memory/MEMORY.md`

These are memory files outside the repo — no git commit required.

- [ ] **Step 1: Update `MEMORY.md`**

Read the file. Replace the "Project Progress" line with:

```
- [Project Progress](project_progress.md) — Auth done; Core SDK ola-12 (OpenAI) + ola-13 (Anthropic) + ola-14 (Proxy HTTP routes) done, ~330 tests, ~21 PRs, next: per-org provider keys OR caching layer OR routing strategies
```

Adjust the test/PR counts based on actual numbers at completion time.

- [ ] **Step 2: Update `project_progress.md`**

Append a new section after the Core SDK section:

```markdown

---

## Proxy HTTP Routes Progress (as of <today>)

### Completed Olas (Proxy)

| Ola | What | PR | Tests Added |
|-----|------|----|-------------|
| 14 | OpenAI-compatible POST /v1/chat/completions: full guard chain (auth → rate-limit → budget → model-access → SDK dispatch → spend log), streaming via SSE, OpenAI-shape error envelope | TBD (#20) | 24 unit + 25 route + 1 live (gated) |

**Total: 50 new proxy tests. Project test total: ~330 default + 3 gated live (1 OpenAI SDK + 1 Anthropic SDK + 1 proxy).**

### Validation criterion result for ola-14

The spec's hard rule: "if `app.sdk` needs even one change to land the proxy, the abstraction has failed."

**Result:** zero changes to `app.sdk`. The SDK was consumed as-is; the only modifications outside the new files were `main.py` (router include + lifespan + error handler), `config.py` (env settings), and `auth/dependencies.py` (one new helper that reuses the existing cache).

### Proxy — Remaining Work

1. **Per-org / per-team encrypted provider keys** — swap `resolve_provider_api_key` to read from DB instead of settings.
2. **Team-level and org-level rate limits** — add precedence rule (most-restrictive wins).
3. **Team-level and org-level budgets** — same.
4. **`/v1/embeddings`** — needs SDK embeddings support first.
5. **`/v1/images/generations`, audio, moderation, batch** — separate olas, each needing SDK support.
6. **`tiktoken` for accurate pre-call token counting** — replace `chars/4` heuristic.
7. **Caching layer** — cache_layer ola.
8. **Routing strategies** — load balancing across multiple keys for the same model, fallback chains.
9. **Observability callbacks** — Datadog/Sentry/Langfuse hooks.
10. **Guardrails** — pre-call moderation, post-call PII scrubbing.
11. **Streaming `prompt_tokens` for Anthropic** — currently 0 due to stateless provider; same as the SDK gap.

Run live tests:
```
OPENAI_API_KEY=sk-... ANTHROPIC_API_KEY=sk-ant-... uv run pytest -m live
```
~$0.0003 per run combined (SDK OpenAI + SDK Anthropic + proxy OpenAI).
```

- [ ] **Step 3: No git commit needed — memory files are outside the repo.**

---

## Task Summary

| Task | Component | Tests added |
|------|-----------|-------------|
| 1 | Config: OPENAI_API_KEY, ANTHROPIC_API_KEY env settings | 0 |
| 2 | Wire schemas: ChatCompletionRequest, ChatMessage, error envelope | 9 |
| 3 | proxy_guard.map_sdk_error | 11 |
| 4 | proxy_guard.enforce_model_access | 2 |
| 5 | proxy_guard.resolve_provider_api_key | 3 |
| 6 | proxy_guard.estimate_input_tokens | 1 |
| 7 | proxy_guard.check_rate_limit | 4 |
| 8 | proxy_guard.check_budget | 3 |
| 9 | auth.dependencies.get_current_api_key | 2 |
| 10 | proxy_routes scaffold + main.py wiring (router, lifespan, error handler) | 0 |
| 11 | Non-streaming POST /v1/chat/completions with full integration | 12 |
| 12 | Streaming POST /v1/chat/completions via SSE | 3 |
| 13 | Upstream error mapping integration tests | 5 |
| 14 | Live test against real OpenAI | 1 (gated) |
| 15 | Memory update | — |

**Total: 56 unit + 1 live = 57 new tests.**

Breakdown by file:
- `tests/test_services/test_proxy_guard.py`: 24 unit tests
- `tests/test_routes/test_chat_schemas.py`: 9 schema tests
- `tests/test_routes/test_proxy_routes.py`: 20 route tests
- `tests/test_auth/test_get_current_api_key.py`: 2 auth tests
- `tests/test_proxy/test_proxy_live.py`: 1 gated live test

Project total after merge: ~330 default + 3 gated live tests.

---

## Self-Review

**Spec coverage:**

- §Scope (in scope) — Tasks 1-13 cover: route, streaming, full middleware chain, server-side keys, error mapping, spend log on completion + partial. Task 14 covers the live test.
- §Public API — Task 11 implements the route signature; Tasks 12+13 verify response shape + error envelope.
- §File structure — Tasks list exact paths matching spec; nothing in `app.sdk` is touched.
- §Architecture — Task 10 (scaffold + main wiring) realizes the integration; Tasks 11+12 implement the dispatch path.
- §`proxy_guard.py` helpers — one task per helper (Tasks 3-8), one for the auth helper (Task 9).
- §Wire schemas — Task 2.
- §Streaming Implementation — Task 12.
- §Error Handling — Task 10 (handler) + Task 11 (try/except) + Task 13 (verification).
- §Testing — Tasks split by file, total matches spec recount (24 unit + 25 route + 1 live = 50 in spec, 57 in plan; difference comes from 9 schema tests in Task 2 not counted in spec's "guard unit tests" + 2 auth tests in Task 9 also not counted).
- §Lifespan Integration — Task 10.
- §Risks — covered in spec; not duplicated in plan tasks.

**Placeholder scan:** No "TBD" / "implement later" / "fill in details" patterns. The `# implemented in Task N` markers in the streaming-stub of Task 11 are explicit forward-references that get replaced in their named tasks.

**Type consistency:** `_FORWARDED_PARAMS` is in the SDK (not redefined here). `_rate_limiter`, `_api_key_cache`, `map_sdk_error`, `enforce_model_access`, `resolve_provider_api_key`, `estimate_input_tokens`, `check_rate_limit`, `check_budget`, `get_current_api_key`, `chat_completions` (route function) — all defined in the task that introduces them and used identically in subsequent tasks.

**Validation criterion:** No task touches `app.sdk`. If a task implementation reveals a need to change the SDK, stop and re-evaluate per the spec's failure rule.
