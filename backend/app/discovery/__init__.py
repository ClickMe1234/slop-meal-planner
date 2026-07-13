"""Recipe discovery and structured import primitives.

The package deliberately contains no browser automation or access-control bypasses.
Adapters only describe ordinary public search pages and parse returned HTML.
"""

from .extraction import extract_recipe
from .registry import SourceRegistry, default_registry
from .search import LiveSearchService, SearchPolicy
from .urls import canonicalize_url, validate_fetch_url

__all__ = [
    "LiveSearchService",
    "SearchPolicy",
    "SourceRegistry",
    "canonicalize_url",
    "default_registry",
    "extract_recipe",
    "validate_fetch_url",
]
