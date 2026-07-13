import re

from .base import SourceAdapter


class GreatBritishChefsAdapter(SourceAdapter):
    key = "great_british_chefs"
    display_name = "Great British Chefs"
    hosts = frozenset({"www.greatbritishchefs.com", "greatbritishchefs.com"})
    search_url_template = "https://www.greatbritishchefs.com/search2?search={query}"
    recipe_path_pattern = re.compile(r"/recipes/[^/]+(?:-recipe)?/?$", re.IGNORECASE)

    def limitation(self) -> str:
        return "Only results present in the public search response are parsed; no login, challenge, or bot-control bypass is attempted."
