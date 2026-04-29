import httpx
import pytest


@pytest.mark.e2e
def test_keycloak_discovery_doc(keycloak_issuer_url):
    resp = httpx.get(
        f"{keycloak_issuer_url}/.well-known/openid-configuration",
        timeout=10,
    )
    assert resp.status_code == 200
    doc = resp.json()
    assert doc["issuer"].endswith("/realms/litellm")
    assert "token_endpoint" in doc
    assert "userinfo_endpoint" in doc
