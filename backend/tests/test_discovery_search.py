import asyncio

from app.discovery.models import SearchResult
from app.discovery.search import LiveSearchService, SearchPolicy


class FakeFetcher:
    def __init__(self):
        self.calls = []

    async def fetch_text(self, url, *, allowed_hosts):
        self.calls.append(url)
        if "bbcgoodfood" in url:
            recipe_url = "https://www.bbcgoodfood.com/recipes/soup"
        elif "greatbritishchefs" in url:
            recipe_url = "https://www.greatbritishchefs.com/recipes/soup-recipe"
        else:
            recipe_url = "https://www.allrecipes.com/recipe/123/soup/"
        return f'<a href="{recipe_url}">Soup</a>'


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
