from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
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
        for raw in parser.json_ld:
            try:
                document = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for node in self._walk(document):
                item = node.get("item") if isinstance(node.get("item"), dict) else node
                types = item.get("@type", "")
                type_values = {str(types).lower()} if isinstance(types, str) else {str(x).lower() for x in types}
                url = item.get("url") or (item.get("@id") if "recipe" in type_values else None)
                title = item.get("name")
                if not isinstance(url, str) or not isinstance(title, str):
                    continue
                candidate = self._result(title, url, search_url, image=item.get("image"), nutrition=item.get("nutrition"))
                if candidate:
                    candidates.append(candidate)

        # Conservative anchor fallback. Path patterns are source-specific, which
        # avoids treating navigation/category links as recipe cards.
        for anchor in parser.anchors:
            title = anchor.text or anchor.image_alt or ""
            candidate = self._result(title, anchor.href, search_url, image=anchor.image_url)
            if candidate:
                candidates.append(candidate)

        deduplicated: dict[str, SearchResult] = {}
        for candidate in candidates:
            existing = deduplicated.get(candidate.url)
            if existing is None or (not existing.image_url and candidate.image_url):
                deduplicated[candidate.url] = candidate
        return tuple(deduplicated.values())

    def _result(
        self,
        title: object,
        url: str,
        base_url: str,
        *,
        image: object = None,
        nutrition: object = None,
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
        )

    @staticmethod
    def _image(value: object) -> str | None:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return next((x for x in value if isinstance(x, str)), None)
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
            for key in ("@graph", "itemListElement"):
                if key in value:
                    yield from cls._walk(value[key])

    @abstractmethod
    def limitation(self) -> str:
        """Human-readable maintenance/access limitation for diagnostics."""
