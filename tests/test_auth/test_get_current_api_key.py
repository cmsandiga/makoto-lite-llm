import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key_auth import generate_api_key
from app.auth.dependencies import _api_key_cache, get_current_api_key
from app.models.api_key import ApiKey
from app.models.user import User


def _make_request(authorization: str | None) -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    return Request({
        "type": "http",
        "headers": headers,
        "method": "POST",
        "path": "/v1/chat/completions",
    })


@pytest.fixture(autouse=True)
def _clear_cache():
    _api_key_cache.clear()
    yield
    _api_key_cache.clear()


async def test_get_current_api_key_returns_apikey_for_sk(db_session: AsyncSession):
    user = User(email="apikey-test@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    raw_key, key_hash = generate_api_key()
    api_key = ApiKey(
        api_key_hash=key_hash,
        user_id=user.id,
        name="test",
    )
    db_session.add(api_key)
    await db_session.commit()

    req = _make_request(f"Bearer {raw_key}")
    result = await get_current_api_key(req, db_session)
    assert result is not None
    assert result.api_key_hash == key_hash


async def test_get_current_api_key_returns_none_for_jwt(db_session: AsyncSession):
    """JWT bearer (not sk- prefix) → no associated ApiKey → returns None."""
    req = _make_request("Bearer eyJhbGc.fake.jwt")
    result = await get_current_api_key(req, db_session)
    assert result is None


async def test_get_current_api_key_returns_none_for_no_header(db_session: AsyncSession):
    """No Authorization header → returns None (route handles auth separately)."""
    req = _make_request(None)
    result = await get_current_api_key(req, db_session)
    assert result is None
