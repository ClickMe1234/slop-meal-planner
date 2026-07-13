from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .errors import DiscoveryError
from .models import CombinedSearchResponse, SearchResult, SourceSearchResponse
from .registry import SourceRegistry, default_registry


@dataclass(frozen=True, slots=True)
class SearchPolicy:
    """Policy returned to the UI and enforced for remote publisher searches."""

    debounce_ms: int = 350
    cache_ttl_seconds: int = 900
    error_cache_ttl_seconds: int = 60
    maximum_cache_entries: int = 256
    minimum_query_length: int = 2
    maximum_results_per_source: int = 24


class LiveSearchService:
    """Debounced, cached fan-out over supported publisher adapters.

    The frontend should display its local PostgreSQL search immediately on each
    keystroke. It calls this remote service after the advertised debounce and
    cancels older requests. The generation check below is a second server-side
    guard: only the newest request for a ``request_key`` reaches publishers.

    Search never runs ingredient matching or nutrition calculation. It only
    exposes publisher-reported preview nutrition already present in result HTML.
    """

    def __init__(
        self,
        fetcher,
        *,
        registry: SourceRegistry = default_registry,
        policy: SearchPolicy = SearchPolicy(),
        saved_url_lookup: Callable[[tuple[str, ...]], set[str] | Awaitable[set[str]]] | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.registry = registry
        self.policy = policy
        self.saved_url_lookup = saved_url_lookup
        self._cache: dict[str, tuple[float, tuple[SourceSearchResponse, ...]]] = {}
        self._generations: dict[str, int] = {}
        self._generation_lock = asyncio.Lock()

    @staticmethod
    def normalise_query(query: str) -> str:
        return " ".join(query.casefold().split())[:200]

    async def search_remote(self, query: str, *, request_key: str | None = None) -> CombinedSearchResponse:
        normalised = self.normalise_query(query)
        if len(normalised) < self.policy.minimum_query_length:
            return CombinedSearchResponse(normalised, (), self.policy.debounce_ms)

        generation = None
        if request_key:
            async with self._generation_lock:
                generation = self._generations.get(request_key, 0) + 1
                self._generations[request_key] = generation
        await asyncio.sleep(self.policy.debounce_ms / 1000)
        if request_key and self._generations.get(request_key) != generation:
            return CombinedSearchResponse(normalised, (), self.policy.debounce_ms, superseded=True)

        now = time.monotonic()
        cached = self._cache.get(normalised)
        cache_hit = cached is not None and now <= cached[0]
        if cache_hit:
            sources = cached[1]
        else:
            sources = tuple(await asyncio.gather(*(self._search_source(adapter, normalised) for adapter in self.registry.adapters)))
            ttl = (
                self.policy.error_cache_ttl_seconds
                if any(source.error_code for source in sources)
                else self.policy.cache_ttl_seconds
            )
            self._cache = {key: value for key, value in self._cache.items() if now <= value[0]}
            if len(self._cache) >= self.policy.maximum_cache_entries:
                self._cache.pop(next(iter(self._cache)))
            self._cache[normalised] = (now + ttl, sources)

        if self.saved_url_lookup:
            urls = tuple(result.url for source in sources for result in source.results)
            saved = self.saved_url_lookup(urls)
            if inspect.isawaitable(saved):
                saved = await saved
            sources = tuple(
                SourceSearchResponse(
                    source=source.source,
                    results=tuple(
                        SearchResult(
                            source=result.source,
                            title=result.title,
                            url=result.url,
                            image_url=result.image_url,
                            publisher_nutrition=result.publisher_nutrition,
                            already_saved=result.url in saved,
                        )
                        for result in source.results
                    ),
                    error_code=source.error_code,
                    error_message=source.error_message,
                )
                for source in sources
            )
        return CombinedSearchResponse(normalised, sources, self.policy.debounce_ms, cache_hit=cache_hit)

    async def search(self, query: str, *, request_key: str | None = None) -> CombinedSearchResponse:
        return await self.search_remote(query, request_key=request_key)

    async def _search_source(self, adapter, query: str) -> SourceSearchResponse:
        try:
            url = adapter.search_url(query)
            html = await self.fetcher.fetch_text(url, allowed_hosts=set(adapter.hosts))
            results = adapter.parse_search_results(html, search_url=url)[: self.policy.maximum_results_per_source]
            return SourceSearchResponse(adapter.key, results)
        except DiscoveryError as exc:
            return SourceSearchResponse(adapter.key, error_code=exc.code, error_message=str(exc))
        except Exception:
            # Do not leak parser/network internals through an API response.
            return SourceSearchResponse(
                adapter.key,
                error_code="SOURCE_PARSE_FAILED",
                error_message=f"{adapter.display_name} results could not be read. {adapter.limitation()}",
            )
