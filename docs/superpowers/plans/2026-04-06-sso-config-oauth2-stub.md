# SSO Config + OAuth2 Stub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-org SSO configuration management with encrypted client secrets, an OAuth2 authorize redirect, and a callback stub (501) — laying the interface for real OIDC providers later.

**Architecture:** Three layers following existing hexagonal pattern: `sso_service.py` (business logic, encrypts secrets, talks to DB), `sso_routes.py` (HTTP border, auth checks, schema conversion), and `wire_in/sso.py` + `wire_out/sso.py` (request/response contracts). The `SSOConfig` model already exists. OAuth2 state is stored in a simple in-memory dict with TTL expiry.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, AES-256-GCM (`app.auth.crypto`), Pydantic v2, pytest + httpx `AsyncClient` + testcontainers

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/app/schemas/wire_in/sso.py` | `SSOConfigCreate` request schema |
| Create | `src/app/schemas/wire_out/sso.py` | `SSOConfigResponse` response schema |
| Create | `src/app/services/sso_service.py` | Create/get/delete SSO config (encrypts secret), authorize URL builder, state store |
| Create | `src/app/routes/sso_routes.py` | 5 HTTP endpoints (3 CRUD + authorize + callback) |
| Modify | `src/app/main.py` | Register `sso_router` |
| Create | `tests/test_services/test_sso_service.py` | Unit tests for service layer |
| Create | `tests/test_routes/test_sso_routes.py` | Integration tests for route layer |

---

### Task 1: Wire Schemas (wire_in + wire_out)

**Files:**
- Create: `src/app/schemas/wire_in/sso.py`
- Create: `src/app/schemas/wire_out/sso.py`

- [ ] **Step 1: Create `wire_in/sso.py`**

```python
# src/app/schemas/wire_in/sso.py
import uuid

from pydantic import BaseModel


class SSOConfigCreate(BaseModel):
    org_id: uuid.UUID
    provider: str  # "google", "azure_ad", "okta", "oidc"
    client_id: str
    client_secret: str  # plaintext — service encrypts before storage
    issuer_url: str
    allowed_domains: list[str] | None = None
    group_to_team_mapping: dict | None = None
    auto_create_user: bool = True
    default_role: str = "member"
```

- [ ] **Step 2: Create `wire_out/sso.py`**

```python
# src/app/schemas/wire_out/sso.py
import uuid
from datetime import datetime

from pydantic import BaseModel


class SSOConfigResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    provider: str
    client_id: str
    client_secret: str  # always "***" — set by route, never from ORM
    issuer_url: str
    allowed_domains: list | None
    group_to_team_mapping: dict | None
    auto_create_user: bool
    default_role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 3: Commit**

```bash
git add src/app/schemas/wire_in/sso.py src/app/schemas/wire_out/sso.py
git commit -m "feat(sso): add wire_in and wire_out schemas for SSO config"
```

---

### Task 2: SSO Service — `create_sso_config`

**Files:**
- Create: `src/app/services/sso_service.py`
- Create: `tests/test_services/test_sso_service.py`

- [ ] **Step 1: Write the failing test for create**

```python
# tests/test_services/test_sso_service.py
import pytest
from uuid_extensions import uuid7

from app.auth.crypto import decrypt
from app.models.organization import Organization
from app.services.sso_service import create_sso_config


async def _create_org(db_session) -> Organization:
    org = Organization(name="TestOrg", slug=f"test-{uuid7()}")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


async def test_create_sso_config(db_session):
    org = await _create_org(db_session)
    config = await create_sso_config(
        db_session,
        org_id=org.id,
        provider="google",
        client_id="google-client-123",
        client_secret="super-secret-value",
        issuer_url="https://accounts.google.com",
        allowed_domains=["acme.com"],
    )
    assert config.org_id == org.id
    assert config.provider == "google"
    assert config.client_id == "google-client-123"
    # client_secret_encrypted is NOT the plaintext
    assert config.client_secret_encrypted != "super-secret-value"
    # but it decrypts back to the original
    assert decrypt(config.client_secret_encrypted) == "super-secret-value"
    assert config.allowed_domains == ["acme.com"]
    assert config.auto_create_user is True
    assert config.default_role == "member"
    assert config.is_active is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_services/test_sso_service.py::test_create_sso_config -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.sso_service'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/app/services/sso_service.py
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import encrypt
from app.exceptions import DuplicateError
from app.models.sso_config import SSOConfig


async def create_sso_config(
    db: AsyncSession,
    org_id: uuid.UUID,
    provider: str,
    client_id: str,
    client_secret: str,
    issuer_url: str,
    allowed_domains: list[str] | None = None,
    group_to_team_mapping: dict | None = None,
    auto_create_user: bool = True,
    default_role: str = "member",
) -> SSOConfig:
    """Create an SSO config. Encrypts client_secret before storage.

    Raises DuplicateError if the org already has a config.
    """
    config = SSOConfig(
        org_id=org_id,
        provider=provider,
        client_id=client_id,
        client_secret_encrypted=encrypt(client_secret),
        issuer_url=issuer_url,
        allowed_domains=allowed_domains,
        group_to_team_mapping=group_to_team_mapping,
        auto_create_user=auto_create_user,
        default_role=default_role,
    )
    db.add(config)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise DuplicateError("SSO config already exists for this organization")
    await db.commit()
    await db.refresh(config)
    return config
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_services/test_sso_service.py::test_create_sso_config -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/services/sso_service.py tests/test_services/test_sso_service.py
git commit -m "feat(sso): create_sso_config service with encryption"
```

---

### Task 3: SSO Service — `create_sso_config` duplicate org (409)

**Files:**
- Modify: `tests/test_services/test_sso_service.py`

- [ ] **Step 1: Write the failing test for duplicate**

Add to `tests/test_services/test_sso_service.py`:

```python
from app.exceptions import DuplicateError


async def test_create_sso_config_duplicate_org(db_session):
    org = await _create_org(db_session)
    await create_sso_config(
        db_session,
        org_id=org.id,
        provider="google",
        client_id="id1",
        client_secret="secret1",
        issuer_url="https://accounts.google.com",
    )
    with pytest.raises(DuplicateError):
        await create_sso_config(
            db_session,
            org_id=org.id,
            provider="okta",
            client_id="id2",
            client_secret="secret2",
            issuer_url="https://okta.example.com",
        )
```

- [ ] **Step 2: Run test to verify it passes** (implementation already handles this)

Run: `uv run pytest tests/test_services/test_sso_service.py::test_create_sso_config_duplicate_org -v`
Expected: PASS — the `IntegrityError` catch in `create_sso_config` handles the unique constraint on `org_id`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_services/test_sso_service.py
git commit -m "test(sso): duplicate org config raises DuplicateError"
```

---

### Task 4: SSO Service — `get_sso_config` and `delete_sso_config`

**Files:**
- Modify: `src/app/services/sso_service.py`
- Modify: `tests/test_services/test_sso_service.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_services/test_sso_service.py`:

```python
from app.services.sso_service import get_sso_config, delete_sso_config


async def test_get_sso_config(db_session):
    org = await _create_org(db_session)
    await create_sso_config(
        db_session,
        org_id=org.id,
        provider="okta",
        client_id="okta-id",
        client_secret="okta-secret",
        issuer_url="https://okta.example.com",
    )
    config = await get_sso_config(db_session, org.id)
    assert config is not None
    assert config.provider == "okta"
    assert config.client_id == "okta-id"


async def test_get_sso_config_not_found(db_session):
    config = await get_sso_config(db_session, uuid7())
    assert config is None


async def test_delete_sso_config(db_session):
    org = await _create_org(db_session)
    await create_sso_config(
        db_session,
        org_id=org.id,
        provider="google",
        client_id="gid",
        client_secret="gsecret",
        issuer_url="https://accounts.google.com",
    )
    result = await delete_sso_config(db_session, org.id)
    assert result is True
    # Verify it's gone
    config = await get_sso_config(db_session, org.id)
    assert config is None


async def test_delete_sso_config_not_found(db_session):
    result = await delete_sso_config(db_session, uuid7())
    assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_services/test_sso_service.py -k "get_sso_config or delete_sso_config" -v`
Expected: FAIL — `ImportError: cannot import name 'get_sso_config'`

- [ ] **Step 3: Implement `get_sso_config` and `delete_sso_config`**

Add to `src/app/services/sso_service.py`:

```python
from sqlalchemy import delete, select


async def get_sso_config(db: AsyncSession, org_id: uuid.UUID) -> SSOConfig | None:
    """Return the SSO config for an org, or None."""
    result = await db.execute(
        select(SSOConfig).where(SSOConfig.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def delete_sso_config(db: AsyncSession, org_id: uuid.UUID) -> bool:
    """Delete the SSO config for an org. Returns True if deleted, False if not found."""
    result = await db.execute(
        delete(SSOConfig).where(SSOConfig.org_id == org_id)
    )
    await db.commit()
    return result.rowcount > 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_services/test_sso_service.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/services/sso_service.py tests/test_services/test_sso_service.py
git commit -m "feat(sso): get and delete SSO config service functions"
```

---

### Task 5: SSO Service — OAuth2 State Store + Authorize URL Builder

**Files:**
- Modify: `src/app/services/sso_service.py`
- Modify: `tests/test_services/test_sso_service.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_services/test_sso_service.py`:

```python
from app.services.sso_service import (
    build_authorize_url,
    validate_state,
    _state_store,
)


async def test_build_authorize_url(db_session):
    org = await _create_org(db_session)
    await create_sso_config(
        db_session,
        org_id=org.id,
        provider="google",
        client_id="goog-123",
        client_secret="secret",
        issuer_url="https://accounts.google.com",
    )
    url, state = await build_authorize_url(
        db_session,
        org_id=org.id,
        callback_url="http://localhost:8000/sso/callback",
    )
    assert "https://accounts.google.com/authorize" in url
    assert "client_id=goog-123" in url
    assert "redirect_uri=http" in url
    assert "response_type=code" in url
    assert "scope=openid+email+profile" in url or "scope=openid%20email%20profile" in url
    assert f"state={state}" in url
    assert len(state) > 16


async def test_build_authorize_url_org_not_found(db_session):
    result = await build_authorize_url(
        db_session,
        org_id=uuid7(),
        callback_url="http://localhost:8000/sso/callback",
    )
    assert result is None


async def test_validate_state_valid():
    # Manually insert a state into the store
    _state_store["test-state-123"] = True
    assert validate_state("test-state-123") is True
    # Second call should fail — state is consumed
    assert validate_state("test-state-123") is False


async def test_validate_state_invalid():
    assert validate_state("nonexistent-state") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_services/test_sso_service.py -k "authorize_url or validate_state" -v`
Expected: FAIL — `ImportError: cannot import name 'build_authorize_url'`

- [ ] **Step 3: Implement authorize URL builder and state store**

Add to `src/app/services/sso_service.py`:

```python
import secrets
from urllib.parse import urlencode

from cachetools import TTLCache

# In-memory state store with 10-minute TTL for CSRF protection.
# Key: state token, Value: True (just needs to exist).
_state_store: TTLCache = TTLCache(maxsize=1024, ttl=600)


async def build_authorize_url(
    db: AsyncSession,
    org_id: uuid.UUID,
    callback_url: str,
) -> tuple[str, str] | None:
    """Build the OAuth2 authorize redirect URL for an org's SSO config.

    Returns (url, state) or None if no config found.
    """
    config = await get_sso_config(db, org_id)
    if config is None:
        return None

    state = secrets.token_urlsafe(32)
    _state_store[state] = True

    params = urlencode({
        "client_id": config.client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
    })
    url = f"{config.issuer_url}/authorize?{params}"
    return url, state


def validate_state(state: str) -> bool:
    """Validate and consume an OAuth2 state token. Returns True if valid."""
    return _state_store.pop(state, None) is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_services/test_sso_service.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/services/sso_service.py tests/test_services/test_sso_service.py
git commit -m "feat(sso): OAuth2 authorize URL builder + state store"
```

---

### Task 6: SSO Routes — CRUD Endpoints (POST, GET, DELETE)

**Files:**
- Create: `src/app/routes/sso_routes.py`
- Modify: `src/app/main.py`
- Create: `tests/test_routes/test_sso_routes.py`

- [ ] **Step 1: Write the failing route tests**

```python
# tests/test_routes/test_sso_routes.py
from uuid_extensions import uuid7

from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.models.organization import Organization
from app.models.user import User


def _admin_headers(user_id):
    token = create_access_token(user_id=user_id, role="proxy_admin")
    return {"Authorization": f"Bearer {token}"}


def _member_headers(user_id):
    token = create_access_token(user_id=user_id, role="member")
    return {"Authorization": f"Bearer {token}"}


async def _setup(db_session):
    """Create an admin user and an org. Returns (admin, org)."""
    admin = User(email=f"admin-{uuid7()}@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    org = Organization(name="SSO Org", slug=f"sso-{uuid7()}")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(admin)
    await db_session.refresh(org)
    return admin, org


# ========== POST /sso/config ==========


async def test_create_sso_config_route(client, db_session):
    admin, org = await _setup(db_session)
    response = await client.post(
        "/sso/config",
        json={
            "org_id": str(org.id),
            "provider": "google",
            "client_id": "goog-123",
            "client_secret": "my-secret",
            "issuer_url": "https://accounts.google.com",
            "allowed_domains": ["acme.com"],
        },
        headers=_admin_headers(admin.id),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["org_id"] == str(org.id)
    assert data["provider"] == "google"
    assert data["client_id"] == "goog-123"
    assert data["client_secret"] == "***"  # masked
    assert data["issuer_url"] == "https://accounts.google.com"
    assert data["allowed_domains"] == ["acme.com"]
    assert data["is_active"] is True


async def test_create_sso_config_duplicate(client, db_session):
    admin, org = await _setup(db_session)
    headers = _admin_headers(admin.id)
    payload = {
        "org_id": str(org.id),
        "provider": "google",
        "client_id": "id1",
        "client_secret": "secret1",
        "issuer_url": "https://accounts.google.com",
    }
    await client.post("/sso/config", json=payload, headers=headers)
    response = await client.post("/sso/config", json=payload, headers=headers)
    assert response.status_code == 409


async def test_create_sso_config_non_admin(client, db_session):
    member = User(email=f"member-{uuid7()}@test.com", password_hash=hash_password("pass"), role="member")
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    response = await client.post(
        "/sso/config",
        json={
            "org_id": str(uuid7()),
            "provider": "google",
            "client_id": "id",
            "client_secret": "secret",
            "issuer_url": "https://example.com",
        },
        headers=_member_headers(member.id),
    )
    assert response.status_code == 403


# ========== GET /sso/config/{org_id} ==========


async def test_get_sso_config_route(client, db_session):
    admin, org = await _setup(db_session)
    headers = _admin_headers(admin.id)
    await client.post(
        "/sso/config",
        json={
            "org_id": str(org.id),
            "provider": "okta",
            "client_id": "okta-id",
            "client_secret": "okta-secret",
            "issuer_url": "https://okta.example.com",
        },
        headers=headers,
    )
    response = await client.get(f"/sso/config/{org.id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "okta"
    assert data["client_secret"] == "***"


async def test_get_sso_config_not_found(client, db_session):
    admin, _ = await _setup(db_session)
    response = await client.get(
        f"/sso/config/{uuid7()}", headers=_admin_headers(admin.id)
    )
    assert response.status_code == 404


# ========== DELETE /sso/config/{org_id} ==========


async def test_delete_sso_config_route(client, db_session):
    admin, org = await _setup(db_session)
    headers = _admin_headers(admin.id)
    await client.post(
        "/sso/config",
        json={
            "org_id": str(org.id),
            "provider": "google",
            "client_id": "gid",
            "client_secret": "gsecret",
            "issuer_url": "https://accounts.google.com",
        },
        headers=headers,
    )
    response = await client.delete(f"/sso/config/{org.id}", headers=headers)
    assert response.status_code == 204

    # Verify it's gone
    get_resp = await client.get(f"/sso/config/{org.id}", headers=headers)
    assert get_resp.status_code == 404


async def test_delete_sso_config_not_found(client, db_session):
    admin, _ = await _setup(db_session)
    response = await client.delete(
        f"/sso/config/{uuid7()}", headers=_admin_headers(admin.id)
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_routes/test_sso_routes.py -v`
Expected: FAIL — 404s everywhere because routes don't exist yet

- [ ] **Step 3: Implement SSO routes**

```python
# src/app/routes/sso_routes.py
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.database import get_db
from app.exceptions import DuplicateError
from app.models.user import User
from app.schemas.wire_in.sso import SSOConfigCreate
from app.schemas.wire_out.sso import SSOConfigResponse
from app.services.sso_service import (
    create_sso_config,
    delete_sso_config,
    get_sso_config,
)

router = APIRouter(prefix="/sso", tags=["sso"])


def _mask_response(config) -> SSOConfigResponse:
    """Convert ORM model to response with client_secret masked."""
    resp = SSOConfigResponse.model_validate(config)
    resp.client_secret = "***"
    return resp


# ========== POST /sso/config — create ==========


@router.post("/config", status_code=201)
async def create(
    body: SSOConfigCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> SSOConfigResponse:
    try:
        config = await create_sso_config(
            db,
            org_id=body.org_id,
            provider=body.provider,
            client_id=body.client_id,
            client_secret=body.client_secret,
            issuer_url=body.issuer_url,
            allowed_domains=body.allowed_domains,
            group_to_team_mapping=body.group_to_team_mapping,
            auto_create_user=body.auto_create_user,
            default_role=body.default_role,
        )
    except DuplicateError as e:
        raise HTTPException(status_code=409, detail=e.detail)
    return _mask_response(config)


# ========== GET /sso/config/{org_id} — read ==========


@router.get("/config/{org_id}")
async def get_one(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> SSOConfigResponse:
    config = await get_sso_config(db, org_id)
    if config is None:
        raise HTTPException(status_code=404, detail="SSO config not found")
    return _mask_response(config)


# ========== DELETE /sso/config/{org_id} — delete ==========


@router.delete("/config/{org_id}", status_code=204)
async def delete_config(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> None:
    deleted = await delete_sso_config(db, org_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="SSO config not found")
```

- [ ] **Step 4: Register the router in `main.py`**

Add to `src/app/main.py`:

```python
from app.routes.sso_routes import router as sso_router
```

And add after the existing `include_router` calls:

```python
app.include_router(sso_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_routes/test_sso_routes.py -v`
Expected: All 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/routes/sso_routes.py src/app/main.py tests/test_routes/test_sso_routes.py
git commit -m "feat(sso): CRUD routes for SSO config with secret masking"
```

---

### Task 7: SSO Routes — OAuth2 Authorize Redirect

**Files:**
- Modify: `src/app/routes/sso_routes.py`
- Modify: `tests/test_routes/test_sso_routes.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_routes/test_sso_routes.py`:

```python
# ========== GET /sso/authorize ==========


async def test_authorize_redirect(client, db_session):
    admin, org = await _setup(db_session)
    headers = _admin_headers(admin.id)
    await client.post(
        "/sso/config",
        json={
            "org_id": str(org.id),
            "provider": "google",
            "client_id": "goog-123",
            "client_secret": "secret",
            "issuer_url": "https://accounts.google.com",
        },
        headers=headers,
    )
    # authorize is public — no auth header needed
    response = await client.get(
        f"/sso/authorize?org_id={org.id}",
        follow_redirects=False,
    )
    assert response.status_code == 307
    location = response.headers["location"]
    assert "https://accounts.google.com/authorize" in location
    assert "client_id=goog-123" in location
    assert "response_type=code" in location


async def test_authorize_org_not_found(client, db_session):
    response = await client.get(
        f"/sso/authorize?org_id={uuid7()}",
        follow_redirects=False,
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_routes/test_sso_routes.py -k "authorize" -v`
Expected: FAIL — 404 (route doesn't exist) or 405

- [ ] **Step 3: Implement authorize endpoint**

Add to `src/app/routes/sso_routes.py`:

```python
from fastapi import Query
from fastapi.responses import RedirectResponse

from app.services.sso_service import build_authorize_url


# ========== GET /sso/authorize — start OAuth2 flow ==========


@router.get("/authorize")
async def authorize(
    org_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    callback_url = f"{settings.base_url}/sso/callback"
    result = await build_authorize_url(db, org_id=org_id, callback_url=callback_url)
    if result is None:
        raise HTTPException(status_code=404, detail="SSO config not found for this organization")
    url, _state = result
    return RedirectResponse(url=url, status_code=307)
```

Also add the import at the top of `sso_routes.py`:

```python
from app.config import settings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_routes/test_sso_routes.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/routes/sso_routes.py tests/test_routes/test_sso_routes.py
git commit -m "feat(sso): OAuth2 authorize redirect endpoint"
```

---

### Task 8: SSO Routes — OAuth2 Callback Stub (501)

**Files:**
- Modify: `src/app/routes/sso_routes.py`
- Modify: `tests/test_routes/test_sso_routes.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_routes/test_sso_routes.py`:

```python
# ========== GET /sso/callback ==========

from app.services.sso_service import _state_store


async def test_callback_valid_state(client, db_session):
    # Manually add a state to simulate an authorize flow
    _state_store["valid-test-state"] = True
    response = await client.get("/sso/callback?code=authcode123&state=valid-test-state")
    assert response.status_code == 501
    assert "not yet implemented" in response.json()["detail"].lower()


async def test_callback_invalid_state(client, db_session):
    response = await client.get("/sso/callback?code=authcode123&state=bogus-state")
    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()


async def test_callback_missing_params(client, db_session):
    response = await client.get("/sso/callback")
    assert response.status_code == 422  # FastAPI validation error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_routes/test_sso_routes.py -k "callback" -v`
Expected: FAIL — 404 (route doesn't exist)

- [ ] **Step 3: Implement callback endpoint**

Add to `src/app/routes/sso_routes.py`:

```python
from app.services.sso_service import validate_state


# ========== GET /sso/callback — stub ==========


@router.get("/callback")
async def callback(
    code: str = Query(...),
    state: str = Query(...),
) -> None:
    if not validate_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter")
    raise HTTPException(status_code=501, detail="OIDC token exchange not yet implemented")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_routes/test_sso_routes.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/routes/sso_routes.py tests/test_routes/test_sso_routes.py
git commit -m "feat(sso): OAuth2 callback stub (501) with state validation"
```

---

### Task 9: Full Test Suite Verification

**Files:** None (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: All 125+ tests PASS (113 existing + 12 new)

- [ ] **Step 2: Run linting**

Run: `ruff check . && ruff format --check .`
Expected: No errors

- [ ] **Step 3: Fix any issues found**

If linting reports issues, fix them and re-run.

- [ ] **Step 4: Final commit (if any lint fixes)**

```bash
git add -u
git commit -m "style(sso): lint fixes"
```

---

## Spec Coverage Checklist

| Spec Requirement | Task |
|-----------------|------|
| SSO config CRUD (create, read, delete) | Tasks 2–4 (service), Task 6 (routes) |
| `client_secret` encrypted at rest via AES-256-GCM | Task 2 (`encrypt()` call) |
| `client_secret` masked in API responses | Task 6 (`_mask_response`) |
| OAuth2 authorize endpoint (redirect) | Task 5 (service), Task 7 (route) |
| OAuth2 callback stub (501) | Task 5 (state store), Task 8 (route) |
| CSRF state parameter | Task 5 (TTL cache store + validate) |
| Config CRUD restricted to `proxy_admin` | Task 6 (`require_role("proxy_admin")`) |
| Authorize/callback are public (no auth) | Tasks 7–8 (no `Depends(get_current_user)`) |
| Duplicate org config → 409 | Task 3 (service), Task 6 (route) |
| Non-admin cannot create → 403 | Task 6 (test) |

---

## Execution Log

**Completed:** 2026-04-14 — PR #12 merged to main

| Task | Commit | Status |
|------|--------|--------|
| 1. Wire Schemas | `317cbcc` | Done |
| 2. create_sso_config | `8edaf62` | Done |
| 3. Duplicate org test | `8960814` | Done |
| 4. get + delete | `3da5205` | Done |
| 5. OAuth2 state + URL | `6145e2b` | Done |
| 6–8. All routes | `a027585` | Done (combined into single commit) |
| 9. Lint fixes | `b54df7b` | Done |

**Final stats:** 22 new tests (10 service + 12 route), 135 total passing

### Implementation Notes

- `SSOConfigResponse` needed a `model_validator(mode="before")` to map ORM's `client_secret_encrypted` → `client_secret = "***"` — plan didn't anticipate the field name mismatch between ORM and schema
- `config.py` gained `base_url: str = "http://localhost:8000"` for the authorize redirect callback URL
- B008 ruff warnings (Depends in defaults) are pre-existing across all route files — standard FastAPI pattern, not fixed

### Testing Decision: Real OIDC (future)

When implementing real OIDC token exchange (replacing the 501 stub), use **both** testing strategies:

1. **`respx`** (httpx mock) — fast service-layer tests, stub IdP token endpoint
2. **Keycloak in testcontainers** — 1-2 full e2e integration tests, real authorize → callback → token exchange flow

Rationale: mocks alone risk passing tests but breaking against real IdPs. Keycloak in testcontainers fits existing test infra pattern (PostgreSQL, Redis already use testcontainers).
