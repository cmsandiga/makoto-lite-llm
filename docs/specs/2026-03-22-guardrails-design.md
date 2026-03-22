# Guardrails Design

**Date:** 2026-03-22
**Sub-project:** #7
**Dependencies:** Core SDK (#2)

## Overview

Extensible guardrail framework for content filtering, PII detection, and safety enforcement. Provides pre-call, during-call, and post-call hooks. Initial integrations: OpenAI Moderation, Presidio PII, custom Python guardrails.

---

## 1. Base Guardrail Interface

```python
class CustomGuardrail(ABC):
    def __init__(
        self,
        guardrail_name: str | None = None,
        event_hook: str | list[str] = "pre_call",  # "pre_call" | "during_call" | "post_call"
        default_on: bool = False,                    # Run on all requests?
        **kwargs,
    ): ...

    async def async_pre_call_hook(
        self,
        user_api_key_dict: dict,
        data: dict,                  # Request data (messages, tools, etc.)
        call_type: str,
    ) -> dict | None:
        """
        TIMING: Before LLM API call
        RETURNS: Modified data dict, or None (no modification)
        RAISES: Exception to block the request
        """
        return None

    async def async_moderation_hook(
        self,
        data: dict,
        user_api_key_dict: dict,
        call_type: str,
    ) -> None:
        """
        TIMING: In parallel with LLM API call
        RAISES: Exception to cancel the request
        CANNOT modify data.
        """
        pass

    async def async_post_call_success_hook(
        self,
        data: dict,
        user_api_key_dict: dict,
        response: ModelResponse,
    ) -> ModelResponse | None:
        """
        TIMING: After LLM returns success
        RETURNS: Modified response, or None (use original)
        RAISES: Exception to reject the response
        """
        return None

    def should_run(self, data: dict, event_type: str) -> bool:
        """
        Returns True if this guardrail should run:
        1. default_on=True AND event matches
        2. OR explicitly requested in metadata.guardrails
        """
```

---

## 2. Hook Execution Pipeline

```
Request arrives
    │
    ├─ 1. PRE-CALL hooks (sequential)
    │     Can modify input data
    │     Can block request (raise Exception)
    │
    ├─ 2. DURING-CALL hooks (parallel with LLM call)
    │     Validation only, cannot modify
    │     Can cancel request (raise Exception)
    │
    ├─ 3. LLM API Call
    │
    └─ 4. POST-CALL hooks (sequential)
          Can modify response
          Can reject response (raise Exception)
```

---

## 3. Initial Integrations

### 3.1 OpenAI Moderation

```python
class OpenAIModerationGuardrail(CustomGuardrail):
    """Calls OpenAI /moderations endpoint to check content safety."""

    def __init__(
        self,
        guardrail_name: str,
        api_key: str | None = None,
        model: str = "omni-moderation-latest",
        **kwargs,
    ): ...
```

**Categories detected:** violence, hate, harassment, self-harm, sexual content

**Config:**
```yaml
guardrails:
  - guardrail_name: "content-safety"
    litellm_params:
      guardrail: openai_moderation
      mode: pre_call
      api_key: ${OPENAI_API_KEY}
      default_on: true
```

### 3.2 Presidio PII Masking

```python
class PresidioPIIGuardrail(CustomGuardrail):
    """Detects and masks PII using Microsoft Presidio."""

    def __init__(
        self,
        guardrail_name: str,
        presidio_analyzer_api_base: str,
        presidio_anonymizer_api_base: str,
        pii_entities_config: dict | None = None,  # {"CREDIT_CARD": "BLOCK", "PERSON": "MASK"}
        output_parse_pii: bool = False,             # Also check response
        **kwargs,
    ): ...
```

**PII entities:** CREDIT_CARD, EMAIL_ADDRESS, PERSON, PHONE_NUMBER, US_SSN, etc.
**Actions:** `BLOCK` (reject request) or `MASK` (replace with placeholder)

**Config:**
```yaml
guardrails:
  - guardrail_name: "pii-filter"
    litellm_params:
      guardrail: presidio
      mode: pre_call
      presidio_analyzer_api_base: http://localhost:8002
      presidio_anonymizer_api_base: http://localhost:8001
      default_on: true
      pii_entities_config:
        CREDIT_CARD: BLOCK
        PERSON: MASK
```

### 3.3 Custom Python Guardrail

```python
# my_guardrails.py
class MyCustomGuardrail(CustomGuardrail):
    async def async_pre_call_hook(self, user_api_key_dict, data, call_type):
        messages = data.get("messages", [])
        for msg in messages:
            if "forbidden_word" in str(msg.get("content", "")):
                raise ValueError("Content policy violation")
        return data
```

**Config:**
```yaml
guardrails:
  - guardrail_name: "custom-filter"
    litellm_params:
      guardrail: my_guardrails.MyCustomGuardrail
      mode: pre_call
      default_on: false
```

---

## 4. Guardrail Registry

```python
class GuardrailRegistry:
    """Manages guardrail initialization and lifecycle."""

    guardrails: dict[str, CustomGuardrail] = {}

    def register(self, name: str, guardrail: CustomGuardrail) -> None: ...
    def initialize_from_config(self, config: list[dict]) -> None: ...
    def get(self, name: str) -> CustomGuardrail | None: ...
    def delete(self, name: str) -> None: ...
```

---

## 5. Per-Request Guardrail Selection

```python
# Request specifies which guardrails to run
response = await completion(
    model="gpt-4",
    messages=[...],
    metadata={
        "guardrails": ["pii-filter", "content-safety"]
    }
)
```

If `default_on=True`, the guardrail runs unless explicitly disabled:
```python
metadata={"disable_guardrails": ["content-safety"]}
```

---

## 6. Guardrail Logging

Each guardrail execution is logged to the observability system:

```python
class GuardrailLogInfo:
    guardrail_name: str
    guardrail_provider: str
    status: str              # "success" | "guardrail_intervened" | "guardrail_failed_to_respond"
    start_time: float
    end_time: float
    duration: float
    masked_entity_count: dict | None  # {"PERSON": 2, "EMAIL": 1}
```

---

## 7. Error Handling

- Guardrail blocks request: HTTP 400 with `detail` explaining the violation
- Guardrail fails to respond: Configurable `fail_open` (allow) or `fail_closed` (block)
- Guardrail timeout: Same as fail-to-respond

---

## 8. Non-Goals (v1)

- Policy engine with pipeline steps (v2)
- Tool permission guardrail (v2)
- 30+ third-party integrations (v2, add as needed)
- DB-stored guardrail configs (v2, initially YAML only)
- MCP security guardrails (v2)
