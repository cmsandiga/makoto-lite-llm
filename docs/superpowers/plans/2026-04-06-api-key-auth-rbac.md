# API Key Auth + RBAC Implementation Plan — Ola 6

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable API key authentication via Bearer header (alongside existing JWT) with in-memory TTL cache, and add RBAC model access resolution with wildcard matching.

**Architecture:** Modify `get_current_user` to detect `sk-` prefix and authenticate via API key hash lookup with a TTL cache (5s, per spec). Add `permission_service.py` with wildcard model matching and access resolution chain (key → team → allow-all). Add `require_model_access` dependency for future proxy routes.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0 async, pytest, cachetools (TTL cache)

**Spec:** `docs/specs/2026-03-22-auth-system-design.md` sections 2.1 (API Keys), 3.4 (Model Access Resolution)

**Deferred to later ola:** Section 3.5 (Object-Level Permissions via `object_permissions` table) — requires the permission CRUD endpoints and is not needed until proxy routes exist.

---

## File Structure

```
src/app/
├── auth/
│   └── dependencies.py            # MODIFY — add sk- detection, API key auth, TTL cache, require_model_access
├── services/
│   └── permission_service.py      # CREATE — wildcard matching, model access resolution chain
tests/
├── test_auth/
│   ├── test_api_key_middleware.py  # CREATE — API key auth via Bearer header + cache tests
│   └── test_rbac.py               # CREATE — wildcard matching, access resolution, model access dependency
├── test_services/
│   └── test_permission_service.py # CREATE — pure function tests for matching + resolution
```

---

### Task 1: API Key Authentication in get_current_user

**Files:**
- Modify: `src/app/auth/dependencies.py`
- Test: `tests/test_auth/test_api_key_middleware.py`

**What this does:** When a Bearer token starts with `sk-`, authenticate it as an API key (hash → cache/DB lookup) instead of as a JWT. Checks: key exists, not blocked, not expired, grace period rotation support. Uses an in-memory TTL cache (5s) to avoid DB hits on every request.

- [ ] **Step 1: Add cachetools dependency**

Run: `uv add cachetools`

- [ ] **Step 2: Write failing tests for API key auth**

```python
# tests/test_auth/test_api_key_middleware.py
from datetime import datetime, timedelta, timezone

from app.auth.api_key_auth import generate_api_key, get_key_prefix, hash_api_key
from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.models.api_key import ApiKey
from app.models.user import User


async def test_api_key_auth(client, db_session):
    """A valid sk- key in the Bearer header should authenticate the request."""
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
        f"/users/{user.id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "dev@test.com"


async def test_api_key_blocked(client, db_session):
    """A blocked API key should return 401."""
    user = User(email="blocked-key@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=user.id,
        is_blocked=True,
    )
    db_session.add(api_key)
    await db_session.commit()

    response = await client.get(
        f"/users/{user.id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 401


async def test_api_key_expired(client, db_session):
    """An expired API key should return 401."""
    user = User(email="expired-key@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=user.id,
        expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(api_key)
    await db_session.commit()

    response = await client.get(
        f"/users/{user.id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 401


async def test_api_key_rotated_grace_period(client, db_session):
    """During grace period, the old key hash (in previous_key_hash) should still work."""
    user = User(email="rotated@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    old_key = generate_api_key()
    new_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(new_key),
        key_prefix=get_key_prefix(new_key),
        user_id=user.id,
        previous_key_hash=hash_api_key(old_key),
        grace_period_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    db_session.add(api_key)
    await db_session.commit()

    # Old key should still work during grace period
    response = await client.get(
        f"/users/{user.id}",
        headers={"Authorization": f"Bearer {old_key}"},
    )
    assert response.status_code == 200


async def test_jwt_still_works(client, db_session):
    """JWT auth should continue working alongside API key auth."""
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()

    token = create_access_token(user_id=admin.id, role="proxy_admin")
    response = await client.get(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth/test_api_key_middleware.py -v`
Expected: FAIL — `get_current_user` doesn't handle `sk-` prefix yet

- [ ] **Step 4: Implement API key auth path with TTL cache in dependencies.py**

Replace `src/app/auth/dependencies.py` entirely:

```python
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from cachetools import TTLCache
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key_auth import hash_api_key
from app.auth.jwt_handler import decode_token
from app.config import settings
from app.database import get_db
from app.models.api_key import ApiKey
from app.models.user import User

# In-memory TTL cache for API key auth (spec section 2.1: 5s TTL).
# Key: api_key_hash -> (ApiKey, User) tuple.
# Avoids DB lookup on every request for frequently-used keys.
_api_key_cache: TTLCache = TTLCache(
    maxsize=4096, ttl=settings.api_key_cache_ttl_seconds
)


def invalidate_api_key_cache(key_hash: str) -> None:
    """Remove a key from the auth cache. Call on update/delete/block."""
    _api_key_cache.pop(key_hash, None)


async def _lookup_api_key(db: AsyncSession, key_hash: str) -> ApiKey | None:
    """Look up an API key by current hash OR previous hash (grace period)."""
    result = await db.execute(
        select(ApiKey).where(
            (ApiKey.api_key_hash == key_hash)
            | (
                (ApiKey.previous_key_hash == key_hash)
                & (ApiKey.grace_period_expires_at > datetime.now(timezone.utc))
            )
        )
    )
    return result.scalar_one_or_none()


async def _authenticate_api_key(db: AsyncSession, raw_key: str) -> User:
    """Authenticate via API key hash lookup with TTL cache. Returns the key's owner User."""
    key_hash = hash_api_key(raw_key)

    # Check cache first
    cached = _api_key_cache.get(key_hash)
    if cached is not None:
        api_key, user = cached
    else:
        api_key = await _lookup_api_key(db, key_hash)
        if api_key is None:
            raise HTTPException(status_code=401, detail="Invalid API key")

        user_result = await db.execute(select(User).where(User.id == api_key.user_id))
        user = user_result.scalar_one_or_none()

        # Cache the result
        _api_key_cache[key_hash] = (api_key, user)

    # Validate state (always check, even from cache — state checks are cheap)
    if api_key.is_blocked:
        raise HTTPException(status_code=401, detail="API key is blocked")
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="API key has expired")
    if user is None or user.is_blocked:
        raise HTTPException(status_code=401, detail="Key owner not found or blocked")

    return user


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """Extract and validate auth from the Authorization header.

    Supports both JWT tokens and API keys (sk- prefix).
    Returns the authenticated User or raises 401.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid authorization header"
        )

    token = auth_header.split(" ", 1)[1]

    # API key path: starts with "sk-"
    if token.startswith("sk-"):
        return await _authenticate_api_key(db, token)

    # JWT path
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = uuid.UUID(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.is_blocked:
        raise HTTPException(status_code=401, detail="User not found or blocked")

    return user


def require_role(*roles: str) -> Callable:
    """Factory that returns a FastAPI dependency enforcing role membership."""

    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return dependency
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth/test_api_key_middleware.py -v`
Expected: All PASS

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/app/auth/dependencies.py tests/test_auth/test_api_key_middleware.py pyproject.toml uv.lock
git commit -m "feat: API key auth via Bearer header with TTL cache and rotation grace period"
```

---

### Task 2: Permission Service — Wildcard Model Matching

**Files:**
- Create: `src/app/services/permission_service.py`
- Create: `tests/test_services/__init__.py`
- Test: `tests/test_services/test_permission_service.py`

**What this does:** Implements glob-style wildcard matching for `allowed_models` patterns. Pure functions, no DB needed.

- [ ] **Step 1: Write failing tests for wildcard matching**

```python
# tests/test_services/test_permission_service.py
from app.services.permission_service import model_matches_pattern, model_is_allowed


def test_exact_match():
    assert model_matches_pattern("gpt-4", "gpt-4") is True
    assert model_matches_pattern("gpt-4", "gpt-3.5") is False


def test_wildcard_suffix():
    assert model_matches_pattern("claude-3-opus", "claude-*") is True
    assert model_matches_pattern("claude-3-sonnet", "claude-*") is True
    assert model_matches_pattern("gpt-4", "claude-*") is False


def test_star_matches_all():
    assert model_matches_pattern("anything", "*") is True
    assert model_matches_pattern("gpt-4-turbo", "*") is True


def test_case_sensitive():
    assert model_matches_pattern("GPT-4", "gpt-4") is False
    assert model_matches_pattern("Claude-3", "claude-*") is False


def test_model_is_allowed_with_list():
    assert model_is_allowed("gpt-4", ["gpt-4", "claude-*"]) is True
    assert model_is_allowed("claude-3-opus", ["gpt-4", "claude-*"]) is True
    assert model_is_allowed("llama-70b", ["gpt-4", "claude-*"]) is False


def test_model_is_allowed_star():
    assert model_is_allowed("anything", ["*"]) is True


def test_model_is_allowed_empty_list_denies():
    """Empty list means 'no models allowed'."""
    assert model_is_allowed("gpt-4", []) is False


def test_model_is_allowed_none_inherits():
    """None means 'inherit from parent' — returns None (not True/False)."""
    assert model_is_allowed("gpt-4", None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_services/test_permission_service.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement permission_service.py**

```python
# src/app/services/permission_service.py


def model_matches_pattern(model: str, pattern: str) -> bool:
    """Check if a model name matches a glob-style pattern.

    Supported patterns:
    - Exact match: "gpt-4" matches "gpt-4"
    - Wildcard suffix: "claude-*" matches "claude-3-opus"
    - Match all: "*" matches everything
    - Case-sensitive
    """
    if pattern == "*":
        return True
    if pattern.endswith("*"):
        return model.startswith(pattern[:-1])
    return model == pattern


def model_is_allowed(model: str, allowed_models: list[str] | None) -> bool | None:
    """Check if a model is in an allowed_models list.

    Returns:
        True  — model is explicitly allowed
        False — model is explicitly denied (empty list or no pattern matches)
        None  — allowed_models is None, meaning 'inherit from parent'
    """
    if allowed_models is None:
        return None
    return any(model_matches_pattern(model, pattern) for pattern in allowed_models)
```

- [ ] **Step 4: Create test_services package**

```bash
mkdir -p tests/test_services && touch tests/test_services/__init__.py
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_services/test_permission_service.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/services/permission_service.py tests/test_services/
git commit -m "feat: wildcard model matching — glob-style pattern support"
```

---

### Task 3: Model Access Resolution Chain

**Files:**
- Modify: `src/app/services/permission_service.py`
- Modify: `tests/test_services/test_permission_service.py`

**What this does:** Implements the resolution chain: key.allowed_models → team.allowed_models → allow-all. Each level returns `True`, `False`, or `None` (inherit).

**Note on org level:** The spec mentions org-level config in the resolution chain, but the Organization model has no `allowed_models` column (it has budget/rate limits only). Org-level model restrictions would need a schema change. This is intentionally deferred — the 2-level chain (key → team) covers all current use cases, and adding the org level is backward-compatible when needed.

- [ ] **Step 1: Write failing tests for the resolution chain**

Add to `tests/test_services/test_permission_service.py`:

```python
from app.services.permission_service import resolve_model_access


def test_resolve_key_level_allows():
    """Key-level allowed_models takes priority."""
    assert resolve_model_access("gpt-4", key_allowed_models=["gpt-4", "claude-*"], team_allowed_models=None) is True


def test_resolve_key_level_denies():
    assert resolve_model_access("llama-70b", key_allowed_models=["gpt-4"], team_allowed_models=["*"]) is False


def test_resolve_inherits_to_team():
    """Key is None (inherit), falls through to team."""
    assert resolve_model_access("gpt-4", key_allowed_models=None, team_allowed_models=["gpt-4"]) is True


def test_resolve_team_denies():
    assert resolve_model_access("llama-70b", key_allowed_models=None, team_allowed_models=["gpt-4"]) is False


def test_resolve_both_none_allows():
    """If both key and team are None (no restrictions), allow."""
    assert resolve_model_access("anything", key_allowed_models=None, team_allowed_models=None) is True


def test_resolve_empty_key_list_denies():
    """Empty list at key level means 'no models allowed' even if team allows."""
    assert resolve_model_access("gpt-4", key_allowed_models=[], team_allowed_models=["*"]) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_services/test_permission_service.py::test_resolve_key_level_allows -v`
Expected: FAIL — `resolve_model_access` doesn't exist

- [ ] **Step 3: Implement resolve_model_access**

Add to `src/app/services/permission_service.py`:

```python
def resolve_model_access(
    model: str,
    key_allowed_models: list[str] | None,
    team_allowed_models: list[str] | None,
) -> bool:
    """Resolve whether a model is accessible through the inheritance chain.

    Resolution order (spec section 3.4):
    1. key.allowed_models — if set, use it
    2. team.allowed_models — if set, use it
    3. Both None — no restrictions, allow all

    Note: org-level model restrictions are deferred (Organization model has no
    allowed_models column). Adding it later is backward-compatible.
    """
    key_result = model_is_allowed(model, key_allowed_models)
    if key_result is not None:
        return key_result

    team_result = model_is_allowed(model, team_allowed_models)
    if team_result is not None:
        return team_result

    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_services/test_permission_service.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/services/permission_service.py tests/test_services/test_permission_service.py
git commit -m "feat: model access resolution chain — key → team → allow"
```

---

### Task 4: require_model_access Dependency

**Files:**
- Modify: `src/app/auth/dependencies.py`
- Test: `tests/test_auth/test_rbac.py`

**What this does:** A FastAPI dependency factory that checks if the authenticated API key / team allows access to a specific model. Used by future proxy routes. JWT-authenticated `proxy_admin` users bypass the check.

- [ ] **Step 1: Write test file with test-only route and tests**

```python
# tests/test_auth/test_rbac.py
from fastapi import Depends

from app.auth.api_key_auth import generate_api_key, get_key_prefix, hash_api_key
from app.auth.dependencies import require_model_access
from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.main import app
from app.models.api_key import ApiKey
from app.models.team import Team
from app.models.user import User

# ---------- Test-only route ----------
# Registers once at module import. Uses require_model_access with path param "model_name".

@app.get("/test-model-access/{model_name}")
async def _test_model_access_route(
    model_name: str,
    user: User = Depends(require_model_access("model_name")),
):
    return {"model": model_name, "user_email": user.email}


# ---------- Tests ----------


async def test_api_key_model_access_allowed(client, db_session):
    """API key with allowed_models=['gpt-4','claude-*'] can access gpt-4."""
    user = User(email="model-ok@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=user.id,
        allowed_models=["gpt-4", "claude-*"],
    )
    db_session.add(api_key)
    await db_session.commit()

    response = await client.get(
        "/test-model-access/gpt-4",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200


async def test_api_key_model_access_denied(client, db_session):
    """API key with allowed_models=['gpt-4'] cannot access llama-70b."""
    user = User(email="model-deny@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=user.id,
        allowed_models=["gpt-4"],
    )
    db_session.add(api_key)
    await db_session.commit()

    response = await client.get(
        "/test-model-access/llama-70b",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 403


async def test_jwt_proxy_admin_bypasses_model_check(client, db_session):
    """JWT-authenticated proxy_admin has no model restrictions."""
    admin = User(email="admin-model@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()

    token = create_access_token(user_id=admin.id, role="proxy_admin")
    response = await client.get(
        "/test-model-access/any-model",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


async def test_api_key_inherits_team_models(client, db_session):
    """API key with no allowed_models inherits from team."""
    team = Team(name="TeamModels", allowed_models=["gpt-4"])
    db_session.add(team)
    await db_session.flush()

    user = User(email="team-inherit@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=user.id,
        team_id=team.id,
        allowed_models=None,  # inherit from team
    )
    db_session.add(api_key)
    await db_session.commit()

    # gpt-4 allowed via team
    response = await client.get(
        "/test-model-access/gpt-4",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200

    # llama denied via team
    response = await client.get(
        "/test-model-access/llama-70b",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth/test_rbac.py -v`
Expected: FAIL — `require_model_access` doesn't exist

- [ ] **Step 3: Implement require_model_access in dependencies.py**

Add to `src/app/auth/dependencies.py` (after the existing functions):

```python
from app.models.team import Team
from app.services.permission_service import resolve_model_access


def require_model_access(path_param: str = "model") -> Callable:
    """Factory returning a dependency that checks model access for the current auth.

    Reads the model name from the path parameter specified by `path_param`.
    proxy_admin users bypass the check. JWT users without an API key have no restrictions.

    Usage:
        @router.post("/chat/completions/{model}")
        async def chat(model: str, user: User = Depends(require_model_access("model"))):
    """

    async def dependency(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        model_name = request.path_params.get(path_param)
        if model_name is None:
            return user

        # proxy_admin bypasses model access checks
        if user.role == "proxy_admin":
            return user

        # Get the auth token to look up the API key
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.split(" ", 1)[1] if " " in auth_header else ""

        # JWT users without an API key — no model restrictions
        if not token.startswith("sk-"):
            return user

        api_key = await _lookup_api_key(db, hash_api_key(token))

        key_models = api_key.allowed_models if api_key else None
        team_models = None

        if api_key and api_key.team_id:
            team_result = await db.execute(select(Team).where(Team.id == api_key.team_id))
            team = team_result.scalar_one_or_none()
            if team:
                team_models = team.allowed_models

        if not resolve_model_access(model_name, key_models, team_models):
            raise HTTPException(
                status_code=403,
                detail=f"Model '{model_name}' is not allowed for this key",
            )

        return user

    return dependency
```

Note: this reuses `_lookup_api_key` from Task 1 — no duplicate query logic.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth/test_rbac.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/auth/dependencies.py tests/test_auth/test_rbac.py
git commit -m "feat: RBAC model access — require_model_access dependency with key → team inheritance"
```
