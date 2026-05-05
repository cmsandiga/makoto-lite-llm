# Core SDK — Anthropic Provider (ola-13) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `AnthropicProvider` as a second `BaseProvider` implementation, matching the scope of ola-12 (chat completions + tools + streaming). Validate that the provider abstraction generalizes without changes to `BaseProvider`, the dispatcher, or any other SDK infrastructure.

**Architecture:** A single new file `src/app/sdk/providers/anthropic.py` implements the 6 abstract methods of `BaseProvider`. Anthropic-specific wire-format translation (system message extraction, tool format, content blocks, SSE event types, error shapes) lives entirely inside that file. Registration via side-effect import in `providers/__init__.py`. Catalog entries appended to `model_prices.json`.

**Tech Stack:** Python 3.11+, Pydantic, httpx (async), pytest + pytest-asyncio, respx (HTTP mocking).

**Spec:** `docs/superpowers/specs/2026-05-05-anthropic-provider-design.md`

---

## File Structure

```
src/app/sdk/providers/
├── __init__.py        # MODIFIED: add `from app.sdk.providers import anthropic`
└── anthropic.py       # NEW

src/app/sdk/
└── model_prices.json  # MODIFIED: append 3 Anthropic entries

tests/test_sdk/
├── providers/
│   └── test_anthropic.py     # NEW: ~30 unit tests
├── test_acompletion.py       # MODIFIED: append 2 e2e dispatcher tests
└── test_anthropic_live.py    # NEW: 1 @pytest.mark.live test
```

**Untouched:** `main.py`, `resolver.py`, `http_client.py`, `cost.py`, `types.py`, `exceptions.py`, `providers/base.py`, `pyproject.toml`, the public `__init__.py`. The whole point of this ola is that `BaseProvider` already supports what we need.

**Validation criterion:** if any of the "Untouched" files needs modification, stop. The abstraction has failed; brainstorm a refactor before continuing.

---

### Task 1: Anthropic provider scaffold + request side

**Goal:** Create `AnthropicProvider` with `get_api_base`, `get_headers`, and `transform_request` implemented. The other 3 methods (`transform_response`, `transform_stream_chunk`, `get_error_class`) raise `NotImplementedError` for now — filled in by Tasks 2-4.

**Files:**
- Create: `src/app/sdk/providers/anthropic.py`
- Create: `tests/test_sdk/providers/test_anthropic.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sdk/providers/test_anthropic.py`:

```python
from app.sdk.providers.anthropic import (
    ANTHROPIC_VERSION,
    DEFAULT_API_BASE,
    DEFAULT_MAX_TOKENS,
    AnthropicProvider,
)


# ---- get_api_base ----

def test_get_api_base_default():
    p = AnthropicProvider()
    assert p.get_api_base("claude-sonnet-4-6", None) == DEFAULT_API_BASE


def test_get_api_base_explicit_override():
    p = AnthropicProvider()
    assert p.get_api_base("claude-sonnet-4-6", "https://my-proxy/v1") == "https://my-proxy/v1"


def test_get_api_base_strips_trailing_slash():
    p = AnthropicProvider()
    assert p.get_api_base("claude-sonnet-4-6", "https://my-proxy/v1/") == "https://my-proxy/v1"


def test_get_api_base_env_var(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_BASE", "https://env-proxy/v1")
    p = AnthropicProvider()
    assert p.get_api_base("claude-sonnet-4-6", None) == "https://env-proxy/v1"


# ---- get_headers ----

def test_get_headers_includes_required():
    p = AnthropicProvider()
    headers = p.get_headers("sk-ant-secret", None)
    assert headers["x-api-key"] == "sk-ant-secret"
    assert headers["anthropic-version"] == ANTHROPIC_VERSION
    assert headers["content-type"] == "application/json"


def test_get_headers_merges_extra():
    p = AnthropicProvider()
    headers = p.get_headers("sk-ant-secret", {"X-Trace-Id": "abc"})
    assert headers["X-Trace-Id"] == "abc"
    assert headers["x-api-key"] == "sk-ant-secret"


# ---- transform_request ----

def test_transform_request_basic():
    p = AnthropicProvider()
    body = p.transform_request(
        "claude-sonnet-4-6",
        [{"role": "user", "content": "hi"}],
        {},
    )
    assert body["model"] == "claude-sonnet-4-6"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["max_tokens"] == DEFAULT_MAX_TOKENS
    assert "system" not in body  # no system message → no field


def test_transform_request_uses_explicit_max_tokens():
    p = AnthropicProvider()
    body = p.transform_request(
        "claude-sonnet-4-6", [], {"max_tokens": 100}
    )
    assert body["max_tokens"] == 100


def test_transform_request_extracts_single_system_message():
    p = AnthropicProvider()
    body = p.transform_request(
        "claude-sonnet-4-6",
        [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Hi"},
        ],
        {},
    )
    assert body["system"] == "Be concise."
    assert body["messages"] == [{"role": "user", "content": "Hi"}]


def test_transform_request_concatenates_multiple_system_messages():
    p = AnthropicProvider()
    body = p.transform_request(
        "claude-sonnet-4-6",
        [
            {"role": "system", "content": "Rule 1."},
            {"role": "system", "content": "Rule 2."},
            {"role": "user", "content": "Hi"},
        ],
        {},
    )
    assert body["system"] == "Rule 1.\n\nRule 2."
    assert body["messages"] == [{"role": "user", "content": "Hi"}]


def test_transform_request_forwards_allowlisted_params():
    p = AnthropicProvider()
    body = p.transform_request(
        "claude-sonnet-4-6",
        [],
        {"temperature": 0.7, "top_p": 0.9, "top_k": 40, "stream": True},
    )
    assert body["temperature"] == 0.7
    assert body["top_p"] == 0.9
    assert body["top_k"] == 40
    assert body["stream"] is True


def test_transform_request_drops_none_values():
    p = AnthropicProvider()
    body = p.transform_request(
        "claude-sonnet-4-6",
        [],
        {"temperature": None, "top_p": 0.9},
    )
    assert "temperature" not in body
    assert body["top_p"] == 0.9


def test_transform_request_drops_unknown_keys():
    p = AnthropicProvider()
    body = p.transform_request(
        "claude-sonnet-4-6",
        [],
        {"temperature": 0.5, "made_up_param": "x"},
    )
    assert "made_up_param" not in body
    assert body["temperature"] == 0.5


def test_transform_request_translates_stop_to_stop_sequences():
    p = AnthropicProvider()
    body = p.transform_request(
        "claude-sonnet-4-6", [], {"stop": ["END", "STOP"]}
    )
    assert body["stop_sequences"] == ["END", "STOP"]
    assert "stop" not in body


def test_transform_request_coerces_stop_string_to_list():
    p = AnthropicProvider()
    body = p.transform_request(
        "claude-sonnet-4-6", [], {"stop": "END"}
    )
    assert body["stop_sequences"] == ["END"]


def test_transform_request_translates_openai_tools():
    p = AnthropicProvider()
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    body = p.transform_request("claude-sonnet-4-6", [], {"tools": openai_tools})
    assert body["tools"] == [
        {
            "name": "get_weather",
            "description": "Get weather",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ]


def test_transform_request_translates_tool_choice_auto():
    p = AnthropicProvider()
    body = p.transform_request(
        "claude-sonnet-4-6", [], {"tool_choice": "auto"}
    )
    assert body["tool_choice"] == {"type": "auto"}


def test_transform_request_omits_tool_choice_none():
    p = AnthropicProvider()
    body = p.transform_request(
        "claude-sonnet-4-6", [], {"tool_choice": "none"}
    )
    assert "tool_choice" not in body


def test_transform_request_translates_tool_choice_function_dict():
    p = AnthropicProvider()
    body = p.transform_request(
        "claude-sonnet-4-6",
        [],
        {"tool_choice": {"type": "function", "function": {"name": "X"}}},
    )
    assert body["tool_choice"] == {"type": "tool", "name": "X"}


def test_transform_request_passes_through_anthropic_shaped_tool_choice():
    p = AnthropicProvider()
    body = p.transform_request(
        "claude-sonnet-4-6", [], {"tool_choice": {"type": "any"}}
    )
    assert body["tool_choice"] == {"type": "any"}


def test_transform_request_drops_top_level_system_kwarg():
    """system-via-messages is the only supported way; system kwarg is dropped."""
    p = AnthropicProvider()
    body = p.transform_request(
        "claude-sonnet-4-6",
        [{"role": "user", "content": "hi"}],
        {"system": "from kwarg"},
    )
    assert "system" not in body  # not in allowlist, and no system message present
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_sdk/providers/test_anthropic.py -v 2>&1 | tail -5
```

Expected: ImportError on `app.sdk.providers.anthropic`.

- [ ] **Step 3: Implement `anthropic.py`**

Create `src/app/sdk/providers/anthropic.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_sdk/providers/test_anthropic.py -v 2>&1 | tail -25
```

Expected: 17 passed (the 17 request-side tests above).

- [ ] **Step 5: Run linters**

```bash
uv run ruff check src/app/sdk/providers/anthropic.py tests/test_sdk/providers/test_anthropic.py
uv run mypy src/app/sdk/providers/anthropic.py
```

Both must be clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/sdk/providers/anthropic.py tests/test_sdk/providers/test_anthropic.py
git commit -m "feat(sdk): Anthropic provider — request side (api_base, headers, transform_request)"
```

---

### Task 2: Anthropic provider — `transform_response`

**Goal:** Implement `transform_response`. Collapse Anthropic content blocks into OpenAI-shaped `Message`, map `stop_reason` → `finish_reason`, rename usage fields.

**Files:**
- Modify: `src/app/sdk/providers/anthropic.py`
- Modify: `tests/test_sdk/providers/test_anthropic.py`

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_sdk/providers/test_anthropic.py`:

```python
# ---- transform_response ----

def test_transform_response_basic_text():
    raw = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-6",
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 1},
    }
    p = AnthropicProvider()
    resp = p.transform_response(raw, "claude-sonnet-4-6")
    assert resp.id == "msg_1"
    assert resp.model == "claude-sonnet-4-6"
    assert resp.choices[0].message.role == "assistant"
    assert resp.choices[0].message.content == "ok"
    assert resp.choices[0].message.tool_calls is None
    assert resp.choices[0].finish_reason == "stop"
    assert resp.usage.prompt_tokens == 10
    assert resp.usage.completion_tokens == 1
    assert resp.usage.total_tokens == 11


def test_transform_response_multi_text_blocks_concatenated():
    raw = {
        "id": "msg_2",
        "model": "claude-sonnet-4-6",
        "content": [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": " world"},
        ],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 1, "output_tokens": 2},
    }
    p = AnthropicProvider()
    resp = p.transform_response(raw, "claude-sonnet-4-6")
    assert resp.choices[0].message.content == "Hello world"


def test_transform_response_with_tool_use_blocks():
    raw = {
        "id": "msg_3",
        "model": "claude-sonnet-4-6",
        "content": [
            {"type": "text", "text": "Let me check."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "get_weather",
                "input": {"city": "sf"},
            },
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 20, "output_tokens": 5},
    }
    p = AnthropicProvider()
    resp = p.transform_response(raw, "claude-sonnet-4-6")
    msg = resp.choices[0].message
    assert msg.content == "Let me check."
    assert msg.tool_calls is not None
    assert len(msg.tool_calls) == 1
    tc = msg.tool_calls[0]
    assert tc.id == "toolu_1"
    assert tc.type == "function"
    assert tc.function.name == "get_weather"
    assert tc.function.arguments == '{"city": "sf"}'
    assert resp.choices[0].finish_reason == "tool_calls"


def test_transform_response_only_tool_use_content_is_none():
    """When the model produces only tool_use blocks, content should be None."""
    raw = {
        "id": "msg_4",
        "model": "claude-sonnet-4-6",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "x",
                "input": {},
            }
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 5, "output_tokens": 1},
    }
    p = AnthropicProvider()
    resp = p.transform_response(raw, "claude-sonnet-4-6")
    assert resp.choices[0].message.content is None
    assert len(resp.choices[0].message.tool_calls) == 1


def test_transform_response_stop_reason_mapping():
    p = AnthropicProvider()
    cases = [
        ("end_turn", "stop"),
        ("max_tokens", "length"),
        ("tool_use", "tool_calls"),
        ("stop_sequence", "stop"),
        ("pause_turn", "pause_turn"),  # passthrough
    ]
    for anthropic_reason, expected in cases:
        raw = {
            "id": "x",
            "model": "claude-sonnet-4-6",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": anthropic_reason,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        resp = p.transform_response(raw, "claude-sonnet-4-6")
        assert resp.choices[0].finish_reason == expected, (
            f"{anthropic_reason} mapped to {resp.choices[0].finish_reason}, expected {expected}"
        )


def test_transform_response_synthesizes_created_field():
    """Anthropic doesn't return a 'created' timestamp; we synthesize one."""
    raw = {
        "id": "x",
        "model": "claude-sonnet-4-6",
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    p = AnthropicProvider()
    resp = p.transform_response(raw, "claude-sonnet-4-6")
    assert resp.created > 0  # any positive integer (current time)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_sdk/providers/test_anthropic.py::test_transform_response_basic_text -v 2>&1 | tail -5
```

Expected: NotImplementedError raised by the stub.

- [ ] **Step 3: Update imports + implement `transform_response`**

In `src/app/sdk/providers/anthropic.py`, replace the existing import block:

```python
import os

from app.sdk.providers.base import BaseProvider, register_provider
from app.sdk.types import ModelResponse, ModelResponseStream
```

with:

```python
import json
import os
import time

from app.sdk.providers.base import BaseProvider, register_provider
from app.sdk.types import (
    Choice,
    Message,
    ModelResponse,
    ModelResponseStream,
    ToolCall,
    FunctionCall,
    Usage,
)

_STOP_REASON_MAP = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "stop_sequence": "stop",
}
```

Then replace the `transform_response` stub with:

```python
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
        finish_reason = _STOP_REASON_MAP.get(anthropic_reason, anthropic_reason)

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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_sdk/providers/test_anthropic.py -v 2>&1 | tail -10
```

Expected: 23 passed (17 from Task 1 + 6 new).

- [ ] **Step 5: Run linters**

```bash
uv run ruff check src/app/sdk/providers/anthropic.py tests/test_sdk/providers/test_anthropic.py
uv run mypy src/app/sdk/providers/anthropic.py
```

Both must be clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/sdk/providers/anthropic.py tests/test_sdk/providers/test_anthropic.py
git commit -m "feat(sdk): Anthropic provider — transform_response (content blocks → ModelResponse)"
```

---

### Task 3: Anthropic provider — `transform_stream_chunk`

**Goal:** Implement streaming chunk translation. Anthropic SSE has 7 event types; most yield `None` (skip), only `content_block_delta` (text or tool args) and `message_delta` (final usage + finish_reason) yield `ModelResponseStream`.

**Files:**
- Modify: `src/app/sdk/providers/anthropic.py`
- Modify: `tests/test_sdk/providers/test_anthropic.py`

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_sdk/providers/test_anthropic.py`:

```python
# ---- transform_stream_chunk ----

def test_transform_stream_chunk_text_delta():
    chunk = {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "Hel"},
    }
    p = AnthropicProvider()
    parsed = p.transform_stream_chunk(chunk, "claude-sonnet-4-6")
    assert parsed is not None
    assert parsed.choices[0].delta.content == "Hel"
    assert parsed.choices[0].delta.tool_calls is None


def test_transform_stream_chunk_input_json_delta():
    chunk = {
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "input_json_delta", "partial_json": '{"ci'},
    }
    p = AnthropicProvider()
    parsed = p.transform_stream_chunk(chunk, "claude-sonnet-4-6")
    assert parsed is not None
    tcs = parsed.choices[0].delta.tool_calls
    assert tcs is not None
    assert len(tcs) == 1
    assert tcs[0].function.arguments == '{"ci'
    # content should be None for tool-arg-only chunks
    assert parsed.choices[0].delta.content is None


def test_transform_stream_chunk_message_start_returns_none():
    chunk = {
        "type": "message_start",
        "message": {
            "id": "msg_1",
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 10, "output_tokens": 0},
        },
    }
    p = AnthropicProvider()
    assert p.transform_stream_chunk(chunk, "claude-sonnet-4-6") is None


def test_transform_stream_chunk_content_block_start_returns_none():
    chunk = {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    }
    p = AnthropicProvider()
    assert p.transform_stream_chunk(chunk, "claude-sonnet-4-6") is None


def test_transform_stream_chunk_content_block_stop_returns_none():
    chunk = {"type": "content_block_stop", "index": 0}
    p = AnthropicProvider()
    assert p.transform_stream_chunk(chunk, "claude-sonnet-4-6") is None


def test_transform_stream_chunk_message_delta_yields_finish_and_usage():
    chunk = {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": 7},
    }
    p = AnthropicProvider()
    parsed = p.transform_stream_chunk(chunk, "claude-sonnet-4-6")
    assert parsed is not None
    assert parsed.choices[0].finish_reason == "stop"
    assert parsed.usage is not None
    # input_tokens are not in this event; provider stateless => prompt_tokens = 0
    assert parsed.usage.prompt_tokens == 0
    assert parsed.usage.completion_tokens == 7


def test_transform_stream_chunk_message_stop_returns_none():
    chunk = {"type": "message_stop"}
    p = AnthropicProvider()
    assert p.transform_stream_chunk(chunk, "claude-sonnet-4-6") is None


def test_transform_stream_chunk_ping_returns_none():
    chunk = {"type": "ping"}
    p = AnthropicProvider()
    assert p.transform_stream_chunk(chunk, "claude-sonnet-4-6") is None


def test_transform_stream_chunk_no_type_key_returns_none():
    chunk = {}
    p = AnthropicProvider()
    assert p.transform_stream_chunk(chunk, "claude-sonnet-4-6") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_sdk/providers/test_anthropic.py::test_transform_stream_chunk_text_delta -v 2>&1 | tail -5
```

Expected: NotImplementedError raised by the stub.

- [ ] **Step 3: Update imports + implement `transform_stream_chunk`**

In `src/app/sdk/providers/anthropic.py`, update the imports from `app.sdk.types` to also include `Delta` and `StreamChoice`:

```python
from app.sdk.types import (
    Choice,
    Delta,
    Message,
    ModelResponse,
    ModelResponseStream,
    StreamChoice,
    ToolCall,
    FunctionCall,
    Usage,
)
```

Add `import uuid` to the top imports (next to `import time`).

Then replace the `transform_stream_chunk` stub with:

```python
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
            finish_reason = _STOP_REASON_MAP.get(anthropic_reason, anthropic_reason)
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_sdk/providers/test_anthropic.py -v 2>&1 | tail -15
```

Expected: 32 passed (23 from prior + 9 new).

- [ ] **Step 5: Run linters**

```bash
uv run ruff check src/app/sdk/providers/anthropic.py tests/test_sdk/providers/test_anthropic.py
uv run mypy src/app/sdk/providers/anthropic.py
```

Both must be clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/sdk/providers/anthropic.py tests/test_sdk/providers/test_anthropic.py
git commit -m "feat(sdk): Anthropic provider — transform_stream_chunk (SSE → ModelResponseStream)"
```

---

### Task 4: Anthropic provider — `get_error_class`

**Goal:** Implement error mapping from Anthropic's wire error format to the SDK's typed exceptions.

**Files:**
- Modify: `src/app/sdk/providers/anthropic.py`
- Modify: `tests/test_sdk/providers/test_anthropic.py`

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_sdk/providers/test_anthropic.py`:

```python
from app.sdk.exceptions import (
    AuthenticationError,
    BadRequestError,
    ContextWindowExceededError,
    InternalServerError,
    LiteLLMError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    TimeoutError as SdkTimeoutError,
)


# ---- get_error_class ----

def test_error_401_authentication():
    p = AnthropicProvider()
    err = p.get_error_class(
        401, {"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}
    )
    assert isinstance(err, AuthenticationError)
    assert err.status_code == 401


def test_error_403_permission():
    p = AnthropicProvider()
    err = p.get_error_class(
        403, {"type": "error", "error": {"type": "permission_error", "message": "no"}}
    )
    assert isinstance(err, AuthenticationError)


def test_error_404_not_found():
    p = AnthropicProvider()
    err = p.get_error_class(
        404, {"type": "error", "error": {"type": "not_found_error", "message": "?"}}
    )
    assert isinstance(err, NotFoundError)


def test_error_408_timeout():
    p = AnthropicProvider()
    err = p.get_error_class(408, {"error": {"message": "slow"}})
    assert isinstance(err, SdkTimeoutError)


def test_error_429_rate_limit():
    p = AnthropicProvider()
    err = p.get_error_class(
        429, {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}
    )
    assert isinstance(err, RateLimitError)


def test_error_400_context_message_phrase():
    p = AnthropicProvider()
    err = p.get_error_class(
        400,
        {"type": "error", "error": {
            "type": "invalid_request_error",
            "message": "prompt is too long for the context window",
        }},
    )
    assert isinstance(err, ContextWindowExceededError)


def test_error_400_max_tokens_phrase():
    p = AnthropicProvider()
    err = p.get_error_class(
        400,
        {"type": "error", "error": {
            "type": "invalid_request_error",
            "message": "max_tokens exceeds model maximum",
        }},
    )
    assert isinstance(err, ContextWindowExceededError)


def test_error_400_generic_bad_request():
    p = AnthropicProvider()
    err = p.get_error_class(
        400,
        {"type": "error", "error": {"type": "invalid_request_error", "message": "missing field"}},
    )
    assert isinstance(err, BadRequestError)


def test_error_503_service_unavailable():
    p = AnthropicProvider()
    err = p.get_error_class(
        503, {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
    )
    assert isinstance(err, ServiceUnavailableError)


def test_error_500_internal():
    p = AnthropicProvider()
    err = p.get_error_class(
        500, {"type": "error", "error": {"type": "api_error", "message": "boom"}}
    )
    assert isinstance(err, InternalServerError)


def test_error_unknown_status_falls_back_to_litellm_error():
    p = AnthropicProvider()
    err = p.get_error_class(418, {"error": {"message": "teapot"}})
    assert type(err) is LiteLLMError
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_sdk/providers/test_anthropic.py::test_error_401_authentication -v 2>&1 | tail -5
```

Expected: NotImplementedError raised by the stub.

- [ ] **Step 3: Update imports + implement `get_error_class`**

In `src/app/sdk/providers/anthropic.py`, add the exception imports near the top:

```python
from app.sdk.exceptions import (
    AuthenticationError,
    BadRequestError,
    ContextWindowExceededError,
    InternalServerError,
    LiteLLMError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    TimeoutError,
)
```

Then replace the `get_error_class` stub with:

```python
    def get_error_class(self, status_code: int, body: dict) -> Exception:
        err = body.get("error") or {}
        msg = err.get("message", str(body))
        msg_lower = msg.lower()

        if status_code == 401:
            return AuthenticationError(status_code, msg)
        if status_code == 403:
            return AuthenticationError(status_code, msg)
        if status_code == 404:
            return NotFoundError(status_code, msg)
        if status_code == 408:
            return TimeoutError(status_code, msg)
        if status_code == 429:
            return RateLimitError(status_code, msg)
        if status_code == 400:
            if "context" in msg_lower or "max_tokens" in msg_lower:
                return ContextWindowExceededError(status_code, msg)
            return BadRequestError(status_code, msg)
        if status_code == 503:
            return ServiceUnavailableError(status_code, msg)
        if 500 <= status_code < 600:
            return InternalServerError(status_code, msg)
        return LiteLLMError(status_code, msg)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_sdk/providers/test_anthropic.py -v 2>&1 | tail -15
```

Expected: 43 passed (32 prior + 11 new).

- [ ] **Step 5: Run linters**

```bash
uv run ruff check src/app/sdk/providers/anthropic.py tests/test_sdk/providers/test_anthropic.py
uv run mypy src/app/sdk/providers/anthropic.py
```

Both must be clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/sdk/providers/anthropic.py tests/test_sdk/providers/test_anthropic.py
git commit -m "feat(sdk): Anthropic provider — get_error_class (status + body → typed exception)"
```

---

### Task 5: Provider registration

**Goal:** Wire `AnthropicProvider` into `PROVIDER_REGISTRY` via the package's side-effect import. Verify registration via a smoke test.

**Files:**
- Modify: `src/app/sdk/providers/__init__.py`
- Modify: `tests/test_sdk/providers/test_anthropic.py`

- [ ] **Step 1: Append the failing test**

Append to `tests/test_sdk/providers/test_anthropic.py`:

```python
def test_provider_is_registered():
    """Importing the providers package side-effects register_provider('anthropic', ...)."""
    from app.sdk.providers.base import PROVIDER_REGISTRY

    assert PROVIDER_REGISTRY["anthropic"] is AnthropicProvider
```

- [ ] **Step 2: Run test to verify it passes already**

The `register_provider("anthropic", AnthropicProvider)` line at the bottom of `anthropic.py` is executed when the module is imported. Since the test file imports `AnthropicProvider` at the top, the registration has already happened.

```bash
uv run pytest tests/test_sdk/providers/test_anthropic.py::test_provider_is_registered -v 2>&1 | tail -5
```

Expected: 1 passed.

But there's still work to do: when the SDK is imported via `from app.sdk import acompletion` (without explicitly importing `app.sdk.providers.anthropic`), the registration only happens if `providers/__init__.py` imports the module. Verify this by also checking that.

- [ ] **Step 3: Update `providers/__init__.py` to trigger registration**

Read `src/app/sdk/providers/__init__.py`. It currently looks like:

```python
"""Side-effect import: registers each provider into PROVIDER_REGISTRY."""
from app.sdk.providers import openai  # noqa: F401  registers "openai"
```

Replace it with:

```python
"""Side-effect import: registers each provider into PROVIDER_REGISTRY."""
from app.sdk.providers import anthropic  # noqa: F401  registers "anthropic"
from app.sdk.providers import openai  # noqa: F401  registers "openai"
```

(Alphabetical ordering by provider name.)

- [ ] **Step 4: Verify the SDK-level import works**

```bash
uv run python -c "from app.sdk import acompletion; from app.sdk.providers.base import PROVIDER_REGISTRY; print(sorted(PROVIDER_REGISTRY))"
```

Expected output: `['anthropic', 'openai']`.

- [ ] **Step 5: Run the full SDK test suite to ensure nothing regressed**

```bash
uv run pytest tests/test_sdk/ -v 2>&1 | tail -3
```

Expected: 76 (current) + 44 (Tasks 1-4) = 120 passing. Plus the 1 new registration test = 121 total. Confirm no failures.

(Adjust the expected count if Tasks 1-4 added a different number of tests than 44 due to test refactoring.)

- [ ] **Step 6: Run linters**

```bash
uv run ruff check src/app/sdk/providers/__init__.py
```

Must be clean.

- [ ] **Step 7: Commit**

```bash
git add src/app/sdk/providers/__init__.py tests/test_sdk/providers/test_anthropic.py
git commit -m "feat(sdk): register Anthropic provider via providers/__init__.py side-effect import"
```

---

### Task 6: Model price catalog + pin test

**Goal:** Append 3 Anthropic chat models to `model_prices.json`. Add a pin test so a typo in JSON fails CI loudly.

**Files:**
- Modify: `src/app/sdk/model_prices.json`
- Modify: `tests/test_sdk/test_cost.py`

**Pricing source:** verify against Anthropic's published pricing page at implementation time; the values below are placeholders that may be off. The pin test catches drift but doesn't validate against the live source — the engineer should sanity-check before committing.

- [ ] **Step 1: Append failing tests to `test_cost.py`**

Append to `tests/test_sdk/test_cost.py`:

```python
def test_anthropic_models_present_in_catalog():
    _reset_cache()
    prices = cost_module._load()
    assert "anthropic/claude-opus-4-7" in prices
    assert "anthropic/claude-sonnet-4-6" in prices
    assert "anthropic/claude-haiku-4-5-20251001" in prices


def test_anthropic_haiku_cost_calc():
    _reset_cache()
    usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    c = calculate_cost("anthropic/claude-haiku-4-5-20251001", usage)
    # 1000 * 8.0e-7 + 500 * 4.0e-6 = 8e-4 + 2e-3 = 0.0028
    assert c == pytest.approx(0.0028, rel=1e-9)


def test_anthropic_catalog_pinned_prices():
    """Pin the Anthropic catalog so a typo in JSON fails CI loudly."""
    _reset_cache()
    prices = cost_module._load()
    assert prices["anthropic/claude-opus-4-7"]["input_cost_per_token"] == 1.5e-5
    assert prices["anthropic/claude-sonnet-4-6"]["output_cost_per_token"] == 1.5e-5
    assert prices["anthropic/claude-haiku-4-5-20251001"]["input_cost_per_token"] == 8.0e-7
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_sdk/test_cost.py::test_anthropic_models_present_in_catalog -v 2>&1 | tail -5
```

Expected: KeyError or assertion failure (catalog doesn't have these entries).

- [ ] **Step 3: Append entries to `model_prices.json`**

Read `src/app/sdk/model_prices.json`. It currently has 4 OpenAI entries inside one top-level JSON object. The trailing entry (`openai/gpt-3.5-turbo`) ends without a comma, then the closing `}` of the object.

Add a comma after the closing `}` of `openai/gpt-3.5-turbo`'s entry, then append:

```json
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
```

(With the trailing `}` of the file remaining at end.)

After editing, verify the JSON is syntactically valid:

```bash
uv run python -c "import json; print(len(json.load(open('src/app/sdk/model_prices.json'))))"
```

Expected output: `7` (4 OpenAI + 3 Anthropic models).

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_sdk/test_cost.py -v 2>&1 | tail -10
```

Expected: 8 passed (5 from ola-12 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/app/sdk/model_prices.json tests/test_sdk/test_cost.py
git commit -m "feat(sdk): add 3 Anthropic chat models to price catalog (Opus 4.7, Sonnet 4.6, Haiku 4.5)"
```

---

### Task 7: End-to-end dispatcher tests

**Goal:** Add 2 tests to `test_acompletion.py` that exercise the full `acompletion(model="anthropic/...")` flow via mocked HTTP responses. This proves the dispatcher reaches `AnthropicProvider` correctly without re-testing provider internals.

**Files:**
- Modify: `tests/test_sdk/test_acompletion.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_sdk/test_acompletion.py`:

```python
@respx.mock
async def test_acompletion_anthropic_happy_path():
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

    resp = await acompletion(
        model="anthropic/claude-haiku-4-5-20251001",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-ant-test",
        max_tokens=10,
    )
    assert isinstance(resp, ModelResponse)
    assert resp.choices[0].message.content == "ok"
    assert resp.usage.prompt_tokens == 10
    assert resp.usage.completion_tokens == 1
    # Cost computed by dispatcher using the catalog
    assert resp.usage.cost is not None
    # 10 * 8.0e-7 + 1 * 4.0e-6 = 8e-6 + 4e-6 = 1.2e-5
    assert resp.usage.cost == pytest.approx(1.2e-5, rel=1e-9)


@respx.mock
async def test_acompletion_anthropic_streaming_returns_wrapper():
    body = (
        b'event: message_start\n'
        b'data: {"type":"message_start","message":'
        b'{"id":"msg_1","model":"claude-haiku-4-5-20251001",'
        b'"usage":{"input_tokens":5,"output_tokens":0}}}\n\n'
        b'event: content_block_start\n'
        b'data: {"type":"content_block_start","index":0,'
        b'"content_block":{"type":"text","text":""}}\n\n'
        b'event: content_block_delta\n'
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":"He"}}\n\n'
        b'event: content_block_delta\n'
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":"llo"}}\n\n'
        b'event: content_block_stop\n'
        b'data: {"type":"content_block_stop","index":0}\n\n'
        b'event: message_delta\n'
        b'data: {"type":"message_delta",'
        b'"delta":{"stop_reason":"end_turn"},'
        b'"usage":{"output_tokens":3}}\n\n'
        b'event: message_stop\n'
        b'data: {"type":"message_stop"}\n\n'
    )
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )
    )

    result = await acompletion(
        model="anthropic/claude-haiku-4-5-20251001",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-ant-test",
        stream=True,
    )
    assert isinstance(result, StreamWrapper)

    chunks: list[ModelResponseStream] = []
    async for chunk in result:
        chunks.append(chunk)

    # Expected chunks: 2 text deltas + 1 message_delta = 3 yielded
    # (message_start, content_block_start, content_block_stop, message_stop return None)
    assert len(chunks) == 3
    assert chunks[0].choices[0].delta.content == "He"
    assert chunks[1].choices[0].delta.content == "llo"
    assert chunks[2].choices[0].finish_reason == "stop"
```

**Note:** The test_acompletion.py file already imports `httpx`, `pytest`, `respx`, `acompletion`, `ModelResponse`, `ModelResponseStream`, `StreamWrapper` at the top from earlier tasks. No new imports are needed. The autouse `_reset_http_client_singleton` fixture also remains in effect, isolating these tests from the OpenAI tests' mocks.

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/test_sdk/test_acompletion.py -v 2>&1 | tail -15
```

Expected: 9 passed (7 from ola-12 + 2 new).

- [ ] **Step 3: Run linters**

```bash
uv run ruff check tests/test_sdk/test_acompletion.py
```

Must be clean. The SSE body literal is wrapped onto multiple `b"..."` fragments to stay under the 100-char line limit; if ruff complains, split further.

- [ ] **Step 4: Commit**

```bash
git add tests/test_sdk/test_acompletion.py
git commit -m "test(sdk): e2e dispatcher tests for Anthropic provider (happy path + streaming)"
```

---

### Task 8: Live test against real Anthropic

**Goal:** A single gated test that hits the real Anthropic API. Mirrors `test_openai_live.py`. Skipped unless `ANTHROPIC_API_KEY` is set AND `-m live` is passed.

**Files:**
- Create: `tests/test_sdk/test_anthropic_live.py`

- [ ] **Step 1: Create the live test**

Create `tests/test_sdk/test_anthropic_live.py`:

```python
"""Live integration test against real Anthropic.

Skipped unless ANTHROPIC_API_KEY is set AND `-m live` is passed.
Run: `ANTHROPIC_API_KEY=sk-ant-... uv run pytest -m live`
Cost: ~$0.0001 per run (claude-haiku-4-5-20251001, ~5 output tokens).
"""

import os

import pytest

from app.sdk import acompletion
from app.sdk.types import ModelResponse


@pytest.mark.live
async def test_anthropic_chat_happy_path():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")

    response = await acompletion(
        model="anthropic/claude-haiku-4-5-20251001",
        messages=[
            {"role": "user", "content": 'Say "ok" and nothing else.'}
        ],
        max_tokens=10,
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
uv run pytest tests/test_sdk/ --collect-only -q 2>&1 | tail -5
```

Expected: collected count includes the new test, plus a "1 deselected" note for the live test.

- [ ] **Step 3: Confirm `-m live` SKIPS without key**

```bash
unset ANTHROPIC_API_KEY  # ensure not set
uv run pytest -m live tests/test_sdk/test_anthropic_live.py -v 2>&1 | tail -5
```

Expected: 1 skipped, reason: `ANTHROPIC_API_KEY not set`.

- [ ] **Step 4: STOP — request user runs the live test with their key**

The live test calls real Anthropic and costs ~$0.0001. **Do NOT run it from a subagent context.** Surface this command to the user:

```bash
ANTHROPIC_API_KEY=sk-ant-... uv run pytest -m live tests/test_sdk/test_anthropic_live.py -v
```

Expected (when the user runs it): 1 passed in ~1-3s.

- [ ] **Step 5: Run linters**

```bash
uv run ruff check tests/test_sdk/test_anthropic_live.py
```

Must be clean.

- [ ] **Step 6: Commit**

```bash
git add tests/test_sdk/test_anthropic_live.py
git commit -m "test(sdk): add gated live test against real Anthropic Haiku 4.5"
```

---

### Task 9: Update progress notes

**Goal:** Update the project memory files to reflect ola-13 completion.

**Files:**
- Modify: `/Users/makoto.sandiga/.claude/projects/-Users-makoto-sandiga-dev-me-makoto-lite-llm/memory/project_progress.md`
- Modify: `/Users/makoto.sandiga/.claude/projects/-Users-makoto-sandiga-dev-me-makoto-lite-llm/memory/MEMORY.md`

These are memory files outside the repo — no git commit required.

- [ ] **Step 1: Update `MEMORY.md`**

Read the file. Replace the line:

```
- [Project Progress](project_progress.md) — Auth done; Core SDK ola-12 (OpenAI chat) done, ~229 tests, 16 PRs, next: Anthropic provider
```

with:

```
- [Project Progress](project_progress.md) — Auth done; Core SDK ola-12 (OpenAI) + ola-13 (Anthropic) done, ~261 tests, 18 PRs (housekeeping #17 + ola-13 #18), next: Gemini provider OR proxy HTTP routes
```

(Adjust counts if test totals differ from estimate.)

- [ ] **Step 2: Update `project_progress.md`**

In the "Completed Olas (Core SDK)" table, append a row:

```
| 13 | Anthropic chat completions: full BaseProvider impl, system extraction, tool translation, SSE → ModelResponseStream, error mapping | TBD (#18) | 32 unit + 2 e2e + 1 live (gated) |
```

Update the totals line below the table:

```
**Total: 125 SDK unit tests + 2 gated live tests (1 OpenAI + 1 Anthropic), 8 plan tasks complete for ola-13.**
```

In the "Core SDK — Remaining Work" section, mark item 1 as DONE and add new follow-ups:

```markdown
1. ~~**Anthropic provider** — DONE in ola-13.~~
2. **Google Gemini provider** — separate ola.
3. **Embeddings** (OpenAI + Gemini + Anthropic) — separate ola.
4. **Images, audio (STT/TTS), rerank** — separate olas.
5. **Sync `completion()` wrappers** — when needed.
6. **`tiktoken` for pre-call estimation** — when needed.
7. **Map `httpx.TimeoutException` → SDK `TimeoutError`** — one-line follow-up.
8. **Replace `model_prices.json` with upstream LiteLLM export** — when more providers land.
9. **Wire `aclose_all()` to FastAPI lifespan** — when proxy routes land.
10. **Streaming `prompt_tokens` for Anthropic** — currently 0 due to stateless provider; either add provider state or surface `message_start` usage. Out of scope until a streaming caller cares about cost.
11. **Liskov fix on `BaseProvider.get_error_class`** — addressed in PR #17 housekeeping.
```

Run live tests:

```
ANTHROPIC_API_KEY=sk-ant-... OPENAI_API_KEY=sk-... uv run pytest -m live
```

- [ ] **Step 3: No git commit needed — memory files are outside the repo.**

---

## Task Summary

| Task | Component | Tests added |
|------|-----------|-------------|
| 1 | Provider scaffold + request side (api_base, headers, transform_request with system extraction, tool translation, tool_choice translation, stop translation, max_tokens default) | 17 |
| 2 | transform_response (content blocks → Message; stop_reason mapping; usage rename) | 6 |
| 3 | transform_stream_chunk (7 SSE event types; text_delta, input_json_delta yields; rest return None) | 9 |
| 4 | get_error_class (9 status branches + fallback) | 11 |
| 5 | Provider registration (side-effect import + smoke test) | 1 |
| 6 | Price catalog (3 entries + pin tests) | 3 |
| 7 | E2E dispatcher tests (happy path + streaming) | 2 |
| 8 | Live test (`@pytest.mark.live` against Haiku 4.5) | 1 (gated) |
| 9 | Memory update | — |

**Total: 47 unit + 2 e2e + 1 live = 50 new tests. SDK total after merge: 126 (76 + 50).**

Breakdown by file:
- `tests/test_sdk/providers/test_anthropic.py`: 44 unit tests (Tasks 1-5)
- `tests/test_sdk/test_cost.py`: 3 new unit tests (Task 6)
- `tests/test_sdk/test_acompletion.py`: 2 new e2e tests (Task 7)
- `tests/test_sdk/test_anthropic_live.py`: 1 gated live test (Task 8)

Real number may shift by a few during implementation.

---

## Self-Review

**Spec coverage:**
- §Scope (chat-only, tools, streaming) — Tasks 1-4 implement the provider; Tasks 5-7 wire it up; Task 8 validates against real API
- §Public API (no changes) — verified by Task 7 (e2e tests use the same `acompletion()` signature) and Task 5 (registration is the only `__init__` change in the SDK)
- §File structure — Tasks list exact paths matching spec
- §Wire format mapping (request) — Task 1 covers system extraction, tool translation, tool_choice, stop, max_tokens default
- §Wire format mapping (response) — Task 2 covers content blocks, stop_reason, usage
- §Streaming — Task 3 covers all 7 SSE event types with explicit test per type
- §Error mapping — Task 4 covers all 9 branches
- §Catalog — Task 6 adds 3 entries with pin tests
- §Testing strategy — Tasks include all unit, e2e, and live test counts from spec
- §Risks (system kwarg dropped, empty content → None, partial JSON) — explicit tests in Tasks 1, 2, 3 cover each

**Placeholder scan:** No "TBD/TODO/implement later" patterns. The `# implemented in Task N` comments in Task 1's stub methods are explicit forward-references, not placeholders — they get replaced in their named tasks.

**Type consistency:** `_FORWARDED_PARAMS`, `DEFAULT_API_BASE`, `ANTHROPIC_VERSION`, `DEFAULT_MAX_TOKENS`, `_STOP_REASON_MAP`, `_translate_tools`, `_translate_tool_choice`, `_extract_system_messages`, `_build_stream_chunk` — all defined in the task that introduces them and used identically in subsequent tasks.

**Validation criterion:** No task touches `BaseProvider`, `main.py`, `resolver.py`, `http_client.py`, `cost.py`, `types.py`, or `exceptions.py`. If a task implementation reveals a need to change one of these, stop and re-evaluate per the spec's failure rule.
