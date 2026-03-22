# Auth System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete authentication, authorization, and multi-tenant management system for an LLM proxy gateway.

**Architecture:** FastAPI application with SQLAlchemy 2.0 async ORM, PostgreSQL database, Redis for rate limiting/caching. Layered architecture: models → services → routes. Auth middleware pipeline processes every request through authenticate → rate limit → budget → model access → route permission checks.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Alembic, PostgreSQL 15+, Redis, PyJWT, bcrypt, cryptography (AES-256), httpx, email-validator, pytest, pytest-asyncio

**Important implementation notes:**
- **SQLAlchemy types:** Use `sqlalchemy.types.Uuid` (not `PgUUID`) and `sqlalchemy.JSON` (not `JSONB`) so models work with both PostgreSQL and SQLite (tests). These are portable types that SQLAlchemy maps to the best available backend type automatically.
- **Cascade deletion:** Use explicit cascade logic in service layer (not SQLAlchemy cascade) so we can record deletions in audit/deleted_* tables before removing records.
- **Brute force protection:** Track `failed_login_attempts` and `lockout_until` on the User model. Enforce in login flow.
- **API key cache:** Implement in-memory TTL cache (5s) in the auth dependency to avoid DB lookups on every request.
- **`budget_id` FK:** All entity tables (org, team, user, api_key) must declare `budget_id` with `ForeignKey("budgets.id")`.

**Spec:** `docs/specs/2026-03-22-auth-system-design.md`

---

## File Structure

```
makoto_lite_llm/
├── pyproject.toml
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
├── src/
│   └── app/
│       ├── __init__.py
│       ├── main.py                      # FastAPI app, lifespan, router includes
│       ├── config.py                    # Pydantic Settings
│       ├── database.py                  # async engine, session factory
│       ├── models/
│       │   ├── __init__.py              # re-exports all models
│       │   ├── base.py                  # DeclarativeBase + UUID/timestamp mixins
│       │   ├── organization.py
│       │   ├── team.py
│       │   ├── project.py
│       │   ├── user.py
│       │   ├── api_key.py
│       │   ├── membership.py           # OrgMembership + TeamMembership
│       │   ├── budget.py
│       │   ├── permission.py           # ObjectPermission + AccessGroup + AccessGroupAssignment
│       │   ├── sso_config.py
│       │   ├── refresh_token.py
│       │   ├── password_reset_token.py
│       │   ├── audit.py               # AuditLog + DeletedUser + DeletedTeam + DeletedKey + ErrorLog
│       │   └── spend.py               # SpendLog + DailyUserSpend + 5 other daily tables
│       ├── auth/
│       │   ├── __init__.py
│       │   ├── password.py             # bcrypt hash/verify
│       │   ├── jwt_handler.py          # create/verify access+refresh tokens
│       │   ├── api_key_auth.py         # generate, hash, verify API keys
│       │   ├── crypto.py               # AES-256 encrypt/decrypt
│       │   ├── dependencies.py         # get_current_user, require_role, etc.
│       │   └── middleware.py           # AuthMiddleware pipeline
│       ├── services/
│       │   ├── __init__.py
│       │   ├── user_service.py
│       │   ├── team_service.py
│       │   ├── org_service.py
│       │   ├── key_service.py
│       │   ├── budget_service.py
│       │   ├── auth_service.py         # login, refresh, logout, password reset
│       │   ├── sso_service.py
│       │   ├── audit_service.py
│       │   ├── spend_service.py
│       │   ├── rate_limiter.py         # Redis sliding window
│       │   └── permission_service.py   # object permissions + access groups
│       ├── routes/
│       │   ├── __init__.py
│       │   ├── auth_routes.py          # /auth/*
│       │   ├── user_routes.py          # /user/*
│       │   ├── team_routes.py          # /team/*
│       │   ├── org_routes.py           # /organization/*
│       │   ├── key_routes.py           # /key/*
│       │   ├── budget_routes.py        # /budget/*
│       │   └── sso_routes.py           # /sso/*
│       └── schemas/
│           ├── __init__.py
│           ├── common.py               # Pagination, ErrorResponse, enums
│           ├── auth.py                 # LoginRequest, TokenResponse, etc.
│           ├── user.py
│           ├── team.py
│           ├── org.py
│           ├── key.py
│           ├── budget.py
│           └── sso.py
├── tests/
│   ├── conftest.py                     # async test DB, client, fixtures
│   ├── test_auth/
│   │   ├── test_password.py
│   │   ├── test_jwt_handler.py
│   │   ├── test_api_key_auth.py
│   │   └── test_crypto.py
│   ├── test_services/
│   │   ├── test_user_service.py
│   │   ├── test_team_service.py
│   │   ├── test_org_service.py
│   │   ├── test_key_service.py
│   │   ├── test_auth_service.py
│   │   ├── test_budget_service.py
│   │   ├── test_rate_limiter.py
│   │   └── test_permission_service.py
│   └── test_routes/
│       ├── test_auth_routes.py
│       ├── test_user_routes.py
│       ├── test_team_routes.py
│       ├── test_org_routes.py
│       ├── test_key_routes.py
│       ├── test_budget_routes.py
│       └── test_sso_routes.py
└── docs/
    ├── specs/
    └── plans/
```

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/app/__init__.py`
- Create: `src/app/config.py`
- Create: `src/app/database.py`
- Create: `src/app/main.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "makoto-lite-llm"
version = "0.1.0"
description = "LLM proxy gateway with auth and multi-tenant management"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "asyncpg>=0.30.0",
    "alembic>=1.14.0",
    "pydantic-settings>=2.0.0",
    "pyjwt[crypto]>=2.9.0",
    "bcrypt>=4.2.0",
    "cryptography>=43.0.0",
    "httpx>=0.27.0",
    "redis[hiredis]>=5.0.0",
    "python-multipart>=0.0.9",
    "email-validator>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
    "aiosqlite>=0.20.0",
    "ruff>=0.8.0",
    "mypy>=1.13.0",
]

[build-system]
requires = ["setuptools>=75.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.mypy]
python_version = "3.11"
strict = true
```

- [ ] **Step 2: Create config.py**

```python
# src/app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/makoto_lite_llm"
    database_url_sync: str = "postgresql://postgres:postgres@localhost:5432/makoto_lite_llm"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    # Encryption
    encryption_key: str = "change-me-32-bytes-key-in-prod!!"  # Must be 32 bytes for AES-256

    # Auth
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 15
    api_key_cache_ttl_seconds: int = 5

    # Rate limiting
    global_rpm_limit: int | None = None
    global_tpm_limit: int | None = None

    model_config = {"env_prefix": "MLITELLM_"}


settings = Settings()
```

- [ ] **Step 3: Create database.py**

```python
# src/app/database.py
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
```

- [ ] **Step 4: Create main.py**

```python
# src/app/main.py
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from app.database import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    await engine.dispose()


app = FastAPI(title="Makoto LiteLLM", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 5: Create src/app/__init__.py**

```python
# src/app/__init__.py
```

- [ ] **Step 6: Create test conftest.py with async SQLite test DB**

```python
# tests/conftest.py
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_db
from app.main import app
from app.models.base import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session() -> AsyncSession:
    async with test_session_factory() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncClient:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
```

- [ ] **Step 7: Write smoke test**

```python
# tests/test_health.py
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 8: Install and run test**

Run: `cd ~/dev/cmsandiga/makoto_lite_llm && pip install -e ".[dev]" && pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 9: Initialize git and commit**

```bash
cd ~/dev/cmsandiga/makoto_lite_llm
git init
echo -e "__pycache__/\n*.pyc\n.pytest_cache/\ntest.db\n*.egg-info/\ndist/\n.mypy_cache/\n.ruff_cache/\n.env" > .gitignore
git add .
git commit -m "feat: project scaffolding — FastAPI + SQLAlchemy + test infrastructure"
```

---

### Task 2: SQLAlchemy Models — Base + Core Entities

**Files:**
- Create: `src/app/models/__init__.py`
- Create: `src/app/models/base.py`
- Create: `src/app/models/organization.py`
- Create: `src/app/models/team.py`
- Create: `src/app/models/project.py`
- Create: `src/app/models/user.py`
- Create: `src/app/models/membership.py`
- Create: `src/app/models/budget.py`
- Test: `tests/test_models/test_core_models.py`

- [ ] **Step 1: Write failing test for model creation**

```python
# tests/test_models/test_core_models.py
import uuid
from sqlalchemy import select
from app.models.organization import Organization
from app.models.team import Team
from app.models.user import User
from app.models.membership import OrgMembership, TeamMembership
from app.models.budget import Budget


async def test_create_organization(db_session):
    org = Organization(name="Acme Corp", slug="acme-corp")
    db_session.add(org)
    await db_session.commit()

    result = await db_session.execute(select(Organization).where(Organization.slug == "acme-corp"))
    fetched = result.scalar_one()
    assert fetched.name == "Acme Corp"
    assert fetched.id is not None
    assert fetched.is_blocked is False


async def test_create_team_with_org(db_session):
    org = Organization(name="Acme", slug="acme")
    db_session.add(org)
    await db_session.flush()

    team = Team(name="Engineering", org_id=org.id)
    db_session.add(team)
    await db_session.commit()

    result = await db_session.execute(select(Team).where(Team.name == "Engineering"))
    fetched = result.scalar_one()
    assert fetched.org_id == org.id


async def test_create_user(db_session):
    user = User(email="alice@example.com", role="proxy_admin")
    db_session.add(user)
    await db_session.commit()

    result = await db_session.execute(select(User).where(User.email == "alice@example.com"))
    fetched = result.scalar_one()
    assert fetched.role == "proxy_admin"
    assert fetched.spend == 0.0
    assert fetched.is_blocked is False


async def test_org_membership(db_session):
    org = Organization(name="Acme", slug="acme")
    user = User(email="bob@example.com", role="member")
    db_session.add_all([org, user])
    await db_session.flush()

    membership = OrgMembership(user_id=user.id, org_id=org.id, role="org_admin")
    db_session.add(membership)
    await db_session.commit()

    result = await db_session.execute(
        select(OrgMembership).where(OrgMembership.user_id == user.id)
    )
    fetched = result.scalar_one()
    assert fetched.role == "org_admin"


async def test_create_budget(db_session):
    budget = Budget(name="Standard", max_budget=100.0, rpm_limit=60)
    db_session.add(budget)
    await db_session.commit()

    result = await db_session.execute(select(Budget).where(Budget.name == "Standard"))
    fetched = result.scalar_one()
    assert fetched.max_budget == 100.0
    assert fetched.rpm_limit == 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models/test_core_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 3: Implement base model**

```python
# src/app/models/base.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

**IMPORTANT:** All model files must use `sqlalchemy.Uuid` (not `PgUUID`) and `sqlalchemy.JSON` (not `JSONB`) for cross-database compatibility. Replace every occurrence of:
- `from sqlalchemy.dialects.postgresql import UUID as PgUUID, JSONB` → `from sqlalchemy import Uuid, JSON`
- `PgUUID(as_uuid=True)` → `Uuid`
- `JSONB` → `JSON`
- `server_default="now()"` → `server_default=func.now()`

- [ ] **Step 4: Implement Organization model**

```python
# src/app/models/organization.py
import uuid
from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class Organization(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True)
    max_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    soft_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    tpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("budgets.id"), nullable=True
    )
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
```

- [ ] **Step 5: Implement Team model**

```python
# src/app/models/team.py
import uuid
from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class Team(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "teams"

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255))
    allowed_models: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    max_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    soft_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    tpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_parallel_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_reset_period: Mapped[str | None] = mapped_column(String(50), nullable=True)
    budget_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
```

- [ ] **Step 6: Implement Project model**

```python
# src/app/models/project.py
import uuid
from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class Project(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "projects"

    team_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("teams.id")
    )
    name: Mapped[str] = mapped_column(String(255))
    allowed_models: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
```

- [ ] **Step 7: Implement User model**

```python
# src/app/models/user.py
import uuid
from sqlalchemy import Boolean, Float, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("sso_provider", "sso_subject", name="uq_sso_identity"),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default="member")
    max_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    spend: Mapped[float] = mapped_column(Float, default=0.0)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    sso_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sso_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    budget_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("budgets.id"), nullable=True
    )
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    lockout_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
```

- [ ] **Step 8: Implement Membership models**

```python
# src/app/models/membership.py
import uuid
from sqlalchemy import Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class OrgMembership(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "org_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "org_id", name="uq_user_org"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id")
    )
    role: Mapped[str] = mapped_column(String(50))
    max_budget: Mapped[float | None] = mapped_column(Float, nullable=True)


class TeamMembership(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "team_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "team_id", name="uq_user_team"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id")
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("teams.id")
    )
    role: Mapped[str] = mapped_column(String(50))
    max_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
```

- [ ] **Step 9: Implement Budget model**

```python
# src/app/models/budget.py
from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class Budget(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "budgets"

    name: Mapped[str] = mapped_column(String(255))
    max_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    soft_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    tpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_parallel_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_reset_period: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

- [ ] **Step 10: Create models __init__.py**

```python
# src/app/models/__init__.py
from app.models.base import Base
from app.models.organization import Organization
from app.models.team import Team
from app.models.project import Project
from app.models.user import User
from app.models.membership import OrgMembership, TeamMembership
from app.models.budget import Budget

__all__ = [
    "Base",
    "Organization",
    "Team",
    "Project",
    "User",
    "OrgMembership",
    "TeamMembership",
    "Budget",
]
```

- [ ] **Step 11: Run tests**

Run: `pytest tests/test_models/test_core_models.py -v`
Expected: All 5 tests PASS

- [ ] **Step 12: Commit**

```bash
git add -A && git commit -m "feat: SQLAlchemy models — org, team, project, user, membership, budget"
```

---

### Task 3: SQLAlchemy Models — API Key, Auth, Audit, Spend

**Files:**
- Create: `src/app/models/api_key.py`
- Create: `src/app/models/permission.py`
- Create: `src/app/models/sso_config.py`
- Create: `src/app/models/refresh_token.py`
- Create: `src/app/models/password_reset_token.py`
- Create: `src/app/models/audit.py`
- Create: `src/app/models/spend.py`
- Test: `tests/test_models/test_auth_models.py`

- [ ] **Step 1: Write failing test for API key and auth models**

```python
# tests/test_models/test_auth_models.py
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from app.models.user import User
from app.models.api_key import ApiKey
from app.models.refresh_token import RefreshToken
from app.models.audit import AuditLog


async def test_create_api_key(db_session):
    user = User(email="alice@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    key = ApiKey(
        api_key_hash="sha256_hash_here",
        key_prefix="sk-abcd12",
        user_id=user.id,
        allowed_models=["gpt-4", "claude-*"],
    )
    db_session.add(key)
    await db_session.commit()

    result = await db_session.execute(select(ApiKey).where(ApiKey.user_id == user.id))
    fetched = result.scalar_one()
    assert fetched.key_prefix == "sk-abcd12"
    assert fetched.spend == 0.0
    assert fetched.is_blocked is False
    assert fetched.allowed_models == ["gpt-4", "claude-*"]


async def test_create_refresh_token(db_session):
    user = User(email="bob@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    token = RefreshToken(
        token_hash="sha256_token_hash",
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(token)
    await db_session.commit()

    result = await db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )
    fetched = result.scalar_one()
    assert fetched.is_revoked is False


async def test_create_audit_log(db_session):
    log = AuditLog(
        actor_id=uuid.uuid4(),
        actor_type="user",
        action="create",
        resource_type="team",
        resource_id=str(uuid.uuid4()),
        ip_address="127.0.0.1",
        user_agent="test",
    )
    db_session.add(log)
    await db_session.commit()

    result = await db_session.execute(select(AuditLog).where(AuditLog.action == "create"))
    fetched = result.scalar_one()
    assert fetched.actor_type == "user"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models/test_auth_models.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ApiKey model**

```python
# src/app/models/api_key.py
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class ApiKey(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "api_keys"

    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    key_prefix: Mapped[str] = mapped_column(String(16))
    key_alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id")
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("teams.id"), nullable=True
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    allowed_models: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    max_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    soft_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    spend: Mapped[float] = mapped_column(Float, default=0.0)
    tpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_parallel_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_reset_period: Mapped[str | None] = mapped_column(String(50), nullable=True)
    budget_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    auto_rotate: Mapped[bool] = mapped_column(Boolean, default=False)
    rotation_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    previous_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grace_period_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
```

- [ ] **Step 4: Implement Permission models**

```python
# src/app/models/permission.py
import uuid
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class ObjectPermission(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "object_permissions"
    __table_args__ = (
        UniqueConstraint(
            "entity_type", "entity_id", "resource_type", "resource_id", "action",
            name="uq_object_permission",
        ),
    )

    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(10))


class AccessGroup(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "access_groups"

    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    resources: Mapped[list | None] = mapped_column(JSONB, nullable=True)


class AccessGroupAssignment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "access_group_assignments"
    __table_args__ = (
        UniqueConstraint(
            "access_group_id", "entity_type", "entity_id",
            name="uq_access_group_assignment",
        ),
    )

    access_group_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("access_groups.id")
    )
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
```

- [ ] **Step 5: Implement SSO Config model**

```python
# src/app/models/sso_config.py
import uuid
from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class SSOConfig(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "sso_configs"

    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id"), unique=True
    )
    provider: Mapped[str] = mapped_column(String(50))
    client_id: Mapped[str] = mapped_column(String(255))
    client_secret_encrypted: Mapped[str] = mapped_column(String(1000))
    issuer_url: Mapped[str] = mapped_column(String(1000))
    allowed_domains: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    group_to_team_mapping: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    auto_create_user: Mapped[bool] = mapped_column(Boolean, default=True)
    default_role: Mapped[str] = mapped_column(String(50), default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
```

- [ ] **Step 6: Implement RefreshToken + PasswordResetToken models**

```python
# src/app/models/refresh_token.py
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class RefreshToken(Base, UUIDMixin):
    __tablename__ = "refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("refresh_tokens.id"), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
```

```python
# src/app/models/password_reset_token.py
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class PasswordResetToken(Base, UUIDMixin):
    __tablename__ = "password_reset_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
```

- [ ] **Step 7: Implement Audit models**

```python
# src/app/models/audit.py
import uuid
from datetime import datetime
from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class AuditLog(Base, UUIDMixin):
    __tablename__ = "audit_log"

    actor_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
    actor_type: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(50))
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str] = mapped_column(String(255))
    before_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str] = mapped_column(String(45))
    user_agent: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DeletedUser(Base, UUIDMixin):
    __tablename__ = "deleted_users"
    original_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
    email: Mapped[str] = mapped_column(String(320))
    deleted_by: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DeletedTeam(Base, UUIDMixin):
    __tablename__ = "deleted_teams"
    original_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(255))
    deleted_by: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
    snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DeletedKey(Base, UUIDMixin):
    __tablename__ = "deleted_keys"
    original_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
    key_prefix: Mapped[str] = mapped_column(String(16))
    deleted_by: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
    snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ErrorLog(Base, UUIDMixin):
    __tablename__ = "error_logs"
    error_type: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(String(2000))
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [ ] **Step 8: Implement Spend models**

```python
# src/app/models/spend.py
import uuid
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class SpendLog(Base, UUIDMixin):
    __tablename__ = "spend_logs"

    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    api_key_hash: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    model: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    spend: Mapped[float] = mapped_column(Float, default=0.0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20))
    response_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DailyUserSpend(Base, UUIDMixin):
    __tablename__ = "daily_user_spend"
    __table_args__ = (
        UniqueConstraint("user_id", "model", "date", name="uq_daily_user_spend"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
    model: Mapped[str] = mapped_column(String(255))
    date: Mapped[date] = mapped_column(Date)
    total_spend: Mapped[float] = mapped_column(Float, default=0.0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)


class DailyTeamSpend(Base, UUIDMixin):
    __tablename__ = "daily_team_spend"
    __table_args__ = (
        UniqueConstraint("team_id", "model", "date", name="uq_daily_team_spend"),
    )
    team_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
    model: Mapped[str] = mapped_column(String(255))
    date: Mapped[date] = mapped_column(Date)
    total_spend: Mapped[float] = mapped_column(Float, default=0.0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)


class DailyOrgSpend(Base, UUIDMixin):
    __tablename__ = "daily_org_spend"
    __table_args__ = (
        UniqueConstraint("org_id", "model", "date", name="uq_daily_org_spend"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
    model: Mapped[str] = mapped_column(String(255))
    date: Mapped[date] = mapped_column(Date)
    total_spend: Mapped[float] = mapped_column(Float, default=0.0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)


class DailyKeySpend(Base, UUIDMixin):
    __tablename__ = "daily_key_spend"
    __table_args__ = (
        UniqueConstraint("api_key_hash", "model", "date", name="uq_daily_key_spend"),
    )
    api_key_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(255))
    date: Mapped[date] = mapped_column(Date)
    total_spend: Mapped[float] = mapped_column(Float, default=0.0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)


class DailyEndUserSpend(Base, UUIDMixin):
    __tablename__ = "daily_end_user_spend"
    __table_args__ = (
        UniqueConstraint("end_user", "model", "date", name="uq_daily_end_user_spend"),
    )
    end_user: Mapped[str] = mapped_column(String(255))
    model: Mapped[str] = mapped_column(String(255))
    date: Mapped[date] = mapped_column(Date)
    total_spend: Mapped[float] = mapped_column(Float, default=0.0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)


class DailyTagSpend(Base, UUIDMixin):
    __tablename__ = "daily_tag_spend"
    __table_args__ = (
        UniqueConstraint("tag", "model", "date", name="uq_daily_tag_spend"),
    )
    tag: Mapped[str] = mapped_column(String(255))
    model: Mapped[str] = mapped_column(String(255))
    date: Mapped[date] = mapped_column(Date)
    total_spend: Mapped[float] = mapped_column(Float, default=0.0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
```

- [ ] **Step 9: Update models/__init__.py with all models**

Add all new model imports to `src/app/models/__init__.py`.

- [ ] **Step 10: Run tests**

Run: `pytest tests/test_models/ -v`
Expected: All 8 tests PASS

- [ ] **Step 11: Commit**

```bash
git add -A && git commit -m "feat: SQLAlchemy models — api_key, permissions, SSO, tokens, audit, spend"
```

---

### Task 4: Auth Core — Password, JWT, API Key, Crypto

**Files:**
- Create: `src/app/auth/password.py`
- Create: `src/app/auth/jwt_handler.py`
- Create: `src/app/auth/api_key_auth.py`
- Create: `src/app/auth/crypto.py`
- Create: `src/app/auth/__init__.py`
- Test: `tests/test_auth/test_password.py`
- Test: `tests/test_auth/test_jwt_handler.py`
- Test: `tests/test_auth/test_api_key_auth.py`
- Test: `tests/test_auth/test_crypto.py`

- [ ] **Step 1: Write failing test for password hashing**

```python
# tests/test_auth/test_password.py
from app.auth.password import hash_password, verify_password


def test_hash_and_verify():
    hashed = hash_password("mysecretpassword")
    assert hashed != "mysecretpassword"
    assert verify_password("mysecretpassword", hashed) is True
    assert verify_password("wrongpassword", hashed) is False


def test_different_hashes_for_same_password():
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2  # bcrypt includes random salt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth/test_password.py -v`
Expected: FAIL

- [ ] **Step 3: Implement password module**

```python
# src/app/auth/__init__.py
```

```python
# src/app/auth/password.py
import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_auth/test_password.py -v`
Expected: PASS

- [ ] **Step 5: Write failing test for JWT handler**

```python
# tests/test_auth/test_jwt_handler.py
import uuid
from app.auth.jwt_handler import create_access_token, create_refresh_token, decode_token


def test_create_and_decode_access_token():
    user_id = uuid.uuid4()
    token = create_access_token(
        user_id=user_id, role="proxy_admin", org_id=None, team_id=None
    )
    payload = decode_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["role"] == "proxy_admin"
    assert payload["type"] == "access"


def test_create_and_decode_refresh_token():
    user_id = uuid.uuid4()
    token = create_refresh_token(user_id=user_id)
    payload = decode_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "refresh"


def test_decode_invalid_token():
    payload = decode_token("invalid.token.here")
    assert payload is None
```

- [ ] **Step 6: Implement JWT handler**

```python
# src/app/auth/jwt_handler.py
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings


def create_access_token(
    user_id: uuid.UUID,
    role: str,
    org_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "org_id": str(org_id) if org_id else None,
        "team_id": str(team_id) if team_id else None,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc)
        + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: uuid.UUID) -> str:
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc)
        + timedelta(days=settings.jwt_refresh_token_expire_days),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
```

- [ ] **Step 7: Run JWT tests**

Run: `pytest tests/test_auth/test_jwt_handler.py -v`
Expected: PASS

- [ ] **Step 8: Write failing test for API key auth**

```python
# tests/test_auth/test_api_key_auth.py
from app.auth.api_key_auth import generate_api_key, hash_api_key


def test_generate_api_key_format():
    key = generate_api_key()
    assert key.startswith("sk-")
    assert len(key) == 43  # "sk-" + 8 prefix + 32 random


def test_generate_api_key_uniqueness():
    k1 = generate_api_key()
    k2 = generate_api_key()
    assert k1 != k2


def test_hash_api_key():
    key = generate_api_key()
    hashed = hash_api_key(key)
    assert len(hashed) == 64  # SHA-256 hex
    assert hash_api_key(key) == hashed  # deterministic


def test_extract_prefix():
    key = generate_api_key()
    prefix = key[:10]  # "sk-" + first 7 chars — but we use 8 after sk-
    assert key.startswith("sk-")
```

- [ ] **Step 9: Implement API key auth**

```python
# src/app/auth/api_key_auth.py
import hashlib
import secrets


def generate_api_key() -> str:
    prefix = secrets.token_hex(4)  # 8 hex chars
    random_part = secrets.token_hex(16)  # 32 hex chars
    return f"sk-{prefix}{random_part}"


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def get_key_prefix(key: str) -> str:
    return key[:11]  # "sk-" + 8 chars (matches spec: "First 8 chars stored in clear")
```

- [ ] **Step 10: Run API key tests**

Run: `pytest tests/test_auth/test_api_key_auth.py -v`
Expected: PASS

- [ ] **Step 11: Write failing test for crypto**

```python
# tests/test_auth/test_crypto.py
from app.auth.crypto import encrypt, decrypt


def test_encrypt_decrypt_roundtrip():
    plaintext = "my-super-secret-client-secret"
    encrypted = encrypt(plaintext)
    assert encrypted != plaintext
    assert decrypt(encrypted) == plaintext


def test_different_ciphertexts_for_same_plaintext():
    e1 = encrypt("same")
    e2 = encrypt("same")
    assert e1 != e2  # different IV each time
```

- [ ] **Step 12: Implement AES-256 crypto**

```python
# src/app/auth/crypto.py
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


def _get_key() -> bytes:
    key = settings.encryption_key.encode()[:32]
    return key.ljust(32, b"\0")


def encrypt(plaintext: str) -> str:
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt(encrypted: str) -> str:
    key = _get_key()
    aesgcm = AESGCM(key)
    data = base64.b64decode(encrypted)
    nonce, ciphertext = data[:12], data[12:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode()
```

- [ ] **Step 13: Run all auth tests**

Run: `pytest tests/test_auth/ -v`
Expected: All PASS

- [ ] **Step 14: Commit**

```bash
git add -A && git commit -m "feat: auth core — password hashing, JWT, API key generation, AES-256 crypto"
```

---

### Task 5: Pydantic Schemas

**Files:**
- Create: `src/app/schemas/__init__.py`
- Create: `src/app/schemas/common.py`
- Create: `src/app/schemas/auth.py`
- Create: `src/app/schemas/user.py`
- Create: `src/app/schemas/team.py`
- Create: `src/app/schemas/org.py`
- Create: `src/app/schemas/key.py`
- Create: `src/app/schemas/budget.py`
- Create: `src/app/schemas/sso.py`

- [ ] **Step 1: Create common schemas**

```python
# src/app/schemas/common.py
import uuid
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


class PaginatedRequest(BaseModel):
    page: int = 1
    page_size: int = 50


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
```

- [ ] **Step 2: Create auth schemas**

```python
# src/app/schemas/auth.py
import uuid
from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
```

- [ ] **Step 3: Create user schemas**

```python
# src/app/schemas/user.py
import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str | None = None
    name: str | None = None
    role: str = "member"
    max_budget: float | None = None
    metadata: dict | None = None


class UserUpdate(BaseModel):
    user_id: uuid.UUID
    role: str | None = None
    name: str | None = None
    max_budget: float | None = None
    is_blocked: bool | None = None
    metadata: dict | None = None


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    role: str
    max_budget: float | None
    spend: float
    is_blocked: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserBlockRequest(BaseModel):
    user_id: uuid.UUID
    blocked: bool
```

- [ ] **Step 4: Create team schemas**

```python
# src/app/schemas/team.py
import uuid
from datetime import datetime
from pydantic import BaseModel


class TeamCreate(BaseModel):
    name: str
    org_id: uuid.UUID | None = None
    allowed_models: list[str] | None = None
    max_budget: float | None = None
    tpm_limit: int | None = None
    rpm_limit: int | None = None
    metadata: dict | None = None


class TeamUpdate(BaseModel):
    team_id: uuid.UUID
    name: str | None = None
    allowed_models: list[str] | None = None
    max_budget: float | None = None
    tpm_limit: int | None = None
    rpm_limit: int | None = None
    metadata: dict | None = None


class TeamResponse(BaseModel):
    id: uuid.UUID
    name: str
    org_id: uuid.UUID | None
    allowed_models: list | None
    max_budget: float | None
    is_blocked: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TeamMemberAdd(BaseModel):
    team_id: uuid.UUID
    user_id: uuid.UUID
    role: str = "member"


class TeamMemberUpdate(BaseModel):
    team_id: uuid.UUID
    user_id: uuid.UUID
    role: str


class TeamMemberDelete(BaseModel):
    team_id: uuid.UUID
    user_id: uuid.UUID
```

- [ ] **Step 5: Create org schemas**

```python
# src/app/schemas/org.py
import uuid
from datetime import datetime
from pydantic import BaseModel


class OrgCreate(BaseModel):
    name: str
    slug: str
    max_budget: float | None = None
    metadata: dict | None = None


class OrgUpdate(BaseModel):
    org_id: uuid.UUID
    name: str | None = None
    max_budget: float | None = None
    metadata: dict | None = None


class OrgResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    max_budget: float | None
    is_blocked: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgMemberAdd(BaseModel):
    org_id: uuid.UUID
    user_id: uuid.UUID
    role: str = "member"


class OrgMemberUpdate(BaseModel):
    org_id: uuid.UUID
    user_id: uuid.UUID
    role: str


class OrgMemberDelete(BaseModel):
    org_id: uuid.UUID
    user_id: uuid.UUID
```

- [ ] **Step 6: Create key schemas**

```python
# src/app/schemas/key.py
import uuid
from datetime import datetime
from pydantic import BaseModel


class KeyGenerate(BaseModel):
    key_alias: str | None = None
    team_id: uuid.UUID | None = None
    org_id: uuid.UUID | None = None
    allowed_models: list[str] | None = None
    max_budget: float | None = None
    tpm_limit: int | None = None
    rpm_limit: int | None = None
    max_parallel_requests: int | None = None
    expires_at: datetime | None = None
    metadata: dict | None = None


class KeyGenerateResponse(BaseModel):
    key: str  # plaintext — only returned once
    key_id: uuid.UUID
    key_prefix: str
    expires_at: datetime | None


class KeyUpdate(BaseModel):
    key_id: uuid.UUID
    key_alias: str | None = None
    allowed_models: list[str] | None = None
    max_budget: float | None = None
    tpm_limit: int | None = None
    rpm_limit: int | None = None
    metadata: dict | None = None


class KeyResponse(BaseModel):
    id: uuid.UUID
    key_prefix: str
    key_alias: str | None
    user_id: uuid.UUID
    team_id: uuid.UUID | None
    org_id: uuid.UUID | None
    allowed_models: list | None
    max_budget: float | None
    spend: float
    is_blocked: bool
    expires_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class KeyRotateRequest(BaseModel):
    key_id: uuid.UUID
    grace_period_hours: int = 24


class KeyBlockRequest(BaseModel):
    key_id: uuid.UUID
    blocked: bool


class KeyBulkUpdate(BaseModel):
    key_ids: list[uuid.UUID]
    allowed_models: list[str] | None = None
    max_budget: float | None = None
```

- [ ] **Step 7: Create budget and SSO schemas**

```python
# src/app/schemas/budget.py
import uuid
from datetime import datetime
from pydantic import BaseModel


class BudgetCreate(BaseModel):
    name: str
    max_budget: float | None = None
    soft_budget: float | None = None
    tpm_limit: int | None = None
    rpm_limit: int | None = None
    max_parallel_requests: int | None = None
    budget_reset_period: str | None = None


class BudgetUpdate(BaseModel):
    budget_id: uuid.UUID
    name: str | None = None
    max_budget: float | None = None
    soft_budget: float | None = None
    tpm_limit: int | None = None
    rpm_limit: int | None = None


class BudgetResponse(BaseModel):
    id: uuid.UUID
    name: str
    max_budget: float | None
    soft_budget: float | None
    tpm_limit: int | None
    rpm_limit: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
```

```python
# src/app/schemas/sso.py
import uuid
from pydantic import BaseModel


class SSOConfigCreate(BaseModel):
    org_id: uuid.UUID
    provider: str
    client_id: str
    client_secret: str
    issuer_url: str
    allowed_domains: list[str] | None = None
    group_to_team_mapping: dict | None = None
    auto_create_user: bool = True
    default_role: str = "member"


class SSOConfigResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    provider: str
    client_id: str
    issuer_url: str
    allowed_domains: list | None
    auto_create_user: bool
    is_active: bool

    model_config = {"from_attributes": True}
```

- [ ] **Step 8: Create schemas/__init__.py**

```python
# src/app/schemas/__init__.py
```

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat: Pydantic schemas for all endpoints"
```

---

### Task 6: Auth Service + Routes (login, refresh, logout, password reset)

**Files:**
- Create: `src/app/services/__init__.py`
- Create: `src/app/services/auth_service.py`
- Create: `src/app/auth/dependencies.py`
- Create: `src/app/routes/__init__.py`
- Create: `src/app/routes/auth_routes.py`
- Test: `tests/test_routes/test_auth_routes.py`

- [ ] **Step 1: Write failing test for login**

```python
# tests/test_routes/test_auth_routes.py
from app.models.user import User
from app.auth.password import hash_password


async def test_login_success(client, db_session):
    user = User(
        email="alice@test.com",
        password_hash=hash_password("secret123"),
        role="member",
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post("/auth/login", json={
        "email": "alice@test.com",
        "password": "secret123",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


async def test_login_wrong_password(client, db_session):
    user = User(
        email="bob@test.com",
        password_hash=hash_password("correct"),
        role="member",
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post("/auth/login", json={
        "email": "bob@test.com",
        "password": "wrong",
    })
    assert response.status_code == 401


async def test_login_blocked_user(client, db_session):
    user = User(
        email="blocked@test.com",
        password_hash=hash_password("pass"),
        role="member",
        is_blocked=True,
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post("/auth/login", json={
        "email": "blocked@test.com",
        "password": "pass",
    })
    assert response.status_code == 403


async def test_refresh_token_flow(client, db_session):
    user = User(
        email="refresh@test.com",
        password_hash=hash_password("pass"),
        role="member",
    )
    db_session.add(user)
    await db_session.commit()

    login = await client.post("/auth/login", json={
        "email": "refresh@test.com",
        "password": "pass",
    })
    refresh_token = login.json()["refresh_token"]

    response = await client.post("/auth/refresh", json={
        "refresh_token": refresh_token,
    })
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_logout(client, db_session):
    user = User(
        email="logout@test.com",
        password_hash=hash_password("pass"),
        role="member",
    )
    db_session.add(user)
    await db_session.commit()

    login = await client.post("/auth/login", json={
        "email": "logout@test.com",
        "password": "pass",
    })
    tokens = login.json()

    response = await client.post(
        "/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == 200

    # Refresh should now fail
    response = await client.post("/auth/refresh", json={
        "refresh_token": tokens["refresh_token"],
    })
    assert response.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_routes/test_auth_routes.py -v`
Expected: FAIL

- [ ] **Step 3: Implement auth_service.py**

```python
# src/app/services/__init__.py
```

```python
# src/app/services/auth_service.py
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key_auth import hash_api_key
from app.auth.jwt_handler import create_access_token, create_refresh_token, decode_token
from app.auth.password import verify_password
from app.models.refresh_token import RefreshToken
from app.models.user import User


async def authenticate_user(
    db: AsyncSession, email: str, password: str
) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or user.password_hash is None:
        return None

    # Brute force protection: check lockout
    if user.lockout_until and user.lockout_until > datetime.now(timezone.utc):
        return None  # Still locked out

    if not verify_password(password, user.password_hash):
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= 5:
            user.lockout_until = datetime.now(timezone.utc) + timedelta(minutes=15)
        await db.commit()
        return None

    # Successful login: reset counters
    user.failed_login_attempts = 0
    user.lockout_until = None
    await db.commit()
    return user


async def create_tokens(
    db: AsyncSession, user: User, ip_address: str | None = None, user_agent: str | None = None
) -> dict[str, str]:
    access_token = create_access_token(user_id=user.id, role=user.role)
    refresh_token_str = create_refresh_token(user_id=user.id)

    token_hash = hash_api_key(refresh_token_str)  # reuse SHA-256
    refresh_token_record = RefreshToken(
        token_hash=token_hash,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(refresh_token_record)
    await db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
    }


async def refresh_tokens(db: AsyncSession, refresh_token_str: str) -> dict[str, str] | None:
    token_hash = hash_api_key(refresh_token_str)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.is_revoked == False,
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    old_token = result.scalar_one_or_none()
    if old_token is None:
        return None

    # Revoke old token
    old_token.is_revoked = True

    # Get user
    user_result = await db.execute(select(User).where(User.id == old_token.user_id))
    user = user_result.scalar_one()

    # Create new tokens
    access_token = create_access_token(user_id=user.id, role=user.role)
    new_refresh_str = create_refresh_token(user_id=user.id)
    new_token_hash = hash_api_key(new_refresh_str)

    new_token = RefreshToken(
        token_hash=new_token_hash,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(new_token)
    old_token.replaced_by = new_token.id
    await db.commit()

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_str,
        "token_type": "bearer",
    }


async def revoke_refresh_token(db: AsyncSession, refresh_token_str: str) -> bool:
    token_hash = hash_api_key(refresh_token_str)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    token = result.scalar_one_or_none()
    if token is None:
        return False
    token.is_revoked = True
    await db.commit()
    return True


async def revoke_all_user_tokens(db: AsyncSession, user_id: uuid.UUID) -> int:
    from sqlalchemy import update
    result = await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.is_revoked == False)
        .values(is_revoked=True)
    )
    await db.commit()
    return result.rowcount
```

- [ ] **Step 4: Implement auth dependencies**

```python
# src/app/auth/dependencies.py
import uuid
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_handler import decode_token
from app.database import get_db
from app.models.user import User
from sqlalchemy import select


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = auth_header.split(" ", 1)[1]
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = uuid.UUID(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.is_blocked:
        raise HTTPException(status_code=401, detail="User not found or blocked")

    return user


def require_role(*roles: str):
    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return dependency
```

- [ ] **Step 5: Implement auth routes**

```python
# src/app/routes/__init__.py
```

```python
# src/app/routes/auth_routes.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.services.auth_service import (
    authenticate_user,
    create_tokens,
    refresh_tokens,
    revoke_all_user_tokens,
    revoke_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await authenticate_user(db, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.is_blocked:
        raise HTTPException(status_code=403, detail="User is blocked")
    return await create_tokens(db, user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    tokens = await refresh_tokens(db, body.refresh_token)
    if tokens is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    return tokens


@router.post("/logout")
async def logout(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    await revoke_refresh_token(db, body.refresh_token)
    return {"status": "ok"}


@router.post("/logout-all")
async def logout_all(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    count = await revoke_all_user_tokens(db, user.id)
    return {"status": "ok", "revoked_count": count}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    # Always return 200 (don't leak whether email exists)
    # In production: send email with reset token
    from app.services.auth_service import create_password_reset_token
    await create_password_reset_token(db, body.email)
    return {"status": "ok", "message": "If the email exists, a reset link has been sent"}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    from app.services.auth_service import reset_password_with_token
    success = await reset_password_with_token(db, body.token, body.new_password)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    return {"status": "ok"}
```

Add to `auth_service.py`:

```python
async def create_password_reset_token(db: AsyncSession, email: str) -> str | None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        return None
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    reset_token = PasswordResetToken(
        token_hash=token_hash,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(reset_token)
    await db.commit()
    return token  # In production, send this via email


async def reset_password_with_token(db: AsyncSession, token: str, new_password: str) -> bool:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.is_used == False,
            PasswordResetToken.expires_at > datetime.now(timezone.utc),
        )
    )
    reset_token = result.scalar_one_or_none()
    if reset_token is None:
        return False
    reset_token.is_used = True
    user = await db.execute(select(User).where(User.id == reset_token.user_id))
    user_obj = user.scalar_one()
    user_obj.password_hash = hash_password(new_password)
    await db.commit()
    return True
```

- [ ] **Step 6: Register auth routes in main.py**

Add to `src/app/main.py`:
```python
from app.routes.auth_routes import router as auth_router
app.include_router(auth_router)
```

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_routes/test_auth_routes.py -v`
Expected: All 5 tests PASS

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: auth service + routes — login, refresh, logout"
```

---

### Task 7: User Management Service + Routes

**Files:**
- Create: `src/app/services/user_service.py`
- Create: `src/app/routes/user_routes.py`
- Test: `tests/test_routes/test_user_routes.py`

- [ ] **Step 1: Write failing test for user CRUD**

```python
# tests/test_routes/test_user_routes.py
from app.models.user import User
from app.auth.password import hash_password
from app.auth.jwt_handler import create_access_token


def _admin_headers(user_id):
    token = create_access_token(user_id=user_id, role="proxy_admin")
    return {"Authorization": f"Bearer {token}"}


async def test_create_user(client, db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()

    response = await client.post(
        "/user/new",
        json={"email": "newuser@test.com", "password": "pass123", "role": "member"},
        headers=_admin_headers(admin.id),
    )
    assert response.status_code == 200
    assert response.json()["email"] == "newuser@test.com"


async def test_list_users(client, db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()

    response = await client.get("/user/list", headers=_admin_headers(admin.id))
    assert response.status_code == 200
    assert len(response.json()) >= 1


async def test_user_info(client, db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()

    response = await client.get(
        f"/user/info/{admin.id}", headers=_admin_headers(admin.id)
    )
    assert response.status_code == 200
    assert response.json()["email"] == "admin@test.com"


async def test_block_user(client, db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    target = User(email="target@test.com", role="member")
    db_session.add_all([admin, target])
    await db_session.commit()

    response = await client.post(
        "/user/block",
        json={"user_id": str(target.id), "blocked": True},
        headers=_admin_headers(admin.id),
    )
    assert response.status_code == 200

    info = await client.get(f"/user/info/{target.id}", headers=_admin_headers(admin.id))
    assert info.json()["is_blocked"] is True


async def test_member_cannot_create_user(client, db_session):
    member = User(email="member@test.com", password_hash=hash_password("pass"), role="member")
    db_session.add(member)
    await db_session.commit()

    token = create_access_token(user_id=member.id, role="member")
    response = await client.post(
        "/user/new",
        json={"email": "other@test.com", "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
```

- [ ] **Step 2: Implement user_service.py**

```python
# src/app/services/user_service.py
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.models.user import User


async def create_user(
    db: AsyncSession,
    email: str,
    password: str | None = None,
    name: str | None = None,
    role: str = "member",
    max_budget: float | None = None,
    metadata: dict | None = None,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password) if password else None,
        name=name,
        role=role,
        max_budget=max_budget,
        metadata_json=metadata,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def list_users(
    db: AsyncSession, page: int = 1, page_size: int = 50
) -> list[User]:
    offset = (page - 1) * page_size
    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(offset).limit(page_size)
    )
    return list(result.scalars().all())


async def update_user(db: AsyncSession, user_id: uuid.UUID, **kwargs) -> User | None:
    user = await get_user(db, user_id)
    if user is None:
        return None
    for key, value in kwargs.items():
        if value is not None and hasattr(user, key):
            setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: uuid.UUID) -> bool:
    user = await get_user(db, user_id)
    if user is None:
        return False
    await db.delete(user)
    await db.commit()
    return True


async def block_user(db: AsyncSession, user_id: uuid.UUID, blocked: bool) -> User | None:
    return await update_user(db, user_id, is_blocked=blocked)
```

- [ ] **Step 3: Implement user_routes.py**

```python
# src/app/routes/user_routes.py
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserBlockRequest, UserCreate, UserResponse, UserUpdate
from app.services.user_service import block_user, create_user, delete_user, get_user, list_users, update_user

router = APIRouter(prefix="/user", tags=["user"])


@router.post("/new", response_model=UserResponse)
async def new_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
):
    user = await create_user(
        db, email=body.email, password=body.password, name=body.name,
        role=body.role, max_budget=body.max_budget, metadata=body.metadata,
    )
    return user


@router.get("/list", response_model=list[UserResponse])
async def user_list(
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
):
    return await list_users(db, page, page_size)


@router.get("/info/{user_id}", response_model=UserResponse)
async def user_info(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
):
    user = await get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/update", response_model=UserResponse)
async def user_update(
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
):
    user = await update_user(
        db, body.user_id, role=body.role, name=body.name,
        max_budget=body.max_budget, is_blocked=body.is_blocked,
        metadata_json=body.metadata,
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/delete")
async def user_delete(
    body: UserUpdate,  # reuse — only needs user_id
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
):
    success = await delete_user(db, body.user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "ok"}


@router.post("/block", response_model=UserResponse)
async def user_block(
    body: UserBlockRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
):
    user = await block_user(db, body.user_id, body.blocked)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user
```

- [ ] **Step 4: Register user routes in main.py**

```python
from app.routes.user_routes import router as user_router
app.include_router(user_router)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_routes/test_user_routes.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: user management — CRUD, block, list with RBAC"
```

---

### Task 8: Organization Management Service + Routes

**Files:**
- Create: `src/app/services/org_service.py`
- Create: `src/app/routes/org_routes.py`
- Test: `tests/test_routes/test_org_routes.py`

Follow the same TDD pattern as Task 7:

- [ ] **Step 1: Write failing tests** for org CRUD + member_add/update/delete + cascade deletion
- [ ] **Step 2: Implement org_service.py** — create, get, list, update, delete, member operations
- [ ] **Step 3: Implement cascade deletion in `delete_org`:**
  - Fetch all teams in org
  - For each team: delete projects, revoke API keys, remove team memberships
  - Delete org memberships
  - Record snapshots in `deleted_teams`, `deleted_keys` tables via `audit_service`
  - Delete the organization
  - All within a single transaction
- [ ] **Step 4: Write tests for cascade:** deleting an org should cascade-delete its teams, projects, and keys
- [ ] **Step 5: Implement org_routes.py** — 8 endpoints matching spec section 5.3
- [ ] **Step 6: Register routes in main.py**
- [ ] **Step 7: Run tests** — `pytest tests/test_routes/test_org_routes.py -v`
- [ ] **Step 8: Commit** — `git commit -m "feat: organization management — CRUD + members + cascade deletion"`

---

### Task 9: Team Management Service + Routes

**Files:**
- Create: `src/app/services/team_service.py`
- Create: `src/app/routes/team_routes.py`
- Test: `tests/test_routes/test_team_routes.py`

Follow the same TDD pattern as Task 7:

- [ ] **Step 1: Write failing tests** for team CRUD + member_add/update/delete + reset_budget + cascade deletion
- [ ] **Step 2: Implement team_service.py** — create, get, list, update, delete, member operations, reset_budget
- [ ] **Step 3: Implement cascade deletion in `delete_team`:**
  - Delete all projects in team
  - Revoke all API keys scoped to team (record in `deleted_keys`)
  - Remove team memberships
  - Record snapshot in `deleted_teams`
  - Delete the team
- [ ] **Step 4: Implement team_routes.py** — 9 endpoints matching spec section 5.2
- [ ] **Step 5: Register routes in main.py**
- [ ] **Step 6: Run tests** — `pytest tests/test_routes/test_team_routes.py -v`
- [ ] **Step 7: Commit** — `git commit -m "feat: team management — CRUD + members + cascade + budget reset"`

---

### Task 10: API Key Management Service + Routes

**Files:**
- Create: `src/app/services/key_service.py`
- Create: `src/app/routes/key_routes.py`
- Test: `tests/test_routes/test_key_routes.py`

- [ ] **Step 1: Write failing tests for key generation and basic CRUD**

```python
# tests/test_routes/test_key_routes.py
async def test_generate_key(client, db_session):
    # Setup admin user, login, then:
    response = await client.post("/key/generate", json={
        "key_alias": "my-prod-key",
        "allowed_models": ["gpt-4", "claude-*"],
        "max_budget": 50.0,
    }, headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["key"].startswith("sk-")
    assert data["key_prefix"] == data["key"][:11]
    # Key is only returned once — verify it's not in subsequent /key/info calls
```

- [ ] **Step 2: Write failing tests for key rotation with grace period**

```python
async def test_rotate_key(client, db_session):
    # Generate a key, then rotate
    rotate_response = await client.post("/key/rotate", json={
        "key_id": str(key_id),
        "grace_period_hours": 2,
    }, headers=admin_headers)
    assert rotate_response.status_code == 200
    new_key = rotate_response.json()["key"]
    assert new_key != original_key

    # Both old and new key should work during grace period
    old_response = await client.get("/health", headers={"Authorization": f"Bearer {original_key}"})
    new_response = await client.get("/health", headers={"Authorization": f"Bearer {new_key}"})
    # Both should authenticate successfully


async def test_reactivate_expired_key(client, db_session):
    # Create key with past expires_at, then reactivate
    response = await client.post("/key/reactivate", json={
        "key_id": str(key_id),
    }, headers=admin_headers)
    assert response.status_code == 200
    # Key should now work again (expires_at cleared)


async def test_reset_spend(client, db_session):
    # Create key with accumulated spend, then reset
    response = await client.post("/key/reset_spend", json={
        "key_id": str(key_id),
    }, headers=admin_headers)
    assert response.status_code == 200
    info = await client.get(f"/key/info/{key_id}", headers=admin_headers)
    assert info.json()["spend"] == 0.0
```

- [ ] **Step 3: Implement key_service.py**

Key functions:
- `generate_key(db, user_id, ...)` → creates ApiKey, returns plaintext key (only time it's available)
- `rotate_key(db, key_id, grace_period_hours)` → stores current hash in `previous_key_hash`, sets `grace_period_expires_at`, generates new key
- `authenticate_by_key(db, raw_key)` → hash → lookup by `api_key_hash` OR `previous_key_hash` (if within grace period)
- `reactivate_key(db, key_id)` → clears `expires_at`, sets `is_blocked=False`
- `reset_spend(db, key_id)` → sets `spend=0.0`
- `block_key(db, key_id, blocked)` → sets `is_blocked`
- `bulk_update(db, key_ids, **fields)` → batch update via single SQL statement
- `delete_key(db, key_id, deleted_by)` → records in `deleted_keys`, then deletes

- [ ] **Step 4: Implement key_routes.py** — 10 endpoints matching spec section 4
- [ ] **Step 5: Register routes in main.py**
- [ ] **Step 6: Run tests** — `pytest tests/test_routes/test_key_routes.py -v`
- [ ] **Step 7: Commit** — `git commit -m "feat: API key management — generate, rotate, block, bulk update"`

---

### Task 11: Budget Management Service + Routes

**Files:**
- Create: `src/app/services/budget_service.py`
- Create: `src/app/routes/budget_routes.py`
- Test: `tests/test_routes/test_budget_routes.py`

- [ ] **Step 1: Write failing tests** for budget CRUD
- [ ] **Step 2: Implement budget_service.py**
- [ ] **Step 3: Implement budget_routes.py** — 4 endpoints matching spec section 5.4
- [ ] **Step 4: Register routes in main.py**
- [ ] **Step 5: Run tests** — `pytest tests/test_routes/test_budget_routes.py -v`
- [ ] **Step 6: Commit** — `git commit -m "feat: budget management — CRUD with entity linking"`

---

### Task 12: Auth Middleware — API Key Authentication

**Files:**
- Create: `src/app/auth/middleware.py`
- Modify: `src/app/auth/dependencies.py` — add API key auth path
- Test: `tests/test_auth/test_middleware.py`

- [ ] **Step 1: Write failing test for API key auth via Bearer header**

```python
# tests/test_auth/test_middleware.py
from app.models.user import User
from app.models.api_key import ApiKey
from app.auth.api_key_auth import generate_api_key, hash_api_key, get_key_prefix


async def test_api_key_auth(client, db_session):
    user = User(email="dev@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=user.id,
    )
    db_session.add(api_key)
    await db_session.commit()

    response = await client.get(
        f"/user/info/{user.id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "dev@test.com"
```

- [ ] **Step 2: Update get_current_user to detect sk- prefix and authenticate via API key**
- [ ] **Step 3: Run tests** — `pytest tests/test_auth/test_middleware.py -v`
- [ ] **Step 4: Commit** — `git commit -m "feat: API key authentication via Bearer header"`

---

### Task 13: RBAC Middleware — Model Access + Route Permissions

**Files:**
- Modify: `src/app/auth/dependencies.py` — add model_access_check, wildcard matching
- Create: `src/app/services/permission_service.py`
- Test: `tests/test_auth/test_rbac.py`

- [ ] **Step 1: Write failing test for wildcard model matching**

```python
# tests/test_auth/test_rbac.py
from app.services.permission_service import model_matches_pattern


def test_exact_match():
    assert model_matches_pattern("gpt-4", "gpt-4") is True
    assert model_matches_pattern("gpt-4", "gpt-3.5") is False


def test_wildcard_match():
    assert model_matches_pattern("claude-3-opus", "claude-*") is True
    assert model_matches_pattern("claude-3-sonnet", "claude-*") is True
    assert model_matches_pattern("gpt-4", "claude-*") is False


def test_star_matches_all():
    assert model_matches_pattern("anything", "*") is True


def test_null_inherits():
    # null allowed_models means "inherit" — separate logic
    pass
```

- [ ] **Step 2: Implement permission_service.py** with model matching + access resolution chain
- [ ] **Step 3: Write test for role-based route access** (org_admin can't access global endpoints)
- [ ] **Step 4: Run tests** — `pytest tests/test_auth/test_rbac.py -v`
- [ ] **Step 5: Commit** — `git commit -m "feat: RBAC — model access resolution with wildcard matching"`

---

### Task 14: Rate Limiting Service

**Files:**
- Create: `src/app/services/rate_limiter.py`
- Test: `tests/test_services/test_rate_limiter.py`

- [ ] **Step 1: Write failing test for sliding window rate limit**

```python
# tests/test_services/test_rate_limiter.py
from app.services.rate_limiter import SlidingWindowRateLimiter


async def test_under_limit():
    limiter = SlidingWindowRateLimiter()  # in-memory for tests
    allowed = await limiter.check_rate_limit("test_key", limit=10, window_seconds=60)
    assert allowed is True


async def test_over_limit():
    limiter = SlidingWindowRateLimiter()
    for _ in range(10):
        await limiter.check_rate_limit("test_key", limit=10, window_seconds=60)
    allowed = await limiter.check_rate_limit("test_key", limit=10, window_seconds=60)
    assert allowed is False
```

- [ ] **Step 2: Implement in-memory sliding window** (Redis version can be swapped in later)
- [ ] **Step 3: Run tests** — `pytest tests/test_services/test_rate_limiter.py -v`
- [ ] **Step 4: Commit** — `git commit -m "feat: sliding window rate limiter — RPM/TPM enforcement"`

---

### Task 15: Spend Tracking Service

**Files:**
- Create: `src/app/services/spend_service.py`
- Test: `tests/test_services/test_spend_service.py`

- [ ] **Step 1: Write failing test for spend logging + daily aggregation**
- [ ] **Step 2: Implement spend_service.py** — log_spend (creates SpendLog + upserts daily aggregates)
- [ ] **Step 3: Run tests** — `pytest tests/test_services/test_spend_service.py -v`
- [ ] **Step 4: Commit** — `git commit -m "feat: spend tracking — per-request logging + daily aggregates"`

---

### Task 16: Audit Logging Service

**Files:**
- Create: `src/app/services/audit_service.py`
- Test: `tests/test_services/test_audit_service.py`

- [ ] **Step 1: Write failing test for audit log creation**
- [ ] **Step 2: Implement audit_service.py** — log_action, log_deletion (writes to deleted_* tables)
- [ ] **Step 3: Integrate audit logging** into user, team, org, key services (add audit calls to create/update/delete operations)
- [ ] **Step 4: Run tests** — `pytest tests/test_services/test_audit_service.py -v`
- [ ] **Step 5: Commit** — `git commit -m "feat: audit logging — action tracking + deletion history"`

---

### Task 17: SSO / OAuth2 Service + Routes

**Files:**
- Create: `src/app/services/sso_service.py`
- Create: `src/app/routes/sso_routes.py`
- Test: `tests/test_routes/test_sso_routes.py`

- [ ] **Step 1: Write failing tests** for SSO config CRUD
- [ ] **Step 2: Implement sso_service.py** — create/get/delete SSO config with encrypted client_secret
- [ ] **Step 3: Implement sso_routes.py** — 5 endpoints matching spec section 7.4 (authorize, callback, config CRUD)
- [ ] **Step 4: Register routes in main.py**
- [ ] **Step 5: Run tests** — `pytest tests/test_routes/test_sso_routes.py -v`
- [ ] **Step 6: Commit** — `git commit -m "feat: SSO — config management + OAuth2 authorize/callback"`

---

### Task 18: Alembic Migration Setup

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/` (auto-generated)

- [ ] **Step 1: Initialize Alembic**

```bash
cd ~/dev/cmsandiga/makoto_lite_llm
alembic init alembic
```

- [ ] **Step 2: Configure alembic/env.py** to use SQLAlchemy models and async engine
- [ ] **Step 3: Generate initial migration**

```bash
alembic revision --autogenerate -m "initial schema"
```

- [ ] **Step 4: Test migration applies cleanly** against a fresh PostgreSQL database
- [ ] **Step 5: Commit** — `git commit -m "feat: Alembic migrations — initial schema with all tables"`

---

### Task 19: Integration Test — Full Auth Flow

**Files:**
- Test: `tests/test_integration/test_full_auth_flow.py`

- [ ] **Step 1: Write end-to-end test**

```python
# tests/test_integration/test_full_auth_flow.py
async def test_full_flow(client, db_session):
    """
    1. Create admin user
    2. Login as admin
    3. Create organization
    4. Create team in org
    5. Add member to team
    6. Generate API key for member
    7. Use API key to authenticate
    8. Rotate API key
    9. Block user
    10. Verify blocked user can't authenticate
    """
    # ... complete flow test
```

- [ ] **Step 2: Run integration test** — `pytest tests/test_integration/ -v`
- [ ] **Step 3: Run full test suite** — `pytest -v`
- [ ] **Step 4: Commit** — `git commit -m "test: integration test — full auth lifecycle flow"`

---

## Task Summary

| Task | Component | Endpoints | Tests |
|------|-----------|-----------|-------|
| 1 | Project scaffolding | /health | 1 |
| 2 | Core models (org, team, user, budget) | — | 5 |
| 3 | Auth models (api_key, audit, spend) | — | 3 |
| 4 | Auth core (password, JWT, API key, crypto) | — | 8 |
| 5 | Pydantic schemas | — | — |
| 6 | Auth routes (login, refresh, logout) | 6 | 5 |
| 7 | User management | 6 | 5 |
| 8 | Organization management | 8 | 5+ |
| 9 | Team management | 9 | 5+ |
| 10 | API Key management | 10 | 8+ |
| 11 | Budget management | 4 | 3+ |
| 12 | API Key auth middleware | — | 2+ |
| 13 | RBAC + model access | — | 5+ |
| 14 | Rate limiting | — | 3+ |
| 15 | Spend tracking | — | 3+ |
| 16 | Audit logging | — | 3+ |
| 17 | SSO / OAuth2 | 5 | 3+ |
| 18 | Alembic migrations | — | 1 |
| 19 | Integration test | — | 1 |

**Total: ~48 endpoints, ~70+ tests, 19 tasks**
