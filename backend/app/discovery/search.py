from __future__ import annotations

import asyncio
import inspect
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from dataclasses import replace
from typing import Literal
from urllib.parse import urlsplit

from .categories import CATEGORY_BY_KEY, RecipeCategory
from .errors import DiscoveryError, UnsupportedSourceError
from .extraction import extract_recipe
from .models import CombinedSearchResponse, ExtractedRecipe, SearchResult, SourceSearchResponse
from .registry import SourceRegistry, default_registry
from .urls import canonicalize_url


@dataclass(frozen=True, slots=True)
class SearchPolicy:
    """Policy returned to the UI and enforced for remote publisher searches."""

    debounce_ms: int = 350
    cache_ttl_seconds: int = 900
    error_cache_ttl_seconds: int = 60
    maximum_cache_entries: int = 256
    minimum_query_length: int = 2
    maximum_results_per_source: int = 24
    preview_cache_ttl_seconds: int = 3600
    maximum_preview_cache_entries: int = 512


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
        self._category_cache: dict[tuple[str, str], tuple[float, SourceSearchResponse]] = {}
        self._preview_cache: dict[str, tuple[float, ExtractedRecipe]] = {}
        self._preview_locks: dict[str, asyncio.Lock] = {}
        self._generations: dict[str, int] = {}
        self._generation_lock = asyncio.Lock()

    @staticmethod
    def normalise_query(query: str) -> str:
        return " ".join(query.casefold().split())[:200]

    async def search_remote(
        self,
        query: str,
        *,
        request_key: str | None = None,
        sources: tuple[str, ...] | None = None,
        source_queries: dict[str, str] | None = None,
        categories: tuple[str, ...] = (),
        category_match: Literal["any", "all"] = "any",
    ) -> CombinedSearchResponse:
        normalised = self.normalise_query(query)
        if len(normalised) < self.policy.minimum_query_length and not categories:
            return CombinedSearchResponse(normalised, (), self.policy.debounce_ms)

        selected = set(sources) if sources is not None else None
        adapters = tuple(
            adapter for adapter in self.registry.adapters
            if selected is None or adapter.key in selected
        )
        source_key = ",".join(sorted(adapter.key for adapter in adapters))
        normalised_source_queries = {
            key: self.normalise_query(value)
            for key, value in (source_queries or {}).items()
        }
        query_key = ",".join(
            f"{adapter.key}={normalised_source_queries.get(adapter.key, normalised)}"
            for adapter in adapters
        )
        category_key = ",".join(categories)
        cache_key = f"{source_key}:{query_key}:{category_key}"

        generation = None
        if request_key:
            async with self._generation_lock:
                generation = self._generations.get(request_key, 0) + 1
                self._generations[request_key] = generation
        await asyncio.sleep(self.policy.debounce_ms / 1000)
        if request_key and self._generations.get(request_key) != generation:
            return CombinedSearchResponse(normalised, (), self.policy.debounce_ms, superseded=True)

        now = time.monotonic()
        cached = self._cache.get(cache_key) if not categories else None
        cache_hit = cached is not None and now <= cached[0]
        if categories:
            before = {
                (adapter.key, category): self._category_cache.get((adapter.key, category))
                for adapter in adapters
                for category in categories
            }
            source_results = tuple(
                await asyncio.gather(
                    *(
                        self._search_source_categories(
                            adapter,
                            tuple(CATEGORY_BY_KEY[key] for key in categories),
                            normalised_source_queries.get(adapter.key, normalised),
                            category_match,
                        )
                        for adapter in adapters
                    )
                )
            )
            cache_hit = all(
                cached_category is not None and now <= cached_category[0]
                for cached_category in before.values()
            )
        elif not cache_hit:
            source_results = tuple(
                await asyncio.gather(
                    *(
                        self._search_source(
                            adapter,
                            normalised_source_queries.get(adapter.key, normalised),
                        )
                        for adapter in adapters
                    )
                )
            )
            ttl = (
                self.policy.error_cache_ttl_seconds
                if any(source.error_code for source in source_results)
                else self.policy.cache_ttl_seconds
            )
            self._cache = {key: value for key, value in self._cache.items() if now <= value[0]}
            if len(self._cache) >= self.policy.maximum_cache_entries:
                self._cache.pop(next(iter(self._cache)))
            self._cache[cache_key] = (now + ttl, source_results)

        if cache_hit and cached is not None:
            source_results = cached[1]

        if self.saved_url_lookup:
            urls = tuple(result.url for source in source_results for result in source.results)
            saved = self.saved_url_lookup(urls)
            if inspect.isawaitable(saved):
                saved = await saved
            source_results = tuple(
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
                            star_rating=result.star_rating,
                            rating_count=result.rating_count,
                            matched_categories=result.matched_categories,
                        )
                        for result in source.results
                    ),
                    error_code=source.error_code,
                    error_message=source.error_message,
                    warnings=source.warnings,
                )
                for source in source_results
            )
        return CombinedSearchResponse(normalised, source_results, self.policy.debounce_ms, cache_hit=cache_hit)

    async def search(
        self,
        query: str,
        *,
        request_key: str | None = None,
        sources: tuple[str, ...] | None = None,
        source_queries: dict[str, str] | None = None,
        categories: tuple[str, ...] = (),
        category_match: Literal["any", "all"] = "any",
    ) -> CombinedSearchResponse:
        return await self.search_remote(
            query,
            request_key=request_key,
            sources=sources,
            source_queries=source_queries,
            categories=categories,
            category_match=category_match,
        )

    async def nutrition_preview(self, url: str, *, force: bool = False) -> ExtractedRecipe:
        """Fetch publisher nutrition without importing the recipe.

        Supported publishers use their adapter host policy. Generic imported
        URLs are limited to the submitted host and its ordinary ``www`` pair,
        matching the worker import boundary. An explicit refresh bypasses the
        normal preview cache so the user can restore source values after an
        edit.
        """

        canonical = canonicalize_url(url)
        try:
            adapter = self.registry.for_url(canonical)
            allowed_hosts = set(adapter.hosts)
        except UnsupportedSourceError:
            host = urlsplit(canonical).hostname or ""
            host_without_www = host.removeprefix("www.")
            allowed_hosts = {host_without_www, f"www.{host_without_www}"}
        now = time.monotonic()
        if not force:
            cached = self._preview_cache.get(canonical)
            if cached is not None and now <= cached[0]:
                return cached[1]

        lock = self._preview_locks.setdefault(canonical, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            if not force:
                cached = self._preview_cache.get(canonical)
                if cached is not None and now <= cached[0]:
                    return cached[1]

            html = await self.fetcher.fetch_text(canonical, allowed_hosts=allowed_hosts)
            recipe = extract_recipe(html, canonical)
            expired_keys = [
                key for key, value in self._preview_cache.items() if now > value[0]
            ]
            for key in expired_keys:
                self._preview_cache.pop(key, None)
                self._preview_locks.pop(key, None)
            if len(self._preview_cache) >= self.policy.maximum_preview_cache_entries:
                evicted = next(iter(self._preview_cache))
                self._preview_cache.pop(evicted)
                self._preview_locks.pop(evicted, None)
            self._preview_cache[canonical] = (
                now + self.policy.preview_cache_ttl_seconds,
                recipe,
            )
            return recipe

    async def _search_source(self, adapter, query: str) -> SourceSearchResponse:
        try:
            url = adapter.search_url(query)
            html = await self.fetcher.fetch_text(url, allowed_hosts=set(adapter.hosts))
            parsed = adapter.parse_search_results(html, search_url=url)
            ranked = sorted(
                (
                    (self._relevance_score(result, query), result)
                    for result in parsed
                ),
                key=lambda item: (
                    item[1].rating_rank is None,
                    -(item[1].rating_rank or 0),
                    -(item[1].rating_count or 0),
                    -item[0],
                    item[1].title.casefold(),
                ),
            )
            results = tuple(
                result
                for score, result in ranked
                if score > 0
            )[: self.policy.maximum_results_per_source]
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

    async def _search_source_categories(
        self,
        adapter,
        categories: tuple[RecipeCategory, ...],
        query: str,
        category_match: Literal["any", "all"],
    ) -> SourceSearchResponse:
        responses = await asyncio.gather(
            *(self._search_category(adapter, category) for category in categories)
        )
        merged: dict[str, SearchResult] = {}
        warnings: list[str] = []
        for category, response in zip(categories, responses, strict=True):
            if response.error_code:
                warnings.append(f"{category.label}: {response.error_message}")
            for result in response.results:
                existing = merged.get(result.url)
                if existing is None:
                    merged[result.url] = result
                    continue
                merged[result.url] = replace(
                    existing,
                    image_url=existing.image_url or result.image_url,
                    publisher_nutrition=existing.publisher_nutrition or result.publisher_nutrition,
                    star_rating=existing.star_rating or result.star_rating,
                    rating_count=(
                        existing.rating_count
                        if existing.rating_count is not None
                        else result.rating_count
                    ),
                    matched_categories=tuple(dict.fromkeys(
                        (*existing.matched_categories, *result.matched_categories)
                    )),
                )

        required_categories = {category.key for category in categories}
        ranked = []
        for result in merged.values():
            if category_match == "all" and not required_categories.issubset(result.matched_categories):
                continue
            relevance = self._relevance_score(result, query) if query else 1
            if relevance > 0:
                ranked.append((relevance, result))
        ranked.sort(key=lambda item: (
            item[1].rating_rank is None,
            -(item[1].rating_rank or 0),
            -(item[1].rating_count or 0),
            -item[0],
            item[1].title.casefold(),
        ))
        results = tuple(result for _, result in ranked)[: self.policy.maximum_results_per_source]
        if results or not warnings:
            return SourceSearchResponse(adapter.key, results, warnings=tuple(warnings))
        return SourceSearchResponse(
            adapter.key,
            error_code="CATEGORY_SEARCH_FAILED",
            error_message=f"{adapter.display_name} category results could not be loaded.",
            warnings=tuple(warnings),
        )

    async def _search_category(
        self,
        adapter,
        category: RecipeCategory,
    ) -> SourceSearchResponse:
        cache_key = (adapter.key, category.key)
        now = time.monotonic()
        cached = self._category_cache.get(cache_key)
        if cached is not None and now <= cached[0]:
            return cached[1]

        target = category.target_for(adapter.key)
        try:
            if target.url:
                url = target.url
                html = await self.fetcher.fetch_text(url, allowed_hosts=set(adapter.hosts))
                parsed = adapter.parse_search_results(html, search_url=url)
                ordered = sorted(
                    parsed,
                    key=lambda result: (
                        result.rating_rank is None,
                        -(result.rating_rank or 0),
                        -(result.rating_count or 0),
                        result.title.casefold(),
                    ),
                )
                results = tuple(
                    replace(result, matched_categories=(category.key,))
                    for result in ordered[: self.policy.maximum_results_per_source]
                )
                response = SourceSearchResponse(adapter.key, results)
            else:
                response = await self._search_source(adapter, target.query or category.label)
                response = replace(
                    response,
                    results=tuple(
                        replace(result, matched_categories=(category.key,))
                        for result in response.results
                    ),
                )
        except DiscoveryError as exc:
            response = SourceSearchResponse(
                adapter.key, error_code=exc.code, error_message=str(exc)
            )
        except Exception:
            response = SourceSearchResponse(
                adapter.key,
                error_code="SOURCE_PARSE_FAILED",
                error_message=f"{adapter.display_name} results could not be read. {adapter.limitation()}",
            )

        ttl = (
            self.policy.error_cache_ttl_seconds
            if response.error_code
            else self.policy.cache_ttl_seconds
        )
        self._category_cache = {
            key: value for key, value in self._category_cache.items() if now <= value[0]
        }
        if len(self._category_cache) >= self.policy.maximum_cache_entries:
            self._category_cache.pop(next(iter(self._category_cache)))
        self._category_cache[cache_key] = (now + ttl, response)
        return response

    @staticmethod
    def _relevance_score(result: SearchResult, query: str) -> int:
        """Reject navigation/category cards and put the closest titles first."""

        phrase = " ".join(query.casefold().split())
        terms = tuple(dict.fromkeys(re.findall(r"[a-z0-9]+", phrase)))
        haystack = f"{result.title} {result.url.replace('-', ' ')}".casefold()
        matches = sum(1 for term in terms if term in haystack)
        if not matches:
            return 0
        score = matches * 20
        if matches == len(terms):
            score += 40
        if phrase and phrase in haystack:
            score += 100
        if result.title.casefold().startswith(phrase):
            score += 20
        return score
