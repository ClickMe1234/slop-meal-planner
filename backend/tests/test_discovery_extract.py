from decimal import Decimal
from pathlib import Path

from app.discovery.adapters import AllrecipesAdapter, GoodFoodAdapter, GreatBritishChefsAdapter
from app.discovery.extraction import extract_recipe

FIXTURES = Path(__file__).parent / "fixtures" / "discovery"


def test_json_ld_recipe_extracts_present_fields_but_requires_review():
    result = extract_recipe(
        (FIXTURES / "recipe_jsonld.html").read_text(encoding="utf-8"),
        "https://recipes.example.org/stew?utm_campaign=test",
    )
    assert result.title == "Tomato & bean stew"
    assert result.canonical_url == "https://recipes.example.org/stew"
    assert result.yield_servings == Decimal("4")
    assert result.ingredient_lines[0] == "2 x 400g tins tomatoes"
    assert result.publisher_nutrition.energy_kcal == Decimal("412")
    assert result.publisher_nutrition.protein_g == Decimal("18")
    assert result.extraction_method == "json_ld"
    assert result.review_required is True
    assert any("food matches" in reason for reason in result.review_reasons)


def test_serving_range_prefills_midpoint_and_flags_confirmation():
    html = '''<script type="application/ld+json">{
      "@type": "Recipe", "name": "Traybake", "recipeYield": "Serves 4-6",
      "recipeIngredient": ["1 onion"]
    }</script>'''
    result = extract_recipe(html, "https://recipes.example/traybake")
    assert result.yield_servings == Decimal("5")
    assert any("midpoint" in reason for reason in result.review_reasons)


def test_semantic_fallback_is_explicit_and_incomplete():
    result = extract_recipe(
        (FIXTURES / "recipe_semantic.html").read_text(encoding="utf-8"),
        "https://fallback.example/recipes/soup",
    )
    assert result.title == "Simple soup"
    assert result.ingredient_lines == ("200 g carrots", "500 ml stock")
    assert result.image_url == "https://fallback.example/images/soup.jpg"
    assert result.yield_servings is None
    assert result.extraction_method == "semantic_html_fallback"
    assert any("Schema.org" in reason for reason in result.review_reasons)


def test_supported_adapter_urls_and_good_food_result_parsing():
    good_food = GoodFoodAdapter()
    assert good_food.search_url("lentil soup") == "https://www.bbcgoodfood.com/search?q=lentil+soup"
    results = good_food.parse_search_results(
        (FIXTURES / "good_food_search.html").read_text(encoding="utf-8"),
        search_url=good_food.search_url("lentil soup"),
    )
    assert [result.title for result in results] == ["Red lentil soup", "Another soup"]
    assert results[0].url == "https://www.bbcgoodfood.com/recipes/red-lentil-soup"
    assert results[0].publisher_nutrition.energy_kcal == Decimal("280")
    assert results[1].image_url == "https://www.bbcgoodfood.com/images/another.jpg"

    assert GreatBritishChefsAdapter().supports_url("https://www.greatbritishchefs.com/recipes/stew-recipe")
    assert AllrecipesAdapter().supports_url("https://www.allrecipes.com/recipe/123/stew/")
