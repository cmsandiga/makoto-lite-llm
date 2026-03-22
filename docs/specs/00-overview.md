# Makoto LiteLLM — Project Overview

**Date:** 2026-03-22
**Goal:** Recreate LiteLLM from scratch as a unified LLM proxy gateway with full auth, routing, caching, observability, and multi-provider support.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Dashboard UI (Next.js)                 │
├─────────────────────────────────────────────────────────┤
│                  Proxy Server (FastAPI)                   │
│  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌──────────────┐ │
│  │   Auth    │ │ Guardrails│ │ Routes │ │ Observability│ │
│  │ Middleware│ │  Pipeline │ │        │ │  Callbacks   │ │
│  └────┬─────┘ └────┬─────┘ └───┬────┘ └──────┬───────┘ │
│       └─────────────┴───────────┴──────────────┘         │
│  ┌──────────────────────────────────────────────────┐   │
│  │              Router (Load Balancing)               │   │
│  │  round-robin | lowest-latency | lowest-cost |     │   │
│  │  fallback | retry | cooldown | circuit-breaker    │   │
│  └──────────────────────┬───────────────────────────┘   │
│  ┌──────────────────────┴───────────────────────────┐   │
│  │              Cache Layer (9 backends)              │   │
│  │  in-memory | redis | s3 | gcs | azure-blob |     │   │
│  │  disk | redis-cluster | semantic-redis | qdrant   │   │
│  └──────────────────────┬───────────────────────────┘   │
│  ┌──────────────────────┴───────────────────────────┐   │
│  │              Core SDK (Provider Abstraction)       │   │
│  │  OpenAI | Anthropic | Google Gemini | extensible  │   │
│  │  chat | embeddings | images | audio | rerank |    │   │
│  │  fine-tuning | batches | files | realtime         │   │
│  └──────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────┤
│  PostgreSQL (SQLAlchemy)  │  Redis (rate limits/cache)   │
└─────────────────────────────────────────────────────────┘
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| Web Framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Database | PostgreSQL 15+ |
| Cache/Rate Limiting | Redis |
| HTTP Client | httpx (async) |
| Auth | PyJWT, bcrypt, cryptography (AES-256) |
| Frontend | Next.js |
| Testing | pytest, pytest-asyncio |
| Linting | Ruff, MyPy, Black |

## Sub-Projects (Implementation Order)

| # | Sub-Project | Spec | Plan | Status |
|---|-------------|------|------|--------|
| 1 | Auth System | [spec](2026-03-22-auth-system-design.md) | [plan](../plans/2026-03-22-auth-system-plan.md) | Ready |
| 2 | Core SDK | [spec](2026-03-22-core-sdk-design.md) | pending | - |
| 3 | Router | [spec](2026-03-22-router-design.md) | pending | - |
| 4 | Cache Layer | [spec](2026-03-22-cache-design.md) | pending | - |
| 5 | Spend & Budgets | [spec](2026-03-22-spend-budgets-design.md) | pending | - |
| 6 | Observability | [spec](2026-03-22-observability-design.md) | pending | - |
| 7 | Guardrails | [spec](2026-03-22-guardrails-design.md) | pending | - |
| 8 | Advanced APIs | [spec](2026-03-22-advanced-apis-design.md) | pending | - |
| 9 | Dashboard UI | [spec](2026-03-22-dashboard-design.md) | pending | - |

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| ORM | SQLAlchemy (not Prisma) | Native Python, async, mature ecosystem |
| Initial providers | OpenAI, Anthropic, Google (3-5) | Cover 90% of use cases, extensible pattern |
| HTTP methods | POST for all mutations | Proxy/firewall compatibility |
| Auth | API keys + JWT + OAuth2 + password | Full enterprise support |
| Rate limiting | Redis sliding window | Distributed, fast, proven pattern |
| Cache types | All portable (Uuid, JSON) | Cross-DB compatibility (PostgreSQL + SQLite tests) |
| Routing | 4 strategies initially | Round robin, lowest latency, lowest cost, fallback |
| Observability | 5-8 integrations | OTel, Prometheus, Langfuse, Datadog, Slack |
| Guardrails | Framework + 3 initial | OpenAI moderation, Presidio PII, custom |

## Dependencies Between Sub-Projects

```
1. Auth System ─────────────────────┐
                                     │
2. Core SDK ────────┐                │
                     ├─ 5. Spend ────┤
3. Router ──────────┘                │
                                     ├─ 9. Dashboard UI
4. Cache Layer ─────────────────────┤
                                     │
6. Observability ───────────────────┤
                                     │
7. Guardrails ──────────────────────┤
                                     │
8. Advanced APIs ───────────────────┘
```

- **Auth** is standalone — no dependencies
- **Core SDK** is standalone — no dependencies
- **Router** depends on Core SDK (routes requests to providers)
- **Cache** depends on Core SDK (caches provider responses)
- **Spend & Budgets** depends on Auth (entities) + Core SDK (cost calculation) + Router (per-request tracking)
- **Observability** depends on Core SDK (callback interface)
- **Guardrails** depends on Core SDK (hook into request pipeline)
- **Advanced APIs** depends on Core SDK (extends provider interface)
- **Dashboard** depends on Auth (login/management) + all others (visualizes everything)

## Complete Capability Catalog

Everything LiteLLM does, organized by domain. Each item needs a spec before implementation. Items marked with the sub-project number are already spec'd. Unmarked items need specs added later.

### Proxy Core

| Capability | Description | Spec'd | Providers (implement 2-3) |
|---|---|---|---|
| Config system (YAML) | Load YAML config, env var interpolation (`os.environ/`), DB config storage, runtime overrides | no | - |
| Health checks | `/health` — check DB, Redis, provider connectivity | no | - |
| Model list | `/v1/models` — aggregate available models from all configured providers | no | - |
| Pass-through endpoints | Forward native provider API calls without transformation (`/anthropic/v1/messages`, `/vertex-ai/...`, etc.) | no | Anthropic, Vertex AI, Cohere |
| Setup wizard / CLI | Interactive onboarding to configure providers, validate API keys | no | - |
| Scheduled tasks (cron) | Budget resets, key rotation checks, health check polling, stale token cleanup | no | - |

### Auth & Access Control (#1 — spec'd)

| Capability | Description | Spec'd |
|---|---|---|
| API key auth | `sk-*` keys, SHA-256 hash, rotation with grace period, cache | yes |
| JWT auth | Access/refresh tokens, RS256/HS256 | yes |
| OAuth2 / SSO | Google, Azure AD, Okta, generic OIDC | yes |
| Password auth | bcrypt, brute force lockout | yes |
| RBAC | 4 roles, permission matrix, route-level checks | yes |
| Org/Team/Project hierarchy | Multi-tenant entity management with cascade deletion | yes |
| API key CRUD | 10 endpoints: generate, rotate, block, bulk update, etc. | yes |
| User/Team/Org CRUD | ~25 management endpoints | yes |
| Budget management | Reusable budgets, entity linking | yes |
| Audit logging | Action tracking, deletion history | yes |
| Object permissions | Fine-grained allow/deny per resource — **endpoints missing** | partial |
| Access groups | Group resources, assign to teams/keys — **endpoints missing** | partial |
| IP whitelist/blacklist | Per-org or global IP filtering | no |
| Invitation links | Invite users via email/link | no |
| SCIM v2 | Auto-provisioning from IdP (RFC 7644) | deferred |

### Core SDK (#2 — spec'd)

| Capability | Description | Spec'd | Providers (implement 2-3) |
|---|---|---|---|
| Chat completion | `/v1/chat/completions` — streaming, tools, vision, JSON mode | yes | OpenAI, Anthropic, Gemini |
| Embeddings | `/v1/embeddings` — batch, dimensions, encoding format | yes | OpenAI, Gemini |
| Provider abstraction | BaseProvider interface, registry, resolution from `"provider/model"` | yes | all |
| Parameter mapping | Transform OpenAI params to provider-native + `drop_params` | yes | all |
| Streaming | `StreamWrapper` with sync/async iterators | yes | all |
| Tool/function calling | Unified tool call format across providers | yes | OpenAI, Anthropic, Gemini |
| Exception mapping | Provider errors → standard exception hierarchy | yes | all |
| Cost calculation | Per-token pricing, model cost catalog | yes | all |
| Token counting | Provider-specific tokenizers + fallback estimation | yes | all |
| HTTP client pool | httpx async with connection pooling, never close on eviction | yes | - |

### Router (#3 — spec'd)

| Capability | Description | Spec'd |
|---|---|---|
| Round robin | Sequential/weighted distribution | yes |
| Lowest latency | Track last N response times, select fastest | yes |
| Lowest cost | Select cheapest provider deployment | yes |
| Fallback & retry | Configurable fallback chains, retry policies per error type | yes |
| Cooldown / circuit breaker | Pause failing deployments, auto-recover | yes |
| Model aliasing | Redirect model names transparently | yes |
| Deployment CRUD | Add/remove deployments at runtime via API | no |
| Tag-based routing | Filter deployments by request tags | no |
| Complexity routing | Route by input complexity (simple→fast model, complex→capable) | no |
| Provider budget limiting | Per-provider spend caps in router | no |
| Deployment affinity | Sticky routing for specific users/sessions | no |

### Cache (#4 — spec'd)

| Capability | Description | Spec'd |
|---|---|---|
| In-memory cache | LRU with TTL, heap-based eviction | yes |
| Redis cache | Circuit breaker, namespace, pipeline writes | yes |
| Redis cluster | Cross-slot compatible | yes |
| Disk cache | Local persistent via `diskcache` | yes |
| S3 cache | AWS S3 with TTL via headers | yes |
| GCS cache | Google Cloud Storage | yes |
| Azure Blob cache | Azure Storage | yes |
| Redis semantic cache | Vector similarity via embeddings | yes |
| Qdrant semantic cache | Vector similarity via Qdrant | yes |
| Dual cache | In-memory + Redis combined | yes |
| Cache key generation | SHA-256 of request params | yes |
| Per-request cache control | TTL, no-cache, no-store, namespace override | yes |
| Embedding partial hits | Cache individual embeddings in batch | yes |

### Spend & Budgets (#5 — spec'd)

| Capability | Description | Spec'd |
|---|---|---|
| Per-request spend logging | Log cost, tokens, model, entity refs per request | yes |
| Daily aggregates (6 tables) | Incremental upsert by user/team/org/key/end-user/tag | yes |
| Budget enforcement | Check spend vs max_budget in middleware | yes |
| Budget reset scheduler | Cron-based reset by period (daily/weekly/monthly/etc.) | partial |
| Soft budget alerts | Emit event when approaching limit | yes |
| Spend query endpoints | Query/filter/aggregate spend data | yes |
| Rate limiting (RPM/TPM) | Redis sliding window, 3 levels (global/entity/model) | yes |
| Max parallel requests | Atomic counter in Redis | yes |

### Observability (#6 — spec'd)

| Capability | Description | Spec'd | Implement |
|---|---|---|---|
| Callback interface | `CustomLogger` base class with pre/success/failure hooks | yes | - |
| Standard logging payload | Unified payload with cost, tokens, timing, metadata | yes | - |
| OpenTelemetry | OTLP traces + metrics | yes | yes |
| Prometheus | Metrics scraping endpoint | yes | yes |
| Langfuse | Traces + generations | yes | yes |
| Datadog | Batch log shipping | yes | yes |
| Slack alerting | Latency, failure, budget, outage alerts | yes | yes |
| Per-team/key callbacks | Dynamic callback credentials from key metadata | yes | - |
| Service logging | Internal service health (Redis, DB) | no | - |
| Batch logger pattern | Queue + flush for high-throughput integrations | yes | - |
| LangSmith | Traces + datasets | no | later |
| Arize / Phoenix | ML monitoring | no | later |
| MLflow | Experiment tracking | no | later |
| Weights & Biases | W&B tracking | no | later |
| PagerDuty | Incident alerting | no | later |
| Email alerts | SMTP / SendGrid / Resend | no | later |

### Guardrails (#7 — spec'd)

| Capability | Description | Spec'd | Implement |
|---|---|---|---|
| Framework (base class) | `CustomGuardrail` with pre/during/post hooks | yes | yes |
| Guardrail registry | Register, initialize, lifecycle management | yes | yes |
| OpenAI Moderation | Content safety via `/moderations` endpoint | yes | yes |
| Presidio PII | Detect/mask PII (CREDIT_CARD, EMAIL, PERSON, etc.) | yes | yes |
| Custom Python guardrails | User-defined guardrail classes | yes | yes |
| Per-request selection | Enable/disable guardrails per request via metadata | yes | yes |
| Guardrail logging | Log status, duration, entities to observability | yes | yes |
| Policy engine | Pipeline steps with conditional branching (allow/block/next) | no | later |
| Tool permission guardrail | Per-tool input/output policies (trusted/untrusted/blocked) | no | later |
| MCP security guardrails | MCP-specific security checks | no | later |
| Lakera, Bedrock, Azure, etc. | 30+ third-party integrations | no | later |
| DB-stored guardrail config | CRUD via API instead of YAML only | no | later |

### Advanced APIs (#8 — spec'd)

| Capability | Description | Spec'd | Providers (implement 2-3) |
|---|---|---|---|
| Image generation | `/v1/images/generations` | yes | OpenAI, Gemini |
| Audio transcription (STT) | `/v1/audio/transcriptions` | yes | OpenAI |
| Text-to-speech (TTS) | `/v1/audio/speech` | yes | OpenAI |
| Fine-tuning | `/v1/fine_tuning/jobs` CRUD | yes | OpenAI |
| Batch processing | `/v1/batches` CRUD | yes | OpenAI |
| Files API | `/v1/files` CRUD + content download | yes | OpenAI |
| Realtime / WebSocket | `/v1/realtime` for streaming audio/text | yes | OpenAI |
| Reranking | `/v1/rerank` | yes | Cohere, Voyage |
| Moderation | `/v1/moderations` | no | OpenAI |
| Text completion (legacy) | `/v1/completions` | no | OpenAI |
| Image editing | `/v1/images/edits` | no | later |
| Image variations | `/v1/images/variations` | no | later |
| Video generation | Text/image to video | no | later |
| OCR | Optical character recognition | no | later |
| Assistants API | Threads, runs, messages | no | later |
| Vector stores | CRUD for vector store management | no | later |

### Dashboard UI (#9 — spec'd)

| Capability | Description | Spec'd |
|---|---|---|
| Login (password + SSO) | Auth flow with sessionStorage | yes |
| Dashboard home | Spend charts, request counts, top models/users | yes |
| API keys management | Generate, edit, rotate, block, bulk ops | yes |
| User management | CRUD, roles, block | yes |
| Team management | CRUD, members, models, budget | yes |
| Organization management | CRUD, members, teams | yes |
| Model configuration | List deployments, add/remove | yes |
| Spend analytics | Charts by model/team/user/key, export CSV | yes |
| Chat playground | Interactive chat with model selector | yes |
| Settings | Logging, guardrails, SSO, cache config | yes |
| Role-based views | Different UI per role | yes |

### Features NOT in any sub-project yet

| Capability | Description | Priority |
|---|---|---|
| **MCP servers** | Register MCP servers, OAuth, tool discovery, BYOK, health checks, approval lifecycle | high |
| **Prompt management** | Prompt templates, versioning, variables, integration with Langfuse/Humanloop | medium |
| **Search tools** | Web search integration (Tavily, Firecrawl, Serper, DuckDuckGo, Jina, etc.) | medium |
| **Tags system** | Tag requests for spend tracking/filtering (`request_tags`) | medium |
| **End-user/customer management** | Track end-users (app consumers, not admins) with regional/model constraints | medium |
| **Agent endpoints** | Create/manage agents with access groups, spend tracking | medium |
| **Provider credential management** | CRUD credentials per provider (beyond API keys — OAuth, service accounts) | medium |
| **Notifications** | In-app notification system for users | low |
| **RAG** | Retrieval-augmented generation with vector store integration | low |
| **Skills / plugins** | Plugin marketplace, Claude skills | low |
| **Cost integrations** | CloudZero, Vantage cost tracking | low |

### Provider Implementation Matrix

For each capability, implement 2-3 providers initially. Full list of providers to support eventually:

**Tier 1 (implement first):** OpenAI, Anthropic, Google Gemini
**Tier 2 (add next):** Azure OpenAI, AWS Bedrock, Mistral, Cohere
**Tier 3 (later):** Groq, Together, Ollama, Fireworks, DeepSeek, Replicate, HuggingFace
**Tier 4 (on demand):** 80+ remaining providers

## Project Structure

```
makoto_lite_llm/
├── src/
│   └── app/
│       ├── main.py              # FastAPI app
│       ├── config.py            # Settings
│       ├── database.py          # SQLAlchemy async
│       ├── models/              # SQLAlchemy models
│       ├── schemas/             # Pydantic request/response
│       ├── auth/                # Auth core (JWT, bcrypt, API keys)
│       ├── services/            # Business logic
│       ├── routes/              # FastAPI endpoints
│       ├── sdk/                 # Core SDK (provider abstraction)
│       │   ├── providers/       # Provider implementations
│       │   ├── types/           # Unified response types
│       │   └── utils/           # Token counting, cost calc
│       ├── router/              # Load balancing & routing
│       ├── cache/               # Cache backends
│       ├── observability/       # Callback system & integrations
│       └── guardrails/          # Guardrail framework
├── tests/
├── alembic/
├── frontend/                    # Next.js dashboard
└── docs/
    ├── specs/                   # Design specifications
    └── plans/                   # Implementation plans
```
