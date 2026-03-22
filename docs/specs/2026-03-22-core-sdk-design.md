# Core SDK Design

**Date:** 2026-03-22
**Sub-project:** #2
**Dependencies:** None

## Overview

Unified Python SDK that abstracts 100+ LLM providers behind a single OpenAI-compatible interface. Initial implementation covers 3-5 providers (OpenAI, Anthropic, Google Gemini) with an extensible architecture for adding more.

---

## 1. Public API

### 1.1 Chat Completion

```python
def completion(
    model: str,                          # "openai/gpt-4", "anthropic/claude-3", "gemini/gemini-pro"
    messages: list[dict],                # OpenAI message format
    *,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    stream: bool = False,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
    response_format: dict | None = None,
    n: int | None = None,
    stop: str | list[str] | None = None,
    user: str | None = None,
    timeout: float = 600,
    api_key: str | None = None,
    api_base: str | None = None,
    **kwargs,
) -> ModelResponse | StreamWrapper

async def acompletion(**same_params) -> ModelResponse | StreamWrapper
```

### 1.2 Embeddings

```python
def embedding(
    model: str,
    input: str | list[str],
    *,
    dimensions: int | None = None,
    encoding_format: str | None = None,  # "float" | "base64"
    timeout: float = 600,
    api_key: str | None = None,
    **kwargs,
) -> EmbeddingResponse

async def aembedding(**same_params) -> EmbeddingResponse
```

### 1.3 Image Generation

```python
def image_generation(
    prompt: str,
    model: str | None = None,
    *,
    n: int | None = None,
    size: str | None = None,           # "1024x1024"
    quality: str | None = None,        # "standard" | "hd"
    style: str | None = None,          # "vivid" | "natural"
    response_format: str | None = None, # "url" | "b64_json"
    timeout: float = 600,
    **kwargs,
) -> ImageResponse

async def aimage_generation(**same_params) -> ImageResponse
```

### 1.4 Audio Transcription

```python
def transcription(
    model: str,
    file: BinaryIO,
    *,
    language: str | None = None,
    response_format: str | None = None,  # "json" | "text" | "srt" | "vtt"
    temperature: float | None = None,
    timeout: float = 600,
    **kwargs,
) -> TranscriptionResponse

async def atranscription(**same_params) -> TranscriptionResponse
```

### 1.5 Text-to-Speech

```python
def speech(
    model: str,
    input: str,
    voice: str | None = None,
    *,
    speed: float | None = None,
    response_format: str | None = None,  # "mp3" | "opus" | "aac" | "flac"
    timeout: float = 600,
    **kwargs,
) -> bytes

async def aspeech(**same_params) -> bytes
```

### 1.6 Reranking

```python
def rerank(
    model: str,
    query: str,
    documents: list[str | dict],
    *,
    top_n: int | None = None,
    return_documents: bool = True,
    **kwargs,
) -> RerankResponse

async def arerank(**same_params) -> RerankResponse
```

---

## 2. Unified Response Types

### ModelResponse (Chat Completion)

```python
class ModelResponse:
    id: str                    # "chatcmpl-{uuid}"
    object: str                # "chat.completion"
    created: int               # Unix timestamp
    model: str
    choices: list[Choice]
    usage: Usage | None

class Choice:
    index: int
    message: Message
    finish_reason: str | None  # "stop" | "length" | "tool_calls"

class Message:
    role: str                  # "assistant"
    content: str | None
    tool_calls: list[ToolCall] | None

class ToolCall:
    id: str
    type: str                  # "function"
    function: FunctionCall     # {name: str, arguments: str}

class Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float | None         # Calculated cost in USD
```

### StreamWrapper

```python
class StreamWrapper:
    def __iter__(self) -> Iterator[ModelResponseStream]: ...
    async def __aiter__(self) -> AsyncIterator[ModelResponseStream]: ...

class ModelResponseStream:
    id: str
    choices: list[StreamChoice]
    usage: Usage | None        # Only in final chunk

class StreamChoice:
    index: int
    delta: Delta               # Partial content/tool_calls
    finish_reason: str | None
```

### EmbeddingResponse

```python
class EmbeddingResponse:
    object: str                # "list"
    data: list[EmbeddingData]  # [{index, embedding: list[float]}]
    model: str
    usage: Usage
```

### ImageResponse

```python
class ImageResponse:
    created: int
    data: list[ImageData]      # [{url?, b64_json?, revised_prompt?}]
```

### TranscriptionResponse

```python
class TranscriptionResponse:
    text: str
    language: str | None
    duration: float | None
```

### RerankResponse

```python
class RerankResponse:
    results: list[RerankResult]  # [{index, relevance_score, document?}]
```

---

## 3. Provider Architecture

### 3.1 Base Provider Interface

```python
class BaseProvider(ABC):
    """All providers implement this interface."""

    @abstractmethod
    def get_supported_params(self, model: str) -> list[str]:
        """Return list of supported OpenAI params for this model."""

    @abstractmethod
    def map_params(self, model: str, params: dict) -> dict:
        """Transform OpenAI params to provider-native format."""

    @abstractmethod
    def transform_request(self, model: str, messages: list, params: dict) -> dict:
        """Build provider-native request body."""

    @abstractmethod
    def transform_response(self, raw_response: dict, model: str, stream: bool) -> ModelResponse:
        """Transform provider response to unified ModelResponse."""

    @abstractmethod
    def get_api_base(self, model: str, api_base: str | None) -> str:
        """Return the API base URL."""

    @abstractmethod
    def get_headers(self, api_key: str, **kwargs) -> dict:
        """Return request headers including auth."""

    def transform_stream_chunk(self, chunk: dict) -> ModelResponseStream:
        """Transform a single streaming chunk."""

    def get_error_class(self, status_code: int, response: dict) -> Exception:
        """Map provider error to standard exception."""
```

### 3.2 Provider Registration

```python
PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {}

def register_provider(name: str, provider_class: type[BaseProvider]):
    PROVIDER_REGISTRY[name] = provider_class
```

### 3.3 Provider Resolution

Model format: `"provider/model-name"` (e.g., `"openai/gpt-4"`, `"anthropic/claude-3-opus"`)

```python
def resolve_provider(model: str) -> tuple[str, str, BaseProvider]:
    """Returns (provider_name, model_name, provider_instance)"""
    # 1. Split on "/" → provider_name, model_name
    # 2. Lookup in PROVIDER_REGISTRY
    # 3. Fallback: check model_name prefixes for known providers
    # 4. Raise UnknownProviderError if not found
```

### 3.4 Initial Providers

| Provider | Chat | Embeddings | Images | Audio | Rerank | Streaming | Tools |
|----------|------|-----------|--------|-------|--------|-----------|-------|
| OpenAI | yes | yes | yes | yes | no | yes | yes |
| Anthropic | yes | no | no | no | no | yes | yes |
| Google Gemini | yes | yes | yes | no | no | yes | yes |

### 3.5 Provider-Specific Notes

**OpenAI:**
- Direct pass-through for most params (native format)
- Supports all response types
- Tool calling with `tool_choice` control

**Anthropic:**
- Messages format transformation (system message → top-level `system` param)
- Tool calling uses different schema (`input_schema` vs `parameters`)
- Vision: base64 images in content blocks
- Cache control headers for prompt caching

**Google Gemini:**
- Messages → `contents` with `parts` transformation
- `tool_config` instead of `tool_choice`
- Image size params: "1024x1024" → "1:1" aspect ratio

---

## 4. HTTP Client

### Async HTTP Client (httpx)

```python
class LLMHttpClient:
    """Manages async httpx clients with connection pooling."""

    async def post(self, url: str, headers: dict, json: dict, timeout: float) -> dict
    async def post_stream(self, url: str, headers: dict, json: dict, timeout: float) -> AsyncIterator[bytes]

    # Client caching: one client per (api_base, api_key) tuple
    # Never close clients on cache eviction (in-flight requests may use them)
    # Cleanup only at shutdown
```

---

## 5. Cost Calculation

```python
class CostCalculator:
    """Calculate per-request cost based on token usage."""

    model_costs: dict  # Loaded from model_prices.json

    def calculate(self, model: str, usage: Usage) -> float:
        """
        cost = (prompt_tokens * input_cost_per_token)
             + (completion_tokens * output_cost_per_token)
        """

    def get_model_info(self, model: str) -> ModelInfo:
        """Return model metadata: max_tokens, costs, capabilities."""
```

### ModelInfo

```python
class ModelInfo:
    max_input_tokens: int | None
    max_output_tokens: int | None
    input_cost_per_token: float
    output_cost_per_token: float
    supports_tools: bool
    supports_vision: bool
    supports_streaming: bool
    mode: str  # "chat" | "embedding" | "image_generation" | etc.
```

---

## 6. Token Counting

```python
def token_counter(model: str, messages: list | None = None, text: str | None = None) -> int:
    """
    Strategy:
    1. Provider-specific tokenizer (tiktoken for OpenAI, etc.)
    2. Fallback: ~4 chars per token estimation
    """
```

---

## 7. Exception Hierarchy

```python
class LiteLLMError(Exception):
    status_code: int
    message: str

class AuthenticationError(LiteLLMError): ...     # 401
class RateLimitError(LiteLLMError): ...           # 429
class BadRequestError(LiteLLMError): ...          # 400
class NotFoundError(LiteLLMError): ...            # 404
class ContentPolicyViolationError(LiteLLMError): ... # 400
class ContextWindowExceededError(LiteLLMError): ...  # 400
class InternalServerError(LiteLLMError): ...      # 500
class TimeoutError(LiteLLMError): ...             # 408
class ServiceUnavailableError(LiteLLMError): ...  # 503
class UnknownProviderError(LiteLLMError): ...     # 400
```

All provider-specific errors are mapped to these standard exceptions.

---

## 8. Global Configuration

```python
# Drop unsupported params silently instead of raising
drop_params: bool = False

# Default timeout for all requests
request_timeout: float = 600

# Number of retries on transient errors
num_retries: int = 0

# Global callbacks for logging/observability
success_callback: list[Callable] = []
failure_callback: list[Callable] = []

# Caching (set by cache layer sub-project)
cache: Cache | None = None
```

---

## 9. Parameter Handling

```python
def get_supported_params(model: str, provider: str) -> list[str]:
    """Return which OpenAI params this model supports."""

def filter_params(params: dict, supported: list[str], drop_params: bool) -> dict:
    """
    If drop_params=True: silently remove unsupported params
    If drop_params=False: raise UnsupportedParamsError
    """
```

---

## 10. Non-Goals

- Provider-specific params beyond OpenAI compat (handled via `**kwargs` pass-through)
- Assistants API (deferred)
- Vector stores (deferred)
- Fine-tuning management (sub-project #8)
- Batch processing (sub-project #8)
- Files API (sub-project #8)
- Realtime/WebSocket (sub-project #8)
