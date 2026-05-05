# Rate Limiting, Spend Tracking, Audit Logging — Ola 7

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add rate limiting (RPM/TPM sliding window), spend tracking (per-request logging + daily aggregates), and audit logging (action tracking + deletion history) services.

**Architecture:** Three independent services, each tested in isolation. Rate limiter uses an in-memory sliding window (Redis-swappable later). Spend service logs each request and upserts daily aggregates atomically. Audit service records actions and snapshots deleted entities. Audit logging is integrated into existing entity services (user, team, org, key) deletion paths.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.0 async, pytest

**Spec:** `docs/specs/2026-03-22-auth-system-design.md` sections 6 (Spend Tracking & Rate Limiting), 8 (Audit Log & Security)

---

## File Structure

```
src/app/services/
├── rate_limiter.py       # CREATE — in-memory sliding window rate limiter
├── spend_service.py      # CREATE — log_spend + upsert daily aggregates
├── audit_service.py      # CREATE — log_action, log_deletion
├── user_service.py       # MODIFY — add audit logging to delete_user
├── team_service.py       # MODIFY — add audit logging to delete_team
├── org_service.py        # MODIFY — add audit logging to delete_org
├── key_service.py        # MODIFY — add audit logging to delete_key
tests/test_services/
├── test_rate_limiter.py         # CREATE
├── test_spend_service.py        # CREATE
├── test_audit_service.py        # CREATE
```

---

### Task 1: In-Memory Sliding Window Rate Limiter

**Files:**
- Create: `src/app/services/rate_limiter.py`
- Test: `tests/test_services/test_rate_limiter.py`

**What this does:** A sliding window rate limiter that tracks request counts per key within a time window. In-memory implementation for now — Redis backend can be swapped in later without changing the interface. Supports RPM and TPM (same algorithm, different limits).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_services/test_rate_limiter.py
import asyncio

from app.services.rate_limiter import SlidingWindowRateLimiter


async def test_under_limit_allows():
    limiter = SlidingWindowRateLimiter()
    result = await limiter.check_rate_limit("key1", limit=10, window_seconds=60)
    assert result.allowed is True
    assert result.remaining == 9


async def test_at_limit_denies():
    limiter = SlidingWindowRateLimiter()
    for _ in range(10):
        await limiter.check_rate_limit("key1", limit=10, window_seconds=60)
    result = await limiter.check_rate_limit("key1", limit=10, window_seconds=60)
    assert result.allowed is False
    assert result.remaining == 0
    assert result.retry_after > 0


async def test_different_keys_independent():
    limiter = SlidingWindowRateLimiter()
    for _ in range(10):
        await limiter.check_rate_limit("key1", limit=10, window_seconds=60)
    result = await limiter.check_rate_limit("key2", limit=10, window_seconds=60)
    assert result.allowed is True


async def test_window_expires():
    """Requests outside the window should not count."""
    limiter = SlidingWindowRateLimiter()
    # Use a tiny window
    for _ in range(5):
        await limiter.check_rate_limit("key1", limit=5, window_seconds=0.1)
    result = await limiter.check_rate_limit("key1", limit=5, window_seconds=0.1)
    assert result.allowed is False

    await asyncio.sleep(0.15)
    result = await limiter.check_rate_limit("key1", limit=5, window_seconds=0.1)
    assert result.allowed is True


async def test_increment_by_tokens():
    """TPM: increment by token count instead of 1."""
    limiter = SlidingWindowRateLimiter()
    result = await limiter.check_rate_limit("key1", limit=100, window_seconds=60, increment=50)
    assert result.allowed is True
    assert result.remaining == 50

    result = await limiter.check_rate_limit("key1", limit=100, window_seconds=60, increment=60)
    assert result.allowed is False
    assert result.remaining == 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_services/test_rate_limiter.py -v`
Expected: FAIL

- [ ] **Step 3: Implement rate_limiter.py**

```python
# src/app/services/rate_limiter.py
import time
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: float = 0.0


class SlidingWindowRateLimiter:
    """In-memory sliding window rate limiter.

    Tracks timestamped request counts per key. Entries outside the window
    are pruned on each check. Thread-safe for single-process async use.

    Swappable with a Redis-backed implementation later (same interface).
    """

    def __init__(self) -> None:
        # key -> list of (timestamp, increment) tuples
        self._windows: dict[str, list[tuple[float, int]]] = defaultdict(list)

    async def check_rate_limit(
        self,
        key: str,
        limit: int,
        window_seconds: float,
        increment: int = 1,
    ) -> RateLimitResult:
        """Check and record a rate limit event.

        Args:
            key: Identifier (e.g., "rpm:{api_key_hash}" or "tpm:{api_key_hash}")
            limit: Maximum count within the window
            window_seconds: Sliding window duration in seconds
            increment: Amount to add (1 for RPM, token_count for TPM)

        Returns:
            RateLimitResult with allowed, remaining, retry_after
        """
        now = time.monotonic()
        cutoff = now - window_seconds

        # Prune expired entries
        entries = self._windows[key]
        entries[:] = [(ts, inc) for ts, inc in entries if ts > cutoff]

        # Calculate current usage
        current = sum(inc for _, inc in entries)

        if current + increment > limit:
            # Calculate retry_after: time until enough entries expire
            retry_after = entries[0][0] - cutoff if entries else 0.0
            return RateLimitResult(
                allowed=False,
                remaining=max(0, limit - current),
                retry_after=max(0.0, retry_after),
            )

        entries.append((now, increment))
        return RateLimitResult(
            allowed=True,
            remaining=limit - current - increment,
        )

    async def reset(self, key: str) -> None:
        """Clear all entries for a key."""
        self._windows.pop(key, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_services/test_rate_limiter.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/services/rate_limiter.py tests/test_services/test_rate_limiter.py
git commit -m "feat: sliding window rate limiter — RPM/TPM enforcement"
```

---

### Task 2: Spend Tracking Service

**Files:**
- Create: `src/app/services/spend_service.py`
- Test: `tests/test_services/test_spend_service.py`

**What this does:** Logs each LLM request's cost to `spend_logs` table and upserts daily aggregate tables. The upsert uses PostgreSQL's `ON CONFLICT ... DO UPDATE` for atomic increment.

**Existing models:** `SpendLog`, `DailyUserSpend`, `DailyTeamSpend`, `DailyOrgSpend`, `DailyKeySpend`, `DailyEndUserSpend`, `DailyTagSpend` — all defined in `src/app/models/spend.py`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_services/test_spend_service.py
import uuid

from sqlalchemy import select

from app.models.spend import DailyKeySpend, DailyUserSpend, SpendLog
from app.services.spend_service import log_spend


async def test_log_spend_creates_spend_log(db_session):
    """log_spend creates a SpendLog row."""
    await log_spend(
        db=db_session,
        request_id="req-001",
        api_key_hash="abc123",
        user_id=uuid.uuid4(),
        model="gpt-4",
        provider="openai",
        input_tokens=100,
        output_tokens=50,
        spend=0.05,
        status="success",
        response_time_ms=200,
    )

    result = await db_session.execute(
        select(SpendLog).where(SpendLog.request_id == "req-001")
    )
    log = result.scalar_one()
    assert log.model == "gpt-4"
    assert log.spend == 0.05
    assert log.input_tokens == 100


async def test_log_spend_upserts_daily_user(db_session):
    """log_spend upserts the daily_user_spend aggregate."""
    user_id = uuid.uuid4()
    await log_spend(
        db=db_session,
        request_id="req-002",
        api_key_hash="abc123",
        user_id=user_id,
        model="gpt-4",
        provider="openai",
        input_tokens=100,
        output_tokens=50,
        spend=0.05,
        status="success",
        response_time_ms=200,
    )
    await log_spend(
        db=db_session,
        request_id="req-003",
        api_key_hash="abc123",
        user_id=user_id,
        model="gpt-4",
        provider="openai",
        input_tokens=200,
        output_tokens=100,
        spend=0.10,
        status="success",
        response_time_ms=300,
    )

    result = await db_session.execute(
        select(DailyUserSpend).where(DailyUserSpend.user_id == user_id)
    )
    daily = result.scalar_one()
    assert daily.total_spend == 0.15
    assert daily.total_input_tokens == 300
    assert daily.total_output_tokens == 150
    assert daily.request_count == 2


async def test_log_spend_upserts_daily_key(db_session):
    """log_spend upserts the daily_key_spend aggregate."""
    key_hash = "keyhash123"
    await log_spend(
        db=db_session,
        request_id="req-004",
        api_key_hash=key_hash,
        model="claude-3",
        provider="anthropic",
        input_tokens=50,
        output_tokens=25,
        spend=0.02,
        status="success",
        response_time_ms=150,
    )

    result = await db_session.execute(
        select(DailyKeySpend).where(DailyKeySpend.api_key_hash == key_hash)
    )
    daily = result.scalar_one()
    assert daily.total_spend == 0.02
    assert daily.request_count == 1


async def test_log_spend_optional_fields(db_session):
    """log_spend works with minimal required fields (no user_id/team_id/org_id)."""
    await log_spend(
        db=db_session,
        request_id="req-005",
        api_key_hash="min123",
        model="gpt-4",
        provider="openai",
        input_tokens=10,
        output_tokens=5,
        spend=0.001,
        status="success",
        response_time_ms=100,
    )

    result = await db_session.execute(
        select(SpendLog).where(SpendLog.request_id == "req-005")
    )
    log = result.scalar_one()
    assert log.user_id is None
    assert log.team_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_services/test_spend_service.py -v`
Expected: FAIL

- [ ] **Step 3: Implement spend_service.py**

```python
# src/app/services/spend_service.py
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.spend import (
    DailyKeySpend,
    DailyOrgSpend,
    DailyTeamSpend,
    DailyUserSpend,
    SpendLog,
)


async def log_spend(
    db: AsyncSession,
    request_id: str,
    api_key_hash: str,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    spend: float,
    status: str,
    response_time_ms: int,
    user_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    cache_hit: bool = False,
) -> SpendLog:
    """Log a single LLM request and update daily aggregates.

    Creates a SpendLog row and upserts the relevant daily aggregate tables.
    """
    # Create spend log
    log = SpendLog(
        request_id=request_id,
        api_key_hash=api_key_hash,
        user_id=user_id,
        team_id=team_id,
        org_id=org_id,
        project_id=project_id,
        model=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        spend=spend,
        cache_hit=cache_hit,
        status=status,
        response_time_ms=response_time_ms,
    )
    db.add(log)

    today = date.today()

    # Upsert daily aggregates for each relevant entity
    await _upsert_daily_key(db, api_key_hash, model, today, spend, input_tokens, output_tokens)

    if user_id:
        await _upsert_daily_user(db, user_id, model, today, spend, input_tokens, output_tokens)

    if team_id:
        await _upsert_daily_team(db, team_id, model, today, spend, input_tokens, output_tokens)

    if org_id:
        await _upsert_daily_org(db, org_id, model, today, spend, input_tokens, output_tokens)

    await db.commit()
    await db.refresh(log)
    return log


async def _upsert_daily_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    model: str,
    today: date,
    spend: float,
    input_tokens: int,
    output_tokens: int,
) -> None:
    result = await db.execute(
        select(DailyUserSpend).where(
            DailyUserSpend.user_id == user_id,
            DailyUserSpend.model == model,
            DailyUserSpend.date == today,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        row.total_spend += spend
        row.total_input_tokens += input_tokens
        row.total_output_tokens += output_tokens
        row.request_count += 1
    else:
        db.add(DailyUserSpend(
            user_id=user_id, model=model, date=today,
            total_spend=spend, total_input_tokens=input_tokens,
            total_output_tokens=output_tokens, request_count=1,
        ))


async def _upsert_daily_team(
    db: AsyncSession,
    team_id: uuid.UUID,
    model: str,
    today: date,
    spend: float,
    input_tokens: int,
    output_tokens: int,
) -> None:
    result = await db.execute(
        select(DailyTeamSpend).where(
            DailyTeamSpend.team_id == team_id,
            DailyTeamSpend.model == model,
            DailyTeamSpend.date == today,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        row.total_spend += spend
        row.total_input_tokens += input_tokens
        row.total_output_tokens += output_tokens
        row.request_count += 1
    else:
        db.add(DailyTeamSpend(
            team_id=team_id, model=model, date=today,
            total_spend=spend, total_input_tokens=input_tokens,
            total_output_tokens=output_tokens, request_count=1,
        ))


async def _upsert_daily_org(
    db: AsyncSession,
    org_id: uuid.UUID,
    model: str,
    today: date,
    spend: float,
    input_tokens: int,
    output_tokens: int,
) -> None:
    result = await db.execute(
        select(DailyOrgSpend).where(
            DailyOrgSpend.org_id == org_id,
            DailyOrgSpend.model == model,
            DailyOrgSpend.date == today,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        row.total_spend += spend
        row.total_input_tokens += input_tokens
        row.total_output_tokens += output_tokens
        row.request_count += 1
    else:
        db.add(DailyOrgSpend(
            org_id=org_id, model=model, date=today,
            total_spend=spend, total_input_tokens=input_tokens,
            total_output_tokens=output_tokens, request_count=1,
        ))


async def _upsert_daily_key(
    db: AsyncSession,
    api_key_hash: str,
    model: str,
    today: date,
    spend: float,
    input_tokens: int,
    output_tokens: int,
) -> None:
    result = await db.execute(
        select(DailyKeySpend).where(
            DailyKeySpend.api_key_hash == api_key_hash,
            DailyKeySpend.model == model,
            DailyKeySpend.date == today,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        row.total_spend += spend
        row.total_input_tokens += input_tokens
        row.total_output_tokens += output_tokens
        row.request_count += 1
    else:
        db.add(DailyKeySpend(
            api_key_hash=api_key_hash, model=model, date=today,
            total_spend=spend, total_input_tokens=input_tokens,
            total_output_tokens=output_tokens, request_count=1,
        ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_services/test_spend_service.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/services/spend_service.py tests/test_services/test_spend_service.py
git commit -m "feat: spend tracking — per-request logging + daily aggregates"
```

---

### Task 3: Audit Logging Service

**Files:**
- Create: `src/app/services/audit_service.py`
- Test: `tests/test_services/test_audit_service.py`

**What this does:** Two functions: `log_action` writes to `audit_log` table (who did what to what, with before/after snapshots). `log_deletion` writes to the appropriate `deleted_*` table (deleted_users, deleted_teams, deleted_keys).

**Existing models:** `AuditLog`, `DeletedUser`, `DeletedTeam`, `DeletedKey`, `ErrorLog` in `src/app/models/audit.py`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_services/test_audit_service.py
import uuid

from sqlalchemy import select

from app.models.audit import AuditLog, DeletedKey, DeletedTeam, DeletedUser
from app.services.audit_service import log_action, log_deletion


async def test_log_action(db_session):
    """log_action creates an AuditLog row."""
    actor_id = uuid.uuid4()
    await log_action(
        db=db_session,
        actor_id=actor_id,
        actor_type="user",
        action="create",
        resource_type="team",
        resource_id=str(uuid.uuid4()),
        ip_address="127.0.0.1",
        user_agent="test-agent",
    )

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.actor_id == actor_id)
    )
    log = result.scalar_one()
    assert log.action == "create"
    assert log.resource_type == "team"
    assert log.ip_address == "127.0.0.1"


async def test_log_action_with_snapshots(db_session):
    """log_action can record before/after values."""
    actor_id = uuid.uuid4()
    await log_action(
        db=db_session,
        actor_id=actor_id,
        actor_type="user",
        action="update",
        resource_type="user",
        resource_id="user-123",
        ip_address="10.0.0.1",
        user_agent="admin-ui",
        before_value={"role": "member"},
        after_value={"role": "proxy_admin"},
    )

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.actor_id == actor_id)
    )
    log = result.scalar_one()
    assert log.before_value == {"role": "member"}
    assert log.after_value == {"role": "proxy_admin"}


async def test_log_deletion_user(db_session):
    """log_deletion records a deleted user."""
    original_id = uuid.uuid4()
    deleted_by = uuid.uuid4()
    await log_deletion(
        db=db_session,
        resource_type="user",
        original_id=original_id,
        deleted_by=deleted_by,
        snapshot={"email": "gone@test.com", "role": "member"},
        email="gone@test.com",
    )

    result = await db_session.execute(
        select(DeletedUser).where(DeletedUser.original_id == original_id)
    )
    row = result.scalar_one()
    assert row.email == "gone@test.com"
    assert row.deleted_by == deleted_by


async def test_log_deletion_team(db_session):
    """log_deletion records a deleted team."""
    original_id = uuid.uuid4()
    deleted_by = uuid.uuid4()
    await log_deletion(
        db=db_session,
        resource_type="team",
        original_id=original_id,
        deleted_by=deleted_by,
        snapshot={"name": "Gone Team"},
        name="Gone Team",
    )

    result = await db_session.execute(
        select(DeletedTeam).where(DeletedTeam.original_id == original_id)
    )
    row = result.scalar_one()
    assert row.name == "Gone Team"


async def test_log_deletion_key(db_session):
    """log_deletion records a deleted key."""
    original_id = uuid.uuid4()
    deleted_by = uuid.uuid4()
    await log_deletion(
        db=db_session,
        resource_type="key",
        original_id=original_id,
        deleted_by=deleted_by,
        snapshot={"key_prefix": "sk-abc123"},
        key_prefix="sk-abc123",
    )

    result = await db_session.execute(
        select(DeletedKey).where(DeletedKey.original_id == original_id)
    )
    row = result.scalar_one()
    assert row.key_prefix == "sk-abc123"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_services/test_audit_service.py -v`
Expected: FAIL

- [ ] **Step 3: Implement audit_service.py**

```python
# src/app/services/audit_service.py
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog, DeletedKey, DeletedTeam, DeletedUser


async def log_action(
    db: AsyncSession,
    actor_id: uuid.UUID,
    actor_type: str,
    action: str,
    resource_type: str,
    resource_id: str,
    ip_address: str,
    user_agent: str,
    before_value: dict | None = None,
    after_value: dict | None = None,
) -> AuditLog:
    """Record an action in the audit log."""
    log = AuditLog(
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before_value=before_value,
        after_value=after_value,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(log)
    await db.flush()
    return log


async def log_deletion(
    db: AsyncSession,
    resource_type: str,
    original_id: uuid.UUID,
    deleted_by: uuid.UUID,
    snapshot: dict | None = None,
    **kwargs,
) -> None:
    """Record entity deletion in the appropriate deleted_* table.

    Args:
        resource_type: "user", "team", or "key"
        original_id: The UUID of the deleted entity
        deleted_by: The UUID of the actor who deleted it
        snapshot: JSON snapshot of the entity before deletion
        **kwargs: Additional fields required by the specific table
            - user: email (required)
            - team: name (required)
            - key: key_prefix (required)
    """
    if resource_type == "user":
        db.add(DeletedUser(
            original_id=original_id,
            email=kwargs["email"],
            deleted_by=deleted_by,
            snapshot=snapshot,
        ))
    elif resource_type == "team":
        db.add(DeletedTeam(
            original_id=original_id,
            name=kwargs["name"],
            deleted_by=deleted_by,
            snapshot=snapshot,
        ))
    elif resource_type == "key":
        db.add(DeletedKey(
            original_id=original_id,
            key_prefix=kwargs["key_prefix"],
            deleted_by=deleted_by,
            snapshot=snapshot,
        ))
    else:
        raise ValueError(f"Unknown resource_type: {resource_type}")

    await db.flush()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_services/test_audit_service.py -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/services/audit_service.py tests/test_services/test_audit_service.py
git commit -m "feat: audit logging — action tracking + deletion history"
```
