from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PublisherNutritionPreview:
    """Publisher-reported values shown as an estimate, never as calculated truth."""

    basis: str | None = None
    energy_kcal: Decimal | None = None
    protein_g: Decimal | None = None
    carbohydrate_g: Decimal | None = None
    fat_g: Decimal | None = None
    fibre_g: Decimal | None = None
    raw: dict[str, object] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return any(
            value is not None
            for value in (self.energy_kcal, self.protein_g, self.carbohydrate_g, self.fat_g)
        )


@dataclass(frozen=True, slots=True)
class SearchResult:
    source: str
    title: str
    url: str
    image_url: str | None = None
    publisher_nutrition: PublisherNutritionPreview | None = None
    already_saved: bool = False


@dataclass(frozen=True, slots=True)
class ExtractedRecipe:
    title: str
    canonical_url: str
    publisher: str | None
    image_url: str | None
    yield_servings: Decimal | None
    ingredient_lines: tuple[str, ...]
    publisher_nutrition: PublisherNutritionPreview | None
    extraction_method: str
    review_required: bool
    review_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceSearchResponse:
    source: str
    results: tuple[SearchResult, ...] = ()
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class CombinedSearchResponse:
    query: str
    sources: tuple[SourceSearchResponse, ...]
    debounce_ms: int
    cache_hit: bool = False
    superseded: bool = False

    @property
    def results(self) -> tuple[SearchResult, ...]:
        return tuple(result for source in self.sources for result in source.results)
