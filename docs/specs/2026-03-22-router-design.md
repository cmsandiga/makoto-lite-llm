# Router Design

**Date:** 2026-03-22
**Sub-project:** #3
**Dependencies:** Core SDK (#2)

## Overview

Load balancing and failover system that distributes LLM requests across multiple provider deployments. Supports multiple routing strategies, automatic fallbacks, circuit breaking, and health tracking.

---

## 1. Router API

```python
class Router:
    def __init__(
        self,
        model_list: list[Deployment],
        *,
        # Strategy
        routing_strategy: str = "round-robin",  # "round-robin" | "lowest-latency" | "lowest-cost" | "simple-shuffle"
        # Reliability
        num_retries: int = 2,
        max_fallbacks: int = 5,
        timeout: float | None = None,
        stream_timeout: float | None = None,
        retry_policy: RetryPolicy | None = None,
        # Fallbacks
        fallbacks: list[dict] | None = None,           # [{"gpt-4": ["gpt-3.5-turbo"]}]
        context_window_fallbacks: list[dict] | None = None,
        # Cooldown
        allowed_fails: int = 3,
        cooldown_time: float = 60.0,
        # Aliasing
        model_group_alias: dict[str, str | dict] | None = None,
        # Cache
        cache: DualCache | None = None,
    ):
```

### Main Methods

```python
async def acompletion(self, model: str, messages: list, **kwargs) -> ModelResponse
async def aembedding(self, model: str, input: list, **kwargs) -> EmbeddingResponse
async def aimage_generation(self, prompt: str, model: str, **kwargs) -> ImageResponse
```

---

## 2. Deployment Configuration

```python
class Deployment:
    model_name: str              # User-facing name: "gpt-4"
    litellm_params: LiteLLMParams
    model_info: ModelInfo | None

class LiteLLMParams:
    model: str                   # Provider model: "openai/gpt-4"
    api_key: str | None
    api_base: str | None
    timeout: float | None
    max_retries: int | None
    tpm: int | None              # Tokens per minute limit
    rpm: int | None              # Requests per minute limit
    weight: int | None           # For weighted routing
    tags: list[str] | None       # For tag-based filtering
```

### YAML Config Format

```yaml
model_list:
  - model_name: gpt-4
    litellm_params:
      model: openai/gpt-4
      api_key: sk-xxx
      tpm: 100000
      rpm: 500
  - model_name: gpt-4
    litellm_params:
      model: azure/gpt-4-deployment
      api_key: azure-xxx
      api_base: https://my-instance.openai.azure.com
      tpm: 80000

router_settings:
  routing_strategy: lowest-latency
  num_retries: 2
  cooldown_time: 60
  fallbacks:
    - gpt-4: [gpt-3.5-turbo]
```

---

## 3. Routing Strategies

### 3.1 Round Robin (Default: `"round-robin"`)
- Cycles through deployments sequentially
- Supports `weight` for weighted distribution
- Simplest strategy, good for evenly-spec'd deployments

### 3.2 Simple Shuffle (`"simple-shuffle"`)
- Random selection from healthy deployments
- Weighted if `weight`, `rpm`, or `tpm` set on deployments
- Uses `random.choices()` with normalized probabilities

### 3.3 Lowest Latency (`"lowest-latency"`)
- Tracks last N response times per deployment (default N=10)
- Selects deployment with lowest average latency
- Configurable buffer: allows selection within `lowest_latency_buffer` of best
- Tracks time-to-first-token for streaming requests

### 3.4 Lowest Cost (`"lowest-cost"`)
- Selects deployment with lowest `input_cost_per_token + output_cost_per_token`
- Uses model pricing data from CostCalculator
- Tie-breaking: lowest current TPM usage

---

## 4. Fallback & Retry Logic

### Fallback Configuration

```python
fallbacks = [
    {"gpt-4": ["gpt-3.5-turbo", "claude-3-haiku"]},  # Specific
    {"*": ["gpt-4"]},                                   # Generic wildcard
]

context_window_fallbacks = [
    {"gpt-3.5-turbo": ["gpt-4"]},  # When context exceeded
]
```

### Retry Policy

```python
class RetryPolicy:
    BadRequestErrorRetries: int | None = None
    AuthenticationErrorRetries: int | None = None
    TimeoutErrorRetries: int | None = None
    RateLimitErrorRetries: int | None = None
    InternalServerErrorRetries: int | None = None
```

### Execution Flow

```
1. Select deployment via routing strategy
2. Send request
3. On failure:
   a. Check retry policy for this error type
   b. If retries remain: select next deployment, retry
   c. If retries exhausted: check fallback models
   d. If fallback available: route to fallback model group
   e. If all exhausted: raise final error
```

---

## 5. Cooldown & Circuit Breaking

### Cooldown Logic

When a deployment fails:
1. Increment `failure_count` for deployment
2. If `failure_count >= allowed_fails` within 1 minute:
   - Mark deployment as "cooled down" for `cooldown_time` seconds
   - Cooled-down deployments excluded from routing
3. After `cooldown_time`: deployment re-enters healthy pool

### Triggers

Cooldown triggered on: 429 (rate limit), 401 (auth), 408 (timeout), 5xx (server errors)
Cooldown skipped on: 400 (bad request — user error, not provider issue)

### Storage

```python
class CooldownCache:
    # Key: "cooldown:{deployment_id}" → CooldownValue
    # TTL: cooldown_time (auto-expires)

class CooldownValue:
    exception_received: str
    status_code: int
    timestamp: float
    cooldown_time: float
```

---

## 6. Model Aliasing

```python
model_group_alias = {
    "gpt-4": "gpt-3.5-turbo",           # Simple redirect
    "internal-model": {                   # Advanced
        "model": "gpt-4",
        "hidden": True,                   # Excluded from model list API
    },
}
```

---

## 7. Health Tracking

### Deployment Stats

Per deployment, the router tracks:
- **Latency**: Last N response times
- **TPM/RPM**: Current tokens/requests per minute
- **Failure count**: Recent failures within window
- **Cooldown state**: Whether deployment is paused

### Model Group Info

```python
class ModelGroupInfo:
    model_group: str
    providers: list[str]
    max_input_tokens: int | None
    max_output_tokens: int | None
    input_cost_per_token: float | None
    output_cost_per_token: float | None
    supports_tools: bool
    supports_vision: bool
    supports_streaming: bool
```

---

## 8. Integration with Proxy

The proxy server creates a Router instance from YAML config and uses it for all LLM requests:

```python
# In proxy startup
router = Router(model_list=config["model_list"], **config["router_settings"])

# In request handler
response = await router.acompletion(model=request.model, messages=request.messages)
```

---

## 9. Non-Goals (v1)

- Tag-based routing (v2)
- Complexity-based routing (v2)
- ML/auto routing (v2)
- Provider budget limiting (handled by Spend sub-project)
- Deployment affinity (v2)
