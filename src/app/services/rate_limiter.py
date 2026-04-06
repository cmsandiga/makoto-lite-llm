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
