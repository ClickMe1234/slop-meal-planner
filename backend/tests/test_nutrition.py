from decimal import Decimal

import pytest

from app.errors import DomainError
from app.models import (
    FoodNutrient,
    FoodRecord,
    Household,
    Recipe,
    RecipeIngredient,
    RecipeVersion,
)
from app.services.nutrition import calculate_recipe, resolve_recipe_nutrition


def test_recipe_nutrition_is_calculated_per_serving(db):
    household = Household(name="Home")
    db.add(household)
    db.flush()
    food = FoodRecord(
        provider="test",
        provider_record_id="chicken",
        dataset_version="1",
        name="Chicken",
        basis_amount=100,
        basis_unit="g",
    )
    db.add(food)
    db.flush()
    for code, amount, unit in (
        ("energy_kcal", 200, "kcal"),
        ("protein_g", 30, "g"),
        ("carbohydrate_g", 0, "g"),
        ("fat_g", 8, "g"),
    ):
        db.add(FoodNutrient(food_record_id=food.id, code=code, amount=amount, unit=unit))
    recipe = Recipe(household_id=household.id, title="Chicken", source_type="custom")
    db.add(recipe)
    db.flush()
    version = RecipeVersion(recipe_id=recipe.id, version_number=1, title="Chicken", yield_servings=2)
    db.add(version)
    db.flush()
    db.add(
        RecipeIngredient(
            recipe_version_id=version.id,
            position=0,
            original_text="300g chicken",
            quantity=300,
            unit="g",
            quantity_grams=300,
            food_phrase="chicken",
            food_record_id=food.id,
        )
    )
    db.flush()

    result = calculate_recipe(db, version.id)

    assert result.total_values["energy_kcal"] == 600
    assert result.per_serving_values["energy_kcal"] == 300
    assert result.per_serving_values["protein_g"] == 45
    assert recipe.eligibility == "planner_ready"


def test_complete_publisher_nutrition_is_primary_even_without_food_matches(db):
    household = Household(name="Home")
    db.add(household)
    db.flush()
    recipe = Recipe(
        household_id=household.id,
        title="Publisher stew",
        source_type="url",
        publisher="Good Food",
        source_url="https://www.bbcgoodfood.com/recipes/stew",
    )
    db.add(recipe)
    db.flush()
    version = RecipeVersion(
        recipe_id=recipe.id,
        version_number=1,
        title=recipe.title,
        yield_servings=4,
        publisher_nutrition={
            "basis": "per serving",
            "energy_kcal": 412,
            "protein_g": 18,
            "carbohydrate_g": 52,
            "fat_g": 11,
        },
    )
    db.add(version)
    db.flush()
    db.add(
        RecipeIngredient(
            recipe_version_id=version.id,
            position=0,
            original_text="1 large onion",
            quantity=1,
            unit="large",
            food_phrase="onion",
            needs_review=True,
        )
    )
    db.flush()

    result = calculate_recipe(db, version.id)

    assert result.status == "publisher"
    assert result.per_serving_values["energy_kcal"] == 412
    assert result.total_values["energy_kcal"] == 1648
    assert recipe.eligibility == "planner_ready"


def test_url_recipe_never_falls_back_to_ingredient_calculation(db):
    household = Household(name="Home")
    db.add(household)
    db.flush()
    recipe = Recipe(
        household_id=household.id,
        title="Publisher recipe without nutrition",
        source_type="url",
        source_url="https://www.bbcgoodfood.com/recipes/no-nutrition",
    )
    db.add(recipe)
    db.flush()
    version = RecipeVersion(
        recipe_id=recipe.id,
        version_number=1,
        title=recipe.title,
        yield_servings=4,
    )
    db.add(version)
    db.flush()

    with pytest.raises(DomainError) as error:
        calculate_recipe(db, version.id)

    assert error.value.code == "PUBLISHER_NUTRITION_UNAVAILABLE"
    assert recipe.eligibility != "planner_ready"


def test_shared_resolver_uses_reviewed_density_and_decimal_amounts(db):
    household = Household(name="Home")
    db.add(household)
    db.flush()
    food = FoodRecord(
        provider="test",
        provider_record_id="plain-flour",
        dataset_version="1",
        name="Plain flour",
        basis_amount=Decimal("100"),
        basis_unit="g",
    )
    db.add(food)
    db.flush()
    for code, amount, unit in (
        ("energy_kcal", Decimal("100"), "kcal"),
        ("protein_g", Decimal("10"), "g"),
        ("carbohydrate_g", Decimal("20"), "g"),
        ("fat_g", Decimal("1"), "g"),
    ):
        db.add(FoodNutrient(food_record_id=food.id, code=code, amount=amount, unit=unit))
    db.flush()

    result = resolve_recipe_nutrition(
        db,
        yield_servings=Decimal("2"),
        household_id=household.id,
        ingredients=[
            {
                "client_id": "flour",
                "original_text": "1 cup plain flour",
                "food_phrase": "plain flour",
                "quantity": Decimal("1"),
                "unit": "cup",
                "included": True,
                "food_record_id": food.id,
            }
        ],
    )

    assert result.complete is True
    assert result.ingredients[0].status == "resolved"
    assert result.ingredients[0].effective_amount == Decimal("125.040")
    assert result.batch_values["energy_kcal"] == Decimal("125.040")
    assert result.per_serving_values["energy_kcal"] == Decimal("62.520")
    assert "reviewed density" in result.assumptions[0].casefold()


def test_shared_resolver_returns_structured_incomplete_nutrient_issue(db):
    household = Household(name="Home")
    db.add(household)
    db.flush()
    food = FoodRecord(
        provider="test",
        provider_record_id="incomplete",
        dataset_version="1",
        name="Incomplete food",
        basis_amount=100,
        basis_unit="g",
    )
    db.add(food)
    db.flush()
    for code, amount, unit in (
        ("energy_kcal", 100, "kcal"),
        ("protein_g", 10, "g"),
        ("carbohydrate_g", 20, "g"),
    ):
        db.add(FoodNutrient(food_record_id=food.id, code=code, amount=amount, unit=unit))
    db.flush()

    result = resolve_recipe_nutrition(
        db,
        yield_servings=Decimal("1"),
        household_id=household.id,
        ingredients=[
            {
                "client_id": "incomplete",
                "quantity": Decimal("100"),
                "unit": "g",
                "included": True,
                "food_record_id": food.id,
            }
        ],
    )

    assert result.complete is False
    assert result.ingredients[0].status == "incomplete_nutrients"
    assert [issue.code for issue in result.issues] == ["INCOMPLETE_FOOD_NUTRIENTS"]
