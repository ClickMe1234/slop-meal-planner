from decimal import Decimal
from pathlib import Path

from app.discovery.adapters import AllrecipesAdapter, GoodFoodAdapter
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
    assert any("amounts and units" in reason for reason in result.review_reasons)


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
    assert results[0].star_rating == Decimal("4.6")
    assert results[0].rating_count == 842
    assert results[1].image_url == "https://www.bbcgoodfood.com/images/another.jpg"

    assert AllrecipesAdapter().supports_url("https://www.allrecipes.com/recipe/123/stew/")


def test_search_result_uses_valid_img_instead_of_srcset_source():
    html = '''<a href="/recipes/soup"><picture>
      <source srcset="/images/soup-480.jpg 480w, /images/soup-1280.jpg 1280w">
      <img src="/images/soup-placeholder.jpg" alt="Soup">
    </picture></a>'''
    result = GoodFoodAdapter().parse_search_results(
        html,
        search_url="https://www.bbcgoodfood.com/search?q=soup",
    )[0]
    assert result.image_url == "https://www.bbcgoodfood.com/images/soup-placeholder.jpg"


def test_search_result_image_keeps_commas_inside_resize_query():
    html = '''<a href="/recipes/soup"><picture>
      <source srcset="https://images.immediate.co.uk/soup.jpg?resize=93,84 93w, https://images.immediate.co.uk/soup.jpg?resize=372,338 372w">
      <img src="https://images.immediate.co.uk/soup.jpg?resize=93,84" alt="Soup">
    </picture></a>'''
    result = GoodFoodAdapter().parse_search_results(
        html,
        search_url="https://www.bbcgoodfood.com/search?q=soup",
    )[0]
    assert result.image_url == "https://images.immediate.co.uk/soup.jpg?resize=93%2C84"
    assert not result.image_url.endswith("/338")


def test_allrecipes_search_card_removes_rating_count_from_title():
    html = '''<a href="/recipe/123/chicken-soup/">
      <img data-src="https://www.allrecipes.com/thmb/chicken.jpg" alt="Chicken Soup">
      Chicken Soup 1,234 Ratings
    </a>'''
    result = AllrecipesAdapter().parse_search_results(
        html,
        search_url="https://www.allrecipes.com/search?q=chicken",
    )[0]
    assert result.title == "Chicken Soup"
    assert result.image_url == "https://www.allrecipes.com/thmb/chicken.jpg"
    assert result.rating_count == 1234


def test_allrecipes_search_card_extracts_rating_and_count_from_text():
    html = '''<a href="/recipe/123/chicken-soup/">
      <img src="https://www.allrecipes.com/thmb/chicken.jpg" alt="Chicken Soup">
      Chicken Soup 4.9 27 Ratings
    </a>'''
    result = AllrecipesAdapter().parse_search_results(
        html,
        search_url="https://www.allrecipes.com/search?q=chicken",
    )[0]
    assert result.title == "Chicken Soup"
    assert result.star_rating == Decimal("4.9")
    assert result.rating_count == 27


def test_allrecipes_search_card_extracts_compact_rating_text():
    result = AllrecipesAdapter().parse_search_results(
        '<a href="/recipe/123/chicken-soup/">Chicken Soup 4.8 (1,204)</a>',
        search_url="https://www.allrecipes.com/search?q=chicken",
    )[0]
    assert result.title == "Chicken Soup"
    assert result.star_rating == Decimal("4.8")
    assert result.rating_count == 1204
