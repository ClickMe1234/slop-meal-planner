from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import AuthContext, get_auth_context, require_csrf
from ..db import get_db
from ..errors import ConflictError, DomainError, NotFoundError
from ..models import Household, MealBatch, MealPlan, PantryLot, PlanStatus, ShoppingItem, ShoppingList
from ..schemas import (
    PantryAdjustment,
    PantryBatchDeleteOut,
    PantryBatchDeleteRequest,
    PantryLotCreate,
    PantryLotOut,
    PantryLotPatch,
    PantryMatchConfirmation,
    PantryMatchSuggestion,
    ShoppingBuildRequest,
    ShoppingItemCreate,
    ShoppingItemNameUpdate,
    ShoppingItemOut,
    ShoppingItemPatch,
    ShoppingListOut,
    ShoppingPantryMatchOut,
    ShoppingPantryMatchRequest,
    ShoppingPantryReviewOut,
    ShoppingPantryReviewRequest,
)
from ..services.pantry import adjust_lot, balances, reserve_plan_batches
from ..services.pantry_matching import pantry_match_candidates, pantry_name_similarity
from ..services.ingredient_names import ingredient_name_keys, remember_ingredient_name
from ..services.quantities import (
    canonical_quantity_unit,
    format_quantity,
    round_purchase_quantity,
    round_quantity,
)
from ..services.shopping import build_shopping_list
from ..services.regional_ingredients import convert_ingredient_text
from ..services.measurement_conversion import (
    available_display_units,
    convert_quantity_to_unit,
    measurement_dimension,
)

router = APIRouter(tags=["pantry and shopping"])


def _pantry_out(db: Session, lot: PantryLot, ingredient_locale: str = "uk") -> PantryLotOut:
    on_hand, reserved, usable = balances(db, lot)
    data = {column.name: getattr(lot, column.name) for column in lot.__table__.columns}
    data["display_name"] = convert_ingredient_text(db, data["display_name"], ingredient_locale)
    data["unit"] = canonical_quantity_unit(lot.unit)
    data["initial_quantity"] = round_quantity(lot.initial_quantity, data["unit"])
    return PantryLotOut(
        **data,
        on_hand_quantity=on_hand,
        reserved_quantity=reserved,
        usable_quantity=usable,
        initial_quantity_display=format_quantity(data["initial_quantity"], data["unit"]),
        on_hand_quantity_display=format_quantity(on_hand, data["unit"]),
        reserved_quantity_display=format_quantity(reserved, data["unit"]),
        usable_quantity_display=format_quantity(usable, data["unit"]),
    )


@router.get("/pantry-items", response_model=list[PantryLotOut])
def list_pantry(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
):
    lots = db.scalars(
        select(PantryLot)
        .where(PantryLot.household_id == context.user.household_id)
        .order_by(PantryLot.expires_on.asc().nullslast(), PantryLot.display_name)
    ).all()
    return [_pantry_out(db, lot, context.user.ingredient_locale) for lot in lots]


@router.get("/pantry-match-suggestions", response_model=list[PantryMatchSuggestion])
def list_pantry_match_suggestions(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
):
    lots = db.scalars(
        select(PantryLot).where(
            PantryLot.household_id == context.user.household_id,
            PantryLot.food_record_id.is_(None),
        )
    ).all()
    suggestions = []
    for lot in lots:
        candidates = pantry_match_candidates(
            db,
            context.user.household_id,
            lot,
            context.user.ingredient_locale,
        )
        if candidates:
            suggestions.append(
                PantryMatchSuggestion(pantry_lot_id=lot.id, candidates=candidates)
            )
    return suggestions


@router.post("/pantry-items", response_model=PantryLotOut, status_code=201)
def create_pantry_lot(
    payload: PantryLotCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    unit = canonical_quantity_unit(payload.unit)
    lot = PantryLot(
        household_id=context.user.household_id,
        display_name=payload.display_name,
        initial_quantity=round_quantity(payload.quantity, unit),
        unit=unit,
        food_record_id=payload.food_record_id,
        expires_on=payload.expires_on,
        always_have=payload.always_have,
        use_soon=payload.use_soon,
    )
    db.add(lot)
    db.commit()
    db.refresh(lot)
    return _pantry_out(db, lot, context.user.ingredient_locale)


@router.post("/pantry-items/{lot_id}/adjust", response_model=PantryLotOut)
def adjust_pantry_lot(
    lot_id: str,
    payload: PantryAdjustment,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    lot = db.get(PantryLot, lot_id)
    if lot is None or lot.household_id != context.user.household_id:
        raise NotFoundError("Pantry lot")
    adjust_lot(db, lot.id, payload.quantity_delta, payload.reason)
    db.commit()
    db.refresh(lot)
    return _pantry_out(db, lot, context.user.ingredient_locale)


@router.patch("/pantry-items/{lot_id}", response_model=PantryLotOut)
def patch_pantry_lot(
    lot_id: str,
    payload: PantryLotPatch,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    lot = db.scalar(select(PantryLot).where(PantryLot.id == lot_id).with_for_update())
    if lot is None or lot.household_id != context.user.household_id:
        raise NotFoundError("Pantry lot")
    if lot.version != payload.expected_version:
        raise ConflictError()

    on_hand, _, _ = balances(db, lot)
    desired_quantity = round_quantity(payload.quantity, lot.unit)
    delta = desired_quantity - on_hand
    changed_name = lot.display_name != payload.display_name
    changed_use_soon = payload.use_soon is not None and lot.use_soon != payload.use_soon
    if changed_name:
        lot.display_name = payload.display_name
    if payload.use_soon is not None:
        lot.use_soon = payload.use_soon
    if delta:
        adjust_lot(db, lot.id, delta, "pantry_item_edited")
    elif changed_name or changed_use_soon:
        lot.version += 1
    db.commit()
    db.refresh(lot)
    return _pantry_out(db, lot, context.user.ingredient_locale)


@router.put("/pantry-items/{lot_id}/food-match", response_model=PantryLotOut)
def confirm_pantry_food_match(
    lot_id: str,
    payload: PantryMatchConfirmation,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    lot = db.scalar(select(PantryLot).where(PantryLot.id == lot_id).with_for_update())
    if lot is None or lot.household_id != context.user.household_id:
        raise NotFoundError("Pantry lot")
    if lot.version != payload.expected_version:
        raise ConflictError()
    candidates = pantry_match_candidates(
        db,
        context.user.household_id,
        lot,
        context.user.ingredient_locale,
    )
    if payload.food_record_id not in {
        str(candidate["food_record_id"]) for candidate in candidates
    }:
        raise DomainError(
            "PANTRY_MATCH_UNAVAILABLE",
            "That ingredient is not a current match from this household's saved recipes",
        )

    lot.food_record_id = payload.food_record_id
    lot.version += 1
    accepted_plans = db.scalars(
        select(MealPlan).where(
            MealPlan.household_id == context.user.household_id,
            MealPlan.status == PlanStatus.ACCEPTED.value,
        )
    ).all()
    for plan in accepted_plans:
        batches = db.scalars(
            select(MealBatch).where(MealBatch.meal_plan_id == plan.id)
        ).all()
        reserve_plan_batches(db, context.user.household_id, list(batches))
        shopping_lists = db.scalars(
            select(ShoppingList).where(
                ShoppingList.meal_plan_id == plan.id,
                ShoppingList.active.is_(True),
            )
        ).all()
        for shopping_list in shopping_lists:
            shopping_list.rebuild_recommended = True
            shopping_list.version += 1
    db.commit()
    db.refresh(lot)
    return _pantry_out(db, lot, context.user.ingredient_locale)


@router.delete("/pantry-items/{lot_id}", status_code=204)
def delete_pantry_lot(
    lot_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    lot = db.scalar(select(PantryLot).where(PantryLot.id == lot_id).with_for_update())
    if lot is None or lot.household_id != context.user.household_id:
        raise NotFoundError("Pantry lot")
    _, reserved, _ = balances(db, lot)
    if reserved > 0:
        raise DomainError(
            "PANTRY_ITEM_RESERVED",
            "This item is reserved by an accepted plan and cannot be deleted",
        )
    db.delete(lot)
    db.commit()


@router.post("/pantry-items/batch-delete", response_model=PantryBatchDeleteOut)
def batch_delete_pantry_lots(
    payload: PantryBatchDeleteRequest,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    requested_ids = list(dict.fromkeys(payload.item_ids))
    lots = db.scalars(
        select(PantryLot)
        .where(
            PantryLot.household_id == context.user.household_id,
            PantryLot.id.in_(requested_ids),
        )
        .with_for_update()
    ).all()
    lots_by_id = {lot.id: lot for lot in lots}
    deleted_ids: list[str] = []
    blocked: list[dict[str, str]] = []
    for lot_id in requested_ids:
        lot = lots_by_id.get(lot_id)
        if lot is None:
            blocked.append(
                {"id": lot_id, "display_name": "Pantry item", "reason": "not_found"}
            )
            continue
        _, reserved, _ = balances(db, lot)
        if reserved > 0:
            blocked.append(
                {
                    "id": lot.id,
                    "display_name": lot.display_name,
                    "reason": "reserved_by_plan",
                }
            )
            continue
        db.delete(lot)
        deleted_ids.append(lot.id)
    db.commit()
    return PantryBatchDeleteOut(deleted_ids=deleted_ids, blocked=blocked)


def _shopping_out(db: Session, shopping_list: ShoppingList, ingredient_locale: str = "uk") -> ShoppingListOut:
    items = db.scalars(
        select(ShoppingItem)
        .where(ShoppingItem.shopping_list_id == shopping_list.id)
        .order_by(ShoppingItem.category, ShoppingItem.display_name)
    ).all()
    return ShoppingListOut(
        **{column.name: getattr(shopping_list, column.name) for column in shopping_list.__table__.columns},
        items=[_shopping_item_data(db, item, ingredient_locale) for item in items],
    )


def _shopping_item_data(
    db: Session,
    item: ShoppingItem,
    ingredient_locale: str,
) -> dict[str, object]:
    data = {column.name: getattr(item, column.name) for column in item.__table__.columns}
    storage_unit = canonical_quantity_unit(item.unit)
    density = Decimal(item.density_g_per_ml) if item.density_g_per_ml is not None else None
    units = available_display_units(storage_unit, density)
    selected_unit = canonical_quantity_unit(item.display_unit or storage_unit)
    if selected_unit not in units:
        selected_unit = units[0]
    options: list[dict[str, object]] = []
    for unit in units:
        converted_exact = convert_quantity_to_unit(
            Decimal(item.exact_quantity), storage_unit, unit, density
        )
        converted_purchase = convert_quantity_to_unit(
            Decimal(item.purchase_quantity), storage_unit, unit, density
        )
        if converted_exact is None or converted_purchase is None:
            continue
        exact = round_quantity(converted_exact, unit)
        purchase = max(round_purchase_quantity(converted_purchase, unit), exact)
        options.append({
            "unit": unit,
            "exact_quantity": exact,
            "purchase_quantity": purchase,
            "exact_quantity_display": format_quantity(exact, unit),
            "purchase_quantity_display": format_quantity(purchase, unit),
            "approximate": measurement_dimension(storage_unit) != measurement_dimension(unit),
        })
    selected = next(option for option in options if option["unit"] == selected_unit)
    conflicts = []
    for conflict in item.pantry_unit_conflicts or []:
        conflict_unit = canonical_quantity_unit(str(conflict["unit"]))
        conflict_quantity = round_quantity(
            Decimal(str(conflict["usable_quantity"])), conflict_unit
        )
        conflicts.append(
            {
                **conflict,
                "display_name": convert_ingredient_text(
                    db, str(conflict["display_name"]), ingredient_locale
                ),
                "usable_quantity": conflict_quantity,
                "unit": conflict_unit,
                "usable_quantity_display": format_quantity(
                    conflict_quantity, conflict_unit
                ),
            }
        )
    match_suggestions = _shopping_pantry_match_suggestions(db, item)
    data.update(
        display_name=convert_ingredient_text(db, item.display_name, ingredient_locale),
        exact_quantity=selected["exact_quantity"],
        purchase_quantity=selected["purchase_quantity"],
        exact_quantity_display=selected["exact_quantity_display"],
        purchase_quantity_display=selected["purchase_quantity_display"],
        unit=selected_unit,
        available_units=list(units),
        quantity_options=options,
        pantry_unit_conflicts=conflicts,
        pantry_match_suggestions=match_suggestions,
    )
    return data


def _shopping_source_keys(db: Session, item: ShoppingItem) -> set[str]:
    return set(item.source_name_keys or ingredient_name_keys(db, item.display_name))


def _shopping_pantry_match_suggestions(
    db: Session,
    item: ShoppingItem,
) -> list[dict[str, object]]:
    shopping_list = db.get(ShoppingList, item.shopping_list_id)
    if shopping_list is None:
        return []
    source_keys = _shopping_source_keys(db, item)
    conflict_lot_ids = {
        str(conflict.get("pantry_lot_id"))
        for conflict in item.pantry_unit_conflicts or []
    }
    suggestions: list[dict[str, object]] = []
    lots = db.scalars(
        select(PantryLot).where(PantryLot.household_id == shopping_list.household_id)
    ).all()
    for lot in lots:
        if lot.id in conflict_lot_ids or source_keys.intersection(
            lot.shopping_name_keys or []
        ):
            continue
        if (
            item.food_record_id
            and lot.food_record_id
            and item.food_record_id != lot.food_record_id
        ):
            continue
        _, _, usable = balances(db, lot)
        if usable <= 0:
            continue
        confidence = pantry_name_similarity(db, lot.display_name, item.display_name)
        if confidence < 0.72:
            continue
        unit = canonical_quantity_unit(lot.unit)
        suggestions.append(
            {
                "pantry_lot_id": lot.id,
                "display_name": lot.display_name,
                "usable_quantity": round_quantity(usable, unit),
                "unit": unit,
                "usable_quantity_display": format_quantity(usable, unit),
                "confidence": round(confidence, 3),
            }
        )
    return sorted(
        suggestions,
        key=lambda suggestion: (
            -float(suggestion["confidence"]),
            str(suggestion["display_name"]).casefold(),
        ),
    )[:3]


def _shopping_item_out(
    db: Session,
    item: ShoppingItem,
    ingredient_locale: str = "uk",
) -> ShoppingItemOut:
    return ShoppingItemOut(**_shopping_item_data(db, item, ingredient_locale))


@router.post("/shopping-lists/build", response_model=ShoppingListOut, status_code=201)
def build_list(
    payload: ShoppingBuildRequest,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    plan = db.scalar(
        select(MealPlan)
        .where(MealPlan.id == payload.meal_plan_id)
        .with_for_update()
    )
    if plan is None or plan.household_id != context.user.household_id:
        raise NotFoundError("Meal plan")
    db.scalar(
        select(Household).where(Household.id == plan.household_id).with_for_update()
    )
    if plan.status != PlanStatus.ACCEPTED.value:
        raise DomainError(
            "PLAN_NOT_ACCEPTED",
            "Accept the plan before building or rebuilding its shopping list",
        )
    shopping_list = build_shopping_list(
        db, context.user.household_id, payload.meal_plan_id, payload.name
    )
    db.commit()
    db.refresh(shopping_list)
    return _shopping_out(db, shopping_list, context.user.ingredient_locale)


@router.get("/shopping-lists/active", response_model=ShoppingListOut)
def active_list(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
):
    shopping_list = db.scalar(
        select(ShoppingList)
        .where(
            ShoppingList.household_id == context.user.household_id,
            ShoppingList.active.is_(True),
        )
        .order_by(ShoppingList.updated_at.desc())
    )
    if shopping_list is None:
        raise NotFoundError("Active shopping list")
    return _shopping_out(db, shopping_list, context.user.ingredient_locale)


@router.post("/shopping-lists/{list_id}/items", response_model=ShoppingItemOut, status_code=201)
def add_manual_item(
    list_id: str,
    payload: ShoppingItemCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    shopping_list = db.get(ShoppingList, list_id)
    if shopping_list is None or shopping_list.household_id != context.user.household_id:
        raise NotFoundError("Shopping list")
    unit = canonical_quantity_unit(payload.unit)
    exact = round_quantity(payload.exact_quantity, unit)
    purchase = max(round_purchase_quantity(payload.purchase_quantity, unit), exact)
    item = ShoppingItem(
        shopping_list_id=shopping_list.id,
        display_name=payload.display_name,
        exact_quantity=exact,
        purchase_quantity=purchase,
        unit=unit,
        display_unit=unit,
        category=payload.category,
        manual=True,
    )
    db.add(item)
    shopping_list.version += 1
    db.commit()
    db.refresh(item)
    return _shopping_item_out(db, item, context.user.ingredient_locale)


@router.patch("/shopping-lists/{list_id}/items/{item_id}", response_model=ShoppingItemOut)
def patch_item(
    list_id: str,
    item_id: str,
    payload: ShoppingItemPatch,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    shopping_list = db.get(ShoppingList, list_id)
    item = db.get(ShoppingItem, item_id)
    if (
        shopping_list is None
        or shopping_list.household_id != context.user.household_id
        or item is None
        or item.shopping_list_id != shopping_list.id
    ):
        raise NotFoundError("Shopping item")
    if item.version != payload.expected_version:
        raise ConflictError()
    if payload.display_unit is not None:
        requested_unit = canonical_quantity_unit(payload.display_unit)
        units = available_display_units(
            item.unit,
            Decimal(item.density_g_per_ml) if item.density_g_per_ml is not None else None,
        )
        if requested_unit not in units:
            raise DomainError(
                "SHOPPING_UNIT_UNAVAILABLE",
                f"{requested_unit} is not available for this ingredient",
            )
        item.display_unit = requested_unit
    for field in ("checked", "purchase_quantity", "category"):
        value = getattr(payload, field)
        if value is not None:
            if field == "purchase_quantity":
                exact = round_quantity(item.exact_quantity, item.unit)
                value = max(round_purchase_quantity(value, item.unit), exact)
            setattr(item, field, value)
    item.version += 1
    shopping_list.version += 1
    db.commit()
    db.refresh(item)
    return _shopping_item_out(db, item, context.user.ingredient_locale)


@router.post(
    "/shopping-lists/{list_id}/items/{item_id}/pantry-match",
    response_model=ShoppingPantryMatchOut,
)
def confirm_shopping_pantry_match(
    list_id: str,
    item_id: str,
    payload: ShoppingPantryMatchRequest,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    shopping_list = db.scalar(
        select(ShoppingList).where(ShoppingList.id == list_id).with_for_update()
    )
    item = db.scalar(
        select(ShoppingItem).where(ShoppingItem.id == item_id).with_for_update()
    )
    if (
        shopping_list is None
        or shopping_list.household_id != context.user.household_id
        or item is None
        or item.shopping_list_id != shopping_list.id
    ):
        raise NotFoundError("Shopping item")
    if item.version != payload.expected_version:
        raise ConflictError()
    suggestion = next(
        (
            value
            for value in _shopping_pantry_match_suggestions(db, item)
            if value["pantry_lot_id"] == payload.pantry_lot_id
        ),
        None,
    )
    if suggestion is None:
        raise DomainError(
            "PANTRY_MATCH_UNAVAILABLE",
            "That pantry item is no longer a suggested match for this shopping ingredient",
        )
    lot = db.scalar(
        select(PantryLot)
        .where(PantryLot.id == payload.pantry_lot_id)
        .with_for_update()
    )
    if lot is None or lot.household_id != context.user.household_id:
        raise NotFoundError("Pantry lot")

    source_keys = _shopping_source_keys(db, item)
    lot.shopping_name_keys = sorted(
        set(lot.shopping_name_keys or []).union(source_keys)
    )
    if lot.food_record_id is None and item.food_record_id is not None:
        lot.food_record_id = item.food_record_id
    lot.version += 1

    _, _, usable = balances(db, lot)
    density = (
        Decimal(item.density_g_per_ml)
        if item.density_g_per_ml is not None
        else None
    )
    converted = convert_quantity_to_unit(usable, lot.unit, item.unit, density)
    shopping_list.version += 1
    if converted is None:
        conflict = {
            "pantry_lot_id": lot.id,
            "display_name": lot.display_name,
            "usable_quantity": str(usable),
            "unit": canonical_quantity_unit(lot.unit),
            "usable_quantity_display": format_quantity(usable, lot.unit),
        }
        item.pantry_unit_conflicts = [
            *(
                value
                for value in item.pantry_unit_conflicts or []
                if value.get("pantry_lot_id") != lot.id
            ),
            conflict,
        ]
        item.version += 1
        db.commit()
        db.refresh(item)
        db.refresh(lot)
        return ShoppingPantryMatchOut(
            removed=False,
            item=_shopping_item_out(db, item, context.user.ingredient_locale),
            pantry_item=_pantry_out(db, lot, context.user.ingredient_locale),
        )

    current_exact = round_quantity(Decimal(item.exact_quantity), item.unit)
    remaining = round_quantity(
        max(current_exact - max(converted, Decimal("0")), Decimal("0")),
        item.unit,
    )
    if remaining <= 0:
        db.delete(item)
        db.commit()
        db.refresh(lot)
        return ShoppingPantryMatchOut(
            removed=True,
            pantry_item=_pantry_out(db, lot, context.user.ingredient_locale),
        )
    item.exact_quantity = remaining
    item.purchase_quantity = max(
        round_purchase_quantity(remaining, item.unit), remaining
    )
    item.version += 1
    db.commit()
    db.refresh(item)
    db.refresh(lot)
    return ShoppingPantryMatchOut(
        removed=False,
        item=_shopping_item_out(db, item, context.user.ingredient_locale),
        pantry_item=_pantry_out(db, lot, context.user.ingredient_locale),
    )


@router.post(
    "/shopping-lists/{list_id}/items/{item_id}/pantry-review",
    response_model=ShoppingPantryReviewOut,
)
def resolve_shopping_pantry_review(
    list_id: str,
    item_id: str,
    payload: ShoppingPantryReviewRequest,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    shopping_list = db.scalar(
        select(ShoppingList).where(ShoppingList.id == list_id).with_for_update()
    )
    item = db.scalar(
        select(ShoppingItem).where(ShoppingItem.id == item_id).with_for_update()
    )
    if (
        shopping_list is None
        or shopping_list.household_id != context.user.household_id
        or item is None
        or item.shopping_list_id != shopping_list.id
    ):
        raise NotFoundError("Shopping item")
    if item.version != payload.expected_version:
        raise ConflictError()
    if not item.pantry_unit_conflicts:
        raise DomainError(
            "PANTRY_REVIEW_COMPLETE",
            "This shopping item no longer has a pantry unit warning",
        )

    if payload.decision == "buy":
        item.pantry_unit_conflicts = []
        item.version += 1
        shopping_list.version += 1
        db.commit()
        db.refresh(item)
        return ShoppingPantryReviewOut(
            removed=False,
            item=_shopping_item_out(db, item, context.user.ingredient_locale),
        )

    conflict = next(
        (
            value
            for value in item.pantry_unit_conflicts
            if value.get("pantry_lot_id") == payload.pantry_lot_id
        ),
        None,
    )
    if conflict is None:
        raise DomainError(
            "PANTRY_REVIEW_LOT_UNAVAILABLE",
            "That pantry item is no longer part of this unit warning",
        )
    lot = db.scalar(
        select(PantryLot)
        .where(PantryLot.id == payload.pantry_lot_id)
        .with_for_update()
    )
    if lot is None or lot.household_id != context.user.household_id:
        raise NotFoundError("Pantry lot")

    pantry_quantity = round_quantity(Decimal(payload.pantry_quantity), lot.unit)
    _, _, usable = balances(db, lot)
    if pantry_quantity > usable:
        raise DomainError(
            "PANTRY_REVIEW_QUANTITY_UNAVAILABLE",
            f"Only {format_quantity(usable, lot.unit)} is currently available",
        )
    requirement_unit = canonical_quantity_unit(str(payload.requirement_unit))
    density = (
        Decimal(item.density_g_per_ml)
        if item.density_g_per_ml is not None
        else None
    )
    covered_in_storage_unit = convert_quantity_to_unit(
        Decimal(payload.requirement_quantity),
        requirement_unit,
        item.unit,
        density,
    )
    if covered_in_storage_unit is None:
        raise DomainError(
            "PANTRY_REVIEW_REQUIREMENT_UNIT_INVALID",
            "The covered requirement must use one of this shopping item's units",
        )
    covered = round_quantity(covered_in_storage_unit, item.unit)
    current_exact = round_quantity(Decimal(item.exact_quantity), item.unit)
    if covered > current_exact:
        raise DomainError(
            "PANTRY_REVIEW_COVERAGE_TOO_LARGE",
            f"The pantry amount cannot cover more than {format_quantity(current_exact, item.unit)}",
        )

    adjust_lot(
        db,
        lot.id,
        -pantry_quantity,
        "shopping_unit_review",
        reference_type="shopping_item",
        reference_id=item.id,
    )
    remaining = round_quantity(current_exact - covered, item.unit)
    shopping_list.version += 1
    if remaining <= 0:
        db.delete(item)
        db.commit()
        db.refresh(lot)
        return ShoppingPantryReviewOut(
            removed=True,
            pantry_item=_pantry_out(db, lot, context.user.ingredient_locale),
        )

    item.exact_quantity = remaining
    item.purchase_quantity = max(
        round_purchase_quantity(remaining, item.unit), remaining
    )
    item.pantry_unit_conflicts = [
        value
        for value in item.pantry_unit_conflicts
        if value.get("pantry_lot_id") != lot.id
    ]
    item.version += 1
    db.commit()
    db.refresh(item)
    db.refresh(lot)
    return ShoppingPantryReviewOut(
        removed=False,
        item=_shopping_item_out(db, item, context.user.ingredient_locale),
        pantry_item=_pantry_out(db, lot, context.user.ingredient_locale),
    )


@router.put(
    "/shopping-lists/{list_id}/items/{item_id}/name",
    response_model=ShoppingItemOut,
)
def update_item_name(
    list_id: str,
    item_id: str,
    payload: ShoppingItemNameUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    """Compare-and-set an item name and remember generated-item corrections."""

    shopping_list = db.scalar(
        select(ShoppingList).where(ShoppingList.id == list_id).with_for_update()
    )
    item = db.scalar(
        select(ShoppingItem).where(ShoppingItem.id == item_id).with_for_update()
    )
    if (
        shopping_list is None
        or shopping_list.household_id != context.user.household_id
        or item is None
        or item.shopping_list_id != shopping_list.id
    ):
        raise NotFoundError("Shopping item")

    desired_name = (
        convert_ingredient_text(db, payload.display_name.strip(), "uk")
        or payload.display_name.strip()
    )
    expected_name = (
        convert_ingredient_text(db, payload.expected_display_name.strip(), "uk")
        or payload.expected_display_name.strip()
    )
    current_key = " ".join(item.display_name.casefold().split())
    desired_key = " ".join(desired_name.casefold().split())
    expected_key = " ".join(expected_name.casefold().split())
    if desired_key == current_key:
        return _shopping_item_out(db, item, context.user.ingredient_locale)
    if expected_key != current_key:
        current_display_name = (
            convert_ingredient_text(
                db, item.display_name, context.user.ingredient_locale
            )
            or item.display_name
        )
        raise DomainError(
            "SHOPPING_NAME_CONFLICT",
            "This ingredient name changed elsewhere while your edit was offline.",
            409,
            actions=[{"current_display_name": current_display_name}],
        )

    if not item.manual:
        keys = list(item.source_name_keys or ingredient_name_keys(db, item.display_name))
        desired_name = remember_ingredient_name(
            db,
            context.user.household_id,
            keys,
            desired_name,
        )
        item.source_name_keys = keys
    item.display_name = desired_name
    item.version += 1
    shopping_list.version += 1
    db.commit()
    db.refresh(item)
    return _shopping_item_out(db, item, context.user.ingredient_locale)


@router.post("/shopping-lists/{list_id}/add-purchased-to-pantry", response_model=list[PantryLotOut])
def add_purchased_to_pantry(
    list_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    """Explicitly add checked shopping quantities to pantry inventory."""

    shopping_list = db.get(ShoppingList, list_id)
    if shopping_list is None or shopping_list.household_id != context.user.household_id:
        raise NotFoundError("Shopping list")
    checked = db.scalars(
        select(ShoppingItem).where(
            ShoppingItem.shopping_list_id == shopping_list.id,
            ShoppingItem.checked.is_(True),
        )
    ).all()
    if not checked:
        raise DomainError("NO_PURCHASED_ITEMS", "Tick purchased items before adding them to the pantry")
    lots: list[PantryLot] = []
    for item in checked:
        unit = canonical_quantity_unit(item.unit)
        lot = PantryLot(
            household_id=context.user.household_id,
            food_record_id=item.food_record_id,
            display_name=item.display_name,
            initial_quantity=round_quantity(item.purchase_quantity, unit),
            unit=unit,
        )
        db.add(lot)
        lots.append(lot)
        item.checked = False
        item.version += 1
    shopping_list.version += 1
    db.flush()
    if shopping_list.meal_plan_id:
        batches = db.scalars(
            select(MealBatch).where(MealBatch.meal_plan_id == shopping_list.meal_plan_id)
        ).all()
        reserve_plan_batches(db, context.user.household_id, list(batches))
    db.commit()
    for lot in lots:
        db.refresh(lot)
    return [_pantry_out(db, lot, context.user.ingredient_locale) for lot in lots]
