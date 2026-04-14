import httpx
import pytest
import respx

from app.services.oidc_client import OIDCClient

ISSUER = "https://accounts.google.com"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
DISCOVERY_DOC = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/o/oauth2/v2/auth",
    "token_endpoint": f"{ISSUER}/o/oauth2/token",
    "userinfo_endpoint": f"{ISSUER}/oauth2/v3/userinfo",
    "jwks_uri": f"{ISSUER}/oauth2/v3/certs",
}
TOKEN_ENDPOINT = f"{ISSUER}/o/oauth2/token"
TOKEN_RESPONSE = {
    "access_token": "ya29.access",
    "id_token": (
        "eyJhbGciOiJSUzI1NiJ9"
        ".eyJzdWIiOiIxMjM0NTYiLCJlbWFpbCI6InVzZXJAYWNtZS5jb20ifQ"
        ".fake"
    ),
    "token_type": "Bearer",
    "expires_in": 3600,
}
USERINFO_ENDPOINT = f"{ISSUER}/oauth2/v3/userinfo"
USERINFO_RESPONSE = {
    "sub": "123456",
    "email": "user@acme.com",
    "name": "Test User",
    "groups": ["Engineering", "Platform"],
}


# === Discovery ===


@respx.mock
async def test_discover_fetches_and_caches():
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json=DISCOVERY_DOC)
    )
    client = OIDCClient(issuer_url=ISSUER)
    doc = await client.discover()
    assert doc["token_endpoint"] == f"{ISSUER}/o/oauth2/token"
    assert doc["userinfo_endpoint"] == f"{ISSUER}/oauth2/v3/userinfo"
    # Second call should use cache, not make another request
    doc2 = await client.discover()
    assert doc2 == doc
    assert respx.calls.call_count == 1


@respx.mock
async def test_discover_bad_status_raises():
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(404, text="Not found")
    )
    client = OIDCClient(issuer_url=ISSUER)
    with pytest.raises(RuntimeError, match="OIDC discovery failed"):
        await client.discover()


# === Token Exchange ===


@respx.mock
async def test_exchange_code():
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json=DISCOVERY_DOC)
    )
    respx.post(TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    client = OIDCClient(issuer_url=ISSUER)
    tokens = await client.exchange_code(
        code="auth-code-123",
        redirect_uri="http://localhost:8000/sso/callback",
        client_id="client-123",
        client_secret="secret-456",
        code_verifier="test-verifier",
    )
    assert tokens["access_token"] == "ya29.access"
    assert "id_token" in tokens
    # Verify the POST body included PKCE code_verifier
    request = respx.calls.last.request
    body = request.content.decode()
    assert "code_verifier=test-verifier" in body
    assert "grant_type=authorization_code" in body


@respx.mock
async def test_exchange_code_error():
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json=DISCOVERY_DOC)
    )
    respx.post(TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(
            400,
            json={"error": "invalid_grant", "error_description": "Code expired"},
        )
    )
    client = OIDCClient(issuer_url=ISSUER)
    with pytest.raises(RuntimeError, match="Token exchange failed"):
        await client.exchange_code(
            code="expired-code",
            redirect_uri="http://localhost:8000/sso/callback",
            client_id="client-123",
            client_secret="secret-456",
        )


# === Userinfo ===


@respx.mock
async def test_fetch_userinfo():
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json=DISCOVERY_DOC)
    )
    respx.get(USERINFO_ENDPOINT).mock(
        return_value=httpx.Response(200, json=USERINFO_RESPONSE)
    )
    client = OIDCClient(issuer_url=ISSUER)
    info = await client.fetch_userinfo(access_token="ya29.access")
    assert info["email"] == "user@acme.com"
    assert info["sub"] == "123456"
    assert info["groups"] == ["Engineering", "Platform"]
    # Verify Bearer token was sent
    request = respx.calls.last.request
    assert request.headers["Authorization"] == "Bearer ya29.access"


@respx.mock
async def test_fetch_userinfo_error():
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json=DISCOVERY_DOC)
    )
    respx.get(USERINFO_ENDPOINT).mock(
        return_value=httpx.Response(401, json={"error": "invalid_token"})
    )
    client = OIDCClient(issuer_url=ISSUER)
    with pytest.raises(RuntimeError, match="Userinfo fetch failed"):
        await client.fetch_userinfo(access_token="expired-token")
