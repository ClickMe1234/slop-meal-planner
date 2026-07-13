from decimal import Decimal

from app.models import (
    FoodNutrient,
    FoodRecord,
    Household,
    Recipe,
    RecipeIngredient,
    RecipeVersion,
)
from app.services.nutrition import calculate_recipe


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

