import asyncio

from app.discovery.models import SearchResult
from app.discovery.search import LiveSearchService, SearchPolicy


class FakeFetcher:
    def __init__(self):
        self.calls = []

    async def fetch_text(self, url, *, allowed_hosts):
        self.calls.append(url)
        title = "Stew" if "stew" in url else "Soup"
        if "bbcgoodfood" in url:
            recipe_url = f"https://www.bbcgoodfood.com/recipes/{title.lower()}"
        elif "greatbritishchefs" in url:
            recipe_url = f"https://www.greatbritishchefs.com/recipes/{title.lower()}-recipe"
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
        assert len(first.results) == 3
        assert sum(result.already_saved for result in first.results) == 1
        assert second.cache_hit is True
        assert len(fetcher.calls) == 3

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
        assert len(fetcher.calls) == 3

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
