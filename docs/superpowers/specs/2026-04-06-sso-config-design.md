# SSO Config + OAuth2 Stub Design

**Date:** 2026-04-06
**Status:** Draft

## Overview

Per-org SSO configuration management with encrypted client secrets, plus a provider interface for the OAuth2 authorize/callback flow. The actual OIDC token exchange is stubbed — the interface is in place for real providers to be plugged in later.

## Scope

**In scope:**
- SSO config CRUD (create, read, delete) — 3 endpoints
- OAuth2 authorize endpoint (builds redirect URL) — 1 endpoint
- OAuth2 callback endpoint (stub, returns 501) — 1 endpoint
- `client_secret` encrypted at rest via AES-256-GCM (`app.auth.crypto`)
- `client_secret` masked in API responses

**Out of scope (deferred):**
- Real OIDC discovery (`.well-known/openid-configuration`)
- Real token exchange with IdPs
- User auto-provisioning on first SSO login
- Group-to-team mapping logic
- SCIM v2

## Components

### 1. SSO Config Service (`src/app/services/sso_service.py`)

```python
async def create_sso_config(
    db, org_id, provider, client_id, client_secret, issuer_url,
    allowed_domains=None, group_to_team_mapping=None,
    auto_create_user=True, default_role="member",
) -> SSOConfig
    # Encrypts client_secret before storage
    # Raises DuplicateError if org already has a config (unique constraint on org_id)

async def get_sso_config(db, org_id) -> SSOConfig | None
    # Returns config with client_secret_encrypted (not decrypted)

async def delete_sso_config(db, org_id) -> bool
```

### 2. SSO Routes (`src/app/routes/sso_routes.py`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/sso/config` | proxy_admin | Create SSO config for an org |
| GET | `/sso/config/{org_id}` | proxy_admin | Read config (secret masked) |
| DELETE | `/sso/config/{org_id}` | proxy_admin | Delete config |
| GET | `/sso/authorize` | none | Start OAuth2 flow — redirect to IdP |
| GET | `/sso/callback` | none | IdP callback — stub (501) |

### 3. Wire Schemas

**`wire_in/sso.py`:**
```python
class SSOConfigCreate(BaseModel):
    org_id: uuid.UUID
    provider: str           # "google", "azure_ad", "okta", "oidc"
    client_id: str
    client_secret: str      # plaintext — service encrypts before storage
    issuer_url: str
    allowed_domains: list[str] | None = None
    group_to_team_mapping: dict | None = None
    auto_create_user: bool = True
    default_role: str = "member"
```

**`wire_out/sso.py`:**
```python
class SSOConfigResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    provider: str
    client_id: str
    client_secret: str      # always "***" — never expose
    issuer_url: str
    allowed_domains: list | None
    group_to_team_mapping: dict | None
    auto_create_user: bool
    default_role: str
    is_active: bool
    created_at: datetime
```

### 4. OAuth2 Authorize Flow

`GET /sso/authorize?org_id={org_id}`

1. Look up `SSOConfig` for the org
2. Build the authorize URL: `{issuer_url}/authorize?client_id={client_id}&redirect_uri={callback_url}&response_type=code&scope=openid email profile&state={random_state}`
3. Return `RedirectResponse` to the authorize URL

The `state` parameter is a random token stored temporarily (in-memory dict with TTL) to prevent CSRF.

### 5. OAuth2 Callback (stub)

`GET /sso/callback?code={code}&state={state}`

1. Validate `state` against stored value
2. Return HTTP 501 with `{"detail": "OIDC token exchange not yet implemented"}`

When implemented later, this will:
- Exchange `code` for tokens via `httpx.post(token_endpoint, ...)`
- Extract claims (email, groups, name)
- Create or link user
- Issue JWT pair
- Redirect to dashboard

## Data Flow

```
Admin creates config → POST /sso/config → encrypt(client_secret) → store in DB

User starts SSO → GET /sso/authorize?org_id=X → lookup config → redirect to IdP

IdP callback → GET /sso/callback?code=Y&state=Z → validate state → (stub: 501)
```

## Security

- `client_secret` encrypted at rest with AES-256-GCM via `app.auth.crypto.encrypt()`
- `client_secret` never returned in API responses — always masked as `"***"`
- `state` parameter prevents CSRF in OAuth2 flow
- Config CRUD restricted to `proxy_admin` role
- Authorize/callback endpoints are public (no auth required — that's the point of SSO)

## Testing

- Create config → verify `client_secret_encrypted` in DB is not plaintext
- Read config → verify response has `client_secret: "***"`
- Delete config → verify gone
- Duplicate org config → 409
- Authorize → verify redirect URL structure
- Callback with invalid state → 400
- Callback with valid state → 501
- Non-admin cannot create config → 403
