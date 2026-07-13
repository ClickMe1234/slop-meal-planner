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
    ShoppingItemOut,
    ShoppingItemPatch,
    ShoppingListOut,
)
from ..services.pantry import adjust_lot, balances, reserve_plan_batches
from ..services.shopping import build_shopping_list

router = APIRouter(tags=["pantry and shopping"])


def _pantry_out(db: Session, lot: PantryLot) -> PantryLotOut:
    on_hand, reserved, usable = balances(db, lot)
    return PantryLotOut(
        **{column.name: getattr(lot, column.name) for column in lot.__table__.columns},
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
    return [_pantry_out(db, lot) for lot in lots]


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
    return _pantry_out(db, lot)


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
    return _pantry_out(db, lot)


def _shopping_out(db: Session, shopping_list: ShoppingList) -> ShoppingListOut:
    items = db.scalars(
        select(ShoppingItem)
        .where(ShoppingItem.shopping_list_id == shopping_list.id)
        .order_by(ShoppingItem.category, ShoppingItem.display_name)
    ).all()
    return ShoppingListOut(
        **{column.name: getattr(shopping_list, column.name) for column in shopping_list.__table__.columns},
        items=items,
    )


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
    return _shopping_out(db, shopping_list)


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
    return _shopping_out(db, shopping_list)


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
    return item


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
    return item


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
    return [_pantry_out(db, lot) for lot in lots]
