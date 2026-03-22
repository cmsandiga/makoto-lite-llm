# Spend & Budgets Design

**Date:** 2026-03-22
**Sub-project:** #5
**Dependencies:** Auth (#1), Core SDK (#2), Router (#3)

## Overview

Per-request cost tracking, daily spend aggregation, and budget enforcement. Integrates with the auth system (entities: user, team, org, key) and the router (per-request spend logging).

---

## 1. Per-Request Spend Logging

Every LLM request creates a `spend_log` row (see Auth spec section 1 for table schema):

```python
async def log_spend(
    db: AsyncSession,
    request_id: str,
    api_key_hash: str,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    spend: float,
    user_id: UUID | None,
    team_id: UUID | None,
    org_id: UUID | None,
    cache_hit: bool,
    status: str,           # "success" | "error"
    response_time_ms: int,
) -> None:
    # 1. Insert into spend_logs
    # 2. Update entity spend counters (api_key.spend, user.spend)
    # 3. Upsert daily aggregate tables
```

---

## 2. Daily Aggregation

6 aggregate tables, all using incremental upsert:

```sql
INSERT INTO daily_user_spend (user_id, model, date, total_spend, total_input_tokens, total_output_tokens, request_count)
VALUES ($1, $2, $3, $4, $5, $6, 1)
ON CONFLICT (user_id, model, date) DO UPDATE SET
  total_spend = daily_user_spend.total_spend + $4,
  total_input_tokens = daily_user_spend.total_input_tokens + $5,
  total_output_tokens = daily_user_spend.total_output_tokens + $6,
  request_count = daily_user_spend.request_count + 1;
```

Same for: `daily_team_spend`, `daily_org_spend`, `daily_key_spend`, `daily_end_user_spend`, `daily_tag_spend`.

---

## 3. Budget Enforcement

### 3.1 Budget Check Middleware

Runs as step 3 in the auth middleware pipeline (after authenticate, before model access):

```python
async def check_budget(entity: User | Team | Organization | ApiKey) -> None:
    """
    Resolution:
    1. If entity has budget_id → use linked Budget
    2. Else → use entity's inline max_budget
    3. Compare current spend vs max_budget
    4. If exceeded → raise BudgetExceededError (HTTP 429)
    """
```

### 3.2 Budget Reset

Budgets reset based on `budget_reset_period`:

| Period | Behavior |
|--------|----------|
| `"daily"` | Reset at midnight UTC |
| `"weekly"` | Reset on Monday midnight UTC |
| `"monthly"` | Reset on 1st of month |
| `"30d"` | Reset 30 days after last reset |
| `"90d"` | Reset 90 days after last reset |
| `"yearly"` | Reset on Jan 1st |

Implementation: Background task checks entities with `budget_reset_period` set and resets `spend = 0` when period expires.

### 3.3 Soft Budget Alerts

When `spend >= soft_budget` (but < `max_budget`):
- Emit event to observability callbacks
- Send Slack alert (if configured)
- Do NOT block the request

---

## 4. Cost Calculation Integration

```python
async def calculate_request_cost(
    model: str,
    usage: Usage,
) -> float:
    """
    Uses CostCalculator from Core SDK:
    cost = (prompt_tokens * input_cost) + (completion_tokens * output_cost)
    """
```

---

## 5. Spend Query Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/spend/logs` | Query spend logs (filtered, paginated) |
| GET | `/spend/daily/{entity_type}/{entity_id}` | Daily spend for entity |
| GET | `/spend/summary` | Aggregated spend by model/provider |
| GET | `/spend/top-models` | Top models by spend |
| GET | `/spend/top-users` | Top users by spend |

---

## 6. Rate Limit Integration

Rate limits (RPM, TPM, max_parallel) are enforced via Redis sliding window (see Auth spec section 6.3). The Spend service provides the budget check, while the rate limiter handles throughput limits.

---

## 7. Non-Goals

- Real-time spend dashboards (handled by Dashboard UI sub-project)
- Provider-level budget limiting (v2)
- Cost alerts via email/PagerDuty (handled by Observability sub-project)
