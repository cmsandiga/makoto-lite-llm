"""OIDC client — handles IdP communication (discovery, token exchange, userinfo)."""

import httpx


class OIDCClient:
    """Async OIDC client for a single issuer."""

    def __init__(self, issuer_url: str) -> None:
        self.issuer_url = issuer_url.rstrip("/")
        self._discovery_cache: dict | None = None

    async def discover(self) -> dict:
        """Fetch the OIDC discovery document. Cached after first call."""
        if self._discovery_cache is not None:
            return self._discovery_cache

        url = f"{self.issuer_url}/.well-known/openid-configuration"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(
                f"OIDC discovery failed for {self.issuer_url}: "
                f"HTTP {resp.status_code}"
            )
        self._discovery_cache = resp.json()
        return self._discovery_cache

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        client_id: str,
        client_secret: str,
        code_verifier: str | None = None,
    ) -> dict:
        """Exchange an authorization code for tokens."""
        discovery = await self.discover()
        token_endpoint = discovery["token_endpoint"]

        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier

        async with httpx.AsyncClient() as client:
            resp = await client.post(token_endpoint, data=data, timeout=10)

        if resp.status_code != 200:
            content_type = resp.headers.get("content-type", "")
            error: dict = (
                resp.json() if content_type.startswith("application/json") else {}
            )
            raise RuntimeError(
                f"Token exchange failed: {error.get('error', resp.status_code)} "
                f"— {error.get('error_description', resp.text)}"
            )
        return resp.json()

    async def fetch_userinfo(self, access_token: str) -> dict:
        """Fetch user claims from the userinfo endpoint."""
        discovery = await self.discover()
        userinfo_endpoint = discovery["userinfo_endpoint"]

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Userinfo fetch failed: HTTP {resp.status_code}"
            )
        return resp.json()
