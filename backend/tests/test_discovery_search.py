import asyncio
from decimal import Decimal

from app.discovery.models import CombinedSearchResponse, SearchResult, SourceSearchResponse, bayesian_rating_score
from app.discovery.registry import default_registry
from app.discovery.search import LiveSearchService, SearchPolicy


class FakeFetcher:
    def __init__(self):
        self.calls = []

    async def fetch_text(self, url, *, allowed_hosts):
        self.calls.append(url)
        title = "Stew" if "stew" in url else "Soup"
        if "bbcgoodfood" in url:
            recipe_url = f"https://www.bbcgoodfood.com/recipes/{title.lower()}"
        else:
            recipe_url = f"https://www.allrecipes.com/recipe/123/{title.lower()}/"
        return f'<a href="{recipe_url}">{title}</a>'


def test_remote_search_is_cached_and_marks_saved_results():
    async def run():
        fetcher = FakeFetcher()

        async def saved(urls):
            return {next(url for url in urls if "allrecipes" in url)}

        service = LiveSearchService(
            fetcher,
            policy=SearchPolicy(debounce_ms=0, cache_ttl_seconds=30),
            saved_url_lookup=saved,
        )
        first = await service.search_remote(" Soup ")
        second = await service.search_remote("soup")
        assert len(first.results) == 2
        assert sum(result.already_saved for result in first.results) == 1
        assert second.cache_hit is True
        assert len(fetcher.calls) == 2

    asyncio.run(run())


def test_newer_request_supersedes_older_request_key():
    async def run():
        fetcher = FakeFetcher()
        service = LiveSearchService(fetcher, policy=SearchPolicy(debounce_ms=10))
        older = asyncio.create_task(service.search_remote("soup", request_key="browser-tab"))
        await asyncio.sleep(0)
        newer = asyncio.create_task(service.search_remote("stew", request_key="browser-tab"))
        old_result, new_result = await asyncio.gather(older, newer)
        assert old_result.superseded is True
        assert new_result.superseded is False
        assert len(fetcher.calls) == 2

    asyncio.run(run())


def test_irrelevant_category_cards_are_removed_and_exact_matches_rank_first():
    score = LiveSearchService._relevance_score
    exact = SearchResult("good_food", "Thai green chicken curry", "https://example/chicken-curry")
    partial = SearchResult("good_food", "Chicken traybake", "https://example/chicken-traybake")
    category = SearchResult("good_food", "Sourdough & Focaccia recipes", "https://example/sourdough")

    assert score(exact, "chicken curry") > score(partial, "chicken curry") > 0
    assert score(category, "chicken curry") == 0


def test_remote_search_only_calls_selected_publishers():
    async def run():
        fetcher = FakeFetcher()
        service = LiveSearchService(fetcher, policy=SearchPolicy(debounce_ms=0))
        result = await service.search_remote("soup", sources=("good_food", "allrecipes"))
        assert {source.source for source in result.sources} == {"good_food", "allrecipes"}
        assert len(fetcher.calls) == 2
        assert not any("greatbritishchefs" in url for url in fetcher.calls)

    asyncio.run(run())


def test_remote_search_can_use_a_regional_query_for_each_publisher():
    async def run():
        fetcher = FakeFetcher()
        service = LiveSearchService(fetcher, policy=SearchPolicy(debounce_ms=0))
        await service.search_remote(
            "courgette",
            source_queries={"good_food": "courgette", "allrecipes": "zucchini"},
        )

        assert any("bbcgoodfood.com/search?q=courgette" in url for url in fetcher.calls)
        assert any("allrecipes.com/search?q=zucchini" in url for url in fetcher.calls)

    asyncio.run(run())


def test_category_only_search_uses_provider_pages_and_independent_cache():
    async def run():
        fetcher = FakeFetcher()
        service = LiveSearchService(
            fetcher,
            policy=SearchPolicy(debounce_ms=0, cache_ttl_seconds=30),
        )

        first = await service.search_remote("", categories=("soups",))
        second = await service.search_remote("", categories=("soups",))

        assert len(first.results) == 2
        assert all(result.matched_categories == ("soups",) for result in first.results)
        assert all("/search?" not in url for url in fetcher.calls)
        assert second.cache_hit is True
        assert len(fetcher.calls) == 2

    asyncio.run(run())


def test_multiple_categories_are_match_any_and_merge_duplicate_urls():
    async def run():
        fetcher = FakeFetcher()
        service = LiveSearchService(fetcher, policy=SearchPolicy(debounce_ms=0))

        response = await service.search_remote("", categories=("soups", "healthy"))

        assert len(response.results) == 3
        assert any(
            result.matched_categories == ("soups", "healthy")
            for result in response.results
        )
        assert {category for result in response.results for category in result.matched_categories} == {
            "soups", "healthy"
        }
        assert len(fetcher.calls) == 4

    asyncio.run(run())


def test_multiple_categories_can_require_every_category():
    async def run():
        fetcher = FakeFetcher()
        service = LiveSearchService(fetcher, policy=SearchPolicy(debounce_ms=0))

        response = await service.search_remote(
            "", categories=("soups", "healthy"), category_match="all"
        )

        assert response.results
        assert all(
            set(result.matched_categories) == {"soups", "healthy"}
            for result in response.results
        )
        assert len(response.results) < 3

    asyncio.run(run())


def test_default_registry_only_enables_current_publishers():
    assert {adapter.key for adapter in default_registry.adapters} == {"good_food", "allrecipes"}


def test_bayesian_rating_rank_rewards_strong_review_evidence():
    established = SearchResult(
        "good_food",
        "Established curry",
        "https://example/established",
        star_rating=Decimal("4.5"),
        rating_count=500,
    )
    single_vote = SearchResult(
        "allrecipes",
        "New curry",
        "https://example/new",
        star_rating=Decimal("5"),
        rating_count=1,
    )
    response = CombinedSearchResponse(
        "curry",
        (
            SourceSearchResponse("allrecipes", (single_vote,)),
            SourceSearchResponse("good_food", (established,)),
        ),
        0,
    )

    assert bayesian_rating_score(Decimal("4.5"), 500) > bayesian_rating_score(Decimal("5"), 1)
    assert response.results == (established, single_vote)


def test_nutrition_preview_fetches_recipe_page_once_and_caches_it():
    async def run():
        class PreviewFetcher:
            def __init__(self):
                self.calls = []

            async def fetch_text(self, url, *, allowed_hosts):
                self.calls.append((url, allowed_hosts))
                return """
                    <script type="application/ld+json">
                    {
                      "@context": "https://schema.org",
                      "@type": "Recipe",
                      "name": "Preview curry",
                      "recipeYield": "4 servings",
                      "recipeIngredient": ["1 tbsp oil"],
                      "publisher": {"@type": "Organization", "name": "Good Food"},
                      "nutrition": {
                        "calories": "410 kcal",
                        "proteinContent": "31 g",
                        "carbohydrateContent": "28 g",
                        "fatContent": "19 g"
                      }
                    }
                    </script>
                """

        fetcher = PreviewFetcher()
        service = LiveSearchService(
            fetcher,
            policy=SearchPolicy(debounce_ms=0, preview_cache_ttl_seconds=30),
        )
        url = "https://www.bbcgoodfood.com/recipes/preview-curry"
        first = await service.nutrition_preview(url)
        second = await service.nutrition_preview(url)

        assert first.publisher_nutrition is not None
        assert first.publisher_nutrition.energy_kcal == 410
        assert first.publisher_nutrition.protein_g == 31
        assert second is first
        assert len(fetcher.calls) == 1

    asyncio.run(run())
