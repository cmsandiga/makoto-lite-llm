import asyncio
import json
from collections.abc import AsyncIterator

import httpx


class _StreamingHTTPError(Exception):
    """Raised internally when post_stream sees a 4xx/5xx before yielding."""

    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.body = body


class LLMHttpClient:
    """Pooled async httpx wrapper. One client per (api_base, api_key) tuple.

    Clients are never closed on cache eviction — there may be in-flight
    requests using them. Cleanup is process-shutdown only via aclose_all().
    """

    def __init__(self, default_timeout: float = 600.0):
        self._clients: dict[tuple[str, str], httpx.AsyncClient] = {}
        self._lock = asyncio.Lock()
        self._default_timeout = default_timeout

    async def _get_client(self, api_base: str, api_key: str) -> httpx.AsyncClient:
        key = (api_base, api_key)
        client = self._clients.get(key)
        if client is not None:
            return client
        async with self._lock:
            client = self._clients.get(key)  # double-checked
            if client is None:
                client = httpx.AsyncClient(
                    base_url=api_base,
                    timeout=httpx.Timeout(self._default_timeout, connect=10.0),
                    limits=httpx.Limits(
                        max_keepalive_connections=20,
                        max_connections=100,
                    ),
                )
                self._clients[key] = client
        return client

    async def post(
        self,
        api_base: str,
        api_key: str,
        path: str,
        headers: dict,
        json_body: dict,
        timeout: float | None = None,
    ) -> tuple[int, dict]:
        client = await self._get_client(api_base, api_key)
        resp = await client.post(
            path,
            headers=headers,
            json=json_body,
            timeout=timeout or self._default_timeout,
        )
        try:
            body = resp.json()
        except json.JSONDecodeError:
            body = {"error": {"message": resp.text}}
        return resp.status_code, body

    async def post_stream(
        self,
        api_base: str,
        api_key: str,
        path: str,
        headers: dict,
        json_body: dict,
        timeout: float | None = None,
    ) -> AsyncIterator[dict]:
        """Yield parsed JSON dicts from an SSE stream.

        Filters '[DONE]' sentinels and blank/non-data lines.
        """
        client = await self._get_client(api_base, api_key)
        async with client.stream(
            "POST",
            path,
            headers=headers,
            json=json_body,
            timeout=timeout or self._default_timeout,
        ) as resp:
            if resp.status_code >= 400:
                body_bytes = await resp.aread()
                try:
                    body = json.loads(body_bytes)
                except json.JSONDecodeError:
                    body = {"error": {"message": body_bytes.decode("utf-8", "replace")}}
                raise _StreamingHTTPError(resp.status_code, body)

            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[len("data: ") :].strip()
                if payload == "[DONE]":
                    return
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    continue  # malformed chunk; skip rather than abort the stream

    async def aclose_all(self) -> None:
        for c in list(self._clients.values()):
            await c.aclose()
        self._clients.clear()


_default_client: LLMHttpClient | None = None


def get_http_client() -> LLMHttpClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMHttpClient()
    return _default_client
