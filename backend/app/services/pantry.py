from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import DomainError, NotFoundError
from ..models import MealBatch, PantryLot, PantryReservation, PantryTransaction, RecipeVersion
from .quantities import canonical_quantity_unit, round_quantity


def balances(db: Session, lot: PantryLot) -> tuple[Decimal, Decimal, Decimal]:
    movement = db.scalar(
        select(func.coalesce(func.sum(PantryTransaction.quantity_delta), 0)).where(
            PantryTransaction.pantry_lot_id == lot.id
        )
    )
    reserved = db.scalar(
        select(func.coalesce(func.sum(PantryReservation.quantity), 0)).where(
            PantryReservation.pantry_lot_id == lot.id
        )
    )
    on_hand = round_quantity(
        Decimal(lot.initial_quantity) + Decimal(movement or 0), lot.unit
    )
    reserved_amount = round_quantity(Decimal(reserved or 0), lot.unit)
    usable = round_quantity(on_hand - reserved_amount, lot.unit)
    return on_hand, reserved_amount, usable


def adjust_lot(db: Session, lot_id: str, delta: Decimal, reason: str) -> PantryTransaction:
    lot = db.get(PantryLot, lot_id)
    if lot is None:
        raise NotFoundError("Pantry lot")
    rounded_delta = round_quantity(delta, lot.unit)
    if rounded_delta == 0:
        raise DomainError("PANTRY_ADJUSTMENT_EMPTY", "Enter a non-zero pantry adjustment")
    on_hand, reserved, _ = balances(db, lot)
    if on_hand + rounded_delta < reserved:
        raise DomainError(
            "PANTRY_QUANTITY_CONFLICT",
            "This adjustment would reduce stock below the quantity reserved by accepted plans",
        )
    transaction = PantryTransaction(
        pantry_lot_id=lot.id, quantity_delta=rounded_delta, reason=reason
    )
    db.add(transaction)
    lot.version += 1
    db.flush()
    return transaction


def reserve_plan_batches(db: Session, household_id: str, batches: list[MealBatch]) -> None:
    """Reserve available matching stock for accepted meal batches, FEFO.

    A shortage is not an error: the shopping-list pipeline buys the remainder.
    Reservations only cover normalized foods in a compatible unit; ambiguous
    ingredients must have been resolved before a recipe becomes planner-ready.
    """

    for batch in batches:
        version = db.get(RecipeVersion, batch.recipe_version_id)
        if version is None or not version.yield_servings:
            raise DomainError("INVALID_BATCH", "A meal batch references an invalid recipe yield")
        scale = Decimal(batch.servings) / Decimal(version.yield_servings)
        requirements: dict[tuple[str, str], Decimal] = {}
        for ingredient in version.ingredients:
            if not ingredient.included or not ingredient.food_record_id:
                continue
            if ingredient.quantity_grams is not None:
                required, unit = Decimal(ingredient.quantity_grams) * scale, "g"
            elif ingredient.quantity is not None and ingredient.unit:
                required = Decimal(ingredient.quantity) * scale
                unit = canonical_quantity_unit(ingredient.unit)
            else:
                continue
            key = (ingredient.food_record_id, unit)
            requirements[key] = requirements.get(key, Decimal("0")) + required

        existing_reservations = db.scalars(
            select(PantryReservation).where(PantryReservation.meal_batch_id == batch.id)
        ).all()
        existing_by_lot = {reservation.pantry_lot_id: reservation for reservation in existing_reservations}
        for (food_record_id, unit), unrounded_required in requirements.items():
            required = round_quantity(unrounded_required, unit)
            existing = sum(
                (
                    Decimal(reservation.quantity)
                    for reservation in existing_reservations
                    if (reserved_lot := db.get(PantryLot, reservation.pantry_lot_id)) is not None
                    and reserved_lot.food_record_id == food_record_id
                    and canonical_quantity_unit(reservation.unit) == unit
                ),
                Decimal("0"),
            )
            remaining = max(required - existing, Decimal("0"))
            if remaining <= 0:
                continue
            lots = db.scalars(
                select(PantryLot)
                .where(
                    PantryLot.household_id == household_id,
                    PantryLot.food_record_id == food_record_id,
                    PantryLot.unit == unit,
                )
                .order_by(PantryLot.expires_on.asc().nullslast(), PantryLot.created_at)
            ).all()
            for lot in lots:
                _, _, usable = balances(db, lot)
                quantity = min(max(usable, Decimal("0")), remaining)
                if quantity > 0:
                    reservation = existing_by_lot.get(lot.id)
                    if reservation is not None:
                        reservation.quantity = round_quantity(
                            Decimal(reservation.quantity) + quantity, unit
                        )
                    else:
                        reservation = PantryReservation(
                            pantry_lot_id=lot.id,
                            meal_batch_id=batch.id,
                            quantity=round_quantity(quantity, unit),
                            unit=unit,
                        )
                        db.add(reservation)
                        existing_by_lot[lot.id] = reservation
                    remaining -= quantity
                if remaining <= 0:
                    break
    db.flush()
