from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import AuthContext, get_auth_context, require_csrf
from ..config import get_settings
from ..data_import.models import NormalizedFood
from ..db import get_db
from ..errors import DomainError
from ..models import SavedFood
from ..schemas import (
    FoodLookupOut,
    FoodLookupSearch,
    FoodLookupSearchOut,
    SavedFoodCreate,
    SavedFoodOut,
    SavedFoodUpdate,
)
from ..services.open_food_facts import (
    OpenFoodFactsNotFound,
    OpenFoodFactsRateLimited,
    OpenFoodFactsUnavailable,
    lookup_product,
    nutrient_map,
    search_products,
)
from ..services.saved_foods import (
    accessible_food_record,
    assert_version,
    create_manual_record,
    get_saved_food,
    persist_open_food_facts,
    saved_food_out,
    sync_planner_food,
)

router = APIRouter(tags=["ingredient library"])


def _metadata_decimal(metadata: dict, key: str) -> Decimal | None:
    value = metadata.get(key)
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _lookup_out(food: NormalizedFood) -> FoodLookupOut:
    metadata = food.metadata if isinstance(food.metadata, dict) else {}
    nutrients = nutrient_map(food)
    warnings: list[str] = []
    if any(value is None for value in nutrients.values()):
        warnings.append("This result is missing calories or one or more macros.")
    if metadata.get("basis_inferred"):
        warnings.append("Confirm whether the label values are per 100g or per 100ml.")
    return FoodLookupOut(
        provider=food.provider,
        provider_record_id=food.provider_record_id,
        name=food.name,
        brand=str(metadata.get("brands") or "") or None,
        barcode=food.provider_record_id,
        basis_amount=food.basis_amount,
        basis_unit=food.basis_unit,
        nutrients=nutrients,
        complete=all(value is not None for value in nutrients.values()),
        package_amount=_metadata_decimal(metadata, "package_amount"),
        package_unit=metadata.get("package_unit"),
        package_description=str(metadata.get("quantity") or "") or None,
        serving_amount=_metadata_decimal(metadata, "serving_amount"),
        serving_unit=metadata.get("serving_unit"),
        serving_description=str(metadata.get("serving_size") or "") or None,
        source_url=metadata.get("source_url"),
        image_url=metadata.get("image_url"),
        attribution=metadata.get("attribution"),
        warnings=warnings,
    )


def _off_settings():
    settings = get_settings()
    if not settings.open_food_facts_enabled:
        raise DomainError(
            "OPEN_FOOD_FACTS_DISABLED",
            "Open Food Facts lookups are disabled on this server",
            503,
        )
    return settings


def _lookup_barcode(barcode: str) -> NormalizedFood:
    settings = _off_settings()
    try:
        return lookup_product(
            barcode,
            user_agent=settings.open_food_facts_user_agent,
            timeout_seconds=settings.open_food_facts_timeout_seconds,
        )
    except ValueError as exc:
        raise DomainError("INVALID_BARCODE", str(exc), 422) from exc
    except OpenFoodFactsNotFound as exc:
        raise DomainError("PRODUCT_NOT_FOUND", str(exc), 404) from exc
    except OpenFoodFactsRateLimited as exc:
        raise DomainError("OPEN_FOOD_FACTS_RATE_LIMITED", str(exc), 429) from exc
    except OpenFoodFactsUnavailable as exc:
        raise DomainError("OPEN_FOOD_FACTS_UNAVAILABLE", str(exc), 503) from exc


@router.get("/food-lookups/barcode/{barcode}", response_model=FoodLookupOut)
def barcode_lookup(
    barcode: str,
    _: AuthContext = Depends(get_auth_context),
):
    return _lookup_out(_lookup_barcode(barcode))


@router.post("/food-lookups/search", response_model=FoodLookupSearchOut)
def packaged_food_search(
    payload: FoodLookupSearch,
    _: AuthContext = Depends(get_auth_context),
):
    settings = _off_settings()
    try:
        result = search_products(
            payload.query,
            page=payload.page,
            user_agent=settings.open_food_facts_user_agent,
            timeout_seconds=settings.open_food_facts_timeout_seconds,
        )
    except ValueError as exc:
        raise DomainError("INVALID_FOOD_SEARCH", str(exc), 422) from exc
    except OpenFoodFactsRateLimited:
        return FoodLookupSearchOut(
            items=[],
            page=payload.page,
            remote_error="Open Food Facts is rate limited. Try again in a minute.",
        )
    except OpenFoodFactsUnavailable:
        return FoodLookupSearchOut(
            items=[],
            page=payload.page,
            remote_error="Open Food Facts search is temporarily unavailable. You can still add the food manually.",
        )
    return FoodLookupSearchOut(
        items=[_lookup_out(food) for food in result.foods],
        page=result.page,
        has_more=result.has_more,
    )


@router.get("/saved-foods", response_model=dict)
def list_saved_foods(
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    conditions = [
        SavedFood.household_id == context.user.household_id,
        SavedFood.archived_at.is_(None),
    ]
    if q.strip():
        conditions.append(func.lower(SavedFood.display_name).contains(q.strip().casefold()))
    total = db.scalar(select(func.count(SavedFood.id)).where(*conditions)) or 0
    rows = db.scalars(
        select(SavedFood)
        .where(*conditions)
        .order_by(SavedFood.display_name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [saved_food_out(db, saved) for saved in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.post("/saved-foods", response_model=SavedFoodOut, status_code=201)
def create_saved_food(
    payload: SavedFoodCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    if payload.source_type == "manual":
        record = create_manual_record(
            db,
            context.user.household_id,
            name=payload.display_name or "Custom ingredient",
            basis_amount=payload.basis_amount,
            basis_unit=payload.basis_unit,
            nutrients=payload.nutrients,
        )
    elif payload.source_type == "open_food_facts":
        record = persist_open_food_facts(db, _lookup_barcode(payload.barcode or ""))
    else:
        record = accessible_food_record(
            db, payload.food_record_id or "", context.user.household_id
        )

    existing = db.scalar(
        select(SavedFood).where(
            SavedFood.household_id == context.user.household_id,
            SavedFood.food_record_id == record.id,
        )
    )
    if existing is not None and existing.archived_at is None:
        raise DomainError(
            "INGREDIENT_ALREADY_SAVED",
            "That ingredient is already in your household library",
            409,
        )

    metadata = record.metadata_json if isinstance(record.metadata_json, dict) else {}
    serving_amount = payload.serving_amount
    serving_unit = payload.serving_unit
    if serving_amount is None:
        serving_amount = _metadata_decimal(metadata, "serving_amount")
        serving_unit = metadata.get("serving_unit") if serving_amount is not None else None
    if existing is None:
        saved = SavedFood(
            household_id=context.user.household_id,
            food_record_id=record.id,
            display_name=(payload.display_name or record.name).strip(),
            serving_amount=serving_amount,
            serving_unit=serving_unit,
            planner_enabled=payload.planner_enabled,
        )
        db.add(saved)
    else:
        saved = existing
        saved.archived_at = None
        saved.display_name = (payload.display_name or record.name).strip()
        saved.serving_amount = serving_amount
        saved.serving_unit = serving_unit
        saved.planner_enabled = payload.planner_enabled
        saved.version += 1
    db.flush()
    sync_planner_food(
        db,
        saved,
        meal_types=[meal_type.value for meal_type in payload.meal_types],
    )
    db.commit()
    db.refresh(saved)
    return saved_food_out(db, saved)


@router.patch("/saved-foods/{saved_food_id}", response_model=SavedFoodOut)
def update_saved_food(
    saved_food_id: str,
    payload: SavedFoodUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    saved = get_saved_food(db, saved_food_id, context.user.household_id)
    assert_version(saved, payload.expected_version)
    record = accessible_food_record(db, saved.food_record_id, context.user.household_id)
    if payload.nutrients is not None:
        record = create_manual_record(
            db,
            context.user.household_id,
            name=payload.display_name,
            basis_amount=payload.basis_amount or record.basis_amount,
            basis_unit=payload.basis_unit or record.basis_unit,
            nutrients=payload.nutrients,
            source_record=record,
        )
        saved.food_record_id = record.id
    saved.display_name = payload.display_name.strip()
    saved.serving_amount = payload.serving_amount
    saved.serving_unit = payload.serving_unit
    saved.planner_enabled = payload.planner_enabled
    saved.version += 1
    sync_planner_food(
        db,
        saved,
        meal_types=[meal_type.value for meal_type in payload.meal_types],
    )
    db.commit()
    db.refresh(saved)
    return saved_food_out(db, saved)


@router.delete("/saved-foods/{saved_food_id}", status_code=204)
def archive_saved_food(
    saved_food_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    saved = get_saved_food(db, saved_food_id, context.user.household_id)
    saved.archived_at = datetime.now(timezone.utc)
    saved.planner_enabled = False
    saved.version += 1
    sync_planner_food(db, saved, meal_types=[])
    db.commit()
