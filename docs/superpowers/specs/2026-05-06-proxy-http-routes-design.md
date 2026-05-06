# Proxy HTTP Routes (ola-14) Design

**Status:** Draft
**Date:** 2026-05-06
**Depends on:** ola-12 (OpenAI provider, PR #16) + ola-13 (Anthropic provider, PR #19) + auth system (PRs #1-#15)

## Goal

Build the HTTP route layer that turns the SDK library into an actual proxy server. Authenticated clients post OpenAI-shaped chat requests; the proxy enforces auth + rate-limit + budget + model-access, dispatches via the SDK, logs spend, and returns OpenAI-shape responses (or SSE streams).

This is the ola where everything previously built — auth dependencies, rate limiter, spend service, SDK providers — actually meets in production code paths. Until now, those were independently testable but unwired.

**Validation criterion:** the SDK package (`app.sdk`) must not change. If implementation surfaces an SDK gap (as ola-13 did with `completions_path`), surface and decide before continuing.

## Scope

**In scope:**

- `POST /v1/chat/completions` — OpenAI-compatible chat endpoint
- Streaming via SSE (`stream: true`)
- Full middleware chain: auth → rate-limit (RPM + TPM) → budget → model-access → dispatch → spend-log
- Server-side provider keys: `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` from env (single set per proxy instance)
- Error mapping: SDK exceptions → OpenAI-shape error envelope with appropriate HTTP status
- Spend logging on completion (including partial logs on streaming disconnect)
- 1 gated live test against real OpenAI

**Out of scope (deferred to later olas):**

- Other endpoints: `/v1/embeddings`, `/v1/images/generations`, `/v1/audio/*`, `/v1/moderations`, `/v1/batches`
- Per-org / per-team encrypted provider keys (server env only)
- Team-level and org-level rate limits (key-level only)
- Team-level and org-level budgets (key-level only)
- Caching layer (separate cache_layer ola)
- Guardrails (pre/post-call moderation; separate ola)
- Observability callbacks (Datadog/Sentry/Langfuse; separate ola)
- `tiktoken` for accurate token counting (we use `chars/4` heuristic)
- Routing strategies (load balancing, fallback chains; separate router ola)
- `n>1` validation (passed through; upstream rejects)
- Custom OpenAI-compatible models (e.g., self-hosted vLLM; needs SDK provider first)

## Public API

**Endpoint:** `POST /v1/chat/completions`

**Request headers:**
- `Authorization: Bearer sk-<proxy-key>` — the proxy key issued via the existing `/keys` API
- `Content-Type: application/json`

**Request body:** OpenAI-compatible chat completion shape. The proxy's wire schema accepts the documented common fields with type-checking, plus `extra="allow"` for forward compatibility. The SDK's per-provider `_FORWARDED_PARAMS` allowlists what's actually sent upstream.

```json
{
  "model": "openai/gpt-4o-mini",
  "messages": [{"role": "user", "content": "hi"}],
  "temperature": 0.7,
  "stream": false
}
```

**Response (non-streaming):** OpenAI-shape `ChatCompletion` object — identical to what the SDK's `ModelResponse` Pydantic model produces (which is OpenAI-shaped by design):

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "gpt-4o-mini-2024-07-18",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "hi back"},
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 8,
    "completion_tokens": 3,
    "total_tokens": 11,
    "cost": 0.000014
  }
}
```

`usage.cost` is a proxy extension (not in the OpenAI spec). Standard OpenAI clients ignore unknown fields.

**Response (streaming, `stream=true`):** Server-Sent Events. Each event is a `data: <json>\n\n` line containing a `ChatCompletionChunk` object (the SDK's `ModelResponseStream`). Terminated by `data: [DONE]\n\n`.

**Error response:** OpenAI-shape error envelope:

```json
{
  "error": {
    "message": "Daily budget exceeded: $0.0150 / $0.01",
    "type": "rate_limit_error",
    "code": "budget_exceeded"
  }
}
```

## File Structure

**New files:**

```
src/app/routes/proxy_routes.py         # POST /v1/chat/completions
src/app/services/proxy_guard.py        # rate-limit + budget + model-access + key resolution + error mapping
src/app/schemas/wire_in/chat.py        # ChatCompletionRequest (OpenAI-shape)
src/app/schemas/wire_out/chat.py       # response shape (re-exports SDK types) + ChatCompletionErrorResponse

tests/test_routes/test_proxy_routes.py  # ~25 route-level tests via TestClient + respx
tests/test_services/test_proxy_guard.py # ~15 unit tests for the guard helpers
tests/test_proxy/test_proxy_live.py     # 1 gated live test against real OpenAI
tests/test_proxy/__init__.py            # empty package marker
```

**Modified files:**

```
src/app/main.py                 # include proxy_router; lifespan registers SDK aclose_all; OpenAI-shape error handler for /v1/*
src/app/config.py               # add OPENAI_API_KEY, ANTHROPIC_API_KEY env settings
src/app/auth/dependencies.py    # add get_current_api_key helper (reuses _api_key_cache)
```

**Untouched:** the SDK (`app.sdk`), models, auth, all existing routes/services. The proxy is purely additive.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  POST /v1/chat/completions                                          │
│                                                                     │
│  1. Auth: get_current_user (existing dep — JWT or sk- API key)     │
│  2. Validate body: ChatCompletionRequest (Pydantic, extra=allow)   │
│  3. Resolve ApiKey for the request: get_current_api_key (NEW dep) │
│                                                                     │
│  ┌────────── proxy_guard ──────────┐                               │
│  │ 4a. enforce_model_access (403)  │                               │
│  │ 4b. check_rate_limit (429)      │ — RPM + TPM (estimated tokens)│
│  │ 4c. check_budget (429)          │ — daily key spend             │
│  │ 4d. resolve_provider_api_key    │ — settings.openai_api_key etc.│
│  └─────────────────────────────────┘                               │
│                                                                     │
│  5. await acompletion(model, messages, api_key=upstream_key, ...)  │
│                                                                     │
│  ┌────── non-streaming ──────┐  ┌────── streaming ──────┐          │
│  │ 6. await log_spend(...)    │  │ 6. StreamingResponse │          │
│  │ 7. return ModelResponse   │  │    wraps generator:   │          │
│  │                            │  │    - yield SSE lines │          │
│  │                            │  │    - finally:        │          │
│  │                            │  │       log_spend(...) │          │
│  └────────────────────────────┘  └───────────────────────┘          │
└─────────────────────────────────────────────────────────────────────┘
```

### Component responsibilities

**`proxy_routes.py`** — the only new route file. One function: `chat_completions(body, user, api_key, db)`. Calls the guard helpers, dispatches via `acompletion`, logs spend, returns the response. ~80 lines. Imports nothing from internal SDK modules — only `from app.sdk import acompletion, ModelResponse, StreamWrapper, LiteLLMError`.

**`proxy_guard.py`** — six pure functions. Each is independently testable. None depends on FastAPI's `Request` object. They take pre-fetched ORM models and primitives, raise `HTTPException` on failure, return primitives or `None`.

**`auth/dependencies.py`** — gains one new helper: `get_current_api_key(request, db)`. Reads the `Authorization` header, hashes the token, returns the cached `ApiKey` (or `None` for JWT auth). Reuses `_api_key_cache` (no new DB hit on the hot path). The route uses both `get_current_user` and `get_current_api_key` as separate dependencies — small change to the auth module, additive.

## `proxy_guard.py` — Function Signatures

### `enforce_model_access(model: str, api_key: ApiKey | None, team: Team | None, org: Organization | None) -> None`

Wraps `permission_service.resolve_model_access`. Skips for `proxy_admin` users (handled by caller — passed via API key context). Raises `HTTPException(403, detail="Model 'X' is not allowed for this key")` on denial.

### `check_rate_limit(api_key: ApiKey, estimated_tokens: int) -> None`

Reads `api_key.rpm_limit` and `api_key.tpm_limit`. For each non-None limit, calls the singleton `SlidingWindowRateLimiter`:

```python
key = f"rpm:{api_key.api_key_hash}"
result = await limiter.check_rate_limit(key, api_key.rpm_limit, window_seconds=60)
if not result.allowed:
    raise HTTPException(
        429,
        detail="Rate limit exceeded",
        headers={"Retry-After": str(int(result.retry_after) + 1)},
    )
```

The TPM check uses `increment=estimated_tokens`; the RPM check uses `increment=1` (default). Order: RPM first (cheap to fail), TPM second.

**Scope:** key-level limits only. Team and org-level limits are documented in the model but not enforced here. Adding them later requires a precedence rule (most-restrictive wins seems right; not yet decided).

### `check_budget(db: AsyncSession, api_key: ApiKey) -> None`

Reads today's spend from `DailyKeySpend`, compares to `api_key.max_budget`. ~25 lines:

```python
async def check_budget(db, api_key):
    if api_key.max_budget is None:
        return
    today = date.today()
    result = await db.execute(
        select(DailyKeySpend.spend).where(
            DailyKeySpend.api_key_hash == api_key.api_key_hash,
            DailyKeySpend.date == today,
        )
    )
    spent_today = result.scalar() or 0.0
    if spent_today >= api_key.max_budget:
        raise HTTPException(
            429,
            detail=(
                f"Daily budget exceeded: ${spent_today:.4f} / ${api_key.max_budget}"
            ),
        )
```

**Scope:** key-level only. Team and org budgets deferred. Race condition: spend updates lag the request, so a key can briefly overspend by one or two requests under concurrency. Documented limitation.

### `resolve_provider_api_key(provider_name: str, settings: Settings) -> str`

Maps `"openai"` to `settings.openai_api_key`, `"anthropic"` to `settings.anthropic_api_key`. Raises `HTTPException(503, detail=f"Provider '{provider_name}' is not configured on this proxy")` if the env var is unset.

New entries in `config.py`:

```python
class Settings(BaseSettings):
    ...
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
```

Both default to `None`; the proxy starts cleanly without them and only fails (with a clear 503) when a request is actually made for that provider.

### `estimate_input_tokens(messages: list[ChatMessage]) -> int`

Coarse heuristic for TPM pre-charge:

```python
return max(1, len(json.dumps([m.model_dump() for m in messages])) // 4)
```

Standard "1 token ≈ 4 chars" approximation. Real counts (from `ModelResponse.usage`) replace the estimate post-call when we re-charge or refund the difference.

**Tagged for follow-up:** `# TODO(ola-N): replace with tiktoken-based counting when available`.

### `map_sdk_error(exc: LiteLLMError) -> tuple[int, dict]`

Translates SDK exceptions to `(http_status, error_body)`. Mapping:

| SDK exception | HTTP status | error.type | error.code |
|---|---|---|---|
| `AuthenticationError` | 401 | `invalid_request_error` | `invalid_api_key` |
| `RateLimitError` | 429 | `rate_limit_error` | `rate_limit_exceeded` |
| `BadRequestError` | 400 | `invalid_request_error` | `bad_request` |
| `NotFoundError` | 404 | `invalid_request_error` | `model_not_found` |
| `ContextWindowExceededError` | 400 | `invalid_request_error` | `context_length_exceeded` |
| `ContentPolicyViolationError` | 400 | `invalid_request_error` | `content_filter` |
| `InternalServerError` | 502 | `api_error` | `upstream_error` |
| `ServiceUnavailableError` | 503 | `api_error` | `service_unavailable` |
| `TimeoutError` | 504 | `api_error` | `timeout` |
| `UnknownProviderError` | 400 | `invalid_request_error` | `model_not_found` |
| `LiteLLMError` (fallback) | 500 | `api_error` | `unknown_error` |

Returns:

```python
(
    status_code,
    {
        "error": {
            "message": exc.message,
            "type": "<from table>",
            "code": "<from table>",
        }
    },
)
```

The route catches `LiteLLMError`, calls `map_sdk_error`, and raises `HTTPException(status_code=status, detail=body["error"])`. The exception handler in `main.py` wraps the detail in `{"error": ...}` for `/v1/*` paths.

## Wire Schemas

### `wire_in/chat.py`

```python
from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    """One message in the conversation."""
    model_config = ConfigDict(extra="allow")
    role: str
    content: str | list[dict] | None = None


class ChatCompletionRequest(BaseModel):
    """OpenAI-shape /v1/chat/completions request body.

    Permissive on top-level extras so new OpenAI fields don't break us;
    the SDK's per-provider transform_request allowlists what's forwarded.
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

The `model` field accepts any string. We don't validate provider prefix at the schema layer; the SDK's resolver does it (single source of truth). Bare names → `UnknownProviderError` → HTTP 400 + `model_not_found`.

### `wire_out/chat.py`

```python
"""Public response shape for /v1/chat/completions.

The SDK's ModelResponse is already OpenAI-shaped, so we re-export it
under its OpenAI name. ModelResponseStream serves the same role for
streaming chunks. No translation layer is needed at the route boundary.
"""
from pydantic import BaseModel

from app.sdk.types import ModelResponse, ModelResponseStream  # noqa: F401


class ChatCompletionErrorBody(BaseModel):
    message: str
    type: str
    code: str | None = None


class ChatCompletionErrorResponse(BaseModel):
    error: ChatCompletionErrorBody
```

## Streaming Implementation

The route detects `body.stream` and returns a `StreamingResponse` wrapping an async generator:

```python
async def _sse_stream_generator(
    wrapper: StreamWrapper,
    db: AsyncSession,
    request_id: str,
    api_key_hash: str,
    model: str,
    user_id: uuid.UUID,
    team_id: uuid.UUID | None,
    org_id: uuid.UUID | None,
    started_at: float,
):
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
    finally:
        # Log spend even if the client disconnected
        elapsed_ms = int((time.time() - started_at) * 1000)
        cost = (
            calculate_cost(model, last_usage)
            if last_usage else None
        )
        await log_spend(
            db,
            request_id=request_id,
            api_key_hash=api_key_hash,
            model=model.split("/", 1)[1],
            provider=model.split("/", 1)[0],
            input_tokens=last_usage.prompt_tokens if last_usage else 0,
            output_tokens=last_usage.completion_tokens if last_usage else 0,
            spend=cost or 0.0,
            status="completed" if finish_reason else "partial",
            response_time_ms=elapsed_ms,
            user_id=user_id,
            team_id=team_id,
            org_id=org_id,
        )
```

`StreamingResponse(_sse_stream_generator(...), media_type="text/event-stream")`.

**Note on Anthropic streaming:** as documented in ola-13, Anthropic streaming yields `prompt_tokens=0` because the provider is stateless and `input_tokens` arrives in `message_start` (a chunk we currently skip). The streamed `last_usage.prompt_tokens` will be 0 for Anthropic; cost will under-charge accordingly. Documented limitation; same as the SDK's known gap.

## Error Handling

Two flavors:

1. **Pre-dispatch errors** (auth, rate-limit, budget, model-access, provider key missing). Raised as `HTTPException(status, detail=str_message)` from the guard helpers. The exception handler in `main.py` wraps the detail in OpenAI envelope shape for `/v1/*` paths.

2. **Dispatch errors** (anything `acompletion` can raise). Caught by a `try/except LiteLLMError` around the `acompletion` call. `map_sdk_error(exc)` produces the status + body. The route raises `HTTPException(status, detail=body["error"])`.

The exception handler:

```python
@app.exception_handler(HTTPException)
async def openai_shape_error_handler(request: Request, exc: HTTPException):
    if not request.url.path.startswith("/v1/"):
        # Existing routes get default FastAPI shape
        return await fastapi.exception_handlers.http_exception_handler(request, exc)
    # /v1/* gets OpenAI-shape envelope
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"message": str(exc.detail), "type": "api_error", "code": None}},
        headers=exc.headers or {},
    )
```

Single registration in `main.py`. Doesn't affect any other route's error shape.

## Testing

### Unit tests — `tests/test_services/test_proxy_guard.py` (~15 tests)

Pure logic. No FastAPI. Each helper tested directly with fixtures (in-memory DB; constructed ORM rows).

| Group | Count | Coverage |
|---|---|---|
| `enforce_model_access` | 2 | proxy_admin bypass; denial raises 403 with model name in detail |
| `check_rate_limit` | 4 | RPM allowed; RPM exceeded → 429 + Retry-After; TPM allowed; TPM exceeded → 429 |
| `check_budget` | 3 | no `max_budget` → no-op; spent < budget allows; spent ≥ budget → 429 with actual spend in message |
| `resolve_provider_api_key` | 3 | OpenAI key resolves; Anthropic key resolves; missing key → 503 |
| `estimate_input_tokens` | 1 | sanity (returns ≥ 1, scales with input length) |
| `map_sdk_error` | 11 | one test per SDK exception subclass + LiteLLMError fallback |

Total: 24 (the design earlier said 15, recount based on this breakdown gives 24).

### Route tests — `tests/test_routes/test_proxy_routes.py` (~25 tests)

Full FastAPI `TestClient` (or `httpx.AsyncClient` since the app is async) + respx mocking the upstream provider. Each test sets up an `ApiKey` fixture, posts to `/v1/chat/completions`, asserts the round trip.

| Group | Count | Coverage |
|---|---|---|
| Happy paths | 4 | OpenAI non-streaming; OpenAI streaming; Anthropic non-streaming; Anthropic streaming. Verify response shape, status 200, SpendLog row created with correct cost |
| Auth | 3 | Missing Authorization → 401; invalid `sk-...` → 401; blocked key → 401 |
| Model access | 2 | `allowed_models=["openai/gpt-4o-mini"]` allows; `openai/gpt-4o` requested with that allowlist → 403 |
| Rate limit | 2 | RPM=2: third request in same minute → 429 with Retry-After; TPM exceeded by big input → 429 |
| Budget | 2 | `max_budget=$0.01` with $0.005 already spent → 200; with $0.015 already spent → 429 |
| Provider key missing | 1 | `anthropic/...` requested when `ANTHROPIC_API_KEY` unset → 503 |
| Upstream errors | 5 | 401 → 401; 429 → 429; 400 context → 400 + `context_length_exceeded`; 500 → 502 + `upstream_error`; 503 → 503 |
| Spend log content | 3 | non-streaming usage matches upstream; streaming spend logged from final chunk; cache_hit defaults to False |
| Request ID | 1 | `X-Request-Id` returned in headers, matches SpendLog row |
| Body validation | 2 | empty `messages` → 422; missing `model` → 422 |

### Live test — `tests/test_proxy/test_proxy_live.py` (1 gated test)

Uses the existing `app_server` fixture pattern (uvicorn in a thread, free port) from the Keycloak e2e setup. Posts to `http://localhost:<port>/v1/chat/completions` with a real `OPENAI_API_KEY` set on the server. Asserts:

- Returns 200
- Response parses as `ChatCompletionResponse`
- A SpendLog row exists in the test DB

Gated by `@pytest.mark.live` AND `OPENAI_API_KEY` set. ~$0.0001 per run against `gpt-4o-mini`.

### Test totals

- 24 guard unit tests
- 25 route tests
- 1 live test

**Total: 50 new tests.** Combined project test count goes from ~280 → ~330.

## Lifespan Integration

Update `main.py`'s `lifespan` to:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    # Shutdown: close pooled HTTP clients used by the SDK
    from app.sdk.http_client import get_http_client
    await get_http_client().aclose_all()
```

Closes httpx connections cleanly on uvicorn exit. No-op if no requests were made.

## Risks

1. **Race on budget.** Documented in §6. Acceptable.
2. **In-process rate limiter.** Documented in CLAUDE.md. Multi-worker deployments need Redis swap (interface is stable).
3. **Streaming + client disconnect.** Generator `finally:` logs whatever we have. Status flag `"partial"` on incomplete streams.
4. **Token estimation precision.** Coarse `chars/4`; under-charges TPM by ~20-30% on code/non-Latin. Real counts arrive post-call.
5. **OpenAI-shape envelope only on `/v1/*`.** Internal routes keep default FastAPI errors. Path-prefix filter in the handler.
6. **Auth dep refetches ApiKey.** Adds `get_current_api_key` helper; reuses cache. Two reads → negligible.

## Validation Criterion

This ola succeeds if:

- All 50 tests pass
- No changes to `app.sdk` (the SDK is consumed as-is)
- The auth chain (CLAUDE.md) is wired and observable in test output
- A real `gpt-4o-mini` call via the live test returns 200 + SpendLog written

If implementation surfaces an SDK gap, decide whether to include it (small additive change like ola-13's `completions_path`) or split into a follow-up.

## Future olas (referenced from project_progress.md)

- ola-N+1: Per-org / per-team encrypted provider keys (swap `resolve_provider_api_key` to read from DB)
- ola-N+2: Team and org-level rate limits + budgets (precedence: most-restrictive wins)
- ola-N+3: `/v1/embeddings` (after SDK adds embeddings support)
- ola-N+4: `tiktoken` integration for accurate pre-call token counting
- ola-N+5: Caching layer
- ola-N+6: Routing strategies (multi-key load balancing, fallback chains)
