from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import AuthContext, get_auth_context
from ..db import get_db
from ..discovery import LiveSearchService
from ..discovery.categories import (
    MAX_SELECTED_CATEGORIES,
    RECIPE_CATEGORIES,
    validate_category_keys,
)
from ..discovery.errors import DiscoveryError, FetchError
from ..discovery.http import PoliteHttpFetcher
from ..discovery.urls import canonicalize_url
from ..errors import DomainError
from ..models import Recipe
from ..models import IngredientLocale
from ..services.regional_ingredients import query_for_locale

router = APIRouter(prefix="/recipe-discovery", tags=["recipe discovery"])

_fetcher: PoliteHttpFetcher | None = None
_image_fetcher: PoliteHttpFetcher | None = None
_service: LiveSearchService | None = None


def _live_service() -> LiveSearchService:
    global _fetcher, _service
    if _service is None:
        _fetcher = PoliteHttpFetcher()
        _service = LiveSearchService(_fetcher)
    return _service


def _live_image_fetcher() -> PoliteHttpFetcher:
    global _image_fetcher
    if _image_fetcher is None:
        _image_fetcher = PoliteHttpFetcher(
            min_host_interval_seconds=0.25,
            max_response_bytes=8_000_000,
        )
    return _image_fetcher


def _json_safe(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


@router.get("/categories")
def list_recipe_categories(
    context: AuthContext = Depends(get_auth_context),
):
    """Return the reviewed cross-publisher category vocabulary in display order."""

    del context
    return {
        "maximum_selected": MAX_SELECTED_CATEGORIES,
        "match": "any",
        "items": [
            {
                "key": category.key,
                "label": category.label,
                "rank": rank,
                "confidence": category.confidence,
                "providers": {
                    "good_food": category.good_food.mode,
                    "allrecipes": category.allrecipes.mode,
                },
            }
            for rank, category in enumerate(RECIPE_CATEGORIES, start=1)
        ],
    }


@router.get("/nutrition-preview")
async def preview_recipe_nutrition(
    url: str = Query(max_length=4096),
    refresh: bool = Query(default=False),
    context: AuthContext = Depends(get_auth_context),
):
    """Return publisher-reported nutrition without saving or calculating."""

    del context  # Authentication is required, but the preview is not household-specific.
    try:
        recipe = await _live_service().nutrition_preview(url, force=refresh)
    except DiscoveryError as exc:
        status = 502 if isinstance(exc, FetchError) else 422
        raise DomainError(exc.code, str(exc), status) from exc
    return _json_safe(
        {
            "url": recipe.canonical_url,
            "publisher": recipe.publisher,
            "yield_servings": recipe.yield_servings,
            "publisher_nutrition": (
                asdict(recipe.publisher_nutrition) if recipe.publisher_nutrition else None
            ),
        }
    )


@router.get("/image")
async def proxy_recipe_image(
    url: str = Query(max_length=4096),
    context: AuthContext = Depends(get_auth_context),
):
    """Return a public recipe image without exposing the user's browser."""

    del context
    try:
        content, content_type = await _live_image_fetcher().fetch_bytes(
            url,
            allowed_content_types={
                "image/avif",
                "image/gif",
                "image/jpeg",
                "image/png",
                "image/webp",
            },
        )
    except DiscoveryError as exc:
        status = 502 if isinstance(exc, FetchError) else 422
        raise DomainError(exc.code, str(exc), status) from exc
    return Response(
        content=content,
        media_type=content_type,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("")
async def discover_recipes(
    q: str = Query(default="", max_length=200),
    request_key: str | None = Query(default=None, max_length=100),
    sources: str | None = Query(default=None, max_length=200),
    publisher_category: list[str] = Query(default=[]),
    publisher_category_match: Literal["any", "all"] = Query(default="any"),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    """Fan out to supported public searches without calculating nutrition."""

    scoped_request_key = (
        f"{context.user.household_id}:{context.user.id}:{request_key}" if request_key else None
    )
    selected_sources = None
    if sources is not None:
        selected_sources = tuple(dict.fromkeys(item.strip() for item in sources.split(",") if item.strip()))
        supported = {adapter.key for adapter in _live_service().registry.adapters}
        unknown = set(selected_sources) - supported
        if unknown:
            raise DomainError("UNSUPPORTED_RECIPE_SOURCE", f"Unsupported recipe source: {', '.join(sorted(unknown))}", 422)
    try:
        selected_categories = validate_category_keys(publisher_category)
    except ValueError as exc:
        raise DomainError("TOO_MANY_RECIPE_CATEGORIES", str(exc), 422) from exc
    except KeyError as exc:
        raise DomainError("UNKNOWN_RECIPE_CATEGORY", f"Unknown recipe category: {exc.args[0]}", 422) from exc
    response = await _live_service().search(
        q,
        request_key=scoped_request_key,
        sources=selected_sources,
        source_queries={
            "good_food": query_for_locale(db, q, IngredientLocale.UK),
            "allrecipes": query_for_locale(db, q, IngredientLocale.US),
        },
        categories=selected_categories,
        category_match=publisher_category_match,
    )
    saved_rows = db.scalars(
        select(Recipe.source_url).where(
            Recipe.household_id == context.user.household_id,
            Recipe.source_url.is_not(None),
        )
    ).all()
    saved: set[str] = set()
    for url in saved_rows:
        try:
            saved.add(canonicalize_url(url))
        except Exception:
            continue

    sources = []
    for source in response.sources:
        source_data = asdict(source)
        for result in source_data["results"]:
            result["already_saved"] = result["url"] in saved
        sources.append(_json_safe(source_data))
    return {
        "query": response.query,
        "sources": sources,
        "results": [
            next(
                result
                for source in sources
                for result in source["results"]
                if result["url"] == ranked.url
            )
            for ranked in response.results
        ],
        "debounce_ms": response.debounce_ms,
        "cache_hit": response.cache_hit,
        "superseded": response.superseded,
    }


async def close_discovery_client() -> None:
    global _fetcher, _image_fetcher, _service
    if _fetcher is not None:
        await _fetcher.aclose()
    if _image_fetcher is not None:
        await _image_fetcher.aclose()
    _fetcher = None
    _image_fetcher = None
    _service = None
