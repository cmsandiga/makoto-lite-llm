import uuid

from app.auth.jwt_handler import create_access_token, create_refresh_token, decode_token


def test_create_and_decode_access_token():
    user_id = uuid.uuid4()
    token = create_access_token(
        user_id=user_id, role="proxy_admin", org_id=None, team_id=None
    )
    payload = decode_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["role"] == "proxy_admin"
    assert payload["type"] == "access"


def test_create_and_decode_refresh_token():
    user_id = uuid.uuid4()
    token = create_refresh_token(user_id=user_id)
    payload = decode_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "refresh"


def test_decode_invalid_token():
    payload = decode_token("invalid.token.here")
    assert payload is None
