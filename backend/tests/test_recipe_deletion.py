from sqlalchemy import select

from app.models import Recipe


def _headers(owner):
    return {"X-CSRF-Token": owner["csrf_token"]}


def _create_recipe(client, owner, title="Recipe to delete"):
    response = client.post(
        "/api/v1/recipes",
        headers=_headers(owner),
        json={
            "title": title,
            "source_type": "custom",
            "yield_servings": 2,
            "meal_types": ["dinner"],
            "ingredients": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_delete_recipe_archives_it_and_removes_it_from_the_collection(
    client, owner, session_factory
):
    recipe = _create_recipe(client, owner)

    response = client.delete(
        f"/api/v1/recipes/{recipe['id']}", headers=_headers(owner)
    )

    assert response.status_code == 204, response.text
    assert client.get("/api/v1/recipes?page_size=100").json()["items"] == []
    assert client.get(f"/api/v1/recipes/{recipe['id']}").status_code == 404
    with session_factory() as db:
        archived = db.scalar(select(Recipe).where(Recipe.id == recipe["id"]))
        assert archived is not None
        assert archived.archived_at is not None
        assert archived.eligibility == "archived"
        assert archived.version == recipe["version"] + 1


def test_delete_recipe_requires_csrf_and_hides_missing_or_archived_recipes(client, owner):
    recipe = _create_recipe(client, owner)

    assert client.delete(f"/api/v1/recipes/{recipe['id']}").status_code == 403
    assert client.delete(
        f"/api/v1/recipes/{recipe['id']}", headers=_headers(owner)
    ).status_code == 204
    assert client.delete(
        f"/api/v1/recipes/{recipe['id']}", headers=_headers(owner)
    ).status_code == 404
    assert client.delete(
        "/api/v1/recipes/not-a-recipe", headers=_headers(owner)
    ).status_code == 404
