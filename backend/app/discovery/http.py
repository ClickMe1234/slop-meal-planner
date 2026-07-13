from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from urllib.parse import urljoin, urlsplit

import httpx

from .errors import FetchError, ResponseTooLargeError
from .urls import validate_fetch_url


class PoliteHttpFetcher:
    """Rate-limited HTML fetcher with redirect and response-size guards."""

    def __init__(
        self,
        *,
        min_host_interval_seconds: float = 1.0,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 2_000_000,
        max_redirects: int = 3,
        user_agent: str = "HouseholdMealPlanner/0.1 (private recipe organiser; contact local administrator)",
        client: httpx.AsyncClient | None = None,
        resolver=None,
    ) -> None:
        self.min_host_interval_seconds = min_host_interval_seconds
        self.max_response_bytes = max_response_bytes
        self.max_redirects = max_redirects
        self._resolver = resolver
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"},
        )
        self._owns_client = client is None
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_request: dict[str, float] = {}

    async def fetch_text(self, url: str, *, allowed_hosts: set[str]) -> str:
        current = await asyncio.to_thread(
            validate_fetch_url,
            url,
            resolver=self._resolver,
            allowed_hosts=allowed_hosts,
        )
        for redirect_count in range(self.max_redirects + 1):
            host = urlsplit(current).hostname or ""
            async with self._locks[host]:
                delay = self.min_host_interval_seconds - (time.monotonic() - self._last_request.get(host, 0.0))
                if delay > 0:
                    await asyncio.sleep(delay)
                try:
                    async with self._client.stream("GET", current) as response:
                        self._last_request[host] = time.monotonic()
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise FetchError("The publisher returned a redirect without a destination")
                            if redirect_count >= self.max_redirects:
                                raise FetchError("The publisher returned too many redirects")
                            current = await asyncio.to_thread(
                                validate_fetch_url,
                                urljoin(current, location),
                                resolver=self._resolver,
                                allowed_hosts=allowed_hosts,
                            )
                            continue
                        if response.status_code in {403, 429}:
                            raise FetchError(
                                "The publisher declined or rate-limited the request; the application will not bypass that control"
                            )
                        if response.status_code >= 400:
                            raise FetchError(f"The publisher returned HTTP {response.status_code}")
                        content_type = response.headers.get("content-type", "").lower()
                        if content_type and "html" not in content_type:
                            raise FetchError("The publisher response was not HTML")
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > self.max_response_bytes:
                                raise ResponseTooLargeError("The publisher response exceeded the safe size limit")
                            chunks.append(chunk)
                        return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                except httpx.HTTPError as exc:
                    raise FetchError("The publisher could not be reached") from exc
        raise FetchError("The publisher redirect could not be resolved")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
