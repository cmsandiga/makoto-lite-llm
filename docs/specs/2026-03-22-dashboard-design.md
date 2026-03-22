# Dashboard UI Design

**Date:** 2026-03-22
**Sub-project:** #9
**Dependencies:** All previous sub-projects

## Overview

Next.js admin dashboard for managing the LLM proxy. Provides UI for authentication, entity management, API key management, spend analytics, model configuration, and chat playground.

---

## 1. Pages & Features

### 1.1 Login Page (`/login`)
- Email/password login form
- SSO buttons (Google, Azure AD, Okta) — dynamically shown based on SSO config
- Redirect to dashboard on success
- Session stored in `sessionStorage` (never `localStorage`)

### 1.2 Dashboard Home (`/`)
- Total spend (today, this week, this month)
- Request count chart (line graph, last 7 days)
- Top models by spend (bar chart)
- Top users by spend (table)
- Active API keys count
- Recent errors summary

### 1.3 API Keys (`/keys`)
- Table: prefix, alias, owner, team, models, spend, status, expiry
- Generate new key (form with all KeyGenerate fields)
- Edit key (models, budget, rate limits)
- Rotate, block, delete actions
- Copy key to clipboard (on generation only)
- Bulk operations

### 1.4 Users (`/users`)
- Table: email, name, role, spend, status
- Create user form
- Edit role, budget, block/unblock
- View user's keys and memberships

### 1.5 Teams (`/teams`)
- Table: name, org, member count, models, budget, spend
- Create team form
- Manage members (add/remove/change role)
- Configure allowed models
- Reset budget

### 1.6 Organizations (`/organizations`)
- Table: name, slug, team count, budget, spend
- Create org form
- Manage members
- View teams within org

### 1.7 Models (`/models`)
- List configured model deployments
- Add/remove deployments
- View per-model spend and latency
- Model group aliases

### 1.8 Spend Analytics (`/analytics`)
- Spend by model (line chart, configurable time range)
- Spend by team/user/key (bar charts)
- Token usage breakdown (input vs output)
- Cost per request trends
- Export to CSV

### 1.9 Chat Playground (`/chat`)
- Model selector (from configured models)
- Chat interface with message history
- Streaming response display
- Parameter controls (temperature, max_tokens, etc.)
- Tool/function calling support

### 1.10 Settings (`/settings`)
- General: proxy name, default model
- Logging: callback configuration
- Guardrails: enable/disable guardrails
- SSO: configure SSO providers
- Cache: cache backend configuration

---

## 2. Tech Stack

| Component | Technology |
|-----------|-----------|
| Framework | Next.js 14+ (App Router) |
| UI Library | React |
| Styling | Tailwind CSS |
| Charts | Recharts or Chart.js |
| HTTP Client | fetch / SWR for data fetching |
| Auth | JWT stored in sessionStorage |

---

## 3. API Integration

The dashboard communicates exclusively with the proxy API:
- Auth: `POST /auth/login` → JWT pair
- All other calls: `Authorization: Bearer {access_token}`
- Token refresh: `POST /auth/refresh` on 401

---

## 4. Auth Flow

```
User opens dashboard
  → Check sessionStorage for access_token
  → If missing/expired → redirect to /login
  → If valid → render dashboard

Login:
  → POST /auth/login (email, password)
  → Store tokens in sessionStorage
  → Redirect to /

SSO Login:
  → Click SSO button → redirect to /sso/authorize
  → IdP auth → callback → JWT pair in URL params
  → Store tokens in sessionStorage
  → Redirect to /
```

---

## 5. Role-Based UI

| Feature | proxy_admin | org_admin | team_admin | member |
|---------|-------------|-----------|------------|--------|
| Dashboard home | full | org scoped | team scoped | own spend |
| API Keys | all | org keys | team keys | own keys |
| Users | all | org users | team members | profile only |
| Teams | all | org teams | own team | view only |
| Organizations | all | own org | hidden | hidden |
| Models | full CRUD | view only | view only | view only |
| Settings | full | hidden | hidden | hidden |

---

## 6. Security

- Tokens in `sessionStorage` only (XSS mitigation)
- No API keys or secrets in `localStorage`
- CORS restricted to dashboard origin
- All API calls over HTTPS in production
- Auto-logout on token expiry

---

## 7. Non-Goals (v1)

- Mobile-responsive design (desktop-first)
- Real-time WebSocket updates on dashboard (polling is fine)
- Guardrail config UI (API/YAML only)
- MCP server management UI
- Custom theming/white-labeling
