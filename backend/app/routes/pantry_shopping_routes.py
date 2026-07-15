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
    PantryLotCreate,
    PantryLotOut,
    ShoppingBuildRequest,
    ShoppingItemCreate,
    ShoppingItemNameUpdate,
    ShoppingItemOut,
    ShoppingItemPatch,
    ShoppingListOut,
)
from ..services.pantry import adjust_lot, balances, reserve_plan_batches
from ..services.ingredient_names import ingredient_name_keys, remember_ingredient_name
from ..services.shopping import build_shopping_list
from ..services.regional_ingredients import convert_ingredient_text

router = APIRouter(tags=["pantry and shopping"])


def _pantry_out(db: Session, lot: PantryLot, ingredient_locale: str = "uk") -> PantryLotOut:
    on_hand, reserved, usable = balances(db, lot)
    data = {column.name: getattr(lot, column.name) for column in lot.__table__.columns}
    data["display_name"] = convert_ingredient_text(db, data["display_name"], ingredient_locale)
    return PantryLotOut(
        **data,
        on_hand_quantity=on_hand,
        reserved_quantity=reserved,
        usable_quantity=usable,
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


@router.post("/pantry-items", response_model=PantryLotOut, status_code=201)
def create_pantry_lot(
    payload: PantryLotCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    lot = PantryLot(
        household_id=context.user.household_id,
        display_name=payload.display_name,
        initial_quantity=payload.quantity,
        unit=payload.unit,
        food_record_id=payload.food_record_id,
        expires_on=payload.expires_on,
        always_have=payload.always_have,
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


def _shopping_out(db: Session, shopping_list: ShoppingList, ingredient_locale: str = "uk") -> ShoppingListOut:
    items = db.scalars(
        select(ShoppingItem)
        .where(ShoppingItem.shopping_list_id == shopping_list.id)
        .order_by(ShoppingItem.category, ShoppingItem.display_name)
    ).all()
    return ShoppingListOut(
        **{column.name: getattr(shopping_list, column.name) for column in shopping_list.__table__.columns},
        items=[
            {
                **{column.name: getattr(item, column.name) for column in item.__table__.columns},
                "display_name": convert_ingredient_text(db, item.display_name, ingredient_locale),
            }
            for item in items
        ],
    )


def _shopping_item_out(
    db: Session,
    item: ShoppingItem,
    ingredient_locale: str = "uk",
) -> ShoppingItemOut:
    data = {column.name: getattr(item, column.name) for column in item.__table__.columns}
    data["display_name"] = convert_ingredient_text(
        db, item.display_name, ingredient_locale
    )
    return ShoppingItemOut(**data)


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
    item = ShoppingItem(
        shopping_list_id=shopping_list.id,
        display_name=payload.display_name,
        exact_quantity=payload.exact_quantity,
        purchase_quantity=payload.purchase_quantity,
        unit=payload.unit,
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
    for field in ("checked", "purchase_quantity", "category"):
        value = getattr(payload, field)
        if value is not None:
            setattr(item, field, value)
    item.version += 1
    shopping_list.version += 1
    db.commit()
    db.refresh(item)
    return _shopping_item_out(db, item, context.user.ingredient_locale)


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
        lot = PantryLot(
            household_id=context.user.household_id,
            food_record_id=item.food_record_id,
            display_name=item.display_name,
            initial_quantity=item.purchase_quantity,
            unit=item.unit,
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
