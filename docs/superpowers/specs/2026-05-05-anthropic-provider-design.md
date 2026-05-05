# Core SDK — Anthropic Provider (ola-13) Design

**Status:** Draft
**Date:** 2026-05-05
**Depends on:** ola-12 (Core SDK OpenAI) — merged in PR #16

## Goal

Add `AnthropicProvider` as a second implementation of `BaseProvider`, mirroring the scope of ola-12 (OpenAI chat completions). Validate that the provider abstraction generalizes to a second provider without changes to the abstraction itself.

**Validation criterion:** if `BaseProvider`, `acompletion()`, `LLMHttpClient`, `resolver.py`, `cost.py`, `types.py`, or `exceptions.py` needs even one change to land this provider, the abstraction has failed its design intent and we stop to brainstorm a refactor before writing more code.

## Scope

**In scope (mirrors ola-12):**

- Anthropic Messages API (`/v1/messages`) — chat completions
- Streaming via SSE
- Tool use (Anthropic's "tool_use" content blocks)
- Cost calculation against a 3-model catalog
- Error mapping from Anthropic's error format to the SDK's typed exceptions
- 1 gated live test against `claude-haiku-4-5-20251001` (~$0.0001 per run)

**Out of scope (deferred to later olas):**

- Vision / multimodal images (`type: "image"` content blocks)
- Extended thinking / reasoning (Claude 4.x `thinking` blocks)
- Prompt caching (`cache_control` markers)
- Vertex AI and AWS Bedrock variants (different auth, separate providers)
- Sync wrapper (`completion()`)
- Token counting endpoint (`/v1/messages/count_tokens`)
- Batch API
- Anthropic-specific errors that don't have a clean SDK exception (`overloaded_error` maps to the closest fit)

## Public API

**No changes.** The user-visible surface is identical to ola-12:

```python
from app.sdk import acompletion

response = await acompletion(
    model="anthropic/claude-sonnet-4-6",
    messages=[
        {"role": "system", "content": "You are concise."},
        {"role": "user", "content": "Hi."},
    ],
    api_key="sk-ant-...",  # or via ANTHROPIC_API_KEY env var
)
```

`acompletion` returns `ModelResponse` (or `StreamWrapper` for streaming). Same exception types. Same cost-on-`response.usage.cost` patching by the dispatcher. The only thing the user changes is the `provider/` prefix in the model string.

## File Structure

**New files:**

```
src/app/sdk/providers/anthropic.py     # ~180 lines, mirrors openai.py shape
tests/test_sdk/providers/test_anthropic.py  # ~30 unit tests
tests/test_sdk/test_anthropic_live.py  # 1 gated live test
```

**Modified files:**

```
src/app/sdk/providers/__init__.py      # +1 line: from app.sdk.providers import anthropic
src/app/sdk/model_prices.json          # +3 entries: 3 Anthropic chat models
tests/test_sdk/test_acompletion.py     # +2 e2e dispatcher tests with mocked Anthropic responses
```

**Untouched:**

`main.py`, `resolver.py`, `http_client.py`, `cost.py`, `types.py`, `exceptions.py`, `providers/base.py`, `pyproject.toml`, the public `__init__.py`. The SDK's API and architecture stay frozen.

## Wire Format Mapping

The provider's job is to bridge Anthropic's wire shape and the SDK's internal types. The dispatcher and consumers see only the SDK types.

### Request: SDK call → Anthropic JSON

The dispatcher hands `transform_request(model, messages, params)` and receives a JSON-ready dict.

| SDK input | Anthropic output |
|---|---|
| `messages` (OpenAI-shaped, may contain `role: "system"` entries) | `messages` (Anthropic shape, system messages extracted) + top-level `system: str` |
| `params["max_tokens"]` (optional) | `max_tokens` (required — defaults to `4096` if not provided) |
| `params["stop"]` (str or list) | `stop_sequences: list[str]` |
| `params["tools"]` (OpenAI shape: `{type, function: {name, description, parameters}}`) | `tools: [{name, description, input_schema}]` |
| `params["tool_choice"]` (OpenAI: `auto`/`none`/`{type, function}`) | `tool_choice: {type: "auto"|"any"|"tool", name?}` |
| `params["temperature"]`, `top_p`, `top_k`, `metadata`, `service_tier`, `stream` | passed through if non-None |
| Other keys | dropped (allowlist) |

### Response: Anthropic JSON → `ModelResponse`

`transform_response(raw, model)` reverses the wire format.

| Anthropic field | SDK field |
|---|---|
| `id` | `id` |
| `model` | `model` |
| (none — Anthropic doesn't return) | `created = int(time.time())` (synthesized) |
| `content: [{type: "text", text}, ...]` (multiple text blocks concatenated) | `choices[0].message.content` (str, or `None` if no text blocks) |
| `content: [{type: "tool_use", id, name, input}, ...]` | `choices[0].message.tool_calls: [{id, type: "function", function: {name, arguments: json.dumps(input)}}]` |
| `stop_reason` | `choices[0].finish_reason` (mapping below) |
| `usage.input_tokens` | `usage.prompt_tokens` |
| `usage.output_tokens` | `usage.completion_tokens` |
| (synthesized) | `usage.total_tokens = prompt_tokens + completion_tokens` |

**`stop_reason` mapping:**

| Anthropic | SDK `finish_reason` |
|---|---|
| `end_turn` | `stop` |
| `max_tokens` | `length` |
| `tool_use` | `tool_calls` |
| `stop_sequence` | `stop` |
| `pause_turn` | passed through as-is (rare; downstream decides) |
| anything else | passed through as-is |

### Streaming: SSE events → `ModelResponseStream` chunks

Anthropic streams 7 distinct event types. `transform_stream_chunk(chunk, model)` dispatches on `chunk["type"]`.

| Anthropic event | Behavior |
|---|---|
| `message_start` | Returns `None` (skip). The first content delta will populate the chunk. |
| `content_block_start` (any block type) | Returns `None`. |
| `content_block_delta` with `delta.type == "text_delta"` | Yields `ModelResponseStream` with `delta.content = chunk["delta"]["text"]`. |
| `content_block_delta` with `delta.type == "input_json_delta"` | Yields with `delta.tool_calls[0].function.arguments = chunk["delta"]["partial_json"]`. Caller concatenates partial strings to assemble the JSON. |
| `content_block_stop` | Returns `None`. |
| `message_delta` | Yields with `finish_reason` mapped from `delta.stop_reason` AND `usage` populated (Anthropic delivers final token counts here, not on `message_stop`). |
| `message_stop` | Returns `None`. |
| `ping` | Returns `None` (keep-alive). |

Streaming chunks need `id` and `created`. The provider falls back to `f"chatcmpl-{uuid.uuid4().hex}"` and `int(time.time())` when absent (some events lack them).

## `AnthropicProvider` Implementation

### Constants

```python
DEFAULT_API_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096

_FORWARDED_PARAMS = {
    "temperature", "top_p", "top_k", "max_tokens", "stream",
    "stop_sequences", "tools", "tool_choice", "metadata", "service_tier",
}
```

### `get_api_base(model, api_base)`

Priority: explicit `api_base` → `ANTHROPIC_API_BASE` env var → `DEFAULT_API_BASE`. Trailing slash stripped.

### `get_headers(api_key, extra_headers)`

```python
{
    "x-api-key": api_key,
    "anthropic-version": ANTHROPIC_VERSION,
    "content-type": "application/json",
}
```

Plus `extra_headers` merged after defaults (so callers can override `anthropic-version` or add tracing headers).

### `transform_request(model, messages, params)`

1. **Extract system messages.** Walk `messages`. Pull entries where `role == "system"`. Concatenate their `content` with `\n\n`. Build a new `messages` list without them.
2. **Set `max_tokens` default.** If `params.get("max_tokens") is None`, use `DEFAULT_MAX_TOKENS`.
3. **Translate `stop`.** If caller passed `stop`, rename to `stop_sequences`. Coerce a single string to `[string]`.
4. **Translate tools.** For each `t` in `params.get("tools") or []`, emit `{"name": t["function"]["name"], "description": t["function"].get("description", ""), "input_schema": t["function"]["parameters"]}`.
5. **Translate `tool_choice`.** Detection rule: if it's a dict containing the key `"function"`, treat as OpenAI shape. Otherwise (string, or a dict with only `"type"`/`"name"` keys), treat as Anthropic shape (pass through).
   - OpenAI string `"auto"` → Anthropic `{"type": "auto"}`
   - OpenAI string `"none"` → omit `tool_choice` from the body entirely
   - OpenAI dict `{"type": "function", "function": {"name": "X"}}` → Anthropic `{"type": "tool", "name": "X"}`
   - Anthropic-shaped dict (e.g., `{"type": "any"}`, `{"type": "tool", "name": "X"}`) → pass through unchanged
6. **Allow-list params.** Iterate `params`; include only keys in `_FORWARDED_PARAMS` with non-None values. Use the translated `stop_sequences`/`tools`/`tool_choice` (not the original `stop`/OpenAI tool shapes).
7. **Build body.**
   ```python
   body = {"model": model, "messages": filtered_messages}
   if system_text:
       body["system"] = system_text
   body["max_tokens"] = max_tokens
   body.update(allowlisted)
   return body
   ```

### `transform_response(raw, model)`

1. Concatenate text blocks: `"".join(b["text"] for b in raw["content"] if b["type"] == "text") or None`.
2. Build `tool_calls` from `tool_use` blocks (or `None` if no tool_use blocks).
3. Map `stop_reason` to `finish_reason` per the table.
4. Build `Usage` from `input_tokens`/`output_tokens`. Synthesize `total_tokens`.
5. Build `Choice(index=0, message=Message(role="assistant", content=text, tool_calls=tcs), finish_reason=...)`.
6. Build `ModelResponse(id=raw["id"], created=int(time.time()), model=raw.get("model", model), choices=[choice], usage=usage)`.

### `transform_stream_chunk(chunk, model)`

`if "type" not in chunk: return None`

Dispatch on `chunk["type"]`:

```python
if chunk["type"] == "content_block_delta":
    delta = chunk["delta"]
    if delta["type"] == "text_delta":
        return _stream_chunk(model, delta_content=delta["text"])
    if delta["type"] == "input_json_delta":
        idx = chunk["index"]  # block index
        return _stream_chunk(model, tool_call_partial=(idx, delta["partial_json"]))
    return None  # other delta types
if chunk["type"] == "message_delta":
    finish = _map_stop_reason(chunk["delta"].get("stop_reason"))
    usage = chunk.get("usage")  # has output_tokens; input_tokens came in message_start
    return _stream_chunk(model, finish_reason=finish, usage=usage)
return None  # message_start, content_block_start, content_block_stop, message_stop, ping
```

`_stream_chunk` is a private helper that builds `ModelResponseStream` with synthesized `id`/`created` defaults.

**Note on streaming usage:** Anthropic delivers `input_tokens` in `message_start` and `output_tokens` in `message_delta` (two separate events). Our provider is stateless, so the final usage chunk (`message_delta`) carries `Usage(prompt_tokens=0, completion_tokens=N, total_tokens=N)` — the input count is dropped because there's no place to retain it across chunks. This differs from OpenAI streaming, where the final chunk carries complete usage.

**Implication for cost calculation:** the dispatcher only computes `usage.cost` on the non-streaming path (`acompletion()` returns a `StreamWrapper` for streaming and never reaches the cost block). So this gap doesn't break the dispatcher. Callers consuming streamed chunks who need cost should compute it themselves after the stream ends — and for Anthropic, the partial `prompt_tokens=0` will under-report cost. Documented limitation; callers needing accurate cost should use `stream=False`. Closing this gap requires either provider state or `StreamWrapper` state, both of which violate Approach A — left for a future ola.

### `get_error_class(status_code, body)`

```python
err = body.get("error") or {}
msg = err.get("message", str(body))
err_type = err.get("type", "")

if status_code == 401:
    return AuthenticationError(status_code, msg)
if status_code == 403:
    return AuthenticationError(status_code, msg)  # closest fit; no PermissionError in SDK
if status_code == 404:
    return NotFoundError(status_code, msg)
if status_code == 408:
    return TimeoutError(status_code, msg)
if status_code == 429:
    return RateLimitError(status_code, msg)
if status_code == 400:
    if "context" in msg.lower() or err_type == "invalid_request_error" and "max_tokens" in msg:
        return ContextWindowExceededError(status_code, msg)
    return BadRequestError(status_code, msg)
if status_code == 503:
    return ServiceUnavailableError(status_code, msg)
if 500 <= status_code < 600:
    return InternalServerError(status_code, msg)
return LiteLLMError(status_code, msg)
```

No equivalent of OpenAI's `content_filter` code — Anthropic surfaces refusals in the response content, not as HTTP errors.

### Module bottom

```python
register_provider("anthropic", AnthropicProvider)
```

## Model Catalog

Append to `src/app/sdk/model_prices.json` (USD per token; verify exact prices from Anthropic docs at implementation time):

```json
{
  "anthropic/claude-opus-4-7": {
    "input_cost_per_token": 1.5e-5,
    "output_cost_per_token": 7.5e-5,
    "max_input_tokens": 200000,
    "max_output_tokens": 32000,
    "supports_tools": true,
    "supports_vision": true,
    "mode": "chat"
  },
  "anthropic/claude-sonnet-4-6": {
    "input_cost_per_token": 3.0e-6,
    "output_cost_per_token": 1.5e-5,
    "max_input_tokens": 200000,
    "max_output_tokens": 64000,
    "supports_tools": true,
    "supports_vision": true,
    "mode": "chat"
  },
  "anthropic/claude-haiku-4-5-20251001": {
    "input_cost_per_token": 8.0e-7,
    "output_cost_per_token": 4.0e-6,
    "max_input_tokens": 200000,
    "max_output_tokens": 8192,
    "supports_tools": true,
    "supports_vision": true,
    "mode": "chat"
  }
}
```

Cost calc already works generically — `calculate_cost("anthropic/claude-haiku-4-5-20251001", usage)` reads from the catalog the same way it does for OpenAI. No code change in `cost.py`.

## Testing

### Unit tests — `tests/test_sdk/providers/test_anthropic.py`

~30 tests, mirroring the structure of `test_openai.py`:

| Group | Count | Coverage |
|---|---|---|
| `get_api_base` | 4 | default, explicit override, env var (monkeypatch), strip trailing slash |
| `get_headers` | 2 | x-api-key + anthropic-version + content-type; extras merge |
| `transform_request` | 8 | model+messages basic; allowlist forwards; drops None; drops unknown; max_tokens default; system extraction (single, multiple → joined, none); tool translation OpenAI→Anthropic; tool_choice translation; stop→stop_sequences |
| `transform_response` | 6 | basic text response; tool_use blocks; multi-block content concat; stop_reason mapping (each value); usage field rename; synthesizes id/created |
| `transform_stream_chunk` | 7 | text_delta yields; input_json_delta yields with partial_json; content_block_start returns None; content_block_stop returns None; message_start returns None; message_delta yields with usage+finish_reason; ping returns None |
| `get_error_class` | 9 | All branches: 401/403/404/408/429/400-context/400-generic/503/500/unknown |
| Registration | 1 | `PROVIDER_REGISTRY["anthropic"] is AnthropicProvider` |

### End-to-end dispatcher tests — append to `test_acompletion.py`

2 tests:

1. `test_acompletion_anthropic_happy_path` — mock `/v1/messages` with a realistic Anthropic response; verify `acompletion(model="anthropic/...")` returns a `ModelResponse` with content, tool calls absent, usage populated and cost computed.
2. `test_acompletion_anthropic_streaming_returns_wrapper` — mock SSE response with `message_start` + `content_block_delta` + `message_delta` events; verify `stream=True` returns a `StreamWrapper` that yields the right number of `ModelResponseStream` chunks.

### Live test — `tests/test_sdk/test_anthropic_live.py`

1 test, `@pytest.mark.live`, mirrors `test_openai_live.py`:

```python
@pytest.mark.live
async def test_anthropic_chat_happy_path():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")

    response = await acompletion(
        model="anthropic/claude-haiku-4-5-20251001",
        messages=[{"role": "user", "content": 'Say "ok" and nothing else.'}],
        max_tokens=10,
        api_key=api_key,
    )

    assert isinstance(response, ModelResponse)
    assert response.choices[0].message.content
    assert response.choices[0].finish_reason in ("stop", "length")
    assert response.usage.prompt_tokens > 0
    assert response.usage.completion_tokens > 0
    assert response.usage.cost is not None
    assert response.usage.cost > 0
```

Cost: ~$0.0001 per run against Haiku. Same gating as OpenAI's live test (`-m live` AND key present, otherwise skipped).

### Test totals

- **New:** ~30 unit + 2 e2e + 1 live = 33 tests
- **SDK total after merge:** 76 (current) + 32 default + 1 live (gated) = 109 (108 default + 1 live)

## Risks and Mitigations

1. **Streaming `tool_use` partial JSON** — Anthropic delivers tool args as a series of `input_json_delta` events with `partial_json` fragments. The caller has to concatenate. Our streaming provider must surface these as partial `arguments` strings on `delta.tool_calls[].function.arguments` so consumers see the same incremental shape they get from OpenAI streaming. **Mitigation:** dedicated unit test (`test_transform_stream_chunk_input_json_delta_yields_partial_args`) asserts the partial passthrough.

2. **System prompt collision** — caller passes both `messages=[{"role": "system", ...}, ...]` AND a top-level `system=` kwarg via `**kwargs`. **Mitigation:** the kwarg is not in `_FORWARDED_PARAMS`, so it gets dropped. Only system-via-messages is supported. Documented in provider docstring + a unit test verifies system-via-kwarg is dropped.

3. **Empty content blocks** — `content: []` is valid (model only made tool calls, no text). **Mitigation:** `transform_response` returns `message.content = None` (not empty string), matching OpenAI's behavior in this scenario. Unit test covers.

4. **`pause_turn` finish_reason** — rare, very long generations. **Mitigation:** pass through unmapped; let downstream handle. Document in the mapping table.

5. **Pricing drift** — the catalog values in this spec are placeholders. **Mitigation:** the implementation plan (Task 1) will fetch current Anthropic pricing from official docs and update the JSON. The pin test (`test_catalog_locked_to_known_prices`) catches future drift.

## Open Questions

None at design-approval time. Implementation may surface details (e.g., exact Anthropic error type names for status 503 — we'll see in the live test). Document deviations in the implementation plan.

## Future Olas (referenced from project_progress.md)

After ola-13:

- ola-14: Gemini provider (third provider — strongest abstraction validation)
- Embeddings (cross-provider — separate ola)
- Vision (when first vision-using caller appears)
- Extended thinking (when first thinking-using caller appears)
- Prompt caching
- Vertex AI / Bedrock variants

These are explicitly not blocked on each other. Each can land independently.
