from sqlalchemy import select

from app.discovery.categories import (
    CATEGORY_BY_KEY,
    MAX_SELECTED_CATEGORIES,
    RECIPE_CATEGORIES,
    categories_for_normalised_tags,
)
from app.models import Recipe, RecipePublisherTag


def _headers(owner):
    return {"X-CSRF-Token": owner["csrf_token"]}


def _create_recipe(client, owner, title):
    response = client.post(
        "/api/v1/recipes",
        headers=_headers(owner),
        json={
            "title": title,
            "source_type": "url",
            "source_url": f"https://www.bbcgoodfood.com/recipes/{title.casefold().replace(' ', '-')}",
            "ingredients": [],
            "meal_types": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_reviewed_category_registry_is_stable_and_cross_provider():
    assert len(RECIPE_CATEGORIES) == 18
    assert len(CATEGORY_BY_KEY) == len(RECIPE_CATEGORIES)
    assert MAX_SELECTED_CATEGORIES == 3
    assert all(category.good_food.url or category.good_food.query for category in RECIPE_CATEGORIES)
    assert all(category.allrecipes.url or category.allrecipes.query for category in RECIPE_CATEGORIES)
    assert categories_for_normalised_tags({"vegetarian", "italian"}) == ("vegetarian",)


def test_category_catalogue_endpoint_returns_ranked_options(client, owner):
    response = client.get("/api/v1/recipe-discovery/categories")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["maximum_selected"] == 3
    assert data["match"] == "any"
    assert data["items"][0]["key"] == "healthy"
    assert data["items"][-1]["key"] == "high_protein"


def test_saved_recipe_search_uses_raw_publisher_tags_and_category_aliases(
    client, owner, session_factory
):
    healthy = _create_recipe(client, owner, "Tomato bowl")
    other = _create_recipe(client, owner, "Plain toast")
    with session_factory() as db:
        recipe = db.scalar(select(Recipe).where(Recipe.id == healthy["id"]))
        db.add_all([
            RecipePublisherTag(
                recipe_id=recipe.id,
                kind="category",
                label="Healthy Recipes",
                normalised_value="healthy recipes",
            ),
            RecipePublisherTag(
                recipe_id=recipe.id,
                kind="cuisine",
                label="Mediterranean",
                normalised_value="mediterranean",
            ),
        ])
        recipe.publisher_metadata_status = "ready"
        db.commit()

    by_category = client.get("/api/v1/recipes?publisher_category=healthy")
    by_raw_tag = client.get("/api/v1/recipes?q=mediterranean")
    narrowed = client.get("/api/v1/recipes?q=toast&publisher_category=healthy")

    assert [item["id"] for item in by_category.json()["items"]] == [healthy["id"]]
    assert [item["id"] for item in by_raw_tag.json()["items"]] == [healthy["id"]]
    item = by_category.json()["items"][0]
    assert item["publisher_categories"] == ["healthy"]
    assert {tag["label"] for tag in item["publisher_tags"]} == {
        "Healthy Recipes", "Mediterranean"
    }
    assert other["id"] not in {item["id"] for item in by_category.json()["items"]}
    assert narrowed.json()["items"] == []


def test_recipe_category_validation_rejects_unknown_or_more_than_three(client, owner):
    unknown = client.get("/api/v1/recipes?publisher_category=made_up")
    too_many = client.get(
        "/api/v1/recipes?publisher_category=healthy&publisher_category=soups"
        "&publisher_category=salads&publisher_category=pasta"
    )

    assert unknown.status_code == 422
    assert unknown.json()["code"] == "UNKNOWN_RECIPE_CATEGORY"
    assert too_many.status_code == 422
    assert too_many.json()["code"] == "TOO_MANY_RECIPE_CATEGORIES"
