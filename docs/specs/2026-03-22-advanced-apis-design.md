# Advanced APIs Design

**Date:** 2026-03-22
**Sub-project:** #8
**Dependencies:** Core SDK (#2), Proxy Server (#1)

## Overview

Extends the Core SDK with additional LLM capabilities: image generation, audio (TTS/STT), fine-tuning, batch processing, files API, and realtime WebSocket. All exposed as proxy endpoints and SDK functions.

---

## 1. Image Generation

### SDK Function
Already defined in Core SDK spec (section 1.3).

### Proxy Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/images/generations` | Generate images from prompt |

### Provider Support

| Provider | Models |
|----------|--------|
| OpenAI | dall-e-2, dall-e-3 |
| Azure | dall-e-3 |
| Google Gemini | imagen-3 |

---

## 2. Audio Transcription (STT)

### SDK Function
Already defined in Core SDK spec (section 1.4).

### Proxy Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/audio/transcriptions` | Transcribe audio to text |

### Provider Support

| Provider | Models |
|----------|--------|
| OpenAI | whisper-1 |
| Azure | whisper |

### Response Formats
`json`, `text`, `srt`, `verbose_json`, `vtt`

---

## 3. Text-to-Speech (TTS)

### SDK Function
Already defined in Core SDK spec (section 1.5).

### Proxy Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/audio/speech` | Generate speech from text |

### Provider Support

| Provider | Voices |
|----------|--------|
| OpenAI | alloy, echo, fable, onyx, nova, shimmer |

### Output Formats
`mp3`, `opus`, `aac`, `flac`

---

## 4. Fine-Tuning

### SDK Functions

```python
def create_fine_tuning_job(
    model: str,
    training_file: str,              # File ID from Files API
    *,
    validation_file: str | None = None,
    hyperparameters: dict | None = None,  # {n_epochs, batch_size, learning_rate_multiplier}
    suffix: str | None = None,
    custom_llm_provider: str = "openai",
    **kwargs,
) -> FineTuningJob

def list_fine_tuning_jobs(after: str | None = None, limit: int | None = None, ...) -> list[FineTuningJob]
def retrieve_fine_tuning_job(job_id: str, ...) -> FineTuningJob
def cancel_fine_tuning_job(job_id: str, ...) -> FineTuningJob
```

Async variants: `acreate_fine_tuning_job`, `alist_fine_tuning_jobs`, etc.

### Proxy Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/fine_tuning/jobs` | Create fine-tuning job |
| GET | `/v1/fine_tuning/jobs` | List jobs |
| GET | `/v1/fine_tuning/jobs/{id}` | Retrieve job |
| POST | `/v1/fine_tuning/jobs/{id}/cancel` | Cancel job |

### Provider Support

| Provider | Notes |
|----------|-------|
| OpenAI | Full support |
| Azure | Azure-specific hyperparameters |

### FineTuningJob Response

```python
class FineTuningJob:
    id: str
    object: str                # "fine_tuning.job"
    model: str
    status: str                # "validating" | "running" | "succeeded" | "failed" | "cancelled"
    training_file: str
    validation_file: str | None
    result_files: list[str]
    trained_tokens: int | None
    created_at: int
    finished_at: int | None
    error: dict | None
```

---

## 5. Batch Processing

### SDK Functions

```python
def create_batch(
    input_file_id: str,
    endpoint: str,                    # "/v1/chat/completions" | "/v1/embeddings"
    completion_window: str = "24h",
    *,
    metadata: dict | None = None,
    custom_llm_provider: str = "openai",
    **kwargs,
) -> Batch

def retrieve_batch(batch_id: str, ...) -> Batch
def list_batches(after: str | None = None, limit: int | None = None, ...) -> list[Batch]
def cancel_batch(batch_id: str, ...) -> Batch
```

### Proxy Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/batches` | Create batch |
| GET | `/v1/batches` | List batches |
| GET | `/v1/batches/{id}` | Retrieve batch |
| POST | `/v1/batches/{id}/cancel` | Cancel batch |

### Provider Support

| Provider | Notes |
|----------|-------|
| OpenAI | Full support |
| Azure | Full support |

### Batch Response

```python
class Batch:
    id: str
    object: str                # "batch"
    endpoint: str
    input_file_id: str
    output_file_id: str | None
    error_file_id: str | None
    status: str                # "validating" | "in_progress" | "completed" | "failed" | "cancelled"
    request_counts: RequestCounts  # {total, completed, failed}
    created_at: int
    completed_at: int | None
```

---

## 6. Files API

### SDK Functions

```python
def create_file(
    file: BinaryIO,
    purpose: str,              # "fine-tune" | "batch" | "assistants"
    *,
    custom_llm_provider: str = "openai",
    **kwargs,
) -> FileObject

def retrieve_file(file_id: str, ...) -> FileObject
def delete_file(file_id: str, ...) -> FileDeleted
def list_files(...) -> list[FileObject]
def file_content(file_id: str, ...) -> bytes
```

### Proxy Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/files` | Upload file |
| GET | `/v1/files` | List files |
| GET | `/v1/files/{id}` | Retrieve file metadata |
| DELETE | `/v1/files/{id}` | Delete file |
| GET | `/v1/files/{id}/content` | Download file content |

### Provider Support

| Provider | Create | Retrieve | Delete | List | Content |
|----------|--------|----------|--------|------|---------|
| OpenAI | yes | yes | yes | yes | yes |
| Azure | yes | yes | yes | yes | yes |

### FileObject Response

```python
class FileObject:
    id: str
    object: str                # "file"
    bytes: int
    filename: str
    purpose: str
    created_at: int
    status: str                # "uploaded" | "processed" | "error"
```

---

## 7. Realtime / WebSocket

### Proxy Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/realtime/client_secrets` | Get ephemeral token for WebRTC |
| WS | `/v1/realtime` | WebSocket connection for realtime audio/text |

### Session Configuration

```python
class RealtimeSessionConfig:
    model: str | None
    instructions: str | None
    voice: str | None
    tools: list[dict] | None
    max_output_tokens: int | None
    output_modalities: list[str] | None  # ["text", "audio"]
```

### Provider Support

| Provider | Notes |
|----------|-------|
| OpenAI | gpt-4o-realtime-preview |

### WebSocket Events

**Client → Server:**
- `session.update` — update session config
- `input_audio_buffer.append` — send audio chunk
- `input_audio_buffer.commit` — finalize audio input
- `response.create` — trigger response generation

**Server → Client:**
- `session.created` / `session.updated`
- `response.created` / `response.done`
- `response.audio.delta` — audio chunk
- `response.text.delta` — text chunk
- `conversation.item.created`

---

## 8. Proxy Endpoint Summary

All endpoints follow OpenAI API compatibility:

| Category | Endpoints | Count |
|----------|-----------|-------|
| Chat | `/v1/chat/completions` | 1 |
| Embeddings | `/v1/embeddings` | 1 |
| Images | `/v1/images/generations` | 1 |
| Audio | `/v1/audio/transcriptions`, `/v1/audio/speech` | 2 |
| Fine-tuning | `/v1/fine_tuning/jobs`, `/v1/fine_tuning/jobs/{id}`, `/v1/fine_tuning/jobs/{id}/cancel` | 3 |
| Batches | `/v1/batches`, `/v1/batches/{id}`, `/v1/batches/{id}/cancel` | 3 |
| Files | `/v1/files`, `/v1/files/{id}`, `/v1/files/{id}/content` | 3 |
| Models | `/v1/models` | 1 |
| Realtime | `/v1/realtime/client_secrets`, `/v1/realtime` (WS) | 2 |
| Rerank | `/v1/rerank` | 1 |
| **Total** | | **18** |

---

## 9. Non-Goals (v1)

- Assistants API (complex state management, defer)
- Vector stores (defer)
- Image editing/variations (defer)
- Video generation (defer)
- OCR (defer)
