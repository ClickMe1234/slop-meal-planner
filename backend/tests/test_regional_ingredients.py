from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models import (
    Household,
    IngredientNameEquivalent,
    MealBatch,
    MealPlan,
    Recipe,
    RecipeIngredient,
    RecipeVersion,
    ShoppingItem,
)
from app.services.regional_ingredients import (
    canonical_ingredient_key,
    convert_ingredient_text,
    equivalent_terms,
)
from app.services.shopping import build_shopping_list


def _add_courgette_pair(db):
    pair = IngredientNameEquivalent(
        us_name="zucchini",
        uk_name="courgette",
        priority=10,
    )
    db.add(pair)
    db.flush()
    db.info.pop("ingredient_name_groups", None)


def test_names_convert_both_ways_and_search_expands(db):
    _add_courgette_pair(db)

    assert convert_ingredient_text(db, "2 large zucchini, sliced", "uk") == "2 large courgette, sliced"
    assert convert_ingredient_text(db, "Courgette ribbons", "us") == "Zucchini ribbons"
    assert set(equivalent_terms(db, "courgette")) == {"courgette", "zucchini"}
    assert canonical_ingredient_key(db, "Zucchini") == canonical_ingredient_key(db, "courgette")


def test_shopping_list_combines_us_and_uk_names(db):
    _add_courgette_pair(db)
    household = Household(name="Home")
    db.add(household)
    db.flush()
    recipe = Recipe(household_id=household.id, title="Two courgettes")
    db.add(recipe)
    db.flush()
    version = RecipeVersion(
        recipe_id=recipe.id,
        version_number=1,
        title=recipe.title,
        yield_servings=1,
    )
    db.add(version)
    db.flush()
    db.add_all(
        [
            RecipeIngredient(
                recipe_version_id=version.id,
                position=0,
                original_text="100 g courgette",
                food_phrase="courgette",
                quantity_grams=100,
            ),
            RecipeIngredient(
                recipe_version_id=version.id,
                position=1,
                original_text="150 g zucchini",
                food_phrase="zucchini",
                quantity_grams=150,
            ),
        ]
    )
    plan = MealPlan(
        household_id=household.id,
        name="Week",
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 20),
    )
    db.add(plan)
    db.flush()
    db.add(
        MealBatch(
            meal_plan_id=plan.id,
            recipe_version_id=version.id,
            servings=1,
            planned_cook_date=plan.start_date,
        )
    )
    db.flush()

    shopping = build_shopping_list(db, household.id, plan.id, "Week shopping")
    items = db.scalars(
        select(ShoppingItem).where(ShoppingItem.shopping_list_id == shopping.id)
    ).all()

    assert len(items) == 1
    assert items[0].display_name == "courgette"
    assert items[0].exact_quantity == Decimal("250")


def test_user_can_save_ingredient_language(client, owner):
    response = client.patch(
        "/api/v1/auth/me",
        headers={"X-CSRF-Token": owner["csrf_token"]},
        json={"ingredient_locale": "us"},
    )

    assert response.status_code == 200
    assert response.json()["ingredient_locale"] == "us"
