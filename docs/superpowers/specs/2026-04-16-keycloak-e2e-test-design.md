# Keycloak OIDC E2E Test — Design Spec

**Date:** 2026-04-16
**Status:** Approved, ready for implementation plan
**Context:** Sub-Project 1 (Auth System), deferred item #2 — real Keycloak e2e test

## Goal

Add a single end-to-end test that exercises the full OIDC authorization-code flow against a real Keycloak server running in a testcontainer. Complements the existing `respx`-mocked unit tests (299 lines service + 336 lines routes + `test_oidc_client.py`) by proving the protocol works against a real IdP, not just our parsing logic.

**Non-goals:**
- Multiple scenarios (domain rejection, group mapping) — already covered by respx mocks.
- Replacing existing mocked tests.
- Testing Keycloak's behavior itself.

## Scope

One test: `tests/e2e/test_sso_keycloak.py::test_oidc_happy_path`.

Covered end-to-end in a single run:
- OIDC discovery document fetch (`OIDCClient.discover`)
- PKCE `code_challenge` accepted by Keycloak
- Authorization code exchange for tokens (client_secret + PKCE verifier)
- Userinfo endpoint parsing (email, sub, name)
- Domain validation against `allowed_domains`
- User provisioning + org membership creation
- Internal JWT issuance returned via dashboard redirect

## Design

### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  pytest session (scope=session)                              │
│                                                              │
│   ┌──────────────────┐   ┌──────────────────────────────┐   │
│   │ Keycloak         │   │ FastAPI app on uvicorn       │   │
│   │ testcontainer    │   │ (thread, 127.0.0.1:<port>)   │   │
│   │ realm=litellm    │◀──│ base_url overridden          │   │
│   │ client=app       │   └──────────────────────────────┘   │
│   │ user=alice       │              ▲                        │
│   └──────────────────┘              │                        │
│            ▲                        │                        │
│            │                        │                        │
│   ┌────────┴────────────────────────┴────────────────┐     │
│   │ Playwright (chromium headless)                    │     │
│   │  1. GET /sso/authorize?org_id=...                 │     │
│   │  2. → redirected to Keycloak login                │     │
│   │  3. fill form, submit                             │     │
│   │  4. Keycloak redirects to /sso/callback?code=...  │     │
│   │  5. app exchanges code (server-to-server)         │     │
│   │  6. app redirects to dashboard with JWTs          │     │
│   │  7. assert URL contains access_token + refresh    │     │
│   └────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### Dependencies

Added under `[project.optional-dependencies] e2e` in `pyproject.toml`:
- `playwright`
- `pytest-playwright`
- `testcontainers[keycloak]`

Installed via `uv sync --extra e2e`. Main `uv sync` stays fast (no ~200MB browser binaries for devs not running e2e).

One-time CI / dev setup: `playwright install chromium`.

### Test gating

Marker-based, not path-based (but file lives under `tests/e2e/` for locality).

- Register `e2e` marker in `pyproject.toml` `[tool.pytest.ini_options]`.
- Default `pytest` run collects but does not execute `@pytest.mark.e2e` tests (via `addopts = "-m 'not e2e'"`).
- `pytest -m e2e` runs them.

Keeps the 152-test fast loop untouched.

### Fixtures (`tests/e2e/conftest.py`)

Session-scoped (boot once per run):

| Fixture | Purpose |
|---|---|
| `keycloak_container` | `KeycloakContainer("quay.io/keycloak/keycloak:24.0")` started with `--import-realm` and a mounted `tests/e2e/fixtures/litellm-realm.json`. Yields the container. |
| `keycloak_issuer_url` | `f"{container.get_base_url()}/realms/litellm"` |
| `app_server` | Starts `uvicorn.Server` in a background thread, bound to `127.0.0.1:<free_port>`. Overrides `settings.base_url`. Yields the base URL. Graceful shutdown on teardown. |
| `browser` / `page` | Provided by `pytest-playwright` (chromium, headless). |

Function-scoped:

| Fixture | Purpose |
|---|---|
| `e2e_db_session` | Yields a session bound to the app's real engine (no savepoint wrapper). Commits are real. |
| `sso_org` | Creates Org + proxy_admin User + SSOConfig pointing `issuer_url → keycloak_issuer_url`, `client_id=app`, `client_secret=secret`, `allowed_domains=["example.com"]`. Committed real. |
| `_e2e_db_cleanup` | Autouse; after each test runs `TRUNCATE ... CASCADE` on the tables touched by the flow (users, org_memberships, team_memberships, sso_configs, orgs, teams, refresh_tokens, audit_log). |

**DB isolation decision — why e2e can't use the existing savepoint pattern:**
The existing `db_session` fixture uses a single connection + savepoints, rolling everything back at test end. That works when all DB access flows through `app.dependency_overrides[get_db]` in the same event loop. E2e is different: uvicorn runs the app in a background thread with its own engine and session factory, so:
- Data the test commits on its session is not visible on the app's connections.
- Data the app commits (user provisioning) is not visible on the test's session.

So e2e uses real commits on a shared engine and truncates between tests. Slower, but it's the only correct choice when the app runs in its own process-like context.

**State store note:** `sso_service._state_store` is a module-level `TTLCache`. Because the app runs in-process (background thread, same Python interpreter), the `/authorize` call and `/callback` call share memory — state propagation works without change.

**Why session-scoped infra:** Keycloak boot ~15s, uvicorn startup ~200ms. Function-scoped would multiply by N tests for no correctness gain. Test-level isolation is provided by TRUNCATE between tests.

### Realm JSON (`tests/e2e/fixtures/litellm-realm.json`)

```json
{
  "realm": "litellm",
  "enabled": true,
  "sslRequired": "none",
  "clients": [{
    "clientId": "app",
    "enabled": true,
    "secret": "secret",
    "publicClient": false,
    "standardFlowEnabled": true,
    "redirectUris": ["http://127.0.0.1:*/sso/callback"],
    "webOrigins": ["+"],
    "protocol": "openid-connect"
  }],
  "users": [{
    "username": "alice",
    "email": "alice@example.com",
    "emailVerified": true,
    "enabled": true,
    "firstName": "Alice",
    "lastName": "Example",
    "credentials": [
      { "type": "password", "value": "alice-password", "temporary": false }
    ]
  }]
}
```

Notes:
- `redirectUris` uses `*` wildcard on the port because the app's uvicorn port is random per session.
- `sslRequired: "none"` because we're on plain HTTP localhost.
- `emailVerified: true` so Keycloak issues the `email` claim without a consent-screen interstitial.
- No group-to-team mapping in the realm — out of scope for the happy-path test.

### The test

```python
# tests/e2e/test_sso_keycloak.py
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.membership import OrgMembership

@pytest.mark.e2e
async def test_oidc_happy_path(page, app_server, sso_org, e2e_db_session):
    await page.goto(f"{app_server}/sso/authorize?org_id={sso_org.id}")

    await page.fill("input[name=username]", "alice")
    await page.fill("input[name=password]", "alice-password")
    await page.click("input[type=submit]")

    await page.wait_for_url(lambda url: "access_token=" in url)

    assert "access_token=" in page.url
    assert "refresh_token=" in page.url

    result = await e2e_db_session.execute(
        select(User).where(User.email == "alice@example.com")
    )
    user = result.scalar_one()
    assert user.sso_provider == "keycloak"
    assert user.sso_subject

    memberships_result = await e2e_db_session.execute(
        select(OrgMembership).where(OrgMembership.user_id == user.id)
    )
    assert memberships_result.scalar_one().org_id == sso_org.id
```

### Error handling / flakiness controls

- `page.wait_for_url(...)` default timeout 30s — sufficient for Keycloak's token endpoint latency.
- Uvicorn thread: `daemon=True`, explicit `server.should_exit = True` on fixture teardown.
- Keycloak readiness: use testcontainers' wait-for-logs or HTTP health check on `/realms/litellm/.well-known/openid-configuration` before the first test runs.
- Playwright browser: single shared browser, one context per test (default pytest-playwright behavior).

### File layout

```
tests/
├── e2e/
│   ├── __init__.py                     (new)
│   ├── conftest.py                     (new — keycloak_container, app_server, sso_org fixtures)
│   ├── fixtures/
│   │   └── litellm-realm.json          (new — realm import)
│   └── test_sso_keycloak.py            (new — the one test)
└── conftest.py                         (unchanged — existing postgres/redis fixtures still session-scoped)
```

### Changes to existing files

- `pyproject.toml`: add `[project.optional-dependencies] e2e` group, register `e2e` marker, set `addopts = "-m 'not e2e'"`.
- No changes to `src/app/` code. If any change proves necessary during implementation, it's a red flag that our implementation has test-unfriendly coupling — surface it explicitly rather than quietly adjust.

## Testing strategy layered

| Layer | Tool | Count | What it proves |
|---|---|---|---|
| Unit — service | respx | ~20 tests | Our service handles mocked IdP responses correctly |
| Unit — routes | respx | ~10 tests | Our HTTP surface maps OIDC responses to correct status codes |
| Unit — OIDCClient | respx | ~5 tests | Our client parses discovery + token + userinfo responses |
| **E2E — real IdP** | **Keycloak + Playwright** | **1 test** | **The OIDC protocol actually works against a real IdP** |

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Keycloak container boot time pads CI | Session-scoped fixture; one boot per session |
| Playwright flakiness on Keycloak login HTML changes | Pinned Keycloak version `24.0`. Document upgrade requires regenerating selectors. |
| Random app port races | Use `socket.bind(("127.0.0.1", 0))` to reserve, then pass to uvicorn |
| State store leaks between tests (if count grows later) | TTLCache TTL=600s; a second test within the same session could collide only if it reuses the same state token, which is `secrets.token_urlsafe(32)` — collision probability negligible |

## Out of scope / deferred

- Domain-rejection e2e (already in respx tests).
- Group-to-team mapping e2e (already in respx tests).
- SCIM v2 (spec deferred to v2).
- Object-level permissions (blocked on proxy routes, Sub-Project 2).

## Open questions

None. All design decisions resolved in the brainstorming session.
