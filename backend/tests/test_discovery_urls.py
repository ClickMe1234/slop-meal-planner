import asyncio

import httpx
import pytest

from app.discovery.errors import FetchError, InvalidUrlError, UnsafeUrlError
from app.discovery.extraction import extract_recipe
from app.discovery.http import MAX_PUBLISHER_HTML_BYTES, PoliteHttpFetcher, _PinnedHTTPSConnection
from app.discovery.urls import canonicalize_url, validate_fetch_url


def test_canonical_url_is_stable_and_removes_tracking():
    assert canonicalize_url(
        "HTTPS://Example.COM:443/recipes/a%20dish?z=2&utm_source=x&a=1#method"
    ) == "https://example.com/recipes/a%20dish?a=1&z=2"


def test_canonical_url_removes_punctuation_accidentally_pasted_after_recipe_url():
    assert canonicalize_url(
        "https://www.allrecipes.com/cheesy-baked-broccoli-bites-recipe-11951704,"
    ) == "https://www.allrecipes.com/cheesy-baked-broccoli-bites-recipe-11951704"


def test_pinned_https_connection_uses_standard_python_tls_extensions(monkeypatch):
    class FakeContext:
        post_handshake_auth = False

        def __init__(self):
            self.alpn_protocols = []

        def set_alpn_protocols(self, protocols):
            self.alpn_protocols = protocols

    context = FakeContext()
    monkeypatch.setattr("app.discovery.http.ssl.create_default_context", lambda: context)

    connection = _PinnedHTTPSConnection(
        "www.allrecipes.com", "93.184.216.34", 443, 10
    )

    assert connection._context is context
    assert context.alpn_protocols == ["http/1.1"]
    assert context.post_handshake_auth is True


def test_canonical_url_resolves_relative_and_rejects_credentials():
    assert canonicalize_url("../recipe/stew", base_url="https://example.org/search/pages/") == (
        "https://example.org/search/recipe/stew"
    )
    with pytest.raises(InvalidUrlError):
        canonicalize_url("https://user:secret@example.org/recipe")


def test_fetch_validation_blocks_private_or_mixed_dns_results():
    with pytest.raises(UnsafeUrlError):
        validate_fetch_url("http://127.0.0.1/recipe")
    with pytest.raises(UnsafeUrlError):
        validate_fetch_url("https://recipes.example/one", resolver=lambda _: ["93.184.216.34", "10.0.0.2"])
    assert validate_fetch_url(
        "https://recipes.example/one",
        resolver=lambda _: ["93.184.216.34"],
        allowed_hosts={"recipes.example"},
    ) == "https://recipes.example/one"


def test_fetcher_pins_the_address_returned_by_the_validating_lookup(monkeypatch):
    lookups = iter((["93.184.216.34"], ["127.0.0.1"]))
    fetcher = PoliteHttpFetcher(
        min_host_interval_seconds=0,
        resolver=lambda _: next(lookups),
    )
    connected: list[str] = []

    def fake_fetch(url, host, address):
        connected.append(address)
        return 200, {"content-type": "text/html"}, b"<html></html>", "utf-8"

    monkeypatch.setattr(fetcher, "_fetch_pinned", fake_fetch)
    assert asyncio.run(
        fetcher.fetch_text(
            "https://recipes.example/one",
            allowed_hosts={"recipes.example"},
        )
    ) == "<html></html>"
    assert connected == ["93.184.216.34"]


def test_fetcher_accepts_bounded_allrecipes_sized_recipe_pages():
    json_ld = '''<script type="application/ld+json">{
      "@type": "Recipe",
      "name": "Large onion recipe",
      "recipeYield": "4 servings",
      "recipeIngredient": ["2 red onions"],
      "recipeInstructions": [{"@type": "HowToStep", "text": "Fry the onions."}]
    }</script>'''
    page = f"<html><head>{json_ld}</head><body><!--{'x' * 2_100_000}--></body></html>"

    async def fetch_and_extract():
        async def respond(_request):
            return httpx.Response(200, headers={"content-type": "text/html"}, text=page)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            fetcher = PoliteHttpFetcher(
                min_host_interval_seconds=0,
                client=client,
                resolver=lambda _: ["93.184.216.34"],
            )
            assert fetcher.max_response_bytes == MAX_PUBLISHER_HTML_BYTES
            html = await fetcher.fetch_text(
                "https://www.allrecipes.com/recipe/123/large-onion-recipe/",
                allowed_hosts={"www.allrecipes.com", "allrecipes.com"},
            )
        return extract_recipe(
            html,
            "https://www.allrecipes.com/recipe/123/large-onion-recipe/",
        )

    result = asyncio.run(fetch_and_extract())

    assert [block.text for block in result.instruction_blocks] == ["Fry the onions."]


def test_image_fetcher_rejects_non_image_content(monkeypatch):
    fetcher = PoliteHttpFetcher(
        min_host_interval_seconds=0,
        resolver=lambda _: ["93.184.216.34"],
    )

    def fake_fetch(url, host, address, *, accept=None):
        assert accept and "image/webp" in accept
        return 200, {"content-type": "text/html"}, b"<script>unsafe</script>", "utf-8"

    monkeypatch.setattr(fetcher, "_fetch_pinned", fake_fetch)
    with pytest.raises(FetchError, match="not a supported image"):
        asyncio.run(
            fetcher.fetch_bytes(
                "https://images.example/one",
                allowed_content_types={"image/png"},
            )
        )
