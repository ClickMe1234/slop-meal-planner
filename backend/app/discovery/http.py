from __future__ import annotations

import asyncio
import http.cookiejar
import time
import urllib.error
import urllib.request
from collections import defaultdict
from urllib.parse import urljoin, urlsplit

import httpx

from .errors import FetchError, ResponseTooLargeError
from .urls import validate_fetch_url


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Expose redirects so every destination is revalidated before fetching."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


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
        self.timeout_seconds = timeout_seconds
        self._resolver = resolver
        self._headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-GB,en;q=0.9",
        }
        # httpx remains injectable for deterministic unit tests. The stdlib
        # transport is used in production because some public publisher pages
        # reject httpx's TLS fingerprint while serving the same HTML to an
        # ordinary standards-compliant client. Cookie handling also permits one
        # normal retry when an edge cache sets a session cookie on its first
        # response; no JavaScript challenge or access control is bypassed.
        self._client = client
        self._owns_client = False
        self._openers: dict[str, urllib.request.OpenerDirector] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_request: dict[str, float] = {}

    def _opener(self, host: str) -> urllib.request.OpenerDirector:
        opener = self._openers.get(host)
        if opener is None:
            opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                _NoRedirectHandler(),
            )
            self._openers[host] = opener
        return opener

    def _fetch_with_urllib(self, url: str, host: str):
        opener = self._opener(host)
        for attempt in range(2):
            request = urllib.request.Request(url, headers=self._headers)
            try:
                response = opener.open(request, timeout=self.timeout_seconds)
            except urllib.error.HTTPError as exc:
                response = exc
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                raise FetchError("The publisher could not be reached") from exc

            try:
                status = int(response.status)
                headers = response.headers
                # A few publisher edges set a regular session cookie on the
                # first 402/403 response. Retry once with that cookie, then
                # preserve the explicit declined-access behaviour below.
                if status in {402, 403} and attempt == 0:
                    response.read(self.max_response_bytes + 1)
                    time.sleep(1)
                    continue
                if status in {301, 302, 303, 307, 308} or status >= 400:
                    return status, headers, b"", "utf-8"

                chunks: list[bytes] = []
                size = 0
                while True:
                    chunk = response.read(65_536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.max_response_bytes:
                        raise ResponseTooLargeError(
                            "The publisher response exceeded the safe size limit"
                        )
                    chunks.append(chunk)
                encoding = headers.get_content_charset() or "utf-8"
                return status, headers, b"".join(chunks), encoding
            finally:
                response.close()
        raise FetchError("The publisher declined the request")

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
                if self._client is None:
                    status, headers, content, encoding = await asyncio.to_thread(
                        self._fetch_with_urllib, current, host
                    )
                else:
                    try:
                        async with self._client.stream("GET", current) as response:
                            status = response.status_code
                            headers = response.headers
                            chunks: list[bytes] = []
                            size = 0
                            async for chunk in response.aiter_bytes():
                                size += len(chunk)
                                if size > self.max_response_bytes:
                                    raise ResponseTooLargeError(
                                        "The publisher response exceeded the safe size limit"
                                    )
                                chunks.append(chunk)
                            content = b"".join(chunks)
                            encoding = response.encoding or "utf-8"
                    except httpx.HTTPError as exc:
                        raise FetchError("The publisher could not be reached") from exc

                self._last_request[host] = time.monotonic()
                if status in {301, 302, 303, 307, 308}:
                    location = headers.get("location")
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
                if status in {402, 403, 429}:
                    raise FetchError(
                        "The publisher declined or rate-limited the request; the application will not bypass that control"
                    )
                if status >= 400:
                    raise FetchError(f"The publisher returned HTTP {status}")
                content_type = headers.get("content-type", "").lower()
                if content_type and "html" not in content_type:
                    raise FetchError("The publisher response was not HTML")
                return content.decode(encoding, errors="replace")
        raise FetchError("The publisher redirect could not be resolved")

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
