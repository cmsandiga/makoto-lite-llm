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
