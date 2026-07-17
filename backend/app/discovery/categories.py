from __future__ import annotations

import re
from dataclasses import dataclass


MAX_SELECTED_CATEGORIES = 3


def normalise_publisher_tag(value: str) -> str:
    """Return a stable comparison value while retaining the original label separately."""

    words = re.findall(r"[a-z0-9]+", value.casefold().replace("&", " and "))
    return " ".join(words)[:160]


@dataclass(frozen=True, slots=True)
class ProviderCategoryTarget:
    url: str | None = None
    query: str | None = None

    @property
    def mode(self) -> str:
        return "category_page" if self.url else "search_fallback"


@dataclass(frozen=True, slots=True)
class RecipeCategory:
    key: str
    label: str
    aliases: tuple[str, ...]
    good_food: ProviderCategoryTarget
    allrecipes: ProviderCategoryTarget
    confidence: str = "high"

    def target_for(self, source: str) -> ProviderCategoryTarget:
        if source == "good_food":
            return self.good_food
        if source == "allrecipes":
            return self.allrecipes
        raise KeyError(source)

    @property
    def normalised_aliases(self) -> frozenset[str]:
        return frozenset(normalise_publisher_tag(value) for value in (self.label, *self.aliases))


def _page(url: str) -> ProviderCategoryTarget:
    return ProviderCategoryTarget(url=url)


def _query(value: str) -> ProviderCategoryTarget:
    return ProviderCategoryTarget(query=value)


# This reviewed, deliberately small cross-publisher vocabulary is the only place
# product categories are defined. Publisher labels remain untouched in storage;
# aliases merely connect those labels to the stable keys exposed by the API.
RECIPE_CATEGORIES: tuple[RecipeCategory, ...] = (
    RecipeCategory(
        "healthy", "Healthy", ("healthy recipes", "healthy eating"),
        _page("https://www.bbcgoodfood.com/recipes/collection/healthy-recipes"),
        _page("https://www.allrecipes.com/recipes/84/healthy-recipes/"),
    ),
    RecipeCategory(
        "dinner_main", "Dinner / Main dishes", ("dinner", "main dish", "main dishes", "main course", "main courses"),
        _page("https://www.bbcgoodfood.com/recipes/collection/dinner-recipes"),
        _page("https://www.allrecipes.com/recipes/80/main-dish/"),
    ),
    RecipeCategory(
        "quick_easy", "Quick & Easy", ("quick and easy", "easy", "quick", "easy recipes"),
        _page("https://www.bbcgoodfood.com/recipes/collection/quick-and-easy-recipes"),
        _page("https://www.allrecipes.com/recipes/1947/everyday-cooking/quick-and-easy/"),
    ),
    RecipeCategory(
        "breakfast_brunch", "Breakfast & Brunch", ("breakfast and brunch", "breakfast", "brunch"),
        _page("https://www.bbcgoodfood.com/recipes/collection/breakfast-recipes"),
        _page("https://www.allrecipes.com/recipes/78/breakfast-and-brunch/"),
    ),
    RecipeCategory(
        "vegetarian", "Vegetarian", ("vegetarian recipes", "vegetarian diet"),
        _page("https://www.bbcgoodfood.com/recipes/collection/vegetarian-recipes"),
        _page("https://www.allrecipes.com/recipes/87/everyday-cooking/vegetarian/"),
    ),
    RecipeCategory(
        "soups", "Soups", ("soup", "soup recipes"),
        _page("https://www.bbcgoodfood.com/recipes/collection/soup-recipes"),
        _page("https://www.allrecipes.com/recipes/16369/soups-stews-and-chili/soup/"),
    ),
    RecipeCategory(
        "salads", "Salads", ("salad", "salad recipes"),
        _page("https://www.bbcgoodfood.com/recipes/collection/salad-recipes"),
        _page("https://www.allrecipes.com/recipes/96/salad/"),
    ),
    RecipeCategory(
        "desserts", "Desserts", ("dessert", "dessert recipes", "pudding", "puddings"),
        _page("https://www.bbcgoodfood.com/recipes/collection/dessert-recipes"),
        _page("https://www.allrecipes.com/recipes/79/desserts/"),
    ),
    RecipeCategory(
        "snacks_appetizers", "Snacks / Appetizers", ("snack", "snacks", "appetizer", "appetizers", "starter", "starters"),
        _query("snacks starters"),
        _page("https://www.allrecipes.com/recipes/76/appetizers-and-snacks/"),
        confidence="medium",
    ),
    RecipeCategory(
        "pasta", "Pasta", ("pasta recipes", "pasta and noodles", "noodles"),
        _page("https://www.bbcgoodfood.com/recipes/collection/pasta-recipes"),
        _page("https://www.allrecipes.com/recipes/95/pasta-and-noodles/"),
    ),
    RecipeCategory(
        "side_dishes", "Side dishes", ("side dish", "sides"),
        _query("side dish"),
        _page("https://www.allrecipes.com/recipes/81/side-dish/"),
        confidence="medium",
    ),
    RecipeCategory(
        "budget", "Budget", ("budget recipes", "budget cooking", "cheap eats", "cheap recipes"),
        _page("https://www.bbcgoodfood.com/recipes/collection/budget-recipes"),
        _page("https://www.allrecipes.com/recipes/15522/everyday-cooking/budget-cooking/"),
    ),
    RecipeCategory(
        "seafood_fish", "Seafood / Fish", ("seafood", "fish", "fish recipes", "seafood recipes"),
        _page("https://www.bbcgoodfood.com/recipes/collection/fish-recipes"),
        _page("https://www.allrecipes.com/recipes/93/seafood/"),
    ),
    RecipeCategory(
        "lunch", "Lunch", ("lunch recipes", "lunches"),
        _page("https://www.bbcgoodfood.com/recipes/collection/lunch-recipes"),
        _page("https://www.allrecipes.com/recipes/17561/lunch/"),
    ),
    RecipeCategory(
        "stews_chilli", "Stews & Chilli", ("stews and chilli", "stews and chili", "stew", "stews", "chilli", "chili"),
        _query("stew chilli"),
        _page("https://www.allrecipes.com/recipes/94/soups-stews-and-chili/"),
        confidence="medium",
    ),
    RecipeCategory(
        "slow_cooker", "Slow cooker", ("slow-cooker", "slow cooker recipes"),
        _page("https://www.bbcgoodfood.com/recipes/collection/slow-cooker-recipes"),
        _page("https://www.allrecipes.com/recipes/253/everyday-cooking/slow-cooker/"),
    ),
    RecipeCategory(
        "one_pot", "One-pot / One-pan", ("one pot", "one-pot", "one pan", "one-pan", "one pot meals"),
        _page("https://www.bbcgoodfood.com/recipes/collection/one-pot-recipes"),
        _page("https://www.allrecipes.com/recipes/15436/everyday-cooking/one-pot-meals/"),
    ),
    RecipeCategory(
        "high_protein", "High-protein", ("high protein", "high-protein recipes"),
        _page("https://www.bbcgoodfood.com/recipes/collection/high-protein-recipes"),
        _query("high protein"),
        confidence="medium",
    ),
)

CATEGORY_BY_KEY = {category.key: category for category in RECIPE_CATEGORIES}


def categories_for_normalised_tags(values: set[str]) -> tuple[str, ...]:
    return tuple(
        category.key
        for category in RECIPE_CATEGORIES
        if category.normalised_aliases.intersection(values)
    )


def validate_category_keys(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    selected = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
    if len(selected) > MAX_SELECTED_CATEGORIES:
        raise ValueError(f"Choose no more than {MAX_SELECTED_CATEGORIES} recipe categories")
    unknown = tuple(value for value in selected if value not in CATEGORY_BY_KEY)
    if unknown:
        raise KeyError(", ".join(unknown))
    return selected
