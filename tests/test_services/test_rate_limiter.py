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
