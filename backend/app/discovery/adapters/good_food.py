import re

from .base import SourceAdapter


class GoodFoodAdapter(SourceAdapter):
    key = "good_food"
    display_name = "Good Food"
    hosts = frozenset({"www.bbcgoodfood.com", "bbcgoodfood.com", "www.goodfood.com", "goodfood.com"})
    search_url_template = "https://www.bbcgoodfood.com/search?q={query}"
    recipe_path_pattern = re.compile(r"/(?:recipes|recipe)/[^/]+/?$", re.IGNORECASE)

    def limitation(self) -> str:
        return "Search depends on Good Food's public HTML/JSON-LD and may need adapter maintenance after site changes."
