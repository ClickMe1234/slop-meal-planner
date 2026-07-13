import pytest

from app.discovery.errors import InvalidUrlError, UnsafeUrlError
from app.discovery.urls import canonicalize_url, validate_fetch_url


def test_canonical_url_is_stable_and_removes_tracking():
    assert canonicalize_url(
        "HTTPS://Example.COM:443/recipes/a%20dish?z=2&utm_source=x&a=1#method"
    ) == "https://example.com/recipes/a%20dish?a=1&z=2"


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
