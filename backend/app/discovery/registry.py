from __future__ import annotations

from collections.abc import Iterable

from .adapters import AllrecipesAdapter, GoodFoodAdapter, SourceAdapter
from .errors import UnsupportedSourceError


class SourceRegistry:
    def __init__(self, adapters: Iterable[SourceAdapter]) -> None:
        self._adapters = {adapter.key: adapter for adapter in adapters}
        if len(self._adapters) == 0:
            raise ValueError("At least one source adapter is required")

    @property
    def adapters(self) -> tuple[SourceAdapter, ...]:
        return tuple(self._adapters.values())

    def get(self, key: str) -> SourceAdapter:
        try:
            return self._adapters[key]
        except KeyError as exc:
            raise UnsupportedSourceError(f"Unsupported recipe source: {key}") from exc

    def for_url(self, url: str) -> SourceAdapter:
        adapter = next((item for item in self._adapters.values() if item.supports_url(url)), None)
        if adapter is None:
            raise UnsupportedSourceError("This recipe website has no dedicated adapter")
        return adapter


default_registry = SourceRegistry((GoodFoodAdapter(), AllrecipesAdapter()))
