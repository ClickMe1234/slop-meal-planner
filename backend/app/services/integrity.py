from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..errors import DomainError
from ..models import (
    MealBatch,
    MealPlan,
    PantryLot,
    PantryReservation,
    PlanStatus,
    ShoppingList,
)
from .pantry import balances, lock_household, reserve_plan_batches
from .shopping import build_shopping_list


def household_integrity_report(db: Session, household_id: str) -> dict[str, Any]:
    """Inspect current derived state without changing user or stock history."""

    db.flush()
    negative_balances: list[dict[str, Any]] = []
    over_reservations: list[dict[str, Any]] = []
    for lot in db.scalars(
        select(PantryLot)
        .where(PantryLot.household_id == household_id)
        .order_by(PantryLot.id)
    ).all():
        on_hand, reserved, usable = balances(db, lot)
        if on_hand < 0:
            negative_balances.append(
                {"lot_id": lot.id, "display_name": lot.display_name, "on_hand": str(on_hand)}
            )
        if reserved > max(on_hand, Decimal("0")):
            over_reservations.append(
                {
                    "lot_id": lot.id,
                    "display_name": lot.display_name,
                    "on_hand": str(on_hand),
                    "reserved": str(reserved),
                    "usable": str(usable),
                }
            )
    active_lists = db.scalars(
        select(ShoppingList)
        .where(
            ShoppingList.household_id == household_id,
            ShoppingList.active.is_(True),
        )
        .order_by(ShoppingList.created_at.desc(), ShoppingList.id)
    ).all()
    active_plans = db.scalars(
        select(MealPlan)
        .where(
            MealPlan.household_id == household_id,
            MealPlan.status.in_([PlanStatus.READY.value, PlanStatus.ACCEPTED.value]),
        )
        .order_by(MealPlan.id)
    ).all()
    invalid_plans: list[dict[str, Any]] = []
    # Import locally because validation is currently shared with HTTP plan
    # mutations; keeping this report read-only avoids a service import cycle.
    from ..routes.planning_routes import _validate_mutable_plan_constraints

    for plan in active_plans:
        try:
            _validate_mutable_plan_constraints(db, plan)
        except DomainError as exc:
            invalid_plans.append(
                {
                    "plan_id": plan.id,
                    "status": plan.status,
                    "code": exc.code,
                    "detail": exc.detail,
                    "actions": exc.actions,
                    "issues": exc.issues,
                }
            )
    cooked_reservations = db.execute(
        select(PantryReservation.id, PantryReservation.meal_batch_id)
        .join(MealBatch, MealBatch.id == PantryReservation.meal_batch_id)
        .join(MealPlan, MealPlan.id == MealBatch.meal_plan_id)
        .where(
            MealPlan.household_id == household_id,
            MealBatch.cooked_at.is_not(None),
        )
    ).all()
    accepted_ids = [
        plan.id for plan in active_plans if plan.status == PlanStatus.ACCEPTED.value
    ]
    return {
        "household_id": household_id,
        "ok": not any(
            (
                negative_balances,
                over_reservations,
                invalid_plans,
                cooked_reservations,
                len(active_lists) > 1,
                len(accepted_ids) > 1,
            )
        ),
        "negative_balances": negative_balances,
        "over_reservations": over_reservations,
        "invalid_active_plans": invalid_plans,
        "duplicate_active_lists": [item.id for item in active_lists[1:]],
        "duplicate_accepted_plans": accepted_ids[1:],
        "cooked_batch_reservations": [
            {"reservation_id": row.id, "batch_id": row.meal_batch_id}
            for row in cooked_reservations
        ],
        "requires_physical_stock_correction": bool(negative_balances),
    }


def repair_household_derived_state(db: Session, household_id: str) -> dict[str, Any]:
    """Repair reservations/list derivations while retaining transaction history."""

    lock_household(db, household_id)
    before = household_integrity_report(db, household_id)
    active_lists = db.scalars(
        select(ShoppingList)
        .where(
            ShoppingList.household_id == household_id,
            ShoppingList.active.is_(True),
        )
        .order_by(ShoppingList.created_at.desc(), ShoppingList.id)
        .with_for_update()
    ).all()
    accepted_plans = db.scalars(
        select(MealPlan)
        .where(
            MealPlan.household_id == household_id,
            MealPlan.status == PlanStatus.ACCEPTED.value,
        )
        .order_by(MealPlan.id)
        .with_for_update()
    ).all()
    if len(accepted_plans) > 1:
        raise DomainError(
            "MULTIPLE_ACCEPTED_PLANS",
            "Choose the authoritative accepted plan before repairing derived state.",
            409,
        )
    rebuilt_list_id: str | None = None
    if accepted_plans:
        plan = accepted_plans[0]
        batches = db.scalars(
            select(MealBatch)
            .where(MealBatch.meal_plan_id == plan.id)
            .order_by(MealBatch.id)
            .with_for_update()
        ).all()
        batch_ids = [batch.id for batch in batches]
        if batch_ids:
            db.execute(
                delete(PantryReservation).where(
                    PantryReservation.meal_batch_id.in_(batch_ids)
                )
            )
        db.flush()
        reserve_plan_batches(
            db,
            household_id,
            [batch for batch in batches if batch.cooked_at is None],
        )
        active_name = active_lists[0].name if active_lists else "Current shopping list"
        rebuilt_list_id = build_shopping_list(db, household_id, plan.id, active_name).id
    else:
        # With an accepted plan, build_shopping_list must see every active
        # duplicate so it can move manual rows onto the authoritative list
        # before deactivating the others. Without a plan there is no rebuild,
        # so retain the newest list and deactivate stale duplicates here.
        for stale in active_lists[1:]:
            stale.active = False
            stale.version += 1
    db.flush()
    return {
        "before": before,
        "after": household_integrity_report(db, household_id),
        "shopping_list_id": rebuilt_list_id,
        "stock_transactions_preserved": True,
    }
