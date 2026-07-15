from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    PantryLot,
    PantryReservation,
    PantryTransaction,
    ShoppingItem,
    ShoppingList,
)
from .quantities import (
    canonical_quantity_unit,
    round_purchase_quantity,
    round_quantity,
)


@dataclass(frozen=True, slots=True)
class QuantityNormalizationResult:
    pantry_lots_changed: int
    transactions_changed: int
    reservations_changed: int
    reservations_removed: int
    shopping_items_changed: int
    lists_marked: int


def normalize_stored_quantities(db: Session) -> QuantityNormalizationResult:
    """Apply the current quantity policy to legacy shopping and pantry data.

    The operation is deliberately idempotent and runs under the deployment
    migration lock. Reservations are capped after rounding so normalization
    can never leave a pantry lot over-reserved.
    """

    lots = db.scalars(select(PantryLot).order_by(PantryLot.id)).all()
    lots_by_id = {lot.id: lot for lot in lots}
    affected_lot_ids: set[str] = set()
    changed_lot_ids: set[str] = set()

    for lot in lots:
        unit = canonical_quantity_unit(lot.unit)
        initial = round_quantity(lot.initial_quantity, unit)
        if lot.unit != unit or Decimal(lot.initial_quantity) != initial:
            lot.unit = unit
            lot.initial_quantity = initial
            changed_lot_ids.add(lot.id)
            affected_lot_ids.add(lot.id)

    transactions = db.scalars(
        select(PantryTransaction).order_by(
            PantryTransaction.pantry_lot_id,
            PantryTransaction.created_at,
            PantryTransaction.id,
        )
    ).all()
    transactions_by_lot: dict[str, list[PantryTransaction]] = defaultdict(list)
    transactions_changed = 0
    for transaction in transactions:
        lot = lots_by_id.get(transaction.pantry_lot_id)
        if lot is None:
            continue
        rounded = round_quantity(transaction.quantity_delta, lot.unit)
        if Decimal(transaction.quantity_delta) != rounded:
            transaction.quantity_delta = rounded
            transactions_changed += 1
            affected_lot_ids.add(lot.id)
        transactions_by_lot[lot.id].append(transaction)

    on_hand_by_lot: dict[str, Decimal] = {}
    for lot in lots:
        on_hand = round_quantity(
            Decimal(lot.initial_quantity)
            + sum(
                (
                    Decimal(transaction.quantity_delta)
                    for transaction in transactions_by_lot[lot.id]
                ),
                Decimal("0"),
            ),
            lot.unit,
        )
        if on_hand < 0:
            correction = PantryTransaction(
                pantry_lot_id=lot.id,
                quantity_delta=-on_hand,
                reason="quantity_rounding",
                reference_type="quantity_policy",
            )
            db.add(correction)
            transactions_by_lot[lot.id].append(correction)
            transactions_changed += 1
            affected_lot_ids.add(lot.id)
            on_hand = Decimal("0")
        on_hand_by_lot[lot.id] = on_hand

    reservations = db.scalars(
        select(PantryReservation).order_by(
            PantryReservation.pantry_lot_id,
            PantryReservation.id,
        )
    ).all()
    capacity_by_lot = {
        lot.id: max(on_hand_by_lot.get(lot.id, Decimal("0")), Decimal("0"))
        for lot in lots
    }
    reservations_changed = 0
    reservations_removed = 0
    for reservation in reservations:
        lot = lots_by_id.get(reservation.pantry_lot_id)
        if lot is None:
            continue
        rounded = round_quantity(reservation.quantity, lot.unit)
        normalized = min(max(rounded, Decimal("0")), capacity_by_lot[lot.id])
        if normalized <= 0:
            db.delete(reservation)
            reservations_removed += 1
            affected_lot_ids.add(lot.id)
            continue
        if (
            reservation.unit != lot.unit
            or Decimal(reservation.quantity) != normalized
        ):
            reservation.unit = lot.unit
            reservation.quantity = normalized
            reservations_changed += 1
            affected_lot_ids.add(lot.id)
        capacity_by_lot[lot.id] -= normalized

    for lot in lots:
        if lot.id in affected_lot_ids:
            lot.version += 1

    changed_list_ids: set[str] = set()
    shopping_items_changed = 0
    items = db.scalars(select(ShoppingItem).order_by(ShoppingItem.id)).all()
    for item in items:
        unit = canonical_quantity_unit(item.unit)
        exact = round_quantity(item.exact_quantity, unit)
        purchase = max(
            round_purchase_quantity(item.purchase_quantity, unit),
            exact,
        )
        if (
            item.unit != unit
            or Decimal(item.exact_quantity) != exact
            or Decimal(item.purchase_quantity) != purchase
        ):
            item.unit = unit
            item.exact_quantity = exact
            item.purchase_quantity = purchase
            item.version += 1
            shopping_items_changed += 1
            changed_list_ids.add(item.shopping_list_id)

    affected_household_ids = {
        lots_by_id[lot_id].household_id
        for lot_id in affected_lot_ids
        if lot_id in lots_by_id
    }
    pantry_changed = bool(affected_household_ids)
    lists_marked = 0
    lists_to_bump = set(changed_list_ids)
    if pantry_changed:
        active_lists = db.scalars(
            select(ShoppingList).where(
                ShoppingList.active.is_(True),
                ShoppingList.household_id.in_(affected_household_ids),
            )
        ).all()
        for shopping_list in active_lists:
            lists_to_bump.add(shopping_list.id)
            if not shopping_list.rebuild_recommended:
                shopping_list.rebuild_recommended = True
                lists_marked += 1

    if lists_to_bump:
        shopping_lists = db.scalars(
            select(ShoppingList).where(ShoppingList.id.in_(lists_to_bump))
        ).all()
        for shopping_list in shopping_lists:
            shopping_list.version += 1

    db.flush()
    return QuantityNormalizationResult(
        pantry_lots_changed=len(changed_lot_ids),
        transactions_changed=transactions_changed,
        reservations_changed=reservations_changed,
        reservations_removed=reservations_removed,
        shopping_items_changed=shopping_items_changed,
        lists_marked=lists_marked,
    )
