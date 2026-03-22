# Cache Layer Design

**Date:** 2026-03-22
**Sub-project:** #4
**Dependencies:** Core SDK (#2)

## Overview

Multi-backend caching system for LLM API responses. Supports 9 cache backends with a unified interface, TTL management, semantic caching, and dual-cache (in-memory + Redis) for optimal performance.

---

## 1. Base Cache Interface

```python
class BaseCache(ABC):
    def __init__(self, default_ttl: int = 60): ...

    @abstractmethod
    async def async_set_cache(self, key: str, value: Any, ttl: int | None = None) -> None: ...

    @abstractmethod
    async def async_get_cache(self, key: str) -> Any | None: ...

    @abstractmethod
    async def async_set_cache_pipeline(self, cache_list: list[tuple[str, Any]], ttl: int | None = None) -> None: ...

    async def async_batch_get_cache(self, keys: list[str]) -> list[Any | None]: ...
    async def async_increment(self, key: str, value: float, ttl: int | None = None) -> float: ...
    async def async_delete(self, key: str) -> None: ...
    async def disconnect(self) -> None: ...
```

---

## 2. Cache Backends

### 2.1 In-Memory Cache (`"local"`)
- **Data structure:** dict + TTL dict + min-heap for eviction
- **Max items:** 200 (configurable)
- **Max per item:** 1MB
- **Eviction:** Heap-based, removes earliest-expiring items
- **Thread safety:** Timestamp-based TTL (no locks)

### 2.2 Redis Cache (`"redis"`)
- **Connection:** redis-py async client with connection pooling
- **Circuit breaker:** Fails fast after 5 consecutive failures, recovers after 60s
- **Namespace:** Optional prefix for multi-tenant isolation (`"namespace:key"`)
- **Pipeline:** Batch writes via Redis pipelines (configurable flush size)

### 2.3 Redis Cluster Cache (`"redis-cluster"`)
- Extends Redis cache for cluster deployments
- Uses `mget_nonatomic()` for cross-slot compatibility

### 2.4 Disk Cache (`"disk"`)
- Wrapper around `diskcache` library
- Persistent local storage at configurable path
- Good for development/single-node deployments

### 2.5 S3 Cache (`"s3"`)
- AWS S3 bucket storage
- Key format: `"namespace/key"` (path-based)
- TTL via `CacheControl: max-age={ttl}` and `Expires` metadata
- Uses boto3 (sync via run_in_executor for async)

### 2.6 GCS Cache (`"gcs"`)
- Google Cloud Storage
- Direct HTTP API via httpx (no SDK dependency)
- Service account auth via signed headers

### 2.7 Azure Blob Cache (`"azure-blob"`)
- Azure Blob Storage
- Auto-creates container if missing
- DefaultAzureCredential for auth

### 2.8 Redis Semantic Cache (`"redis-semantic"`)
- Vector similarity using embeddings
- Requires: `similarity_threshold` (0.0-1.0)
- Uses `redisvl` library for vector search
- Calls embedding API to vectorize prompts
- Returns cached response if similarity > threshold

### 2.9 Qdrant Semantic Cache (`"qdrant-semantic"`)
- Vector similarity using Qdrant
- Configurable quantization: binary, scalar, product
- Auto-creates collection if missing
- Direct HTTP API calls

---

## 3. Dual Cache

Combines in-memory + Redis for optimal read performance:

```python
class DualCache:
    def __init__(self, in_memory: InMemoryCache, redis: RedisCache | None):

    async def async_get_cache(self, key: str, local_only: bool = False) -> Any | None:
        # 1. Check in-memory (fast path)
        # 2. On miss: check Redis
        # 3. On Redis hit: populate in-memory
        # 4. Throttle Redis batch reads (configurable interval)

    async def async_set_cache(self, key: str, value: Any, local_only: bool = False) -> None:
        # Write to both in-memory AND Redis
```

---

## 4. Cache Key Generation

```python
def generate_cache_key(**kwargs) -> str:
    """
    1. Collect all LLM params: model, messages, temperature, etc.
    2. Skip None values
    3. Concatenate: "{param}: {value}" pairs
    4. SHA-256 hash
    5. Prepend namespace if set
    """
```

**Model key resolution (for cross-model caching):**
1. `caching_group` (if model in a caching group)
2. `model_group` (router model group name)
3. `model` (direct model name)

---

## 5. Cache Control (Per-Request)

```python
class CacheControl:
    ttl: int | None = None           # Override default TTL
    namespace: str | None = None     # Override default namespace
    s_maxage: int | None = None      # Max age before stale
    no_cache: bool = False           # Skip cache lookup
    no_store: bool = False           # Don't store response
    use_cache: bool = False          # Opt-in (when mode=default_off)
```

Usage in request:
```python
response = await completion(
    model="gpt-4",
    messages=[...],
    cache={"ttl": 3600, "no-cache": False},
)
```

---

## 6. Cache Mode

```python
class CacheMode(str, Enum):
    default_on = "default_on"    # Cache all (opt-out with no-store)
    default_off = "default_off"  # Cache nothing (opt-in with use-cache)
```

---

## 7. Caching Handler Integration

```python
class CachingHandler:
    """Hooks into completion/embedding calls for transparent caching."""

    async def get_cache(self, model: str, call_type: str, **kwargs) -> CachedResult | None:
        # Generate key, check cache, validate max-age

    async def set_cache(self, result: ModelResponse, **kwargs) -> None:
        # Store result with timestamp for max-age validation
```

**Embedding partial hits:**
- For batch embeddings, some inputs may hit cache
- Handler returns partial response + list of missing inputs
- Main function only calls API for misses
- Final response merges cached + fresh results

---

## 8. Stored Data Format

```python
cached_data = {
    "timestamp": time.time(),     # For max-age validation
    "response": serialized_result  # JSON-serialized ModelResponse
}
```

---

## 9. Supported Call Types

| Type | Cached |
|------|--------|
| completion / acompletion | yes |
| embedding / aembedding | yes (with partial hits) |
| transcription / atranscription | yes |
| rerank / arerank | yes |
| image_generation | no (too large, non-deterministic) |
| speech | no (binary, non-deterministic) |

---

## 10. Error Handling

- Cache operations **never raise** to the caller
- All exceptions logged but swallowed
- If cache fails, request proceeds without caching
- Redis circuit breaker prevents cascading failures

---

## 11. Configuration

```python
# Enable globally
cache = Cache(type="redis", host="localhost", port=6379, ttl=3600)

# Enable per-request
response = await completion(..., cache={"ttl": 86400, "namespace": "v2"})
```
