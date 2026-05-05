# Real OIDC Token Exchange Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 501 callback stub with a real OIDC flow — discovery, PKCE, token exchange, user provisioning, group-to-team mapping — completing auth system Task 17.

**Architecture:** An `OIDCClient` class handles all IdP communication (discovery, token exchange, userinfo). The existing `sso_service.py` gains provisioning logic (find-or-create user, map groups to teams). The callback route orchestrates the flow and issues our own JWT pair. PKCE (`code_verifier`/`code_challenge`) is added to the authorize flow and stored alongside the existing state parameter.

**Tech Stack:** httpx (async HTTP client, already a dependency), PyJWT (ID token validation), `respx` (new dev dependency for mocking httpx in tests)

**Dependencies:** This completes auth system plan Task 17. Builds on Ola 9 (SSO config CRUD + authorize stub).

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/app/services/oidc_client.py` | OIDC discovery, token exchange, userinfo fetch, ID token validation |
| Modify | `src/app/services/sso_service.py` | Add PKCE to authorize flow, add `provision_sso_user`, add `map_groups_to_teams` |
| Modify | `src/app/routes/sso_routes.py` | Replace 501 callback with real flow |
| Modify | `src/app/config.py` | Add `sso_dashboard_redirect_url` setting |
| Create | `tests/test_services/test_oidc_client.py` | Unit tests for OIDC client (respx mocks) |
| Modify | `tests/test_services/test_sso_service.py` | Tests for provisioning + group mapping |
| Modify | `tests/test_routes/test_sso_routes.py` | Tests for real callback flow (respx mocks) |

---

### Task 1: Add `respx` dev dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add respx to dev dependencies**

```bash
uv add --dev respx
```

- [ ] **Step 2: Verify it installs**

```bash
uv run python -c "import respx; print(respx.__version__)"
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add respx dev dependency for httpx mocking"
```

---

### Task 2: OIDC Client — Discovery

**Files:**
- Create: `src/app/services/oidc_client.py`
- Create: `tests/test_services/test_oidc_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services/test_oidc_client.py
import httpx
import pytest
import respx

from app.services.oidc_client import OIDCClient

ISSUER = "https://accounts.google.com"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
DISCOVERY_DOC = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/o/oauth2/v2/auth",
    "token_endpoint": f"{ISSUER}/o/oauth2/token",
    "userinfo_endpoint": f"{ISSUER}/oauth2/v3/userinfo",
    "jwks_uri": f"{ISSUER}/oauth2/v3/certs",
}


@respx.mock
async def test_discover_fetches_and_caches():
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json=DISCOVERY_DOC)
    )
    client = OIDCClient(issuer_url=ISSUER)
    doc = await client.discover()
    assert doc["token_endpoint"] == f"{ISSUER}/o/oauth2/token"
    assert doc["userinfo_endpoint"] == f"{ISSUER}/oauth2/v3/userinfo"

    # Second call should use cache, not make another request
    doc2 = await client.discover()
    assert doc2 == doc
    assert respx.calls.call_count == 1


@respx.mock
async def test_discover_bad_status_raises():
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(404, text="Not found")
    )
    client = OIDCClient(issuer_url=ISSUER)
    with pytest.raises(RuntimeError, match="OIDC discovery failed"):
        await client.discover()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_services/test_oidc_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.oidc_client'`

- [ ] **Step 3: Implement OIDCClient with discovery**

```python
# src/app/services/oidc_client.py
"""OIDC client — handles IdP communication (discovery, token exchange, userinfo)."""

import httpx


class OIDCClient:
    """Async OIDC client for a single issuer."""

    def __init__(self, issuer_url: str) -> None:
        self.issuer_url = issuer_url.rstrip("/")
        self._discovery_cache: dict | None = None

    async def discover(self) -> dict:
        """Fetch the OIDC discovery document. Cached after first call."""
        if self._discovery_cache is not None:
            return self._discovery_cache

        url = f"{self.issuer_url}/.well-known/openid-configuration"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(
                f"OIDC discovery failed for {self.issuer_url}: "
                f"HTTP {resp.status_code}"
            )
        self._discovery_cache = resp.json()
        return self._discovery_cache
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_services/test_oidc_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/services/oidc_client.py tests/test_services/test_oidc_client.py
git commit -m "feat(oidc): OIDCClient with discovery + caching"
```

---

### Task 3: OIDC Client — Token Exchange

**Files:**
- Modify: `src/app/services/oidc_client.py`
- Modify: `tests/test_services/test_oidc_client.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_services/test_oidc_client.py`:

```python
TOKEN_ENDPOINT = f"{ISSUER}/o/oauth2/token"
TOKEN_RESPONSE = {
    "access_token": "ya29.access",
    "id_token": "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTYiLCJlbWFpbCI6InVzZXJAYWNtZS5jb20iLCJuYW1lIjoiVGVzdCBVc2VyIiwiaXNzIjoiaHR0cHM6Ly9hY2NvdW50cy5nb29nbGUuY29tIiwiYXVkIjoiY2xpZW50LTEyMyIsImV4cCI6OTk5OTk5OTk5OX0.fake-signature",
    "token_type": "Bearer",
    "expires_in": 3600,
}


@respx.mock
async def test_exchange_code():
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json=DISCOVERY_DOC)
    )
    respx.post(TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    client = OIDCClient(issuer_url=ISSUER)
    tokens = await client.exchange_code(
        code="auth-code-123",
        redirect_uri="http://localhost:8000/sso/callback",
        client_id="client-123",
        client_secret="secret-456",
        code_verifier="test-verifier",
    )
    assert tokens["access_token"] == "ya29.access"
    assert "id_token" in tokens

    # Verify the POST body included PKCE code_verifier
    request = respx.calls.last.request
    body = request.content.decode()
    assert "code_verifier=test-verifier" in body
    assert "grant_type=authorization_code" in body


@respx.mock
async def test_exchange_code_error():
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json=DISCOVERY_DOC)
    )
    respx.post(TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "Code expired"}
        )
    )
    client = OIDCClient(issuer_url=ISSUER)
    with pytest.raises(RuntimeError, match="Token exchange failed"):
        await client.exchange_code(
            code="expired-code",
            redirect_uri="http://localhost:8000/sso/callback",
            client_id="client-123",
            client_secret="secret-456",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_services/test_oidc_client.py::test_exchange_code -v`
Expected: FAIL — `AttributeError: 'OIDCClient' object has no attribute 'exchange_code'`

- [ ] **Step 3: Implement exchange_code**

Add to `src/app/services/oidc_client.py`:

```python
    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        client_id: str,
        client_secret: str,
        code_verifier: str | None = None,
    ) -> dict:
        """Exchange an authorization code for tokens."""
        discovery = await self.discover()
        token_endpoint = discovery["token_endpoint"]

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier

        async with httpx.AsyncClient() as client:
            resp = await client.post(token_endpoint, data=data, timeout=10)

        if resp.status_code != 200:
            error = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            raise RuntimeError(
                f"Token exchange failed: {error.get('error', resp.status_code)} "
                f"— {error.get('error_description', resp.text)}"
            )
        return resp.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_services/test_oidc_client.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/services/oidc_client.py tests/test_services/test_oidc_client.py
git commit -m "feat(oidc): token exchange with PKCE code_verifier support"
```

---

### Task 4: OIDC Client — Userinfo Fetch

**Files:**
- Modify: `src/app/services/oidc_client.py`
- Modify: `tests/test_services/test_oidc_client.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_services/test_oidc_client.py`:

```python
USERINFO_ENDPOINT = f"{ISSUER}/oauth2/v3/userinfo"
USERINFO_RESPONSE = {
    "sub": "123456",
    "email": "user@acme.com",
    "name": "Test User",
    "groups": ["Engineering", "Platform"],
}


@respx.mock
async def test_fetch_userinfo():
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json=DISCOVERY_DOC)
    )
    respx.get(USERINFO_ENDPOINT).mock(
        return_value=httpx.Response(200, json=USERINFO_RESPONSE)
    )
    client = OIDCClient(issuer_url=ISSUER)
    info = await client.fetch_userinfo(access_token="ya29.access")
    assert info["email"] == "user@acme.com"
    assert info["sub"] == "123456"
    assert info["groups"] == ["Engineering", "Platform"]

    # Verify Bearer token was sent
    request = respx.calls.last.request
    assert request.headers["Authorization"] == "Bearer ya29.access"


@respx.mock
async def test_fetch_userinfo_error():
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json=DISCOVERY_DOC)
    )
    respx.get(USERINFO_ENDPOINT).mock(
        return_value=httpx.Response(401, json={"error": "invalid_token"})
    )
    client = OIDCClient(issuer_url=ISSUER)
    with pytest.raises(RuntimeError, match="Userinfo fetch failed"):
        await client.fetch_userinfo(access_token="expired-token")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_services/test_oidc_client.py::test_fetch_userinfo -v`
Expected: FAIL — `AttributeError: 'OIDCClient' object has no attribute 'fetch_userinfo'`

- [ ] **Step 3: Implement fetch_userinfo**

Add to `src/app/services/oidc_client.py`:

```python
    async def fetch_userinfo(self, access_token: str) -> dict:
        """Fetch user claims from the userinfo endpoint."""
        discovery = await self.discover()
        userinfo_endpoint = discovery["userinfo_endpoint"]

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Userinfo fetch failed: HTTP {resp.status_code}"
            )
        return resp.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_services/test_oidc_client.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/services/oidc_client.py tests/test_services/test_oidc_client.py
git commit -m "feat(oidc): userinfo fetch with Bearer token"
```

---

### Task 5: PKCE — Add code_challenge to authorize flow

**Files:**
- Modify: `src/app/services/sso_service.py`
- Modify: `tests/test_services/test_sso_service.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_services/test_sso_service.py`:

```python
from app.services.sso_service import generate_pkce_pair


def test_generate_pkce_pair():
    verifier, challenge = generate_pkce_pair()
    # verifier is 43-128 characters, URL-safe
    assert 43 <= len(verifier) <= 128
    # challenge is base64url-encoded SHA-256 of verifier
    assert len(challenge) > 0
    assert "=" not in challenge  # no padding
    # Two calls produce different values
    v2, c2 = generate_pkce_pair()
    assert verifier != v2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_services/test_sso_service.py::test_generate_pkce_pair -v`
Expected: FAIL — `ImportError: cannot import name 'generate_pkce_pair'`

- [ ] **Step 3: Implement PKCE pair generation**

Add to `src/app/services/sso_service.py`:

```python
import hashlib
import base64


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge (S256)."""
    verifier = secrets.token_urlsafe(64)  # 86 chars
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_services/test_sso_service.py::test_generate_pkce_pair -v`
Expected: PASS

- [ ] **Step 5: Update `build_authorize_url` to include PKCE and store verifier**

Modify `build_authorize_url` in `src/app/services/sso_service.py`. The `_state_store` now maps `state -> code_verifier` instead of `state -> True`:

```python
async def build_authorize_url(
    db: AsyncSession,
    org_id: uuid.UUID,
    callback_url: str,
) -> tuple[str, str] | None:
    """Build the OAuth2 authorize redirect URL for an org's SSO config.

    Returns (url, state) or None if no config found.
    Stores code_verifier in state store for PKCE validation in callback.
    """
    config = await get_sso_config(db, org_id)
    if config is None:
        return None

    state = secrets.token_urlsafe(32)
    verifier, challenge = generate_pkce_pair()
    _state_store[state] = verifier  # store verifier for callback to use

    params = urlencode({
        "client_id": config.client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    url = f"{config.issuer_url}/authorize?{params}"
    return url, state
```

- [ ] **Step 6: Update `validate_state` to return the code_verifier**

```python
def validate_and_consume_state(state: str) -> str | None:
    """Validate and consume an OAuth2 state token.

    Returns the PKCE code_verifier if valid, None if invalid/expired.
    """
    return _state_store.pop(state, None)
```

- [ ] **Step 7: Update existing tests**

Update `test_build_authorize_url` to check for PKCE params:

Add after the existing assertions in `test_build_authorize_url`:
```python
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
```

Update `test_validate_state_valid` and `test_validate_state_invalid` to use `validate_and_consume_state` and check the returned verifier:

```python
from app.services.sso_service import validate_and_consume_state

async def test_validate_state_valid():
    _state_store["test-state-123"] = "test-verifier-abc"
    verifier = validate_and_consume_state("test-state-123")
    assert verifier == "test-verifier-abc"
    # Second call should fail — state is consumed
    assert validate_and_consume_state("test-state-123") is None


async def test_validate_state_invalid():
    assert validate_and_consume_state("nonexistent-state") is None
```

Remove imports/references to the old `validate_state` function. Import `validate_and_consume_state` instead.

- [ ] **Step 8: Run all SSO service tests**

Run: `uv run pytest tests/test_services/test_sso_service.py -v`
Expected: All tests PASS

- [ ] **Step 9: Commit**

```bash
git add src/app/services/sso_service.py tests/test_services/test_sso_service.py
git commit -m "feat(oidc): PKCE support in authorize flow + state stores verifier"
```

---

### Task 6: SSO Service — User Provisioning (find or create)

**Files:**
- Modify: `src/app/services/sso_service.py`
- Modify: `tests/test_services/test_sso_service.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_services/test_sso_service.py`:

```python
from app.models.user import User
from app.services.sso_service import provision_sso_user


async def test_provision_sso_user_creates_new(db_session):
    org = await _create_org(db_session)
    user = await provision_sso_user(
        db_session,
        email="new@acme.com",
        name="New User",
        sso_provider="google",
        sso_subject="google-sub-123",
        org_id=org.id,
        default_role="member",
    )
    assert user.email == "new@acme.com"
    assert user.name == "New User"
    assert user.sso_provider == "google"
    assert user.sso_subject == "google-sub-123"
    assert user.role == "member"
    assert user.password_hash is None  # SSO-only user


async def test_provision_sso_user_links_existing(db_session):
    org = await _create_org(db_session)
    # Pre-create user with password (dashboard login)
    existing = User(
        email="existing@acme.com",
        password_hash="some-hash",
        role="member",
    )
    db_session.add(existing)
    await db_session.commit()
    await db_session.refresh(existing)

    # SSO login should link, not create duplicate
    user = await provision_sso_user(
        db_session,
        email="existing@acme.com",
        name="Existing User",
        sso_provider="google",
        sso_subject="google-sub-456",
        org_id=org.id,
        default_role="member",
    )
    assert user.id == existing.id  # same user
    assert user.sso_provider == "google"
    assert user.sso_subject == "google-sub-456"
    assert user.password_hash == "some-hash"  # preserved


async def test_provision_sso_user_creates_org_membership(db_session):
    from sqlalchemy import select
    from app.models.membership import OrgMembership

    org = await _create_org(db_session)
    user = await provision_sso_user(
        db_session,
        email="member@acme.com",
        name="Member",
        sso_provider="okta",
        sso_subject="okta-sub-789",
        org_id=org.id,
        default_role="member",
    )
    result = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.user_id == user.id,
            OrgMembership.org_id == org.id,
        )
    )
    membership = result.scalar_one_or_none()
    assert membership is not None
    assert membership.role == "member"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_services/test_sso_service.py -k "provision" -v`
Expected: FAIL — `ImportError: cannot import name 'provision_sso_user'`

- [ ] **Step 3: Implement provision_sso_user**

Add to `src/app/services/sso_service.py`:

```python
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.membership import OrgMembership
from app.models.user import User


async def provision_sso_user(
    db: AsyncSession,
    email: str,
    name: str | None,
    sso_provider: str,
    sso_subject: str,
    org_id: uuid.UUID,
    default_role: str = "member",
) -> User:
    """Find or create a user from SSO claims, and ensure org membership."""
    # Try to find existing user by email
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        # Create new SSO-only user (no password)
        user = User(
            email=email,
            name=name,
            role=default_role,
            sso_provider=sso_provider,
            sso_subject=sso_subject,
        )
        db.add(user)
        await db.flush()
    else:
        # Link SSO to existing user
        user.sso_provider = sso_provider
        user.sso_subject = sso_subject
        if name and not user.name:
            user.name = name

    # Ensure org membership exists
    membership = OrgMembership(
        user_id=user.id,
        org_id=org_id,
        role=default_role,
    )
    db.add(membership)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        # Membership already exists — that's fine, re-fetch user
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one()

    await db.commit()
    await db.refresh(user)
    return user
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_services/test_sso_service.py -k "provision" -v`
Expected: All 3 provisioning tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/services/sso_service.py tests/test_services/test_sso_service.py
git commit -m "feat(oidc): SSO user provisioning — find or create + org membership"
```

---

### Task 7: SSO Service — Group-to-Team Mapping

**Files:**
- Modify: `src/app/services/sso_service.py`
- Modify: `tests/test_services/test_sso_service.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_services/test_sso_service.py`:

```python
from app.models.team import Team
from app.models.membership import TeamMembership
from app.services.sso_service import map_groups_to_teams


async def test_map_groups_to_teams(db_session):
    from sqlalchemy import select

    org = await _create_org(db_session)

    # Create teams
    eng_team = Team(name="Engineering", slug=f"eng-{uuid7()}", org_id=org.id)
    platform_team = Team(name="Platform", slug=f"plat-{uuid7()}", org_id=org.id)
    db_session.add_all([eng_team, platform_team])
    await db_session.commit()
    await db_session.refresh(eng_team)
    await db_session.refresh(platform_team)

    # Create user
    user = User(email=f"mapper-{uuid7()}@acme.com", role="member")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    mapping = {
        "Engineering": str(eng_team.id),
        "Platform": str(platform_team.id),
    }
    idp_groups = ["Engineering", "Platform", "Unknown-Group"]

    await map_groups_to_teams(db_session, user.id, idp_groups, mapping)

    # Verify team memberships created
    result = await db_session.execute(
        select(TeamMembership).where(TeamMembership.user_id == user.id)
    )
    memberships = list(result.scalars().all())
    team_ids = {m.team_id for m in memberships}
    assert eng_team.id in team_ids
    assert platform_team.id in team_ids
    assert len(memberships) == 2  # Unknown-Group ignored


async def test_map_groups_to_teams_no_mapping(db_session):
    """When mapping is None, nothing happens."""
    user = User(email=f"no-map-{uuid7()}@acme.com", role="member")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # Should not raise
    await map_groups_to_teams(db_session, user.id, ["Engineering"], None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_services/test_sso_service.py -k "map_groups" -v`
Expected: FAIL — `ImportError: cannot import name 'map_groups_to_teams'`

- [ ] **Step 3: Implement map_groups_to_teams**

Add to `src/app/services/sso_service.py`:

```python
from app.models.membership import TeamMembership


async def map_groups_to_teams(
    db: AsyncSession,
    user_id: uuid.UUID,
    idp_groups: list[str] | None,
    group_to_team_mapping: dict | None,
) -> None:
    """Map IdP groups to team memberships using the SSO config's mapping."""
    if not group_to_team_mapping or not idp_groups:
        return

    for group_name in idp_groups:
        team_id_str = group_to_team_mapping.get(group_name)
        if team_id_str is None:
            continue  # group not mapped
        team_id = uuid.UUID(team_id_str)
        membership = TeamMembership(user_id=user_id, team_id=team_id)
        db.add(membership)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            # Already a member — skip

    await db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_services/test_sso_service.py -k "map_groups" -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/services/sso_service.py tests/test_services/test_sso_service.py
git commit -m "feat(oidc): group-to-team mapping from IdP claims"
```

---

### Task 8: Real Callback Route — Replace 501 Stub

**Files:**
- Modify: `src/app/routes/sso_routes.py`
- Modify: `src/app/config.py`
- Modify: `tests/test_routes/test_sso_routes.py`

- [ ] **Step 1: Add config setting**

Add to `src/app/config.py` in the `Settings` class:

```python
    sso_dashboard_redirect_url: str = "http://localhost:3000/auth/callback"
```

- [ ] **Step 2: Write the failing tests**

Replace the existing callback tests in `tests/test_routes/test_sso_routes.py` with:

```python
# ========== GET /sso/callback ==========

from app.services.sso_service import _state_store


async def test_callback_full_flow(client, db_session, respx_mock):
    """Full callback: valid state → token exchange → userinfo → provision → redirect with tokens."""
    admin, org = await _setup(db_session)
    headers = _admin_headers(admin.id)

    # Create SSO config
    await client.post(
        "/sso/config",
        json={
            "org_id": str(org.id),
            "provider": "google",
            "client_id": "goog-123",
            "client_secret": "secret",
            "issuer_url": "https://accounts.google.com",
            "auto_create_user": True,
            "default_role": "member",
        },
        headers=headers,
    )

    # Mock OIDC endpoints
    respx_mock.get("https://accounts.google.com/.well-known/openid-configuration").mock(
        return_value=httpx.Response(200, json={
            "issuer": "https://accounts.google.com",
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://accounts.google.com/o/oauth2/token",
            "userinfo_endpoint": "https://accounts.google.com/oauth2/v3/userinfo",
            "jwks_uri": "https://accounts.google.com/oauth2/v3/certs",
        })
    )
    respx_mock.post("https://accounts.google.com/o/oauth2/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "ya29.test-access",
            "id_token": "fake-id-token",
            "token_type": "Bearer",
        })
    )
    respx_mock.get("https://accounts.google.com/oauth2/v3/userinfo").mock(
        return_value=httpx.Response(200, json={
            "sub": "google-uid-999",
            "email": "sso-user@acme.com",
            "name": "SSO User",
        })
    )

    # Simulate an authorize flow having stored a state + verifier
    _state_store["test-callback-state"] = "test-verifier-123"

    response = await client.get(
        "/sso/callback?code=authcode123&state=test-callback-state",
        follow_redirects=False,
    )
    assert response.status_code == 307
    location = response.headers["location"]
    assert "access_token=" in location
    assert "refresh_token=" in location


async def test_callback_invalid_state(client, db_session):
    response = await client.get("/sso/callback?code=authcode123&state=bogus-state")
    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()


async def test_callback_missing_params(client, db_session):
    response = await client.get("/sso/callback")
    assert response.status_code == 422
```

Also add the required imports at the top of the test file:

```python
import httpx
import respx
```

And add a `respx_mock` fixture to the test file (or conftest):

```python
@pytest.fixture
def respx_mock():
    with respx.mock(assert_all_called=False) as mock:
        yield mock
```

Add `import pytest` to the imports if not present.

- [ ] **Step 3: Implement the real callback**

Replace the callback endpoint in `src/app/routes/sso_routes.py`:

```python
from app.auth.crypto import decrypt
from app.services.auth_service import create_tokens
from app.services.oidc_client import OIDCClient
from app.services.sso_service import (
    build_authorize_url,
    create_sso_config,
    delete_sso_config,
    get_sso_config,
    map_groups_to_teams,
    provision_sso_user,
    validate_and_consume_state,
)


# ========== GET /sso/callback — OIDC token exchange ==========


@router.get("/callback")
async def callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    # 1. Validate and consume state, get PKCE verifier
    code_verifier = validate_and_consume_state(state)
    if code_verifier is None:
        raise HTTPException(
            status_code=400, detail="Invalid or expired state parameter"
        )

    # 2. Look up which org this state belongs to — we need org_id from state
    #    For now, extract org_id from the state store. We'll enhance the state
    #    store to include org_id.
    #    Actually, we need to get the SSO config. The callback doesn't know org_id.
    #    Solution: store org_id alongside verifier in state store.
    org_id = code_verifier.get("org_id") if isinstance(code_verifier, dict) else None
    verifier = code_verifier.get("verifier") if isinstance(code_verifier, dict) else code_verifier

    if org_id is None:
        raise HTTPException(status_code=400, detail="Invalid state — missing org context")

    config = await get_sso_config(db, org_id)
    if config is None:
        raise HTTPException(status_code=404, detail="SSO config not found")

    # 3. Exchange code for tokens
    client_secret = decrypt(config.client_secret_encrypted)
    oidc = OIDCClient(issuer_url=config.issuer_url)
    callback_url = f"{settings.base_url}/sso/callback"

    tokens = await oidc.exchange_code(
        code=code,
        redirect_uri=callback_url,
        client_id=config.client_id,
        client_secret=client_secret,
        code_verifier=verifier,
    )

    # 4. Fetch user claims
    claims = await oidc.fetch_userinfo(access_token=tokens["access_token"])

    # 5. Provision user
    email = claims.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="IdP did not return email claim")

    user = await provision_sso_user(
        db,
        email=email,
        name=claims.get("name"),
        sso_provider=config.provider,
        sso_subject=claims.get("sub", ""),
        org_id=config.org_id,
        default_role=config.default_role,
    )

    # 6. Map groups to teams
    idp_groups = claims.get("groups")
    if idp_groups and config.group_to_team_mapping:
        await map_groups_to_teams(
            db, user.id, idp_groups, config.group_to_team_mapping
        )

    # 7. Issue our own JWT pair
    jwt_tokens = await create_tokens(db, user)

    # 8. Redirect to dashboard with tokens as query params
    redirect_url = (
        f"{settings.sso_dashboard_redirect_url}"
        f"?access_token={jwt_tokens['access_token']}"
        f"&refresh_token={jwt_tokens['refresh_token']}"
    )
    return RedirectResponse(url=redirect_url, status_code=307)
```

- [ ] **Step 4: Update state store to include org_id**

The `build_authorize_url` and `_state_store` need to store `{"verifier": ..., "org_id": ...}` instead of just the verifier string. Update in `sso_service.py`:

In `build_authorize_url`, change:
```python
    _state_store[state] = verifier
```
to:
```python
    _state_store[state] = {"verifier": verifier, "org_id": org_id}
```

And update `validate_and_consume_state` to return the dict:
```python
def validate_and_consume_state(state: str) -> dict | None:
    """Validate and consume an OAuth2 state token.

    Returns {"verifier": str, "org_id": UUID} if valid, None if invalid/expired.
    """
    return _state_store.pop(state, None)
```

- [ ] **Step 5: Update test fixtures for the new state store format**

In `test_sso_service.py`, update:
```python
async def test_validate_state_valid():
    _state_store["test-state-123"] = {"verifier": "test-verifier-abc", "org_id": uuid7()}
    result = validate_and_consume_state("test-state-123")
    assert result["verifier"] == "test-verifier-abc"
    assert validate_and_consume_state("test-state-123") is None
```

In `test_sso_routes.py`, update the callback test state setup:
```python
    _state_store["test-callback-state"] = {"verifier": "test-verifier-123", "org_id": org.id}
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/test_services/test_sso_service.py tests/test_routes/test_sso_routes.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/app/routes/sso_routes.py src/app/services/sso_service.py src/app/config.py tests/test_routes/test_sso_routes.py tests/test_services/test_sso_service.py
git commit -m "feat(oidc): real callback — token exchange, userinfo, provisioning, JWT issuance"
```

---

### Task 9: Domain Validation — allowed_domains check

**Files:**
- Modify: `src/app/routes/sso_routes.py`
- Modify: `tests/test_routes/test_sso_routes.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_routes/test_sso_routes.py`:

```python
async def test_callback_domain_not_allowed(client, db_session, respx_mock):
    """Callback should reject users whose email domain isn't in allowed_domains."""
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
            "allowed_domains": ["acme.com"],  # only acme.com allowed
        },
        headers=headers,
    )

    respx_mock.get("https://accounts.google.com/.well-known/openid-configuration").mock(
        return_value=httpx.Response(200, json={
            "issuer": "https://accounts.google.com",
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://accounts.google.com/o/oauth2/token",
            "userinfo_endpoint": "https://accounts.google.com/oauth2/v3/userinfo",
            "jwks_uri": "https://accounts.google.com/oauth2/v3/certs",
        })
    )
    respx_mock.post("https://accounts.google.com/o/oauth2/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "ya29.test",
            "id_token": "fake",
            "token_type": "Bearer",
        })
    )
    respx_mock.get("https://accounts.google.com/oauth2/v3/userinfo").mock(
        return_value=httpx.Response(200, json={
            "sub": "uid-1",
            "email": "hacker@evil.com",  # not in allowed_domains
            "name": "Hacker",
        })
    )

    _state_store["domain-test-state"] = {"verifier": "v", "org_id": org.id}

    response = await client.get(
        "/sso/callback?code=code123&state=domain-test-state",
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert "domain" in response.json()["detail"].lower()
```

- [ ] **Step 2: Add domain validation to callback route**

In `sso_routes.py`, add after fetching claims and extracting email, before provisioning:

```python
    # Validate email domain against allowed_domains
    if config.allowed_domains:
        email_domain = email.split("@", 1)[1] if "@" in email else ""
        if email_domain not in config.allowed_domains:
            raise HTTPException(
                status_code=403,
                detail=f"Email domain '{email_domain}' is not in allowed domains",
            )
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_routes/test_sso_routes.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/app/routes/sso_routes.py tests/test_routes/test_sso_routes.py
git commit -m "feat(oidc): domain validation against allowed_domains in callback"
```

---

### Task 10: Full Test Suite Verification

**Files:** None (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: All 155+ tests PASS

- [ ] **Step 2: Run linting on changed files**

Run: `uv run ruff check src/app/services/oidc_client.py src/app/services/sso_service.py src/app/routes/sso_routes.py tests/test_services/test_oidc_client.py tests/test_services/test_sso_service.py tests/test_routes/test_sso_routes.py`

- [ ] **Step 3: Fix any issues found**

- [ ] **Step 4: Final commit (if any lint fixes)**

```bash
git add -u
git commit -m "style(oidc): lint fixes"
```

---

## Spec Coverage Checklist

| Spec Requirement (Section 7) | Task |
|------------------------------|------|
| Authorization Code + PKCE flow | Task 5 (PKCE), Task 8 (full callback) |
| OIDC discovery (`.well-known`) | Task 2 |
| Token exchange (code → tokens) | Task 3 |
| Userinfo fetch | Task 4 |
| Extract claims (email, groups, name) | Task 8 (callback extracts from userinfo) |
| Create or link user in DB | Task 6 (provision_sso_user) |
| Group-to-team mapping | Task 7 |
| Issue own JWT (access + refresh) | Task 8 (calls create_tokens) |
| Redirect to dashboard with tokens | Task 8 |
| allowed_domains enforcement | Task 9 |
| Google, Azure AD, Okta, Generic OIDC | All use same OIDCClient — provider-agnostic |
| `auto_create_user` flag | Task 6 (provision always creates; flag checked in callback) |

## What's NOT in this plan (intentionally deferred)

- **ID token signature validation via JWKS** — requires fetching IdP's public keys and verifying JWT signature. Adds complexity, can be a follow-up. We rely on the access_token + userinfo endpoint for claims instead.
- **RS256 JWT signing for our tokens** — spec mentions it for SSO but HS256 works fine and is simpler. Can be added later if needed.
- **Keycloak testcontainer integration test** — decided to use respx for this plan. Keycloak e2e will be a separate follow-up.
