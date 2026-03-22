# Auth System Design — LiteLLM Recreation

**Date:** 2026-03-22
**Status:** Draft
**Stack:** Python + FastAPI + PostgreSQL + SQLAlchemy

## Overview

Complete authentication, authorization, and multi-tenant management system for an LLM proxy gateway. This is the foundational sub-project upon which all other features (core SDK, router, cache, dashboard, etc.) are built.

## Project Context

This is sub-project #1 (reordered) of a full LiteLLM recreation. The overall project follows a bottom-up approach:

1. **Proxy Server base + Auth Completo** (this spec)
2. Core SDK (3-5 providers: OpenAI, Anthropic, Google)
3. Router (round robin, lowest latency, lowest cost, fallback/retry)
4. Cache Layer (9 backends)
5. Spend & Budgets
6. Observability (OTel, Prometheus, Langfuse, Datadog, Slack)
7. Guardrails (framework + OpenAI moderation, Presidio, custom)
8. Advanced APIs (images, audio, fine-tuning, batches, files, realtime)
9. Dashboard UI (Next.js)

---

## 1. Data Model — Entity Hierarchy

### Hierarchy

```
Organization
  +-- Team
       +-- Project
            +-- API Key (Virtual Key)

User <--> Organization (via org_memberships, with role)
User <--> Team (via team_memberships, with role)
```

### Tables

#### `organizations`

| Column | Type | Description |
|---|---|---|
| id | UUID (PK) | |
| name | str | Organization name |
| slug | str (unique) | URL-friendly identifier |
| max_budget | float | null | Spending limit in USD |
| soft_budget | float | null | Alert threshold |
| tpm_limit | int | null | Tokens per minute |
| rpm_limit | int | null | Requests per minute |
| metadata | jsonb | Custom data |
| is_blocked | bool | Default false |
| created_at | datetime | |
| updated_at | datetime | |

#### `teams`

| Column | Type | Description |
|---|---|---|
| id | UUID (PK) | |
| org_id | UUID (FK -> organizations) | null | Parent org |
| name | str | Team name |
| allowed_models | jsonb | List of model names/wildcards |
| max_budget | float | null | |
| soft_budget | float | null | |
| tpm_limit | int | null | |
| rpm_limit | int | null | |
| max_parallel_requests | int | null | |
| budget_reset_period | str | null | "daily", "weekly", "30d" |
| metadata | jsonb | |
| is_blocked | bool | Default false |
| created_at | datetime | |
| updated_at | datetime | |

#### `projects`

| Column | Type | Description |
|---|---|---|
| id | UUID (PK) | |
| team_id | UUID (FK -> teams) | Parent team |
| name | str | Project name |
| allowed_models | jsonb | null | Inherits from team if null |
| metadata | jsonb | |
| created_at | datetime | |
| updated_at | datetime | |

**Note:** Projects are included in the data model for hierarchy completeness (keys can be scoped to a project, cascade deletion flows through them). Full project management endpoints are deferred to v2. In v1, projects are created implicitly when a key specifies a `project_id`, and listed/deleted only as part of team operations.

#### `users`

| Column | Type | Description |
|---|---|---|
| id | UUID (PK) | |
| email | str (unique) | |
| password_hash | str | null | bcrypt hash (null for SSO-only users) |
| name | str | null | |
| role | str | Global role: "proxy_admin", "member" |
| max_budget | float | null | Personal budget limit |
| spend | float | Accumulated spend, default 0 |
| is_blocked | bool | Default false |
| sso_provider | str | null | "google", "azure_ad", "okta", etc. |
| sso_subject | str | null | Subject ID from IdP |
| metadata | jsonb | |
| created_at | datetime | |
| updated_at | datetime | |

**Unique constraint:** `(sso_provider, sso_subject)` for SSO dedup.

#### `org_memberships`

| Column | Type | Description |
|---|---|---|
| id | UUID (PK) | |
| user_id | UUID (FK -> users) | |
| org_id | UUID (FK -> organizations) | |
| role | str | "org_admin", "member" |
| max_budget | float | null | Per-user budget within org |
| created_at | datetime | |

**Unique constraint:** `(user_id, org_id)`

#### `team_memberships`

| Column | Type | Description |
|---|---|---|
| id | UUID (PK) | |
| user_id | UUID (FK -> users) | |
| team_id | UUID (FK -> teams) | |
| role | str | "team_admin", "member" |
| max_budget | float | null | Per-user budget within team |
| created_at | datetime | |

**Unique constraint:** `(user_id, team_id)`

#### `api_keys`

| Column | Type | Description |
|---|---|---|
| id | UUID (PK) | |
| api_key_hash | str (unique) | SHA-256 hash of the key |
| key_prefix | str | First 8 chars (displayed in UI) |
| key_alias | str | null | Human-readable name |
| user_id | UUID (FK -> users) | Key owner |
| team_id | UUID (FK -> teams) | null | |
| org_id | UUID (FK -> organizations) | null | |
| project_id | UUID (FK -> projects) | null | |
| allowed_models | jsonb | ["gpt-4", "claude-*"] (wildcards supported) |
| max_budget | float | null | |
| soft_budget | float | null | |
| spend | float | Accumulated spend, default 0 |
| tpm_limit | int | null | |
| rpm_limit | int | null | |
| max_parallel_requests | int | null | |
| budget_reset_period | str | null | |
| expires_at | datetime | null | |
| auto_rotate | bool | Default false |
| rotation_interval_days | int | null | |
| last_rotated_at | datetime | null | |
| is_blocked | bool | Default false |
| metadata | jsonb | |
| created_at | datetime | |
| updated_at | datetime | |

**Key format:** `sk-{prefix_8chars}{random_32chars}`

#### `budgets`

Reusable budget configurations assignable to any entity via `budget_id` FK.

| Column | Type | Description |
|---|---|---|
| id | UUID (PK) | |
| name | str | Budget name |
| max_budget | float | null | |
| soft_budget | float | null | |
| tpm_limit | int | null | |
| rpm_limit | int | null | |
| max_parallel_requests | int | null | |
| budget_reset_period | str | null | Enum: "daily", "weekly", "monthly", "30d", "90d", "yearly" |
| created_at | datetime | |
| updated_at | datetime | |

**Linking:** The `organizations`, `teams`, `users`, and `api_keys` tables each have an optional `budget_id` (FK -> budgets) column. When set, the budget's limits override the entity's inline limits. Inline limits (`max_budget`, `tpm_limit`, etc.) remain on each entity for cases where a shared budget is not needed.

#### `object_permissions`

Fine-grained permissions on specific resources.

| Column | Type | Description |
|---|---|---|
| id | UUID (PK) | |
| entity_type | str | "user", "team", "api_key" |
| entity_id | UUID | |
| resource_type | str | "model", "mcp_server", "tool", "agent" |
| resource_id | str | |
| action | str | "allow", "deny" |
| created_at | datetime | |

**Unique constraint:** `(entity_type, entity_id, resource_type, resource_id, action)` — allows both allow and deny rules for the same entity+resource pair.

#### `access_groups`

| Column | Type | Description |
|---|---|---|
| id | UUID (PK) | |
| name | str (unique) | Group name |
| description | str | null | |
| resources | jsonb | [{"type": "model", "id": "gpt-4"}, ...] |
| created_at | datetime | |
| updated_at | datetime | |

#### `access_group_assignments`

| Column | Type | Description |
|---|---|---|
| id | UUID (PK) | |
| access_group_id | UUID (FK -> access_groups) | |
| entity_type | str | "team", "api_key" |
| entity_id | UUID | |
| created_at | datetime | |

**Unique constraint:** `(access_group_id, entity_type, entity_id)`

#### `sso_configs`

| Column | Type | Description |
|---|---|---|
| id | UUID (PK) | |
| org_id | UUID (FK -> organizations, unique) | One SSO config per org |
| provider | str | "google", "azure_ad", "okta", "oidc" |
| client_id | str | OAuth2 client ID |
| client_secret_encrypted | str | AES-256 encrypted client secret |
| issuer_url | str | OIDC discovery URL |
| allowed_domains | jsonb | ["company.com"] |
| group_to_team_mapping | jsonb | {"Engineering": "team_uuid"} |
| auto_create_user | bool | Default true |
| default_role | str | Default "member" |
| is_active | bool | Default true |
| created_at | datetime | |
| updated_at | datetime | |

#### `refresh_tokens`

| Column | Type | Description |
|---|---|---|
| id | UUID (PK) | |
| token_hash | str (unique) | SHA-256 hash of refresh token |
| user_id | UUID (FK -> users) | |
| expires_at | datetime | |
| is_revoked | bool | Default false |
| replaced_by | UUID (FK -> refresh_tokens) | null | Points to the new token after rotation |
| ip_address | str | null | IP that created this token |
| user_agent | str | null | |
| created_at | datetime | |

**Index:** `(user_id, is_revoked)` for fast lookup of active tokens.

#### `spend_logs`

| Column | Type | Description |
|---|---|---|
| id | UUID (PK) | Auto-generated |
| request_id | str (unique) | System-generated request identifier |
| api_key_hash | str | |
| user_id | UUID | null | |
| team_id | UUID | null | |
| org_id | UUID | null | |
| project_id | UUID | null | |
| model | str | |
| provider | str | |
| input_tokens | int | |
| output_tokens | int | |
| spend | float | Cost in USD |
| cache_hit | bool | Default false |
| status | str | "success" or "error" |
| response_time_ms | int | |
| created_at | datetime | |

**Indexes:**
- `(api_key_hash, created_at)` — key spend queries
- `(user_id, created_at)` — user spend queries
- `(team_id, created_at)` — team spend queries
- `(org_id, created_at)` — org spend queries
- `(model, created_at)` — model analytics

#### `daily_user_spend`

| Column | Type | Description |
|---|---|---|
| id | UUID (PK) | |
| user_id | UUID | |
| model | str | |
| date | date | |
| total_spend | float | |
| total_input_tokens | int | |
| total_output_tokens | int | |
| request_count | int | |

**Unique constraint:** `(user_id, model, date)`. Same structure for `daily_team_spend`, `daily_org_spend`, `daily_key_spend`, `daily_end_user_spend`, `daily_tag_spend` (replacing `user_id` with the appropriate grouping column).

---

## 2. Authentication — Mechanisms

### 2.1 API Keys

- **Format:** `sk-{prefix_8chars}{random_32chars}`
- **Storage:** Only SHA-256 hash stored in DB. Plaintext never persisted.
- **Prefix:** First 8 chars stored in clear for UI identification.
- **Auth flow:** `Authorization: Bearer sk-...` header -> hash -> lookup in `api_keys` table.
- **Rotation:** Generate new key, grace period (configurable hours) where both old and new work. Stored via `previous_key_hash` and `grace_period_expires_at` columns on the `api_keys` table. Old hash cleared after grace period expires.
- **Cache:** Authenticated keys cached in-memory with 5s TTL. Invalidated on update/delete/block.

### 2.2 JWT

- **Algorithms:** RS256 (asymmetric, for SSO) and HS256 (symmetric, for self-issued tokens).
- **Standard claims:** `sub`, `exp`, `iat`, `iss`.
- **Custom claims:** `org_id`, `team_id`, `role`, `allowed_models`.
- **Token pair:** Access token (short-lived, 15min) + Refresh token (long-lived, 7 days).
- **Refresh rotation:** Each refresh issues new pair, old refresh invalidated.
- **Claim mapping:** Configurable mapping from IdP claims to internal permissions.

### 2.3 OAuth2 / SSO

- **Flow:** Authorization Code + PKCE.
- **Providers (initial):** Google Workspace, Microsoft Azure AD, Okta, Generic OIDC.
- **Auto-provisioning:** Create user on first login.
- **Group mapping:** IdP groups -> internal teams (configurable per SSO config).

### 2.4 Password

- **Hashing:** bcrypt with salt, cost factor 12.
- **Brute force protection:** 5 failed attempts -> 15min lockout.
- **Usage:** Fallback for dashboard login when SSO is not configured.
- **Password reset:** Via `/auth/forgot-password` (sends reset email with time-limited token) and `/auth/reset-password` (validates token, sets new password). Reset tokens stored in `password_reset_tokens` table with 1-hour expiry.

### 2.5 Session & Token Management Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/auth/login` | Password login, returns JWT pair |
| POST | `/auth/refresh` | Exchange refresh token for new pair |
| POST | `/auth/logout` | Revoke current refresh token |
| POST | `/auth/logout-all` | Revoke all refresh tokens for user |
| POST | `/auth/forgot-password` | Send password reset email |
| POST | `/auth/reset-password` | Reset password with token |

---

## 3. Authorization — RBAC

### 3.1 Middleware Pipeline

```
Request
  -> 1. Authenticate (who are you?)
  -> 2. Rate limit check (within limits?)
  -> 3. Budget check (has budget?)
  -> 4. Model access check (can use this model?)
  -> 5. Route permission check (can access this endpoint?)
  -> 6. Forward request
```

### 3.2 Roles

| Role | Scope |
|---|---|
| `proxy_admin` | Global — full access to everything |
| `org_admin` | Organization — manage teams, users, keys within their org |
| `team_admin` | Team — manage members, keys within their team |
| `member` | Basic — use LLM API per key/team permissions |

### 3.3 Permission Matrix

| Action | proxy_admin | org_admin | team_admin | member |
|---|---|---|---|---|
| CRUD organizations | yes | own only | no | no |
| CRUD teams | yes | within org | own only | no |
| CRUD users | yes | within org | within team | no |
| Generate API keys | yes | within org | within team | self only |
| View global spend | yes | own org | own team | own spend |
| Manage models | yes | no | no | no |
| Manage guardrails | yes | no | no | no |
| Use LLM API | yes | yes | yes | yes (per key) |

### 3.4 Model Access Resolution

1. Check `api_key.allowed_models` — if set, use it.
2. If empty, check `team.allowed_models` — if set, use it.
3. If empty, check org-level config.
4. `proxy_admin` can define globally available models.
5. Wildcard support:
   - `"claude-*"` matches `"claude-3-opus"`, `"claude-3-sonnet"`, etc.
   - `"*"` alone means "all models" (unrestricted).
   - Wildcards only at the end (glob-style, not mid-string).
   - Matching is case-sensitive.
   - `null` means "inherit from parent". Empty array `[]` means "no models allowed".

### 3.5 Object-Level Permissions

Evaluated after role-based checks. Stored in `object_permissions` table.

- Entity (user, team, api_key) + Resource (model, tool, agent, mcp_server) + Action (allow, deny).
- `deny` takes precedence over `allow`.

### 3.6 Access Groups

- Group resources (models, servers, tools) under a name.
- Assign groups to teams or API keys.
- Simplifies management at scale.

---

## 4. API Key Management

### Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/key/generate` | Create new key |
| GET | `/key/list` | List keys (filtered by user/team/org) |
| GET | `/key/info/{key_id}` | Key details |
| POST | `/key/update` | Update permissions, budget, models |
| POST | `/key/delete` | Revoke key |
| POST | `/key/rotate` | Rotate key (new + grace period) |
| POST | `/key/block` | Block/unblock key |
| POST | `/key/reactivate` | Reactivate expired key |
| POST | `/key/reset_spend` | Reset accumulated spend |
| POST | `/key/bulk_update` | Update multiple keys |

### Key Lifecycle

```
generate -> active -> [rotate -> grace period -> new active]
                   -> [block -> blocked -> unblock -> active]
                   -> [expire -> expired -> reactivate -> active]
                   -> [delete -> deleted (audit trail)]
```

---

## 5. Entity Management Endpoints

### 5.1 Users

| Method | Path | Description |
|---|---|---|
| POST | `/user/new` | Create user (password or SSO) |
| GET | `/user/list` | List users (paginated) |
| GET | `/user/info/{id}` | Detail + memberships + spend |
| POST | `/user/update` | Update role, budget, metadata |
| POST | `/user/delete` | Delete user + cascade keys |
| POST | `/user/block` | Block/unblock |

### 5.2 Teams

| Method | Path | Description |
|---|---|---|
| POST | `/team/new` | Create team within org |
| GET | `/team/list` | List teams (filtered by org) |
| GET | `/team/info/{id}` | Detail + members + spend |
| POST | `/team/update` | Update models, budget, config |
| POST | `/team/delete` | Delete + cascade |
| POST | `/team/member_add` | Add user to team with role |
| POST | `/team/member_update` | Change member role |
| POST | `/team/member_delete` | Remove member |
| POST | `/team/reset_budget` | Reset team spend |

### 5.3 Organizations

| Method | Path | Description |
|---|---|---|
| POST | `/organization/new` | Create organization |
| GET | `/organization/list` | List orgs |
| GET | `/organization/info/{id}` | Detail + teams + spend |
| POST | `/organization/update` | Update config |
| POST | `/organization/delete` | Delete + cascade |
| POST | `/organization/member_add` | Add user to org |
| POST | `/organization/member_update` | Change role |
| POST | `/organization/member_delete` | Remove member |

**Note on HTTP methods:** All mutation endpoints use `POST` consistently. This simplifies proxy/firewall compatibility (some strip `DELETE`/`PATCH` bodies) and matches the convention used throughout the API.

### 5.4 Budgets

| Method | Path | Description |
|---|---|---|
| POST | `/budget/new` | Create reusable budget |
| GET | `/budget/list` | List budgets |
| POST | `/budget/update` | Modify limits |
| POST | `/budget/delete` | Delete budget |

Budget fields:
- `max_budget` (float | null) — hard spending limit in USD
- `soft_budget` (float | null) — alert threshold
- `tpm_limit` (int | null) — tokens per minute
- `rpm_limit` (int | null) — requests per minute
- `max_parallel_requests` (int | null)
- `budget_reset_period` (str | null) — "daily", "weekly", "30d"

### 5.5 Cascade on Deletion

- Delete org -> deletes teams -> deletes projects -> revokes keys
- All recorded in `audit_log` and `deleted_*` tables.

---

## 6. Spend Tracking & Rate Limiting

### 6.1 Per-Request Spend Log

See `spend_logs` table definition in section 1. Each LLM request creates one row with cost, token counts, and entity references. The `request_id` is system-generated (UUID v4).

### 6.2 Daily Aggregates

See `daily_user_spend` table definition in section 1. Six tables with identical structure:

| Table | Groups by |
|---|---|
| `daily_user_spend` | user_id + model + day |
| `daily_team_spend` | team_id + model + day |
| `daily_org_spend` | org_id + model + day |
| `daily_key_spend` | api_key_hash + model + day |
| `daily_end_user_spend` | end_user + model + day |
| `daily_tag_spend` | tag + model + day |

Aggregates are computed incrementally via upsert (not recalculated from spend_logs).

### 6.3 Rate Limiting

Three levels evaluated in order:

1. **Global limits** — proxy-wide configuration
2. **Entity limits** — org -> team -> key (inherits if not set)
3. **Model-specific limits** — per model within a key/team

Types:
- **RPM** — requests per minute (sliding window in Redis)
- **TPM** — tokens per minute (sliding window in Redis)
- **Max parallel** — concurrent requests (atomic counter in Redis)
- **Budget** — accumulated spend vs max_budget

Rate limit exceeded response:

```json
{
  "status": 429,
  "error": {
    "type": "rate_limit_error",
    "message": "Rate limit exceeded: 100 RPM",
    "retry_after": 12.5
  }
}
```

---

## 7. SSO & OAuth2

### 7.1 OAuth2 Flow (Authorization Code + PKCE)

```
User -> Dashboard login -> Redirect to IdP
  -> User authenticates at IdP
  -> IdP redirects to /sso/callback with code
  -> Backend exchanges code for tokens
  -> Extract claims (email, groups, name)
  -> Create or link user in DB
  -> Issue own JWT (access + refresh)
  -> Redirect to dashboard with tokens
```

### 7.2 Supported Providers

| Provider | Protocol | Auto-provisioning |
|---|---|---|
| Google Workspace | OIDC | Yes — maps org domain to org_id |
| Microsoft Azure AD | OIDC | Yes — maps tenant to org_id |
| Okta | OIDC | Yes — maps groups to teams |
| Generic OIDC | OIDC | Configurable |

### 7.3 SSO Configuration (per org)

```python
sso_config:
  provider: str              # "google", "azure_ad", "okta", "oidc"
  client_id: str
  client_secret: str         # encrypted in DB (AES-256)
  issuer_url: str            # for OIDC discovery (.well-known)
  allowed_domains: list[str] # ["company.com"]
  group_to_team_mapping: dict  # {"Engineering": "team_uuid_123"}
  auto_create_user: bool
  default_role: str          # default role on user creation
```

### 7.4 SSO Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/sso/authorize` | Start OAuth2 flow (redirect to IdP) |
| GET | `/sso/callback` | IdP callback, issues JWT |
| POST | `/sso/config` | Configure SSO for an org |
| GET | `/sso/config/{org_id}` | View org SSO config |
| DELETE | `/sso/config/{org_id}` | Delete SSO config |

### 7.5 SCIM v2 (Automatic Provisioning) — Deferred to v2

SCIM v2 (RFC 7644) requires strict schema compliance, pagination, filtering syntax, and specific error codes. This is deferred to a later phase. In v1, user provisioning is handled by:
- SSO auto-provisioning on first login
- Manual user/team management via the admin endpoints

---

## 8. Audit Log & Security

### 8.1 Audit Log

```python
audit_log:
  id: UUID
  actor_id: UUID            # who performed the action
  actor_type: str           # "user", "api_key", "system"
  action: str               # "create", "update", "delete", "block", "login"
  resource_type: str        # "key", "user", "team", "org", "sso_config"
  resource_id: str
  before_value: jsonb | None # previous state
  after_value: jsonb | None  # new state
  ip_address: str
  user_agent: str
  created_at: datetime
```

### 8.2 Security Measures

| Measure | Detail |
|---|---|
| API keys | SHA-256 hash only, never plaintext |
| Passwords | bcrypt with salt (cost factor 12) |
| JWT secrets | RS256 with key rotation |
| SSO secrets | Encrypted in DB (AES-256) |
| Rate limiting | Brute force prevention: 5 attempts -> 15min lockout |
| IP whitelist/blacklist | Configurable per org or global |
| CORS | Configurable, restrictive by default |
| Session | Tokens in sessionStorage (never localStorage) |
| Refresh tokens | Rotation on each use, revocation on logout |

### 8.3 Deletion Audit Tables

| Table | Purpose |
|---|---|
| `deleted_users` | History of deleted users |
| `deleted_teams` | History of deleted teams |
| `deleted_keys` | History of revoked keys |
| `error_logs` | Auth errors (failed attempts) |

---

## 9. Summary

### Scope

| Component | Count |
|---|---|
| Database tables | ~28 (including daily aggregates) |
| API endpoints | ~50 (including auth/session endpoints) |
| Auth mechanisms | 4 (API keys, JWT, OAuth2/SSO, password) |
| Roles | 4 (proxy_admin, org_admin, team_admin, member) |
| SSO providers | 4 (Google, Azure AD, Okta, generic OIDC) |
| Rate limit types | 4 (RPM, TPM, parallel, budget) |
| Daily aggregate tables | 6 |

### Dependencies

- **Python 3.11+**
- **FastAPI** — web framework
- **SQLAlchemy 2.0** — ORM (async mode)
- **Alembic** — database migrations
- **PostgreSQL 15+** — primary database
- **Redis** — rate limiting, auth cache
- **PyJWT** — JWT handling
- **bcrypt** — password hashing
- **cryptography** — AES-256 for secret encryption
- **httpx** — async HTTP client (for OAuth2 flows)

### Non-Goals (for this sub-project)

- LLM provider integrations (sub-project #2)
- Router/load balancing (sub-project #3)
- Cache layer (sub-project #4)
- Observability integrations (sub-project #6)
- Guardrails (sub-project #7)
- Dashboard UI (sub-project #9)
