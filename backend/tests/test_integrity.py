from decimal import Decimal

from sqlalchemy import select

from app.models import PantryLot, ShoppingList, User
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
