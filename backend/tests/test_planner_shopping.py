from decimal import Decimal
from datetime import date

import pytest

from app.services.planner import (
    ParticipantTarget,
    PlannerInfeasibleError,
    RecipeCandidate,
    choose_shared_recipe,
)
from app.services.shopping import round_purchase
from app.services.pantry import reserve_plan_batches
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


def test_shopping_rounds_count_but_not_weight():
    assert round_purchase(Decimal("3.75"), "eggs") == 4
    assert round_purchase(Decimal("430.5"), "g") == Decimal("430.5")


def test_planner_never_silently_relaxes_hard_tolerance():
    candidate = RecipeCandidate("too-light", "v1", {"energy_kcal": Decimal("100")})
    participant = ParticipantTarget(
        "member", "calorie", Decimal("25"), Decimal("2000"), None, None, None,
        tolerance_percent=Decimal("5"),
    )

    with pytest.raises(PlannerInfeasibleError):
        choose_shared_recipe([candidate], [participant])


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
