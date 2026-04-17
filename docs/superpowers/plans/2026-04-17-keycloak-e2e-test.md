# Keycloak OIDC E2E Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single end-to-end test that exercises the full OIDC flow (/sso/authorize → Keycloak login → /sso/callback → JWT issuance) against a real Keycloak server running in a testcontainer, driven by a headless Playwright browser.

**Architecture:** A new `tests/e2e/` package with its own `conftest.py` holds session-scoped fixtures that (1) boot a Keycloak container with a pre-imported realm, (2) run our FastAPI app under uvicorn in a background thread on a random port, and (3) provide a real DB session on the existing postgres testcontainer. A single `@pytest.mark.e2e` test drives Playwright through the flow and asserts both the final redirect URL and the provisioned DB state.

**Tech Stack:**
- `playwright` + `pytest-playwright` — chromium headless browser automation
- `testcontainers[keycloak]` — Keycloak 24.0 container with realm import
- `uvicorn` (already a dep) — background thread HTTP server for the app
- `pytest.mark.e2e` marker + `addopts = "-m 'not e2e'"` — gating

**Dependencies:** Completes Sub-Project 1 (Auth System) deferred item #2. Design spec: `docs/superpowers/specs/2026-04-16-keycloak-e2e-test-design.md`.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `pyproject.toml` | Add `[project.optional-dependencies] e2e`, register `e2e` marker, set `addopts` to exclude marker by default |
| Create | `tests/e2e/__init__.py` | Empty — marks directory as a pytest package |
| Create | `tests/e2e/fixtures/litellm-realm.json` | Keycloak realm: 1 client (`app`), 1 user (`alice`), wildcard port redirect URI |
| Create | `tests/e2e/conftest.py` | Session-scoped `keycloak_container`, `keycloak_issuer_url`, `app_server`; function-scoped `e2e_db_session`, `sso_org`, autouse `_e2e_db_cleanup` |
| Create | `tests/e2e/test_sso_keycloak.py` | The one `@pytest.mark.e2e` happy-path test |
| Modify | `.claude/projects/-Users-makoto-sandiga-dev-me-makoto-lite-llm/memory/project_progress.md` | Bump ola/test counts |

---

### Task 1: Add optional e2e dependencies + register marker

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the `[project.optional-dependencies] e2e` group**

Open `pyproject.toml`. After the existing `dependencies = [...]` block (around line 26), and before `[dependency-groups]`, add:

```toml
[project.optional-dependencies]
e2e = [
    "playwright>=1.48.0",
    "pytest-playwright>=0.6.2",
    "testcontainers[keycloak]>=4.14.2",
]
```

- [ ] **Step 2: Register the `e2e` marker and set the default-exclude addopts**

Modify the existing `[tool.pytest.ini_options]` block (around line 46–52). Replace with:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
addopts = "-m 'not e2e'"
markers = [
    "e2e: full end-to-end tests that boot containers and a browser; run with `pytest -m e2e`",
]
filterwarnings = [
    "ignore::DeprecationWarning:testcontainers",
]
```

- [ ] **Step 3: Install the e2e extra**

Run:

```bash
uv sync --extra e2e
```

Expected: installs playwright, pytest-playwright, and testcontainers[keycloak] without errors. `uv.lock` updates.

- [ ] **Step 4: Verify default pytest run still passes and excludes e2e**

```bash
uv run pytest --collect-only -q 2>&1 | tail -5
```

Expected output ends with `152 tests collected` (same as before — nothing e2e exists yet).

```bash
uv run pytest -v 2>&1 | tail -5
```

Expected: `152 passed` (same count as the previous green baseline).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add [e2e] optional deps and register e2e pytest marker"
```

---

### Task 2: Install Playwright's chromium browser

**Files:**
- None (installs to user cache)

- [ ] **Step 1: Install chromium via playwright**

```bash
uv run playwright install chromium
```

Expected: downloads chromium (~170 MB) to `~/Library/Caches/ms-playwright/` (macOS) or `~/.cache/ms-playwright/` (Linux). Takes 30–90s depending on network.

- [ ] **Step 2: Verify the browser binary loads**

```bash
uv run python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(headless=True); b.close(); p.stop(); print('chromium ok')"
```

Expected output: `chromium ok`.

No commit — this is a one-time local / CI setup step. Document it in the Task 9 memory note.

---

### Task 3: Create the e2e directory skeleton and realm JSON fixture

**Files:**
- Create: `tests/e2e/__init__.py`
- Create: `tests/e2e/fixtures/litellm-realm.json`

- [ ] **Step 1: Create empty `__init__.py`**

```bash
mkdir -p tests/e2e/fixtures
touch tests/e2e/__init__.py
```

- [ ] **Step 2: Write the realm JSON**

Create `tests/e2e/fixtures/litellm-realm.json` with exactly this content:

```json
{
  "realm": "litellm",
  "enabled": true,
  "sslRequired": "none",
  "clients": [
    {
      "clientId": "app",
      "enabled": true,
      "secret": "secret",
      "publicClient": false,
      "standardFlowEnabled": true,
      "directAccessGrantsEnabled": false,
      "redirectUris": ["http://127.0.0.1:*/sso/callback"],
      "webOrigins": ["+"],
      "protocol": "openid-connect"
    }
  ],
  "users": [
    {
      "username": "alice",
      "email": "alice@example.com",
      "emailVerified": true,
      "enabled": true,
      "firstName": "Alice",
      "lastName": "Example",
      "credentials": [
        {
          "type": "password",
          "value": "alice-password",
          "temporary": false
        }
      ]
    }
  ]
}
```

- [ ] **Step 3: Verify JSON is valid**

```bash
uv run python -c "import json; json.load(open('tests/e2e/fixtures/litellm-realm.json')); print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/__init__.py tests/e2e/fixtures/litellm-realm.json
git commit -m "test(e2e): add keycloak realm JSON fixture (litellm realm, 1 client, 1 user)"
```

---

### Task 4: Keycloak container fixture

**Files:**
- Create: `tests/e2e/conftest.py`
- Create: `tests/e2e/test_smoke_keycloak.py` (temporary smoke test — removed in Task 8)

- [ ] **Step 1: Write the initial conftest with the Keycloak fixture**

Create `tests/e2e/conftest.py`:

```python
"""E2E fixtures — Keycloak, uvicorn app server, real DB session, realm import.

Activated only via `pytest -m e2e` per the addopts in pyproject.toml.
"""

import os
import sys
from pathlib import Path

import pytest
from testcontainers.keycloak import KeycloakContainer

# Same Colima override pattern as the top-level conftest.
if sys.platform == "darwin":
    os.environ.setdefault(
        "DOCKER_HOST", "unix:///Users/makoto.sandiga/.colima/default/docker.sock"
    )
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

REALM_FIXTURE = (
    Path(__file__).parent / "fixtures" / "litellm-realm.json"
).resolve()


@pytest.fixture(scope="session")
def keycloak_container():
    """Boot Keycloak 24 with the litellm realm pre-imported.

    Mounts the realm JSON at /opt/keycloak/data/import/ and adds
    --import-realm to the start command.
    """
    container = (
        KeycloakContainer("quay.io/keycloak/keycloak:24.0")
        .with_volume_mapping(
            str(REALM_FIXTURE),
            "/opt/keycloak/data/import/litellm-realm.json",
            mode="ro",
        )
        .with_command("start-dev --import-realm")
    )
    with container as started:
        yield started


@pytest.fixture(scope="session")
def keycloak_issuer_url(keycloak_container) -> str:
    """URL of the imported litellm realm."""
    base = keycloak_container.get_base_url().rstrip("/")
    return f"{base}/realms/litellm"
```

- [ ] **Step 2: Write a smoke test that hits Keycloak's discovery doc**

Create `tests/e2e/test_smoke_keycloak.py`:

```python
import httpx
import pytest


@pytest.mark.e2e
def test_keycloak_discovery_doc(keycloak_issuer_url):
    resp = httpx.get(
        f"{keycloak_issuer_url}/.well-known/openid-configuration",
        timeout=10,
    )
    assert resp.status_code == 200
    doc = resp.json()
    assert doc["issuer"].endswith("/realms/litellm")
    assert "token_endpoint" in doc
    assert "userinfo_endpoint" in doc
```

- [ ] **Step 3: Run the smoke test**

```bash
uv run pytest -m e2e tests/e2e/test_smoke_keycloak.py -v
```

Expected: 1 passed (boot takes ~15–25s the first time).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/conftest.py tests/e2e/test_smoke_keycloak.py
git commit -m "test(e2e): add keycloak_container fixture with realm import and smoke test"
```

---

### Task 5: App server fixture (uvicorn in a background thread)

**Files:**
- Modify: `tests/e2e/conftest.py`
- Modify: `tests/e2e/test_smoke_keycloak.py` (add app-server smoke assertion)

- [ ] **Step 1: Append the app_server fixture to conftest**

Add to the bottom of `tests/e2e/conftest.py`:

```python
import socket
import threading
import time

import httpx
import uvicorn


def _reserve_free_port() -> int:
    """Bind to 127.0.0.1:0, read the assigned port, release the socket."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def app_server(postgres_container):  # postgres_container comes from top-level conftest
    """Start uvicorn in a background thread; yield the base URL.

    Depends on postgres_container so the app's engine has a reachable DB.
    Overrides `DATABASE_URL` env var BEFORE the first `from app.*` import by
    patching app.database.engine + AsyncSessionLocal after the fact.
    """
    # 1. Point the app's engine at the postgres testcontainer.
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app import database

    pg_url = postgres_container.get_connection_url().replace("psycopg2", "asyncpg")
    new_engine = create_async_engine(pg_url, echo=False)
    new_sessionmaker = async_sessionmaker(
        new_engine, expire_on_commit=False
    )
    old_engine = database.engine
    old_sessionmaker = database.AsyncSessionLocal
    database.engine = new_engine
    database.AsyncSessionLocal = new_sessionmaker

    # 2. Create tables on the new engine (idempotent — top-level conftest
    #    already did this, but only on its own `db_engine`).
    import asyncio
    from app.models import Base

    async def _create():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())

    # 3. Override settings.base_url to point at our soon-to-start uvicorn.
    from app.config import settings
    from app.main import app

    port = _reserve_free_port()
    base_url = f"http://127.0.0.1:{port}"
    old_base_url = settings.base_url
    settings.base_url = base_url

    # 4. Start uvicorn in a thread.
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # 5. Wait for /health to return 200 (max 10s).
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base_url}/health", timeout=1)
            if r.status_code == 200:
                break
        except httpx.RequestError:
            pass
        time.sleep(0.1)
    else:
        server.should_exit = True
        raise RuntimeError("uvicorn app_server did not become ready within 10s")

    yield base_url

    # Teardown: shut down server, restore engine.
    server.should_exit = True
    thread.join(timeout=5)
    settings.base_url = old_base_url
    database.engine = old_engine
    database.AsyncSessionLocal = old_sessionmaker

    async def _dispose():
        await new_engine.dispose()

    asyncio.run(_dispose())
```

- [ ] **Step 2: Add a smoke check to the existing test file**

Modify `tests/e2e/test_smoke_keycloak.py` — add this test at the bottom:

```python
@pytest.mark.e2e
def test_app_server_health(app_server):
    resp = httpx.get(f"{app_server}/health", timeout=5)
    assert resp.status_code == 200
```

- [ ] **Step 3: Run both smoke tests**

```bash
uv run pytest -m e2e tests/e2e/test_smoke_keycloak.py -v
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/conftest.py tests/e2e/test_smoke_keycloak.py
git commit -m "test(e2e): add app_server fixture (uvicorn in thread, free port, engine override)"
```

---

### Task 6: Real DB session fixture + per-test TRUNCATE cleanup

**Files:**
- Modify: `tests/e2e/conftest.py`
- Modify: `tests/e2e/test_smoke_keycloak.py` (add DB smoke)

- [ ] **Step 1: Append DB fixtures to conftest**

Add to the bottom of `tests/e2e/conftest.py`:

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def e2e_db_session(app_server) -> AsyncSession:
    """A real session on the app's (now-overridden) engine.

    No savepoint wrapper — commits are real. Relies on _e2e_db_cleanup
    (autouse) to TRUNCATE after each test.
    """
    from app import database

    async with database.AsyncSessionLocal() as session:
        yield session


_TABLES_TO_TRUNCATE = [
    "audit_log",
    "refresh_tokens",
    "team_memberships",
    "org_memberships",
    "sso_configs",
    "api_keys",
    "users",
    "teams",
    "orgs",
    "budgets",
]


@pytest.fixture(autouse=True)
async def _e2e_db_cleanup(app_server):
    """After each test, TRUNCATE all tables the flow touches.

    CASCADE handles FK dependencies. Order in _TABLES_TO_TRUNCATE is
    informational — TRUNCATE ... CASCADE handles it regardless.
    """
    yield
    from app import database

    async with database.engine.begin() as conn:
        tables = ", ".join(_TABLES_TO_TRUNCATE)
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
```

- [ ] **Step 2: Add a DB smoke test**

Modify `tests/e2e/test_smoke_keycloak.py` — add:

```python
from sqlalchemy import select


@pytest.mark.e2e
async def test_db_session_round_trip(e2e_db_session):
    from app.models.budget import Budget
    from app.models.org import Org

    budget = Budget(max_budget_usd=100)
    e2e_db_session.add(budget)
    await e2e_db_session.flush()

    org = Org(name="Test Org", slug="test-org-e2e", budget_id=budget.id)
    e2e_db_session.add(org)
    await e2e_db_session.commit()

    result = await e2e_db_session.execute(
        select(Org).where(Org.slug == "test-org-e2e")
    )
    assert result.scalar_one().name == "Test Org"
```

- [ ] **Step 3: Add a cleanup-verifying test (must come after the round-trip test alphabetically; pytest runs in file order, so add it AFTER the round-trip)**

Modify `tests/e2e/test_smoke_keycloak.py` — add at the bottom:

```python
@pytest.mark.e2e
async def test_db_cleanup_between_tests(e2e_db_session):
    from app.models.org import Org

    result = await e2e_db_session.execute(
        select(Org).where(Org.slug == "test-org-e2e")
    )
    assert result.scalar_one_or_none() is None, (
        "Truncate cleanup should have removed the previous test's org"
    )
```

- [ ] **Step 4: Run smoke tests**

```bash
uv run pytest -m e2e tests/e2e/test_smoke_keycloak.py -v
```

Expected: 4 passed. The cleanup test confirms TRUNCATE ran between tests.

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/conftest.py tests/e2e/test_smoke_keycloak.py
git commit -m "test(e2e): add e2e_db_session + autouse TRUNCATE cleanup"
```

---

### Task 7: `sso_org` fixture

**Files:**
- Modify: `tests/e2e/conftest.py`
- Modify: `tests/e2e/test_smoke_keycloak.py` (add sso_org smoke)

- [ ] **Step 1: Append `sso_org` fixture**

Add to the bottom of `tests/e2e/conftest.py`:

```python
import uuid
from dataclasses import dataclass


@dataclass
class E2ESSOOrg:
    id: uuid.UUID
    slug: str


@pytest.fixture
async def sso_org(e2e_db_session, keycloak_issuer_url) -> E2ESSOOrg:
    """Create Org + Budget + SSOConfig pointing at the Keycloak realm.

    Returns a small value object so tests can reference the org's id/slug
    without holding onto an ORM instance (which would detach after
    session scope ends).
    """
    from app.models.budget import Budget
    from app.models.org import Org
    from app.services.sso_service import create_sso_config

    budget = Budget(max_budget_usd=1000)
    e2e_db_session.add(budget)
    await e2e_db_session.flush()

    slug = f"sso-test-{uuid.uuid4().hex[:8]}"
    org = Org(name="SSO Test Org", slug=slug, budget_id=budget.id)
    e2e_db_session.add(org)
    await e2e_db_session.commit()
    await e2e_db_session.refresh(org)

    await create_sso_config(
        e2e_db_session,
        org_id=org.id,
        provider="keycloak",
        client_id="app",
        client_secret="secret",
        issuer_url=keycloak_issuer_url,
        allowed_domains=["example.com"],
        group_to_team_mapping=None,
        auto_create_user=True,
        default_role="member",
    )

    return E2ESSOOrg(id=org.id, slug=slug)
```

- [ ] **Step 2: Add a smoke test**

Modify `tests/e2e/test_smoke_keycloak.py` — add at the bottom:

```python
@pytest.mark.e2e
async def test_sso_org_fixture_creates_config(sso_org, e2e_db_session):
    from app.models.sso_config import SSOConfig

    result = await e2e_db_session.execute(
        select(SSOConfig).where(SSOConfig.org_id == sso_org.id)
    )
    config = result.scalar_one()
    assert config.provider == "keycloak"
    assert config.client_id == "app"
    assert config.allowed_domains == ["example.com"]
```

- [ ] **Step 3: Run smoke tests**

```bash
uv run pytest -m e2e tests/e2e/test_smoke_keycloak.py -v
```

Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/conftest.py tests/e2e/test_smoke_keycloak.py
git commit -m "test(e2e): add sso_org fixture (Org + Budget + SSOConfig pointing at Keycloak)"
```

---

### Task 8: The real e2e test — full OIDC flow via Playwright

**Files:**
- Create: `tests/e2e/test_sso_keycloak.py`
- Delete: `tests/e2e/test_smoke_keycloak.py`

- [ ] **Step 1: Write the e2e test**

Create `tests/e2e/test_sso_keycloak.py`:

```python
"""E2E: real OIDC flow against Keycloak, driven by Playwright."""

import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select

from app.models.membership import OrgMembership
from app.models.user import User


@pytest.mark.e2e
async def test_oidc_happy_path(app_server, sso_org, e2e_db_session):
    """End-to-end: start authorize, log in at Keycloak, land on dashboard
    redirect with JWT tokens, verify user+membership in DB.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        # 1. Kick off SSO flow — follows redirect to Keycloak login page.
        await page.goto(
            f"{app_server}/sso/authorize?org_id={sso_org.id}"
        )

        # 2. Fill Keycloak login form. Keycloak 24 field ids: username, password.
        await page.fill("input[name=username]", "alice")
        await page.fill("input[name=password]", "alice-password")
        await page.click("input[type=submit]")

        # 3. Wait until the browser lands on the dashboard redirect URL
        #    (which contains access_token in its query string).
        await page.wait_for_url(
            lambda url: "access_token=" in url, timeout=30_000
        )

        # 4. Assert on the final URL.
        final_url = page.url
        assert "access_token=" in final_url
        assert "refresh_token=" in final_url

        await browser.close()

    # 5. Assert DB state — user provisioned, membership created.
    user_result = await e2e_db_session.execute(
        select(User).where(User.email == "alice@example.com")
    )
    user = user_result.scalar_one()
    assert user.sso_provider == "keycloak"
    assert user.sso_subject  # non-empty subject from the IdP
    assert user.name == "Alice Example" or user.name == "alice"  # claim value

    membership_result = await e2e_db_session.execute(
        select(OrgMembership).where(OrgMembership.user_id == user.id)
    )
    membership = membership_result.scalar_one()
    assert membership.org_id == sso_org.id
```

- [ ] **Step 2: Delete the temporary smoke test file**

```bash
rm tests/e2e/test_smoke_keycloak.py
```

- [ ] **Step 3: Run the e2e test**

```bash
uv run pytest -m e2e tests/e2e/test_sso_keycloak.py -v
```

Expected: `1 passed` in ~25–45s (Keycloak boot + browser launch + full flow).

- [ ] **Step 4: Run the default (non-e2e) suite to verify it still excludes e2e**

```bash
uv run pytest -v 2>&1 | tail -3
```

Expected: `152 passed` (unchanged; the `addopts = "-m 'not e2e'"` hides the e2e test).

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/test_sso_keycloak.py tests/e2e/test_smoke_keycloak.py
git commit -m "test(e2e): add keycloak OIDC happy-path e2e test (Playwright + real IdP)"
```

Note on the `git add` line: `git add` also stages the deletion of `test_smoke_keycloak.py`.

---

### Task 9: Update progress notes

**Files:**
- Modify: `/Users/makoto.sandiga/.claude/projects/-Users-makoto-sandiga-dev-me-makoto-lite-llm/memory/project_progress.md`

- [ ] **Step 1: Update the auto-memory progress note**

Replace the "Remaining Work" section (around line 28–32) with:

```markdown
### Auth System — Remaining Work

1. **Cache invalidation gap:** FIXED in PR #13 (key_service.block_key/rotate_key now call invalidate_api_key_cache).
2. **Org-level model access:** FIXED in PR #13 (resolve_model_access now checks org-level allowed_models).
3. **Keycloak e2e test:** DONE — `tests/e2e/test_sso_keycloak.py` (1 test, @pytest.mark.e2e gated).
4. **Object-level permissions:** Spec section 3.5 deferred — needs CRUD endpoints + proxy routes first.

Run e2e: `uv sync --extra e2e && uv run playwright install chromium && uv run pytest -m e2e`
```

Also update the header date (line 7) to `2026-04-17` and the PR/test counts:
- Tests: 135 → 153 (152 default + 1 e2e)
- PRs: 12 → 15 merged (after this lands)

- [ ] **Step 2: Update MEMORY.md one-liner**

In `/Users/makoto.sandiga/.claude/projects/-Users-makoto-sandiga-dev-me-makoto-lite-llm/memory/MEMORY.md`, update the progress line to:

```
- [Project Progress](project_progress.md) — Auth system done incl. Keycloak e2e, 153 tests, 15 PRs, next: Core SDK
```

- [ ] **Step 3: No git commit needed — memory files are outside the repo.**

---

## Self-Review

**Spec coverage:**
- ✅ 1 happy-path test — Task 8
- ✅ Playwright chromium headless — Task 2 + Task 8
- ✅ Realm-JSON import at boot — Task 3 + Task 4
- ✅ `@pytest.mark.e2e` gating — Task 1
- ✅ `[project.optional-dependencies] e2e` — Task 1
- ✅ Session-scoped Keycloak + app_server — Tasks 4 + 5
- ✅ Function-scoped e2e_db_session + autouse truncate — Task 6
- ✅ sso_org fixture — Task 7
- ✅ Asserts on final URL + DB state (user, sso_provider, sso_subject, org membership) — Task 8
- ✅ State store works across /authorize → /callback because app runs in-process (noted in Task 5's engine/settings override)
- ✅ Wildcard port in redirectUris matches random uvicorn port — Task 3

**Placeholder scan:** No TBD, TODO, "implement later", or generic "add error handling". Every step has exact code or exact commands.

**Type consistency:** `E2ESSOOrg(id, slug)` used in Task 7 and referenced in Task 8 (`sso_org.id`) — consistent. `app_server` yields a `str` (base URL) — used as `f"{app_server}/..."` in all tests. `e2e_db_session` is an `AsyncSession` — used with `.execute(select(...))` consistently.

**Known trade-off documented:** The `app.database.engine` monkeypatching in Task 5 is surgical but explicit. A cleaner alternative (setting `DATABASE_URL` env var before any app import) was rejected because the top-level `tests/conftest.py` already imports `app.database` before the e2e conftest loads.
