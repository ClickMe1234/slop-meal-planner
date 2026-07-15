from datetime import date
from decimal import Decimal

from app.models import (
    Household,
    MealBatch,
    MealPlan,
    Recipe,
    RecipeIngredient,
    RecipeVersion,
    ShoppingList,
)
from app.services.ingredient_names import (
    ingredient_name_keys,
    preferred_ingredient_name,
    remember_ingredient_name,
)
from app.services.ingredient_reparse import reparse_stale_imported_ingredients
from app.services.ingredients import PARSER_VERSION


def test_household_name_override_applies_to_singular_and_plural_names(db):
    household = Household(name="Home")
    db.add(household)
    db.flush()

    singular_keys = ingredient_name_keys(db, "courgette")
    plural_keys = ingredient_name_keys(db, "courgettes")
    assert set(singular_keys).intersection(plural_keys) == {"stem:courgett"}

    remember_ingredient_name(db, household.id, singular_keys, "green courgette")
    db.flush()

    display_name, overridden = preferred_ingredient_name(
        db,
        household.id,
        plural_keys,
        "courgettes",
    )
    assert display_name == "green courgette"
    assert overridden is True


def test_reparse_updates_url_imports_and_prompts_to_rebuild_active_lists(db):
    household = Household(name="Home")
    db.add(household)
    db.flush()
    recipe = Recipe(
        household_id=household.id,
        title="Courgette traybake",
        source_type="url",
        source_url="https://example.com/courgette",
    )
    db.add(recipe)
    db.flush()
    version = RecipeVersion(
        recipe_id=recipe.id,
        version_number=1,
        title=recipe.title,
        yield_servings=Decimal("2"),
    )
    db.add(version)
    db.flush()
    ingredient = RecipeIngredient(
        recipe_version_id=version.id,
        position=0,
        original_text="cubed courgette",
        food_phrase="cubed courgette",
    )
    db.add(ingredient)
    plan = MealPlan(
        household_id=household.id,
        name="Week",
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 26),
    )
    db.add(plan)
    db.flush()
    db.add(
        MealBatch(
            meal_plan_id=plan.id,
            recipe_version_id=version.id,
            servings=Decimal("2"),
            planned_cook_date=date(2026, 7, 20),
        )
    )
    shopping_list = ShoppingList(
        household_id=household.id,
        meal_plan_id=plan.id,
        name="Current shopping list",
        active=True,
    )
    db.add(shopping_list)
    db.flush()

    result = reparse_stale_imported_ingredients(db)

    assert result.scanned == 1
    assert result.changed == 1
    assert result.flagged == 0
    assert result.lists_marked == 1
    assert ingredient.food_phrase == "courgette"
    assert ingredient.parsed_food_phrase == "courgette"
    assert ingredient.parser_version == PARSER_VERSION
    assert "stem:courgett" in ingredient.parser_name_keys
    assert shopping_list.rebuild_recommended is True
    assert shopping_list.version == 2

    repeated = reparse_stale_imported_ingredients(db)
    assert repeated.scanned == 0
    assert repeated.changed == 0
    assert repeated.lists_marked == 0


def test_reparse_preserves_a_user_overridden_name(db):
    household = Household(name="Home")
    db.add(household)
    db.flush()
    recipe = Recipe(
        household_id=household.id,
        title="Family recipe",
        source_type="url",
        source_url="https://example.com/family",
    )
    db.add(recipe)
    db.flush()
    version = RecipeVersion(
        recipe_id=recipe.id,
        version_number=1,
        title=recipe.title,
        yield_servings=Decimal("2"),
    )
    db.add(version)
    db.flush()
    ingredient = RecipeIngredient(
        recipe_version_id=version.id,
        position=0,
        original_text="cubed courgette",
        food_phrase="our garden squash",
        name_overridden=True,
    )
    db.add(ingredient)
    db.flush()

    result = reparse_stale_imported_ingredients(db)

    assert result.scanned == 1
    assert ingredient.food_phrase == "our garden squash"
    assert ingredient.parsed_food_phrase == "courgette"
    assert ingredient.name_overridden is True
