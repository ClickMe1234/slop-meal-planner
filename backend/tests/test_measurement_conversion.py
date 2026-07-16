from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models import (
    FoodRecord,
    Household,
    MealBatch,
    MealPlan,
    PantryLot,
    PantryReservation,
    Recipe,
    RecipeIngredient,
    RecipeVersion,
    ShoppingItem,
    ShoppingList,
)
from app.services.measurement_conversion import (
    INGREDIENT_MEASUREMENT_PROFILES,
    normalise_shopping_measurement,
    resolve_measurement_profile,
)
from app.services.shopping import build_shopping_list


def _planned_recipe(db, ingredients, *, servings=1):
    household = Household(name="Home")
    db.add(household)
    db.flush()
    recipe = Recipe(household_id=household.id, title="Measured recipe")
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
    for position, values in enumerate(ingredients):
        db.add(
            RecipeIngredient(
                recipe_version_id=version.id,
                position=position,
                original_text=values.pop("original_text"),
                **values,
            )
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
            servings=servings,
            planned_cook_date=plan.start_date,
        )
    )
    db.flush()
    return household, plan


def _items(db, shopping_list):
    return db.scalars(
        select(ShoppingItem).where(ShoppingItem.shopping_list_id == shopping_list.id)
    ).all()


def test_registry_is_reviewed_and_has_complete_provenance():
    assert len(INGREDIENT_MEASUREMENT_PROFILES) >= 40
    assert all(profile.density_g_per_ml > 0 for profile in INGREDIENT_MEASUREMENT_PROFILES)
    assert all(
        profile.source and profile.source_url and profile.source_reference
        for profile in INGREDIENT_MEASUREMENT_PROFILES
    )


def test_known_densities_normalise_to_stable_mass_storage():
    flour = resolve_measurement_profile("all-purpose flour")
    milk = resolve_measurement_profile("whole milk")

    assert normalise_shopping_measurement(Decimal("1"), "cup", flour.density_g_per_ml) == (
        Decimal("125.040"),
        "g",
    )
    assert normalise_shopping_measurement(Decimal("103"), "g", milk.density_g_per_ml) == (
        Decimal("103"),
        "g",
    )


def test_unknown_ingredients_combine_within_dimension_without_guessing():
    assert normalise_shopping_measurement(Decimal("2"), "tbsp", None) == (
        Decimal("30"),
        "ml",
    )


def test_preparation_specific_name_wins_over_the_generic_profile():
    profile = resolve_measurement_profile("cooked rice", "rice")

    assert profile is not None
    assert profile.canonical_name == "cooked rice"
    assert profile.density_g_per_ml == Decimal("0.73")
    assert normalise_shopping_measurement(Decimal("2"), "oz", None) == (
        Decimal("56.6990"),
        "g",
    )


def test_shopping_combines_flour_volume_and_mass_into_grams(db):
    household, plan = _planned_recipe(
        db,
        [
            {
                "original_text": "100 g plain flour",
                "quantity": Decimal("100"),
                "unit": "g",
                "quantity_grams": Decimal("100"),
                "food_phrase": "plain flour",
            },
            {
                "original_text": "1 cup all-purpose flour",
                "quantity": Decimal("1"),
                "unit": "cup",
                "food_phrase": "all-purpose flour",
            },
        ],
    )

    shopping = build_shopping_list(db, household.id, plan.id, "Week shopping")
    items = _items(db, shopping)

    assert len(items) == 1
    assert items[0].unit == "g"
    assert items[0].exact_quantity == Decimal("225")
    assert items[0].purchase_quantity == Decimal("226")


def test_shopping_combines_milk_mass_and_volume_with_mass_storage(db):
    household, plan = _planned_recipe(
        db,
        [
            {
                "original_text": "103 g milk",
                "quantity": Decimal("103"),
                "unit": "g",
                "quantity_grams": Decimal("103"),
                "food_phrase": "milk",
            },
            {
                "original_text": "200 ml whole milk",
                "quantity": Decimal("200"),
                "unit": "ml",
                "food_phrase": "whole milk",
            },
        ],
    )

    shopping = build_shopping_list(db, household.id, plan.id, "Week shopping")
    items = _items(db, shopping)

    assert len(items) == 1
    assert items[0].unit == "g"
    assert items[0].exact_quantity == Decimal("309")
    assert items[0].purchase_quantity == Decimal("309")


def test_unknown_ingredient_combines_spoons_as_ml_but_keeps_grams_separate(db):
    household, plan = _planned_recipe(
        db,
        [
            {
                "original_text": "1 tbsp mystery seasoning",
                "quantity": Decimal("1"),
                "unit": "tbsp",
                "food_phrase": "mystery seasoning",
            },
            {
                "original_text": "2 tsp mystery seasoning",
                "quantity": Decimal("2"),
                "unit": "tsp",
                "food_phrase": "mystery seasoning",
            },
            {
                "original_text": "10 g mystery seasoning",
                "quantity": Decimal("10"),
                "unit": "g",
                "quantity_grams": Decimal("10"),
                "food_phrase": "mystery seasoning",
            },
        ],
    )

    shopping = build_shopping_list(db, household.id, plan.id, "Week shopping")
    items = sorted(_items(db, shopping), key=lambda item: item.unit)

    assert [(item.unit, item.exact_quantity) for item in items] == [
        ("g", Decimal("10")),
        ("ml", Decimal("25")),
    ]


def test_food_record_density_overrides_registry_and_cross_unit_pantry_is_deducted(db):
    food = FoodRecord(
        provider="test",
        provider_record_id="milk",
        dataset_version="1",
        name="Milk",
        density_g_per_ml=Decimal("1.05"),
    )
    db.add(food)
    db.flush()
    household, plan = _planned_recipe(
        db,
        [
            {
                "original_text": "210 g milk",
                "quantity": Decimal("210"),
                "unit": "g",
                "quantity_grams": Decimal("210"),
                "food_phrase": "milk",
                "food_record_id": food.id,
            }
        ],
    )
    lot = PantryLot(
        household_id=household.id,
        food_record_id=food.id,
        display_name="Milk",
        initial_quantity=Decimal("50"),
        unit="ml",
    )
    db.add(lot)
    db.flush()
    batch = db.scalar(select(MealBatch).where(MealBatch.meal_plan_id == plan.id))
    db.add(
        PantryReservation(
            pantry_lot_id=lot.id,
            meal_batch_id=batch.id,
            quantity=Decimal("50"),
            unit="ml",
        )
    )
    db.flush()

    shopping = build_shopping_list(db, household.id, plan.id, "Week shopping")
    item = _items(db, shopping)[0]

    assert item.unit == "g"
    assert item.exact_quantity == Decimal("158")


def test_chia_and_coriander_have_reviewed_density_profiles():
    assert resolve_measurement_profile("chia seed").density_g_per_ml == Decimal("0.72")
    assert resolve_measurement_profile("fresh coriander").density_g_per_ml == Decimal("0.06667")


def test_merged_item_is_checked_only_when_all_previous_lines_were_checked(db):
    household, plan = _planned_recipe(
        db,
        [
            {
                "original_text": "100 g flour",
                "quantity": Decimal("100"),
                "unit": "g",
                "quantity_grams": Decimal("100"),
                "food_phrase": "flour",
            },
            {
                "original_text": "1 cup flour",
                "quantity": Decimal("1"),
                "unit": "cup",
                "food_phrase": "flour",
            },
        ],
    )
    previous = ShoppingList(
        household_id=household.id,
        meal_plan_id=plan.id,
        name="Old",
        active=True,
    )
    db.add(previous)
    db.flush()
    db.add_all(
        [
            ShoppingItem(
                shopping_list_id=previous.id,
                display_name="all-purpose flour",
                exact_quantity=100,
                purchase_quantity=100,
                unit="g",
                checked=True,
                source_name_keys=["all-purpose flour", "stem:all-purpos flour"],
            ),
            ShoppingItem(
                shopping_list_id=previous.id,
                display_name="flour",
                exact_quantity=1,
                purchase_quantity=1,
                unit="cup",
                checked=False,
                source_name_keys=["flour", "stem:flour"],
            ),
        ]
    )
    db.flush()

    shopping = build_shopping_list(db, household.id, plan.id, "New")
    item = _items(db, shopping)[0]

    assert item.checked is False
