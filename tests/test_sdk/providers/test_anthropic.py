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
