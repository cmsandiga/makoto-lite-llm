# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A ground-up recreation of LiteLLM — a unified LLM proxy gateway with auth, routing, caching, observability, and multi-provider support. Currently in the **planning/spec phase**; no implementation code exists yet. All specs are in `docs/specs/` and implementation plans in `docs/plans/`.

## Tech Stack

- **Language:** Python 3.11+
- **Framework:** FastAPI with SQLAlchemy 2.0 async ORM
- **Database:** PostgreSQL 15+ (SQLite for tests)
- **Cache/Rate limiting:** Redis
- **Auth:** PyJWT, bcrypt, cryptography (AES-256)
- **HTTP client:** httpx (async)
- **Frontend:** Next.js (sub-project #9, last to implement)
- **Testing:** pytest, pytest-asyncio
- **Linting:** Ruff, MyPy, Black

## Commands

Commands are not yet defined (no `pyproject.toml` exists). When implementing, expect:

```bash
# Install
uv sync  # or pip install -e ".[dev]"

# Run server
uvicorn src.app.main:app --reload

# Tests
pytest
pytest tests/path/to/test_file.py::test_name  # single test

# Lint/format
ruff check .
ruff format .
mypy src/

# Migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
```

## Architecture

```
Dashboard UI (Next.js)
        │
Proxy Server (FastAPI)
  Auth Middleware → Guardrails → Routes → Observability Callbacks
        │
  Router (load balancing: round-robin | lowest-latency | lowest-cost | fallback)
        │
  Cache Layer (in-memory | redis | s3 | gcs | azure-blob | disk | semantic)
        │
  Core SDK (provider abstraction: OpenAI | Anthropic | Google Gemini)
        │
PostgreSQL (SQLAlchemy)   Redis (rate limits / cache)
```

### Source layout (planned)

```
src/app/
├── main.py          # FastAPI app, lifespan, router includes
├── config.py        # Pydantic Settings
├── database.py      # async engine, session factory
├── models/          # SQLAlchemy models (UUIDs + timestamp mixins)
├── schemas/         # Pydantic request/response schemas
├── auth/            # JWT, bcrypt, API key generation, middleware pipeline
├── services/        # Business logic (one file per domain)
├── routes/          # FastAPI endpoint definitions
├── sdk/             # Provider abstraction layer
│   ├── providers/   # Per-provider implementations (OpenAI, Anthropic, Gemini)
│   ├── types/       # Unified response types
│   └── utils/       # Token counting, cost calculation
├── router/          # Load balancing & routing strategies
├── cache/           # Cache backends
├── observability/   # Callback system & integrations
└── guardrails/      # Guardrail framework & implementations
```

### Implementation order

Sub-projects must be implemented in order due to dependencies:
1. **Auth System** (standalone) — see `docs/specs/2026-03-22-auth-system-design.md` + plan
2. **Core SDK** (standalone) — provider abstraction, BaseProvider interface
3. **Router** (depends on Core SDK)
4. **Cache Layer** (depends on Core SDK)
5. **Spend & Budgets** (depends on Auth + Core SDK + Router)
6. **Observability** (depends on Core SDK)
7. **Guardrails** (depends on Core SDK)
8. **Advanced APIs** (depends on Core SDK)
9. **Dashboard UI** (depends on everything)

## Critical Implementation Rules

- **SQLAlchemy types:** Use `sqlalchemy.types.Uuid` and `sqlalchemy.JSON` (not `PgUUID`/`JSONB`) so models work with both PostgreSQL (prod) and SQLite (tests).
- **Cascade deletion:** Implement in the service layer explicitly — not via SQLAlchemy cascade — so deletions can be recorded in `audit`/`deleted_*` tables before removal.
- **API key cache:** In-memory TTL cache (5s) in the auth dependency to avoid DB hits on every request.
- **`budget_id` FK:** All entity tables (org, team, user, api_key) must have `ForeignKey("budgets.id")`.
- **HTTP client:** httpx async with connection pooling; never close connections on cache eviction.
- **Auth middleware pipeline order:** authenticate → rate limit → budget → model access → route permission.
- **Brute force protection:** Track `failed_login_attempts` and `lockout_until` on the User model; enforce in login flow.
