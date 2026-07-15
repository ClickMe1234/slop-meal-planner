from decimal import Decimal
from datetime import date

import pytest

from app.services.planner import (
    ParticipantTarget,
    PlannerInfeasibleError,
    RecipeCandidate,
    aggregate_nutrition_violations,
    choose_shared_recipe,
)
from app.services.shopping import round_purchase
from app.services.pantry import balances, reserve_plan_batches
from app.services.shopping import build_shopping_list
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
)
from sqlalchemy import select


def test_planner_chooses_recipe_and_quarter_portions():
    candidates = [
        RecipeCandidate("light", "v1", {"energy_kcal": Decimal("250")}),
        RecipeCandidate("filling", "v2", {"energy_kcal": Decimal("500")}),
    ]
    participants = [
        ParticipantTarget("a", "calorie", Decimal("25"), Decimal("2000"), None, None, None),
        ParticipantTarget("b", "calorie", Decimal("25"), Decimal("1500"), None, None, None),
    ]

    choice = choose_shared_recipe(candidates, participants)

    assert choice.candidate.recipe_id == "filling"
    assert choice.portions == {"a": Decimal("1.0"), "b": Decimal("0.75")}


def test_shopping_rounds_purchase_amounts_for_their_unit():
    assert round_purchase(Decimal("3.75"), "eggs") == 4
    assert round_purchase(Decimal("430.5"), "g") == 431
    assert round_purchase(Decimal("1.231"), "l") == Decimal("1.24")
    assert round_purchase(Decimal("1.01"), "tbsp") == Decimal("1.25")


def test_planner_never_silently_relaxes_hard_tolerance():
    candidate = RecipeCandidate("too-light", "v1", {"energy_kcal": Decimal("100")})
    participant = ParticipantTarget(
        "member", "calorie", Decimal("25"), Decimal("2000"), None, None, None,
        tolerance_percent=Decimal("5"),
    )

    with pytest.raises(PlannerInfeasibleError):
        choose_shared_recipe([candidate], [participant])


def test_planner_can_explicitly_choose_the_closest_portion_outside_tolerance():
    candidate = RecipeCandidate("too-light", "v1", {"energy_kcal": Decimal("100")})
    participant = ParticipantTarget(
        "member", "calorie", Decimal("25"), Decimal("2000"), None, None, None,
        tolerance_percent=Decimal("5"),
    )

    choice = choose_shared_recipe(
        [candidate], [participant], enforce_nutrition_bounds=False
    )

    assert choice.candidate.recipe_id == "too-light"
    assert choice.portions == {"member": Decimal("2.00")}


def test_daily_bounds_allow_meal_allocation_deviations_to_offset():
    breakfast = ParticipantTarget(
        "member", "calorie", Decimal("50"), Decimal("1000"), None, None, None
    )
    dinner = ParticipantTarget(
        "member", "calorie", Decimal("50"), Decimal("1000"), None, None, None
    )

    assert aggregate_nutrition_violations(
        [breakfast, dinner], {"energy_kcal": Decimal("1000")}
    ) == []
    assert aggregate_nutrition_violations(
        [breakfast, dinner], {"energy_kcal": Decimal("900")}
    )


def test_macro_minimum_has_ten_gram_daily_tolerance_and_readable_messages():
    target = ParticipantTarget(
        "member", "calorie", Decimal("100"), Decimal("1800"), None, None, None,
        tolerance_percent=Decimal("5"), protein_min_g=Decimal("130"),
    )

    assert aggregate_nutrition_violations(
        [target], {"energy_kcal": Decimal("1800"), "protein_g": Decimal("120")}
    ) == []

    violations = aggregate_nutrition_violations(
        [target], {"energy_kcal": Decimal("1705.25"), "protein_g": Decimal("119")}
    )

    assert violations == [
        "Calories: 1705.25 kcal (allowed 1710–1890 kcal)",
        "Protein: 119 g (minimum 120 g after tolerance)",
    ]
    assert all("E+" not in message for message in violations)


def test_calorie_mode_minimum_steers_recipe_ranking_without_penalising_excess():
    participant = ParticipantTarget(
        "member", "calorie", Decimal("25"), Decimal("2000"), None, None, None,
        protein_min_g=Decimal("120"),
    )
    low_protein = RecipeCandidate(
        "low-protein", "v1", {"energy_kcal": Decimal("500"), "protein_g": Decimal("15")}
    )
    high_protein = RecipeCandidate(
        "high-protein", "v2", {"energy_kcal": Decimal("500"), "protein_g": Decimal("35")}
    )

    choice = choose_shared_recipe(
        [low_protein, high_protein], [participant], enforce_nutrition_bounds=False
    )

    assert choice.candidate.recipe_id == "high-protein"
    assert choice.portions == {"member": Decimal("1.0")}


def test_zero_calorie_mode_minimum_preserves_calorie_only_ranking():
    participant = ParticipantTarget(
        "member", "calorie", Decimal("25"), Decimal("2000"), None, None, None,
        protein_min_g=Decimal("0"), carbohydrate_min_g=Decimal("0"), fat_min_g=Decimal("0"),
    )
    first = RecipeCandidate(
        "first", "v1", {"energy_kcal": Decimal("500"), "protein_g": Decimal("5")}
    )
    second = RecipeCandidate(
        "second", "v2", {"energy_kcal": Decimal("500"), "protein_g": Decimal("50")}
    )

    choice = choose_shared_recipe([first, second], [participant])

    assert choice.candidate.recipe_id == "first"


def test_stored_preference_terms_softly_rank_feasible_recipes():
    participant = ParticipantTarget(
        "member", "calorie", Decimal("25"), Decimal("2000"), None, None, None
    )
    spinach = RecipeCandidate(
        "spinach", "v1", {"energy_kcal": Decimal("500")}, ingredient_text="spinach pasta"
    )
    broccoli = RecipeCandidate(
        "broccoli", "v2", {"energy_kcal": Decimal("500")}, ingredient_text="broccoli pasta"
    )

    preferred = choose_shared_recipe(
        [broccoli, spinach], [participant], preferred_terms=frozenset({"spinach"})
    )
    disliked = choose_shared_recipe(
        [spinach, broccoli], [participant], disliked_terms=frozenset({"spinach"})
    )

    assert preferred.candidate.recipe_id == "spinach"
    assert disliked.candidate.recipe_id == "broccoli"


def test_accepted_plan_reservations_reduce_the_shopping_remainder(db):
    household = Household(name="Home")
    db.add(household)
    db.flush()
    food = FoodRecord(
        provider="cofid", provider_record_id="rice", dataset_version="2021", name="Rice"
    )
    db.add(food)
    db.flush()
    recipe = Recipe(household_id=household.id, title="Rice bowl")
    db.add(recipe)
    db.flush()
    version = RecipeVersion(
        recipe_id=recipe.id, version_number=1, title=recipe.title, yield_servings=2
    )
    db.add(version)
    db.flush()
    db.add(
        RecipeIngredient(
            recipe_version_id=version.id,
            position=0,
            original_text="100 g rice",
            quantity_grams=100,
            food_phrase="Rice",
            food_record_id=food.id,
        )
    )
    plan = MealPlan(
        household_id=household.id,
        name="Week",
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 22),
    )
    db.add(plan)
    db.flush()
    batch = MealBatch(
        meal_plan_id=plan.id,
        recipe_version_id=version.id,
        servings=9,
        planned_cook_date=plan.start_date,
    )
    lot = PantryLot(
        household_id=household.id,
        food_record_id=food.id,
        display_name="Rice",
        initial_quantity=300,
        unit="g",
    )
    db.add_all([batch, lot])
    db.flush()

    reserve_plan_batches(db, household.id, [batch])
    reservation = db.scalar(select(PantryReservation))
    assert reservation.quantity == Decimal("300")

    shopping = build_shopping_list(db, household.id, plan.id, "Week shopping")
    item = db.scalar(select(ShoppingItem).where(ShoppingItem.shopping_list_id == shopping.id))
    assert item.exact_quantity == Decimal("150")


def test_shopping_keeps_readable_required_amount_but_rounds_purchase_up(db):
    household = Household(name="Home")
    db.add(household)
    db.flush()
    recipe = Recipe(household_id=household.id, title="Rice bowl")
    db.add(recipe)
    db.flush()
    version = RecipeVersion(
        recipe_id=recipe.id, version_number=1, title=recipe.title, yield_servings=1
    )
    db.add(version)
    db.flush()
    db.add(
        RecipeIngredient(
            recipe_version_id=version.id,
            position=0,
            original_text="430.1 g rice",
            quantity_grams=Decimal("430.1"),
            food_phrase="Rice",
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
            servings=1,
            planned_cook_date=plan.start_date,
        )
    )
    db.flush()

    shopping = build_shopping_list(db, household.id, plan.id, "Week shopping")
    item = db.scalar(
        select(ShoppingItem).where(ShoppingItem.shopping_list_id == shopping.id)
    )

    assert item.exact_quantity == Decimal("430")
    assert item.purchase_quantity == Decimal("431")


def test_pantry_reservations_round_indivisible_recipe_units(db):
    household = Household(name="Home")
    db.add(household)
    db.flush()
    food = FoodRecord(
        provider="cofid", provider_record_id="celery", dataset_version="2021", name="Celery"
    )
    db.add(food)
    db.flush()
    recipe = Recipe(household_id=household.id, title="Celery salad")
    db.add(recipe)
    db.flush()
    version = RecipeVersion(
        recipe_id=recipe.id, version_number=1, title=recipe.title, yield_servings=1
    )
    db.add(version)
    db.flush()
    db.add(
        RecipeIngredient(
            recipe_version_id=version.id,
            position=0,
            original_text="1/2 stalk celery",
            quantity=Decimal("0.5"),
            unit="stalk",
            food_phrase="Celery",
            food_record_id=food.id,
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
    batch = MealBatch(
        meal_plan_id=plan.id,
        recipe_version_id=version.id,
        servings=1,
        planned_cook_date=plan.start_date,
    )
    lot = PantryLot(
        household_id=household.id,
        food_record_id=food.id,
        display_name="Celery",
        initial_quantity=1,
        unit="stalk",
    )
    db.add_all([batch, lot])
    db.flush()

    reserve_plan_batches(db, household.id, [batch])
    reservation = db.scalar(select(PantryReservation))

    assert reservation.quantity == Decimal("1")
    assert balances(db, lot) == (Decimal("1"), Decimal("1"), Decimal("0"))
