# Observability Design

**Date:** 2026-03-22
**Sub-project:** #6
**Dependencies:** Core SDK (#2)

## Overview

Pluggable callback system for logging, monitoring, and alerting. Provides a standard logging payload that all integrations consume. Initial integrations: OpenTelemetry, Prometheus, Langfuse, Datadog, Slack.

---

## 1. Callback Interface

```python
class CustomLogger(ABC):
    """Base class for all observability integrations."""

    def __init__(self, turn_off_message_logging: bool = False): ...

    # Pre-request
    async def async_log_pre_api_call(self, model: str, messages: list, kwargs: dict) -> None: ...

    # Success
    async def async_log_success_event(
        self, kwargs: dict, response_obj: Any, start_time: datetime, end_time: datetime
    ) -> None: ...

    # Failure
    async def async_log_failure_event(
        self, kwargs: dict, response_obj: Any, start_time: datetime, end_time: datetime
    ) -> None: ...

    # Audit (admin actions)
    async def async_log_audit_event(self, audit_log: AuditLogPayload) -> None: ...

    # Pre-request modification hook
    async def async_pre_request_hook(
        self, model: str, messages: list, kwargs: dict
    ) -> dict | None: ...
```

---

## 2. Standard Logging Payload

Every callback receives this standardized payload in `kwargs["standard_logging_object"]`:

```python
class StandardLoggingPayload:
    # Identity
    id: str                              # Request ID
    trace_id: str                        # Trace ID for multi-call tracking

    # Request info
    call_type: str                       # "completion" | "embedding" | etc.
    model: str
    custom_llm_provider: str | None
    api_base: str
    stream: bool | None

    # Cost & tokens
    response_cost: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    # Timing
    start_time: float                    # Unix timestamp
    end_time: float
    response_time: float                 # Seconds

    # Status
    status: str                          # "success" | "failure"
    error_str: str | None
    error_information: ErrorInfo | None

    # Cache
    cache_hit: bool | None
    cache_key: str | None
    saved_cache_cost: float

    # Messages (can be redacted)
    messages: str | list | dict | None
    response: str | list | dict | None

    # Model parameters
    model_parameters: dict

    # Metadata
    metadata: StandardLoggingMetadata

class StandardLoggingMetadata:
    user_api_key_hash: str | None
    user_api_key_alias: str | None
    user_api_key_team_id: str | None
    user_api_key_org_id: str | None
    user_api_key_user_id: str | None
    end_user: str | None
    request_tags: list[str]
    requester_ip_address: str | None

class ErrorInfo:
    error_code: str | None
    error_class: str | None
    error_message: str | None
    llm_provider: str | None
    traceback: str | None
```

---

## 3. Callback Registration

```python
# Global registration
success_callbacks: list[str | CustomLogger] = []
failure_callbacks: list[str | CustomLogger] = []

# Register by name (resolved to class internally)
success_callbacks = ["langfuse", "prometheus", "otel"]

# Register by instance
success_callbacks = [LangfuseLogger(public_key="...", secret="...")]
```

### Callback Invocation

```python
# After successful LLM call
for callback in success_callbacks:
    try:
        await callback.async_log_success_event(kwargs, response, start_time, end_time)
    except Exception:
        logger.exception("Callback error")  # Never block the response
```

---

## 4. Initial Integrations

### 4.1 OpenTelemetry (`"otel"`)

```python
class OpenTelemetryLogger(CustomLogger):
    """Exports traces and metrics via OTLP protocol."""

    def __init__(
        self,
        exporter: str = "otlp_http",     # "console" | "otlp_http" | "otlp_grpc"
        endpoint: str | None = None,
        headers: str | None = None,
        service_name: str = "makoto-litellm",
    ): ...
```

**Creates spans:**
- `litellm_request` — top-level span per request
- Attributes: model, provider, tokens, cost, latency, status

**Metrics:**
- `litellm.request.duration` (histogram)
- `litellm.request.tokens` (counter)
- `litellm.request.cost` (counter)

### 4.2 Prometheus (`"prometheus"`)

```python
class PrometheusLogger(CustomLogger):
    """Exports metrics for Prometheus scraping."""
```

**Metrics:**
- `litellm_requests_total` (Counter) — labels: model, provider, status
- `litellm_request_duration_seconds` (Histogram) — labels: model, provider
- `litellm_tokens_total` (Counter) — labels: model, direction (input/output)
- `litellm_spend_total` (Counter) — labels: model, team_id, user_id
- `litellm_request_errors_total` (Counter) — labels: model, error_class

### 4.3 Langfuse (`"langfuse"`)

```python
class LangfuseLogger(CustomLogger):
    """Sends traces to Langfuse for LLM observability."""

    def __init__(
        self,
        public_key: str | None = None,
        secret_key: str | None = None,
        host: str | None = None,
        flush_interval: int = 1,
    ): ...
```

**Data sent:**
- Trace per request (with trace_id for multi-call tracking)
- Generation per LLM call (prompt, completion, tokens, cost, latency)
- Metadata, tags, user info

### 4.4 Datadog (`"datadog"`)

```python
class DatadogLogger(CustomLogger):
    """Batch-sends logs to Datadog."""

    def __init__(
        self,
        api_key: str | None = None,       # DD_API_KEY
        site: str | None = None,           # DD_SITE
        batch_size: int = 100,
        flush_interval: int = 5,           # seconds
    ): ...
```

**Payload:** JSON logs with `ddsource`, `ddtags`, `hostname`, `message`, `status`

### 4.5 Slack Alerting (`"slack"`)

```python
class SlackAlerting(CustomLogger):
    """Sends alerts to Slack webhooks."""

    def __init__(
        self,
        webhook_url: str | None = None,
        alerting_threshold: float = 300,   # seconds (latency alert)
        alert_types: list[str] = [],       # "latency" | "failures" | "budget" | "outage"
    ): ...
```

**Alert types:**
- `latency_alerts` — response time > threshold
- `failed_request_alerts` — API call failures
- `budget_alerts` — entity budget exceeded/approaching
- `outage_alerts` — provider outage detected (multiple failures)

---

## 5. Message Logging Control

```python
# Global: redact all messages from logging
turn_off_message_logging = True

# Per-callback instance
PrometheusLogger(turn_off_message_logging=True)

# Per-request
completion(..., metadata={"turn_off_message_logging": True})
```

---

## 6. Batch Logger Pattern

For high-throughput integrations (Datadog, Slack):

```python
class BatchLogger(CustomLogger):
    log_queue: list = []
    batch_size: int = 100
    flush_interval: int = 5  # seconds

    async def async_log_success_event(self, ...):
        self.log_queue.append(payload)
        if len(self.log_queue) >= self.batch_size:
            await self.flush()

    async def flush(self):
        batch, self.log_queue = self.log_queue[:], []
        await self.send_batch(batch)
```

---

## 7. Dynamic Callback Params

Per-key/team callback credentials (set via API key metadata):

```python
class DynamicCallbackParams:
    langfuse_public_key: str | None
    langfuse_secret_key: str | None
    langfuse_host: str | None
    datadog_api_key: str | None
    turn_off_message_logging: bool | None
```

Accessed via `kwargs.get("standard_callback_dynamic_params")`.

---

## 8. Non-Goals (v1)

- LangSmith, Arize, MLflow, Weights & Biases (v2)
- Custom webhook integration (v2)
- Log streaming via WebSocket (v2)
- Cost alerts via email/PagerDuty (v2)
