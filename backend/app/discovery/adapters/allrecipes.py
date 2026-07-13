import re

from .base import SourceAdapter


class AllrecipesAdapter(SourceAdapter):
    key = "allrecipes"
    display_name = "Allrecipes"
    hosts = frozenset({"www.allrecipes.com", "allrecipes.com"})
    search_url_template = "https://www.allrecipes.com/search?q={query}"
    recipe_path_pattern = re.compile(r"/(?:recipe/\d+/[^/]+|[^/]+-recipe-\d+)/?$", re.IGNORECASE)

    def _result(
        self,
        title,
        url,
        base_url,
        *,
        image=None,
        nutrition=None,
        rating=None,
        rating_count=None,
    ):
        # Search cards include the rating count in the anchor text. It is not
        # part of the recipe title and made otherwise valid results look noisy.
        raw_title = str(title)
        rating_suffix = re.search(
            r"\s+(?P<rating>[0-5](?:\.\d+)?)\s*(?:out of 5\s*)?(?:\(\s*)?(?P<count>\d[\d,]*)\s+(?:Ratings?|Reviews?)\s*\)?\s*$",
            raw_title,
            flags=re.IGNORECASE,
        )
        if rating_suffix:
            rating = rating or rating_suffix.group("rating")
            rating_count = rating_count or rating_suffix.group("count")
            raw_title = raw_title[:rating_suffix.start()]
        parenthesised_rating_suffix = re.search(
            r"\s+(?P<rating>[0-5](?:\.\d+)?)\s*\(\s*(?P<count>\d[\d,]*)\s*\)\s*$",
            raw_title,
        )
        if parenthesised_rating_suffix:
            rating = rating or parenthesised_rating_suffix.group("rating")
            rating_count = rating_count or parenthesised_rating_suffix.group("count")
            raw_title = raw_title[:parenthesised_rating_suffix.start()]
        count_suffix = re.search(r"\s+(?P<count>\d[\d,]*)\s+Ratings?\s*$", raw_title, flags=re.IGNORECASE)
        if count_suffix:
            rating_count = rating_count or count_suffix.group("count")
            raw_title = raw_title[:count_suffix.start()]
        cleaned_title = raw_title
        return super()._result(
            cleaned_title,
            url,
            base_url,
            image=image,
            nutrition=nutrition,
            rating=rating,
            rating_count=rating_count,
        )

    def limitation(self) -> str:
        return "Only server-returned public markup is supported; client-only or blocked results produce an explicit empty/error response."
