import re

from .base import SourceAdapter


class AllrecipesAdapter(SourceAdapter):
    key = "allrecipes"
    display_name = "Allrecipes"
    hosts = frozenset({"www.allrecipes.com", "allrecipes.com"})
    search_url_template = "https://www.allrecipes.com/search?q={query}"
    recipe_path_pattern = re.compile(r"/(?:recipe/\d+/[^/]+|[^/]+-recipe-\d+)/?$", re.IGNORECASE)

    def _result(self, title, url, base_url, *, image=None, nutrition=None):
        # Search cards include the rating count in the anchor text. It is not
        # part of the recipe title and made otherwise valid results look noisy.
        cleaned_title = re.sub(r"\s+\d[\d,]*\s+Ratings?\s*$", "", str(title), flags=re.IGNORECASE)
        return super()._result(
            cleaned_title,
            url,
            base_url,
            image=image,
            nutrition=nutrition,
        )

    def limitation(self) -> str:
        return "Only server-returned public markup is supported; client-only or blocked results produce an explicit empty/error response."
