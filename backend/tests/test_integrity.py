from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models import (
    MealPlan,
    PantryLot,
    PlanStatus,
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
