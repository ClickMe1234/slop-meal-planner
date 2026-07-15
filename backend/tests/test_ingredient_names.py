from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.models import (
    Household,
    IngredientNameOverride,
    MealBatch,
    MealPlan,
    Recipe,
    RecipeIngredient,
    RecipeVersion,
    ShoppingItem,
    ShoppingList,
    User,
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


def test_reparse_repairs_only_unambiguous_quantity_arithmetic(db):
    household = Household(name="Home")
    db.add(household)
    db.flush()
    recipe = Recipe(
        household_id=household.id,
        title="Calculated ingredients",
        source_type="url",
        source_url="https://example.com/calculated-ingredients",
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
    delight = RecipeIngredient(
        recipe_version_id=version.id,
        position=0,
        original_text="2 x 55g bars Turkish delight halved and sliced",
        quantity=Decimal("2"),
        unit="g",
        quantity_grams=Decimal("110"),
        food_phrase="Turkish delight",
        parsed_food_phrase="Turkish delight",
        parser_version="ingredient-parser-nlp-2.7.0+adapter1",
    )
    chicken = RecipeIngredient(
        recipe_version_id=version.id,
        position=1,
        original_text="4 skinless, boneless chicken breast halves - cooked and diced",
        quantity=Decimal("4"),
        unit="item",
        food_phrase="chicken breast halves",
        parsed_food_phrase="chicken breast halves",
        parser_version="ingredient-parser-nlp-2.7.0+adapter1",
    )
    reviewed_onions = RecipeIngredient(
        recipe_version_id=version.id,
        position=2,
        original_text="2 onions",
        quantity=Decimal("3"),
        unit="item",
        food_phrase="onions",
        parsed_food_phrase="onions",
        parser_version="ingredient-parser-nlp-2.7.0+adapter1",
    )
    db.add_all([delight, chicken, reviewed_onions])
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

    assert result.scanned == 3
    assert result.changed == 2
    assert result.lists_marked == 1
    assert delight.quantity == Decimal("2")
    assert delight.unit == "bar"
    assert delight.quantity_grams == Decimal("110")
    assert chicken.quantity == Decimal("2")
    assert chicken.unit == "item"
    assert chicken.food_phrase == "chicken breasts"
    assert reviewed_onions.quantity == Decimal("3")
    assert reviewed_onions.unit == "item"
    assert shopping_list.rebuild_recommended is True


def test_shopping_name_edit_remembers_generated_names_and_detects_conflicts(
    client,
    owner,
    session_factory,
):
    with session_factory() as db:
        user = db.get(User, owner["user"]["id"])
        shopping_list = ShoppingList(
            household_id=user.household_id,
            name="Current shopping list",
            active=True,
        )
        db.add(shopping_list)
        db.flush()
        item = ShoppingItem(
            shopping_list_id=shopping_list.id,
            display_name="courgettes",
            exact_quantity=Decimal("2"),
            purchase_quantity=Decimal("2"),
            unit="item",
            category="Produce",
            source_name_keys=ingredient_name_keys(db, "courgettes"),
        )
        db.add(item)
        db.commit()
        list_id, item_id = shopping_list.id, item.id

    headers = {"X-CSRF-Token": owner["csrf_token"]}
    renamed = client.put(
        f"/api/v1/shopping-lists/{list_id}/items/{item_id}/name",
        headers=headers,
        json={
            "display_name": "garden courgette",
            "expected_display_name": "courgettes",
        },
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["display_name"] == "garden courgette"

    conflict = client.put(
        f"/api/v1/shopping-lists/{list_id}/items/{item_id}/name",
        headers=headers,
        json={
            "display_name": "summer squash",
            "expected_display_name": "courgettes",
        },
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "SHOPPING_NAME_CONFLICT"
    assert conflict.json()["actions"][0]["current_display_name"] == "garden courgette"

    with session_factory() as db:
        user = db.get(User, owner["user"]["id"])
        override_count = db.scalar(
            select(func.count(IngredientNameOverride.id)).where(
                IngredientNameOverride.household_id == user.household_id
            )
        )
        display_name, remembered = preferred_ingredient_name(
            db,
            user.household_id,
            ingredient_name_keys(db, "courgette"),
            "courgette",
        )
        recipe = Recipe(
            household_id=user.household_id,
            title="Remembered courgettes",
            source_type="url",
            source_url="https://example.com/remembered-courgettes",
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
        db.add(
            RecipeIngredient(
                recipe_version_id=version.id,
                position=0,
                original_text="2 courgettes",
                quantity=Decimal("2"),
                unit="item",
                food_phrase="courgettes",
                parsed_food_phrase="courgettes",
                parser_version=PARSER_VERSION,
                parser_name_keys=ingredient_name_keys(db, "courgettes"),
                needs_review=True,
            )
        )
        db.commit()
        recipe_id = recipe.id
    assert override_count == 2
    assert display_name == "garden courgette"
    assert remembered is True

    remembered_recipe = client.get(f"/api/v1/recipes/{recipe_id}")
    assert remembered_recipe.status_code == 200, remembered_recipe.text
    assert remembered_recipe.json()["ingredients"][0]["food_phrase"] == "garden courgette"
    assert remembered_recipe.json()["ingredients"][0]["needs_review"] is False
    assert remembered_recipe.json()["review_count"] == 0
