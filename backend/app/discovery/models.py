from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


RATING_PRIOR_MEAN = Decimal("3.5")
RATING_PRIOR_COUNT = 25


def bayesian_rating_score(star_rating: Decimal, rating_count: int) -> Decimal:
    """Shrink small-sample ratings toward a neutral catalogue prior.

    This is the Bayesian weighted-average formula commonly used for ranked
    reviews. Twenty-five prior ratings prevent a single perfect vote from
    outranking a very well-established recipe while becoming negligible for
    recipes with hundreds of ratings.
    """

    count = max(0, rating_count)
    return (
        star_rating * count + RATING_PRIOR_MEAN * RATING_PRIOR_COUNT
    ) / (count + RATING_PRIOR_COUNT)


@dataclass(frozen=True, slots=True)
class PublisherNutritionPreview:
    """Publisher-reported values retained separately from ingredient calculations."""

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
    star_rating: Decimal | None = None
    rating_count: int | None = None
    matched_categories: tuple[str, ...] = ()

    @property
    def rating_rank(self) -> Decimal | None:
        if self.star_rating is None or self.rating_count is None or self.rating_count <= 0:
            return None
        return bayesian_rating_score(self.star_rating, self.rating_count)


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
    publisher_tags: tuple[PublisherTag, ...] = ()


@dataclass(frozen=True, slots=True)
class PublisherTag:
    kind: str
    label: str
    normalised_value: str


@dataclass(frozen=True, slots=True)
class SourceSearchResponse:
    source: str
    results: tuple[SearchResult, ...] = ()
    error_code: str | None = None
    error_message: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CombinedSearchResponse:
    query: str
    sources: tuple[SourceSearchResponse, ...]
    debounce_ms: int
    cache_hit: bool = False
    superseded: bool = False

    @property
    def results(self) -> tuple[SearchResult, ...]:
        results = tuple(result for source in self.sources for result in source.results)
        return tuple(sorted(
            results,
            key=lambda result: (
                result.rating_rank is None,
                -(result.rating_rank or Decimal("0")),
                -(result.rating_count or 0),
                result.title.casefold(),
            ),
        ))
