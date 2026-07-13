from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from html import unescape
from urllib.parse import quote_plus, urlsplit

from ..extraction import parse_publisher_nutrition
from ..html import RecipeHtmlParser
from ..models import SearchResult
from ..urls import canonicalize_url


class SourceAdapter(ABC):
    """Contract for a supported publisher's ordinary public search page."""

    key: str
    display_name: str
    hosts: frozenset[str]
    search_url_template: str
    recipe_path_pattern: re.Pattern[str]

    def supports_url(self, url: str) -> bool:
        try:
            host = (urlsplit(canonicalize_url(url)).hostname or "").lower()
        except Exception:
            return False
        return host in self.hosts

    def search_url(self, query: str) -> str:
        cleaned = " ".join(query.split())
        if len(cleaned) < 2:
            raise ValueError("Search queries must contain at least two characters")
        return self.search_url_template.format(query=quote_plus(cleaned))

    def is_recipe_path(self, path: str) -> bool:
        return bool(self.recipe_path_pattern.search(path))

    def parse_search_results(self, html: str, *, search_url: str) -> tuple[SearchResult, ...]:
        parser = RecipeHtmlParser()
        parser.feed(html)
        candidates: list[SearchResult] = []

        # Some publishers expose ItemList/Recipe JSON-LD on result pages. Prefer
        # it because it is explicitly machine-readable and may include nutrition.
        for raw in (*parser.json_ld, *parser.json_data):
            try:
                document = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for node in self._walk(document):
                item = node.get("item") if isinstance(node.get("item"), dict) else node
                types = item.get("@type", "")
                type_values = {str(types).lower()} if isinstance(types, str) else {str(x).lower() for x in types}
                url = item.get("url") or (item.get("@id") if "recipe" in type_values else None)
                title = item.get("name") or item.get("title")
                if not isinstance(url, str) or not isinstance(title, str):
                    continue
                aggregate_rating = item.get("aggregateRating") or item.get("rating")
                if not isinstance(aggregate_rating, dict):
                    aggregate_rating = {}
                candidate = self._result(
                    title,
                    url,
                    search_url,
                    image=item.get("image"),
                    nutrition=item.get("nutrition"),
                    rating=aggregate_rating.get("ratingValue"),
                    rating_count=aggregate_rating.get("ratingCount") or aggregate_rating.get("reviewCount"),
                )
                if candidate:
                    candidates.append(candidate)

        # Conservative anchor fallback. Path patterns are source-specific, which
        # avoids treating navigation/category links as recipe cards.
        for anchor in parser.anchors:
            title = anchor.text or anchor.image_alt or ""
            candidate = self._result(
                title,
                anchor.href,
                search_url,
                image=anchor.image_url,
                rating=anchor.rating_value,
                rating_count=anchor.rating_count,
            )
            if candidate:
                candidates.append(candidate)

        deduplicated: dict[str, SearchResult] = {}
        for candidate in candidates:
            existing = deduplicated.get(candidate.url)
            if existing is None:
                deduplicated[candidate.url] = candidate
            else:
                deduplicated[candidate.url] = replace(
                    existing,
                    image_url=existing.image_url or candidate.image_url,
                    publisher_nutrition=existing.publisher_nutrition or candidate.publisher_nutrition,
                    star_rating=existing.star_rating or candidate.star_rating,
                    rating_count=(
                        existing.rating_count
                        if existing.rating_count is not None
                        else candidate.rating_count
                    ),
                )
        return tuple(deduplicated.values())

    def _result(
        self,
        title: object,
        url: str,
        base_url: str,
        *,
        image: object = None,
        nutrition: object = None,
        rating: object = None,
        rating_count: object = None,
    ) -> SearchResult | None:
        cleaned_title = unescape(" ".join(str(title).split()))
        if not cleaned_title:
            return None
        try:
            canonical = canonicalize_url(url, base_url=base_url)
        except Exception:
            return None
        parts = urlsplit(canonical)
        if (parts.hostname or "").lower() not in self.hosts or not self.is_recipe_path(parts.path):
            return None
        image_url = self._image(image)
        if image_url:
            try:
                image_url = canonicalize_url(image_url, base_url=base_url)
            except Exception:
                image_url = None
        return SearchResult(
            source=self.key,
            title=cleaned_title,
            url=canonical,
            image_url=image_url,
            publisher_nutrition=parse_publisher_nutrition(nutrition),
            star_rating=self._rating(rating),
            rating_count=self._rating_count(rating_count),
        )

    @staticmethod
    def _rating(value: object) -> Decimal | None:
        try:
            rating = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            return None
        return rating if Decimal("0") <= rating <= Decimal("5") else None

    @staticmethod
    def _rating_count(value: object) -> int | None:
        if value is None:
            return None
        match = re.search(r"\d[\d,\s]*", str(value))
        if not match:
            return None
        try:
            return int(re.sub(r"[^\d]", "", match.group()))
        except ValueError:
            return None

    @staticmethod
    def _image(value: object) -> str | None:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            candidates = [SourceAdapter._image(item) for item in value]
            candidates = [item for item in candidates if item]
            return candidates[-1] if candidates else None
        if isinstance(value, dict):
            result = value.get("url") or value.get("contentUrl")
            return result if isinstance(result, str) else None
        return None

    @classmethod
    def _walk(cls, value: object):
        if isinstance(value, list):
            for item in value:
                yield from cls._walk(item)
        elif isinstance(value, dict):
            yield value
            for child in value.values():
                if isinstance(child, (dict, list)):
                    yield from cls._walk(child)

    @abstractmethod
    def limitation(self) -> str:
        """Human-readable maintenance/access limitation for diagnostics."""
