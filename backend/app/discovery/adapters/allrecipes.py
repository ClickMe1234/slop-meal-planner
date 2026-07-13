import re

from .base import SourceAdapter


class AllrecipesAdapter(SourceAdapter):
    key = "allrecipes"
    display_name = "Allrecipes"
    hosts = frozenset({"www.allrecipes.com", "allrecipes.com"})
    search_url_template = "https://www.allrecipes.com/search?q={query}"
    recipe_path_pattern = re.compile(r"/(?:recipe/\d+/[^/]+|[^/]+-recipe-\d+)/?$", re.IGNORECASE)

    def limitation(self) -> str:
        return "Only server-returned public markup is supported; client-only or blocked results produce an explicit empty/error response."
