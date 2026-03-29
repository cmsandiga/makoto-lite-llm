# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A ground-up recreation of LiteLLM — a unified LLM proxy gateway with auth, routing, caching, observability, and multi-provider support. Auth system is in active implementation (Ola 4b). All specs are in `docs/specs/` and implementation plans in `docs/plans/`.

## Tech Stack

- **Language:** Python 3.11+
- **Framework:** FastAPI with SQLAlchemy 2.0 async ORM
- **Database:** PostgreSQL 15+ (testcontainers for tests)
- **Cache/Rate limiting:** Redis
- **Auth:** PyJWT, bcrypt, cryptography (AES-256)
- **HTTP client:** httpx (async)
- **Frontend:** Next.js (sub-project #9, last to implement)
- **Testing:** pytest, pytest-asyncio, testcontainers
- **Linting:** Ruff, MyPy

## Commands

```bash
# Install
uv sync

# Run server
uvicorn src.app.main:app --reload

# Tests
uv run pytest -v
uv run pytest tests/path/to/test_file.py::test_name  # single test

# Lint/format
ruff check .
ruff format .
mypy src/

# Migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
```

## Architecture — Clean Architecture / Hexagonal (Ports & Adapters)

```
┌─────────────────────────────────────────────────────────────┐
│  OUTSIDE WORLD (HTTP clients)                               │
│                                                             │
│  wire_in (request schemas)  ──▶  ROUTE  ──▶  wire_out      │
│  Pydantic validates input        │   ▲       (response      │
│  at the border                   │   │        schemas)      │
│                                  │   │                      │
│                          model_validate()  ← conversion     │
│                          happens HERE       at the border   │
├──────────────────────────────────┼───┼──────────────────────┤
│  SERVICE LAYER (business logic)  │   │                      │
│  - Receives/returns ORM models   ▼   │                      │
│  - Knows nothing about HTTP          │                      │
│  - Knows nothing about wire_in/out   │                      │
│  - Explicit parameters (no **kwargs) │                      │
├──────────────────────────────────────┼──────────────────────┤
│  MODEL LAYER (database)              ▼                      │
│  - SQLAlchemy ORM objects                                   │
│  - Portable types (Uuid, JSON)                              │
│  - No business logic                                        │
└─────────────────────────────────────────────────────────────┘
```

### Data flow

```
Client request → wire_in schema (validates) → Route → Service → Model (DB)
Client response ← wire_out schema ← model_validate() ← Route ← Service ← Model
```

### Source layout

```
src/app/
├── main.py              # FastAPI app, lifespan, router includes
├── config.py            # Pydantic Settings
├── database.py          # async engine, session factory
│
│   # ── MODEL LAYER (database / ORM) ──
├── models/              # SQLAlchemy models (UUIDs + timestamp mixins)
│
│   # ── AUTH PRIMITIVES ──
├── auth/
│   ├── password.py      # bcrypt hash/verify
│   ├── jwt_handler.py   # create/verify access+refresh tokens
│   ├── api_key_auth.py  # generate, hash, verify API keys
│   ├── crypto.py        # AES-256-GCM encrypt/decrypt
│   └── dependencies.py  # get_current_user, require_role (FastAPI deps)
│
│   # ── SERVICE LAYER (business logic, HTTP-agnostic) ──
├── services/            # One file per domain, explicit params, returns ORM models
│
│   # ── ROUTE LAYER (HTTP border — wire_in → service → wire_out) ──
├── routes/              # RESTful endpoints, explicit model_validate() at the border
│
│   # ── SCHEMA LAYER (wire protocol — separated by direction) ──
├── schemas/
│   ├── common.py        # Enums, ErrorResponse, PaginatedResponse
│   ├── wire_in/         # What the CLIENT SENDS us (request validation)
│   │   ├── auth.py      # LoginRequest, RefreshRequest, ResetPasswordRequest
│   │   ├── user.py      # UserCreate, UserUpdateProfile, UserUpdateBudget
│   │   ├── team.py      # TeamCreate, TeamUpdate, TeamMemberAdd
│   │   ├── org.py       # OrgCreate, OrgUpdate, OrgMemberAdd
│   │   └── key.py       # KeyGenerate, KeyUpdate, KeyRotateRequest
│   └── wire_out/        # What WE SEND BACK (response serialization)
│       ├── common.py    # StatusResponse, HealthResponse, LogoutAllResponse
│       ├── auth.py      # TokenResponse
│       ├── user.py      # UserResponse
│       ├── team.py      # TeamResponse
│       ├── org.py       # OrgResponse
│       └── key.py       # KeyResponse, KeyGenerateResponse
│
│   # ── FUTURE SUB-PROJECTS ──
├── sdk/                 # Provider abstraction (OpenAI, Anthropic, Gemini)
├── router/              # Load balancing & routing strategies
├── cache/               # Cache backends
├── observability/       # Callback system & integrations
└── guardrails/          # Guardrail framework & implementations
```

## Architectural Rules

### Layer boundaries (MANDATORY)

1. **Routes are the border.** They convert between wire format and domain objects:
   - Receive wire_in schemas (Pydantic validates automatically)
   - Call service functions with explicit parameters
   - Convert service results to wire_out using `model_validate()` or constructor
   - Never return raw dicts or ORM models — always wire_out schemas

2. **Services are HTTP-agnostic.** They:
   - Receive explicit typed parameters (no `**kwargs`, no Pydantic schemas)
   - Return ORM models or primitives (never wire_out schemas)
   - Never import from `routes/`, `wire_in/`, or `wire_out/`
   - Handle business logic, DB operations, and domain rules

3. **Models are logic-free.** They:
   - Define database structure only
   - No business logic, no validation beyond DB constraints
   - Use portable types (`Uuid`, `JSON`) for PostgreSQL + test compatibility

### Route implementation pattern

```python
from app.schemas.wire_in.user import UserCreate        # what comes IN
from app.schemas.wire_out.user import UserResponse      # what goes OUT

@router.post("", status_code=201)
async def create(body: UserCreate, ...) -> UserResponse:
    user = await create_user(db, email=body.email, ...)  # service returns ORM model
    return UserResponse.model_validate(user)              # explicit conversion at border
```

### Service implementation pattern

```python
async def update_user_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str | None = None,          # every parameter explicit
    role: str | None = None,
    metadata_json: dict | None = None,
) -> User | None:                     # returns ORM model, not schema
```

### REST conventions

| Action | Method | URL pattern | Status |
|--------|--------|-------------|--------|
| Create | POST | `/resources` | 201 |
| List | GET | `/resources` | 200 |
| Get one | GET | `/resources/{id}` | 200 |
| Update | PATCH | `/resources/{id}` or `/resources/{id}/aspect` | 200 |
| Delete | DELETE | `/resources/{id}` | 204 |
| Actions | POST | `/auth/login`, `/auth/logout` | 200 |

- Plural nouns (`/users`, `/teams`, not `/user`, `/team`)
- IDs in the URL path, never in the request body
- Split update schemas by concern (`UserUpdateProfile`, `UserUpdateBudget`, `UserBlockRequest`)

### Transaction safety

- Use `flush()` when you need generated IDs mid-transaction (sends SQL, doesn't commit)
- Single `commit()` at the end to keep operations atomic
- Never two `commit()` calls for operations that should be atomic

## Critical Implementation Rules

- **SQLAlchemy types:** Use `sqlalchemy.types.Uuid` and `sqlalchemy.JSON` (not `PgUUID`/`JSONB`) so models work with both PostgreSQL (prod) and SQLite (tests).
- **Cascade deletion:** Implement in the service layer explicitly — not via SQLAlchemy cascade — so deletions can be recorded in `audit`/`deleted_*` tables before removal.
- **API key cache:** In-memory TTL cache (5s) in the auth dependency to avoid DB hits on every request.
- **`budget_id` FK:** All entity tables (org, team, user, api_key) must have `ForeignKey("budgets.id")`.
- **HTTP client:** httpx async with connection pooling; never close connections on cache eviction.
- **Auth middleware pipeline order:** authenticate → rate limit → budget → model access → route permission.
- **Brute force protection:** Track `failed_login_attempts` and `lockout_until` on the User model; enforce in login flow.
- **No `**kwargs`:** All service function parameters must be explicit — visible to IDE autocomplete, caught by type checkers.
- **No hardcoded responses:** Every response goes through a wire_out schema. No `return {"status": "ok"}`.

## Implementation order

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
