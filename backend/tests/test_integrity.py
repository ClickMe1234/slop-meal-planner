from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.models import (
    FoodRecord,
    MealBatch,
    MealPlan,
    PantryLot,
    PantryReservation,
    PlanStatus,
    Recipe,
    RecipeIngredient,
    RecipeVersion,
    ShoppingItem,
    ShoppingList,
    User,
)
from app.services.integrity import (
    household_integrity_report,
    repair_household_derived_state,
)


def test_integrity_report_and_repair_preserve_physical_stock_discrepancy(
    owner, session_factory
):
    with session_factory() as db:
        user = db.get(User, owner["user"]["id"])
        lot = PantryLot(
            household_id=user.household_id,
            display_name="Miscounted rice",
            initial_quantity=Decimal("-5"),
            unit="g",
        )
        db.add_all(
            [
                lot,
                ShoppingList(
                    household_id=user.household_id,
                    name="Older active list",
                    active=True,
                ),
                ShoppingList(
                    household_id=user.household_id,
                    name="Newer active list",
                    active=True,
                ),
            ]
        )
        db.commit()

        before = household_integrity_report(db, user.household_id)
        assert before["ok"] is False
        assert before["negative_balances"][0]["lot_id"] == lot.id
        assert before["requires_physical_stock_correction"] is True
        assert len(before["duplicate_active_lists"]) == 1

        repaired = repair_household_derived_state(db, user.household_id)
        db.commit()

        assert repaired["stock_transactions_preserved"] is True
        assert repaired["after"]["duplicate_active_lists"] == []
        assert repaired["after"]["requires_physical_stock_correction"] is True
        active = db.scalars(
            select(ShoppingList).where(
                ShoppingList.household_id == user.household_id,
                ShoppingList.active.is_(True),
            )
        ).all()
        assert len(active) == 1


def test_integrity_repair_preserves_manual_items_across_duplicate_active_lists(
    owner, session_factory
):
    with session_factory() as db:
        user = db.get(User, owner["user"]["id"])
        plan = MealPlan(
            household_id=user.household_id,
            name="Accepted week",
            start_date=date(2026, 9, 7),
            end_date=date(2026, 9, 13),
            status=PlanStatus.ACCEPTED.value,
        )
        db.add(plan)
        db.flush()
        older = ShoppingList(
            household_id=user.household_id,
            meal_plan_id=plan.id,
            name="Older active list",
            active=True,
        )
        newer = ShoppingList(
            household_id=user.household_id,
            meal_plan_id=plan.id,
            name="Newer active list",
            active=True,
        )
        db.add_all([older, newer])
        db.flush()
        older_manual = ShoppingItem(
            shopping_list_id=older.id,
            display_name="older manual item",
            exact_quantity=1,
            purchase_quantity=1,
            unit="item",
            manual=True,
        )
        newer_manual = ShoppingItem(
            shopping_list_id=newer.id,
            display_name="newer manual item",
            exact_quantity=2,
            purchase_quantity=2,
            unit="item",
            manual=True,
        )
        db.add_all([older_manual, newer_manual])
        db.commit()
        manual_ids = {older_manual.id, newer_manual.id}

        repaired = repair_household_derived_state(db, user.household_id)
        db.commit()

        active = db.scalar(
            select(ShoppingList).where(
                ShoppingList.household_id == user.household_id,
                ShoppingList.active.is_(True),
            )
        )
        assert active is not None
        assert repaired["shopping_list_id"] == active.id
        assert repaired["after"]["duplicate_active_lists"] == []
        preserved = db.scalars(
            select(ShoppingItem)
            .where(
                ShoppingItem.shopping_list_id == active.id,
                ShoppingItem.manual.is_(True),
            )
            .order_by(ShoppingItem.display_name)
        ).all()
        assert {item.id for item in preserved} == manual_ids
        assert [item.display_name for item in preserved] == [
            "newer manual item",
            "older manual item",
        ]


def test_integrity_repair_clears_reservations_from_superseded_plans(
    owner, session_factory
):
    with session_factory() as db:
        user = db.get(User, owner["user"]["id"])
        food = FoodRecord(
            provider="manual",
            provider_record_id="integrity-rice",
            dataset_version="test",
            name="Rice",
        )
        recipe = Recipe(household_id=user.household_id, title="Rice")
        db.add_all([food, recipe])
        db.flush()
        version = RecipeVersion(
            recipe_id=recipe.id,
            version_number=1,
            title=recipe.title,
            yield_servings=2,
        )
        db.add(version)
        db.flush()
        ingredient = RecipeIngredient(
            recipe_version_id=version.id,
            position=0,
            original_text="40 g rice",
            quantity_grams=Decimal("40"),
            food_phrase="Rice",
            food_record_id=food.id,
        )
        accepted = MealPlan(
            household_id=user.household_id,
            name="Accepted week",
            start_date=date(2026, 9, 7),
            end_date=date(2026, 9, 13),
            status=PlanStatus.ACCEPTED.value,
        )
        superseded = MealPlan(
            household_id=user.household_id,
            name="Superseded week",
            start_date=date(2026, 8, 31),
            end_date=date(2026, 9, 6),
            status=PlanStatus.READY.value,
        )
        lot = PantryLot(
            household_id=user.household_id,
            food_record_id=food.id,
            display_name="Rice",
            initial_quantity=Decimal("100"),
            unit="g",
        )
        db.add_all([ingredient, accepted, superseded, lot])
        db.flush()
        accepted_batch = MealBatch(
            meal_plan_id=accepted.id,
            recipe_version_id=version.id,
            servings=2,
            planned_cook_date=accepted.start_date,
        )
        stale_cooked_batch = MealBatch(
            meal_plan_id=superseded.id,
            recipe_version_id=version.id,
            servings=2,
            planned_cook_date=superseded.start_date,
            cooked_at=datetime.now(UTC),
        )
        db.add_all([accepted_batch, stale_cooked_batch])
        db.flush()
        db.add_all(
            [
                PantryReservation(
                    pantry_lot_id=lot.id,
                    meal_batch_id=accepted_batch.id,
                    quantity=Decimal("25"),
                    unit="g",
                ),
                PantryReservation(
                    pantry_lot_id=lot.id,
                    meal_batch_id=stale_cooked_batch.id,
                    quantity=Decimal("30"),
                    unit="g",
                ),
            ]
        )
        db.commit()

        repaired = repair_household_derived_state(db, user.household_id)
        db.commit()

        assert repaired["after"]["cooked_batch_reservations"] == []
        reservations = db.scalars(select(PantryReservation)).all()
        assert len(reservations) == 1
        assert reservations[0].meal_batch_id == accepted_batch.id
        assert reservations[0].quantity == Decimal("40")


def test_integrity_repair_clears_reservations_without_an_accepted_plan(
    owner, session_factory
):
    with session_factory() as db:
        user = db.get(User, owner["user"]["id"])
        recipe = Recipe(household_id=user.household_id, title="Rice")
        db.add(recipe)
        db.flush()
        version = RecipeVersion(
            recipe_id=recipe.id,
            version_number=1,
            title=recipe.title,
            yield_servings=2,
        )
        ready = MealPlan(
            household_id=user.household_id,
            name="Unaccepted week",
            start_date=date(2026, 9, 7),
            end_date=date(2026, 9, 13),
            status=PlanStatus.READY.value,
        )
        lot = PantryLot(
            household_id=user.household_id,
            display_name="Rice",
            initial_quantity=Decimal("100"),
            unit="g",
        )
        db.add_all([version, ready, lot])
        db.flush()
        batch = MealBatch(
            meal_plan_id=ready.id,
            recipe_version_id=version.id,
            servings=2,
            planned_cook_date=ready.start_date,
        )
        db.add(batch)
        db.flush()
        db.add(
            PantryReservation(
                pantry_lot_id=lot.id,
                meal_batch_id=batch.id,
                quantity=Decimal("30"),
                unit="g",
            )
        )
        db.commit()

        repaired = repair_household_derived_state(db, user.household_id)
        db.commit()

        assert repaired["shopping_list_id"] is None
        assert db.scalars(select(PantryReservation)).all() == []
