from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import DomainError, NotFoundError
from ..models import (
    FoodRecord,
    Household,
    MealBatch,
    PantryLot,
    PantryReservation,
    PantryTransaction,
    RecipeVersion,
)
from .measurement_conversion import convert_quantity_to_unit
from .quantities import canonical_quantity_unit, round_quantity


def lock_household(db: Session, household_id: str) -> Household:
    """Acquire the household coordination lock used by inventory workflows.

    Inventory, reservations, and the active shopping list are household-wide
    state.  Locking this stable parent row before reading any dependent row
    gives PostgreSQL a deterministic lock order and serialises operations that
    otherwise would each lock a different pantry/list row first.  SQLite
    simply ignores ``FOR UPDATE`` while keeping the same transaction shape in
    tests.
    """

    household = db.scalar(
        select(Household)
        .where(Household.id == household_id)
        .with_for_update()
    )
    if household is None:
        raise NotFoundError("Household")
    return household


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


def adjust_lot(
    db: Session,
    lot_id: str,
    delta: Decimal,
    reason: str,
    *,
    reference_type: str | None = None,
    reference_id: str | None = None,
) -> PantryTransaction:
    # Service callers outside the HTTP routes (recipe synchronisation and
    # maintenance jobs) must follow the same lock order as the routes.  The
    # first lookup is only used to discover the household; the locked lookup
    # below is the row whose balance will be changed.
    lot = db.get(PantryLot, lot_id)
    if lot is None:
        raise NotFoundError("Pantry lot")
    lock_household(db, lot.household_id)
    lot = db.scalar(
        select(PantryLot).where(PantryLot.id == lot_id).with_for_update()
    )
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
        pantry_lot_id=lot.id,
        quantity_delta=rounded_delta,
        reason=reason,
        reference_type=reference_type,
        reference_id=reference_id,
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

    # Flush before any balance query.  The application intentionally uses
    # autoflush=False, so a reservation created for an earlier batch would
    # otherwise be invisible to the next batch and the same lot could be
    # over-reserved.
    lock_household(db, household_id)
    db.flush()

    batch_ids = sorted({batch.id for batch in batches})
    if batch_ids:
        locked_batches = db.scalars(
            select(MealBatch)
            .where(MealBatch.id.in_(batch_ids))
            .order_by(MealBatch.id)
            .with_for_update()
        ).all()
        batches_by_id = {batch.id: batch for batch in locked_batches}
        # Keep the caller's order because requirements from the same plan are
        # deterministic, while the dependent row locks above are ordered by
        # primary key for all concurrent callers.
        batches = [batches_by_id.get(batch.id, batch) for batch in batches]

    # Lock every household lot once, in id order, before FEFO allocation.  A
    # later query can sort this in expiry order without changing lock order.
    locked_lots = db.scalars(
        select(PantryLot)
        .where(PantryLot.household_id == household_id)
        .order_by(PantryLot.id)
        .with_for_update()
    ).all()

    for batch in batches:
        # Once food has been cooked its reservation has either been consumed
        # or is historical.  Re-acceptance, purchase intake, and pantry-match
        # refreshes must never reserve it again.
        if batch.cooked_at is not None:
            continue
        version = db.get(RecipeVersion, batch.recipe_version_id)
        if version is None or not version.yield_servings:
            raise DomainError("INVALID_BATCH", "A meal batch references an invalid recipe yield")
        scale = Decimal(batch.servings) / Decimal(version.yield_servings)
        requirements: dict[tuple[str, str], Decimal] = {}
        for ingredient in version.ingredients:
            if not ingredient.included or not ingredient.food_record_id:
                continue
            if ingredient.quantity is not None and ingredient.unit:
                required = Decimal(ingredient.quantity) * scale
                unit = canonical_quantity_unit(ingredient.unit)
            elif ingredient.quantity_grams is not None:
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
            food = db.get(FoodRecord, food_record_id)
            density = Decimal(food.density_g_per_ml) if food and food.density_g_per_ml is not None else None
            existing = sum(
                (
                    converted
                    for reservation in existing_reservations
                    if (reserved_lot := db.get(PantryLot, reservation.pantry_lot_id)) is not None
                    and reserved_lot.food_record_id == food_record_id
                    and (converted := convert_quantity_to_unit(
                        Decimal(reservation.quantity), reservation.unit, unit, density
                    )) is not None
                ),
                Decimal("0"),
            )
            remaining = max(required - existing, Decimal("0"))
            if remaining <= 0:
                continue
            lots = sorted(
                (
                    lot
                    for lot in locked_lots
                    if lot.food_record_id == food_record_id
                ),
                key=lambda lot: (
                    lot.expires_on is None,
                    lot.expires_on,
                    lot.created_at,
                    lot.id,
                ),
            )
            for lot in lots:
                # Reservation rows added or updated earlier in this function
                # are pending in this session.  Flush before reading balances
                # so the next batch sees them even with autoflush disabled.
                db.flush()
                _, _, usable = balances(db, lot)
                available = convert_quantity_to_unit(usable, lot.unit, unit, density)
                if available is None:
                    continue
                quantity_in_required_unit = min(max(available, Decimal("0")), remaining)
                quantity_in_lot_unit = convert_quantity_to_unit(
                    quantity_in_required_unit, unit, lot.unit, density
                )
                if quantity_in_lot_unit is not None and quantity_in_lot_unit > 0:
                    quantity_in_lot_unit = min(usable, round_quantity(quantity_in_lot_unit, lot.unit))
                    reservation = existing_by_lot.get(lot.id)
                    if reservation is not None:
                        reservation.quantity = round_quantity(
                            Decimal(reservation.quantity) + quantity_in_lot_unit, lot.unit
                        )
                    else:
                        reservation = PantryReservation(
                            pantry_lot_id=lot.id,
                            meal_batch_id=batch.id,
                            quantity=quantity_in_lot_unit,
                            unit=canonical_quantity_unit(lot.unit),
                        )
                        db.add(reservation)
                        existing_by_lot[lot.id] = reservation
                    reserved_in_required_unit = convert_quantity_to_unit(
                        quantity_in_lot_unit, lot.unit, unit, density
                    )
                    remaining -= reserved_in_required_unit or Decimal("0")
                    db.flush()
                if remaining <= 0:
                    break
    db.flush()
