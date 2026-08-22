from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import AuthContext, get_auth_context, require_csrf
from ..db import get_db
from ..discovery.errors import DiscoveryError, FetchError
from ..errors import DomainError, NotFoundError
from ..models import (
    MealBatch,
    MealOccurrence,
    MealPlan,
    NutritionCalculation,
    PublisherMetadataStatus,
    Recipe,
    RecipeEligibility,
    RecipeIngredient,
    RecipeMealType,
    RecipeMethodSnapshot,
    RecipeVersion,
    new_id,
)
from ..schemas import (
    MethodDocument,
    MethodExtractRequest,
    MethodPreviewCreate,
    MethodPreviewSave,
    MethodRefreshApply,
    MethodSourceBlock,
    MethodUpdate,
    MethodViewOut,
)
from ..services.ingredient_names import ingredient_name_keys, preferred_ingredient_name
from ..services.ingredients import PARSER_VERSION, parse_ingredient
from ..services.nutrition import publisher_values
from ..services.recipe_methods import (
    METHOD_PARSER_VERSION,
    parse_method_document,
    rendered_source_blocks,
    scaled_ingredients,
    snapshot_values,
    source_blocks_from_extracted,
    source_text_from_blocks,
)
from ..services.recipe_plan_sync import sync_recipe_versions_to_current_plans
from .discovery_routes import _live_service
from .recipe_routes import _latest_version, _recipe_detail


router = APIRouter(tags=["recipe methods"])
PREVIEW_TTL_SECONDS = 30 * 60


@dataclass(slots=True)
class _MethodPreview:
    token: str
    user_id: str
    household_id: str
    expires_at: float
    extracted: Any
    ingredients: list[RecipeIngredient]
    blocks: list[dict[str, Any]]
    snapshot: RecipeMethodSnapshot
    recipe_id: str | None = None


_previews: dict[str, _MethodPreview] = {}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _prune_previews() -> None:
    now = time.monotonic()
    for token in [token for token, preview in _previews.items() if preview.expires_at <= now]:
        _previews.pop(token, None)


def _preview_for_user(token: str, context: AuthContext) -> _MethodPreview:
    _prune_previews()
    preview = _previews.get(token)
    if (
        preview is None
        or preview.user_id != context.user.id
        or preview.household_id != context.user.household_id
    ):
        raise NotFoundError("Method preview")
    return preview


def _ingredients_from_lines(
    db: Session, household_id: str, lines: tuple[str, ...]
) -> list[RecipeIngredient]:
    ingredients: list[RecipeIngredient] = []
    for position, line in enumerate(lines):
        parsed = parse_ingredient(line)
        keys = ingredient_name_keys(db, parsed.food_phrase)
        display_name, remembered = preferred_ingredient_name(
            db, household_id, keys, parsed.food_phrase
        )
        ingredients.append(
            RecipeIngredient(
                id=new_id(),
                recipe_version_id="preview",
                lineage_id=new_id(),
                position=position,
                original_text=line,
                quantity=parsed.quantity,
                unit=parsed.unit,
                quantity_grams=parsed.quantity_grams,
                food_phrase=display_name,
                parsed_food_phrase=parsed.food_phrase,
                preparation=parsed.preparation,
                parser_version=PARSER_VERSION,
                name_confidence=(
                    Decimal(str(round(parsed.name_confidence, 4)))
                    if parsed.name_confidence is not None
                    else None
                ),
                name_overridden=remembered,
                parser_name_keys=keys,
                included=not parsed.optional,
                optional=parsed.optional,
                needs_review=parsed.needs_review and not remembered,
            )
        )
    return ingredients


def _snapshot_from_preview(
    blocks: list[dict[str, Any]], ingredients: list[RecipeIngredient], user_id: str, extraction_method: str
) -> RecipeMethodSnapshot:
    return RecipeMethodSnapshot(
        id=new_id(),
        recipe_version_id="preview",
        **snapshot_values(
            blocks=blocks,
            ingredients=ingredients,
            source_kind="publisher",
            extractor_version=extraction_method,
            created_by_user_id=user_id,
        ),
    )


def _preview_view(preview: _MethodPreview, context: AuthContext, db: Session) -> MethodViewOut:
    version = RecipeVersion(
        id="preview",
        recipe_id="preview",
        version_number=0,
        title=preview.extracted.title,
        yield_servings=preview.extracted.yield_servings,
    )
    version.ingredients = preview.ingredients
    requested = preview.extracted.yield_servings
    ingredients = scaled_ingredients(
        db,
        version,
        requested_servings=requested,
        ingredient_locale=context.user.ingredient_locale,
        measurement_system=context.user.measurement_system,
    )
    return MethodViewOut(
        title=preview.extracted.title,
        publisher=preview.extracted.publisher,
        source_url=preview.extracted.canonical_url,
        preview_token=preview.token,
        method_status="needs_review",
        source_kind=preview.snapshot.source_kind,
        source_blocks=preview.snapshot.source_blocks,
        method=preview.snapshot.document,
        coverage=preview.snapshot.coverage,
        confidence=preview.snapshot.confidence,
        ingredients=ingredients,
        rendered_blocks=rendered_source_blocks(
            db, preview.snapshot, ingredients, context.user.ingredient_locale
        ),
        base_servings=preview.extracted.yield_servings,
        requested_servings=requested,
        scaling_available=preview.extracted.yield_servings is not None,
    )


async def _create_preview(
    url: str,
    context: AuthContext,
    db: Session,
    *,
    recipe_id: str | None = None,
) -> _MethodPreview:
    try:
        extracted = await _live_service().nutrition_preview(url)
    except DiscoveryError as exc:
        status = 502 if isinstance(exc, FetchError) else 422
        raise DomainError(
            exc.code,
            f"{exc}. Open the source and paste the method to continue.",
            status,
            actions=[{"kind": "open_source", "label": "Open source", "href": url}],
        ) from exc
    blocks = source_blocks_from_extracted(extracted.instruction_blocks)
    if not blocks:
        raise DomainError(
            "METHOD_NOT_FOUND",
            "No cooking method was found. Open the source and paste or write it manually.",
            422,
            actions=[{"kind": "open_source", "label": "Open source", "href": url}],
        )
    ingredients = _ingredients_from_lines(db, context.user.household_id, extracted.ingredient_lines)
    token = secrets.token_urlsafe(32)
    preview = _MethodPreview(
        token=token,
        user_id=context.user.id,
        household_id=context.user.household_id,
        expires_at=time.monotonic() + PREVIEW_TTL_SECONDS,
        extracted=extracted,
        ingredients=ingredients,
        blocks=blocks,
        snapshot=_snapshot_from_preview(blocks, ingredients, context.user.id, extracted.extraction_method),
        recipe_id=recipe_id,
    )
    _prune_previews()
    _previews[token] = preview
    return preview


def _clone_version(db: Session, previous: RecipeVersion) -> tuple[RecipeVersion, list[RecipeIngredient]]:
    next_version = RecipeVersion(
        recipe_id=previous.recipe_id,
        version_number=previous.version_number + 1,
        title=previous.title,
        yield_servings=previous.yield_servings,
        minimum_servings=previous.minimum_servings,
        serving_increment=previous.serving_increment,
        custom_instructions=previous.custom_instructions,
        source_checksum=previous.source_checksum,
        publisher_nutrition=previous.publisher_nutrition,
    )
    db.add(next_version)
    db.flush()
    ingredients: list[RecipeIngredient] = []
    for previous_ingredient in previous.ingredients:
        values = {
            column.name: getattr(previous_ingredient, column.name)
            for column in previous_ingredient.__table__.columns
            if column.name not in {"id", "recipe_version_id"}
        }
        ingredient = RecipeIngredient(recipe_version_id=next_version.id, **values)
        db.add(ingredient)
        ingredients.append(ingredient)
    calculation = db.scalar(
        select(NutritionCalculation)
        .where(NutritionCalculation.recipe_version_id == previous.id)
        .order_by(NutritionCalculation.calculated_at.desc())
    )
    if calculation is not None:
        db.add(
            NutritionCalculation(
                recipe_version_id=next_version.id,
                status=calculation.status,
                total_values=dict(calculation.total_values or {}),
                per_serving_values=dict(calculation.per_serving_values or {}),
                contributions=list(calculation.contributions or []),
                assumptions=list(calculation.assumptions or []),
                dataset_snapshot=dict(calculation.dataset_snapshot or {}),
            )
        )
    db.flush()
    return next_version, ingredients


def _validate_bindings(document: MethodDocument, ingredients: list[RecipeIngredient]) -> None:
    lineages = {ingredient.lineage_id for ingredient in ingredients}
    missing = {
        binding.ingredient_lineage_id
        for binding in document.ingredient_bindings
        if binding.ingredient_lineage_id not in lineages
    }
    if missing:
        raise DomainError(
            "METHOD_INGREDIENT_MISSING",
            "One or more method inputs refer to ingredients that are no longer in this recipe.",
            422,
        )
    fractions: dict[str, Decimal] = {}
    remainders: set[str] = set()
    for binding in document.ingredient_bindings:
        if binding.portion_mode == "fraction" and binding.portion_value is not None:
            fractions[binding.ingredient_lineage_id] = (
                fractions.get(binding.ingredient_lineage_id, Decimal("0")) + binding.portion_value
            )
        if binding.portion_mode == "remainder":
            if binding.ingredient_lineage_id in remainders:
                raise DomainError(
                    "METHOD_PORTION_CONFLICT",
                    "An ingredient can have only one remainder allocation.",
                    422,
                )
            remainders.add(binding.ingredient_lineage_id)
    if any(value > 1 for value in fractions.values()):
        raise DomainError(
            "METHOD_PORTION_CONFLICT",
            "Ingredient fraction allocations cannot exceed the recipe total.",
            422,
        )


def _method_view(
    db: Session,
    recipe: Recipe,
    version: RecipeVersion,
    snapshot: RecipeMethodSnapshot,
    context: AuthContext,
    *,
    requested_servings: Decimal | None,
    batch_context: dict[str, Any] | None = None,
    refresh_diff: dict[str, Any] | None = None,
) -> MethodViewOut:
    ingredients = scaled_ingredients(
        db,
        version,
        requested_servings=requested_servings,
        ingredient_locale=context.user.ingredient_locale,
        measurement_system=context.user.measurement_system,
    )
    return MethodViewOut(
        recipe_id=recipe.id,
        recipe_version_id=version.id,
        recipe_version_number=version.version_number,
        recipe_version=recipe.version,
        title=version.title,
        publisher=recipe.publisher,
        source_url=recipe.source_url,
        method_status=snapshot.status,
        source_kind=snapshot.source_kind,
        source_blocks=snapshot.source_blocks,
        method=snapshot.document,
        coverage=snapshot.coverage,
        confidence=snapshot.confidence,
        household_notes=snapshot.household_notes,
        ingredients=ingredients,
        rendered_blocks=rendered_source_blocks(
            db, snapshot, ingredients, context.user.ingredient_locale
        ),
        base_servings=version.yield_servings,
        requested_servings=requested_servings,
        scaling_available=version.yield_servings is not None,
        batch_context=batch_context,
        refresh_diff=refresh_diff,
    )


def _repair_custom_method_snapshot(
    db: Session,
    version: RecipeVersion,
    user_id: str,
) -> RecipeMethodSnapshot | None:
    """Recreate the method snapshot for older custom versions if needed."""

    instructions = (version.custom_instructions or "").strip()
    if not instructions or version.method_snapshot is not None:
        return version.method_snapshot
    blocks = [
        {
            "id": "block-1",
            "position": 0,
            "heading": None,
            "text": instructions,
        }
    ]
    snapshot = RecipeMethodSnapshot(
        recipe_version_id=version.id,
        **snapshot_values(
            blocks=blocks,
            ingredients=version.ingredients,
            source_kind="custom",
            extractor_version="user-authored",
            created_by_user_id=user_id,
        ),
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _recipe_for_household(db: Session, recipe_id: str, household_id: str) -> Recipe:
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.household_id != household_id or recipe.archived_at is not None:
        raise NotFoundError("Recipe")
    return recipe


def _batch_context(db: Session, batch: MealBatch) -> dict[str, Any]:
    occurrences = db.scalars(
        select(MealOccurrence)
        .where(MealOccurrence.batch_id == batch.id)
        .order_by(MealOccurrence.meal_date, MealOccurrence.meal_type)
    ).all()
    return {
        "batch_id": batch.id,
        "servings": float(batch.servings),
        "planned_cook_date": batch.planned_cook_date.isoformat(),
        "cooked_at": batch.cooked_at.isoformat() if batch.cooked_at else None,
        "occurrences": [
            {"date": item.meal_date.isoformat(), "meal_type": item.meal_type}
            for item in occurrences
        ],
    }


def _historical_method_recovery_actions(recipe_id: str, batch_id: str) -> list[dict[str, Any]]:
    return [
        {
            "kind": "recover_historical_method",
            "label": "Use current method for this batch",
            "recipe_id": recipe_id,
            "batch_id": batch_id,
            "suggestion": (
                "This copies the current saved method onto the historical batch so it can be "
                "scaled. The cooked record and batch ingredients stay unchanged."
            ),
        },
        {
            "kind": "current_method",
            "label": "Open current recipe method",
            "href": f"/recipes/{recipe_id}/method",
        },
    ]


@router.post("/recipe-discovery/method-previews", response_model=MethodViewOut)
async def create_method_preview(
    payload: MethodPreviewCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    preview = await _create_preview(payload.url, context, db)
    return _preview_view(preview, context, db)


@router.get("/recipe-discovery/method-previews/{preview_token}", response_model=MethodViewOut)
def get_method_preview(
    preview_token: str,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    return _preview_view(_preview_for_user(preview_token, context), context, db)


@router.post(
    "/recipe-discovery/method-previews/{preview_token}/save",
    response_model=dict,
    status_code=201,
)
def save_method_preview(
    preview_token: str,
    payload: MethodPreviewSave,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    preview = _preview_for_user(preview_token, context)
    existing = db.scalar(
        select(Recipe).where(
            Recipe.household_id == context.user.household_id,
            Recipe.source_url == preview.extracted.canonical_url,
            Recipe.archived_at.is_(None),
        )
    )
    if existing is not None:
        return _recipe_detail(db, existing, context.user.ingredient_locale).model_dump(mode="json")
    recipe = Recipe(
        household_id=context.user.household_id,
        title=preview.extracted.title,
        eligibility=RecipeEligibility.NEEDS_REVIEW.value,
        source_type="url",
        source_url=preview.extracted.canonical_url,
        publisher=preview.extracted.publisher,
        image_url=preview.extracted.image_url,
        publisher_metadata_status=PublisherMetadataStatus.READY.value,
        publisher_metadata_refreshed_at=datetime.now(timezone.utc),
    )
    db.add(recipe)
    db.flush()
    for meal_type in payload.meal_types:
        db.add(RecipeMealType(recipe_id=recipe.id, meal_type=meal_type.value))
    version = RecipeVersion(
        recipe_id=recipe.id,
        version_number=1,
        title=recipe.title,
        yield_servings=preview.extracted.yield_servings,
        publisher_nutrition=(
            _json_safe(asdict(preview.extracted.publisher_nutrition))
            if preview.extracted.publisher_nutrition
            else None
        ),
    )
    db.add(version)
    db.flush()
    saved_ingredients: list[RecipeIngredient] = []
    for item in preview.ingredients:
        values = {
            column.name: getattr(item, column.name)
            for column in item.__table__.columns
            if column.name not in {"id", "recipe_version_id"}
        }
        ingredient = RecipeIngredient(recipe_version_id=version.id, **values)
        db.add(ingredient)
        saved_ingredients.append(ingredient)
    db.flush()
    db.add(
        RecipeMethodSnapshot(
            recipe_version_id=version.id,
            **snapshot_values(
                blocks=preview.blocks,
                ingredients=saved_ingredients,
                source_kind="publisher",
                extractor_version=preview.extracted.extraction_method,
                created_by_user_id=context.user.id,
            ),
        )
    )
    if publisher_values(version) is not None and version.yield_servings:
        recipe.eligibility = RecipeEligibility.PLANNER_READY.value
    db.commit()
    _previews.pop(preview_token, None)
    db.refresh(recipe)
    return _recipe_detail(db, recipe, context.user.ingredient_locale).model_dump(mode="json")


@router.get("/recipes/{recipe_id}/method", response_model=MethodViewOut)
def get_recipe_method(
    recipe_id: str,
    batch_id: str | None = Query(default=None),
    servings: Decimal | None = Query(default=None, gt=0, le=100_000),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    recipe = _recipe_for_household(db, recipe_id, context.user.household_id)
    batch_context = None
    if batch_id:
        batch = db.scalar(
            select(MealBatch)
            .join(MealPlan, MealPlan.id == MealBatch.meal_plan_id)
            .where(MealBatch.id == batch_id, MealPlan.household_id == context.user.household_id)
        )
        if batch is None:
            raise NotFoundError("Meal batch")
        version = db.get(RecipeVersion, batch.recipe_version_id)
        if version is None or version.recipe_id != recipe.id:
            raise DomainError("BATCH_RECIPE_MISMATCH", "That batch does not use this recipe.", 422)
        requested = Decimal(batch.servings)
        batch_context = _batch_context(db, batch)
    else:
        version = _latest_version(db, recipe.id)
        if version is None:
            raise DomainError("CORRUPT_RECIPE", "The recipe has no version.", 500)
        requested = servings or version.yield_servings
    snapshot = version.method_snapshot
    if snapshot is None and recipe.source_type == "custom":
        locked_version = db.scalar(
            select(RecipeVersion)
            .where(RecipeVersion.id == version.id)
            .with_for_update()
        )
        if locked_version is not None:
            db.expire(locked_version, ["method_snapshot"])
            version = locked_version
            snapshot = version.method_snapshot
        if snapshot is None:
            repaired = _repair_custom_method_snapshot(db, version, context.user.id)
            if repaired is not None:
                db.commit()
                db.expire(version, ["method_snapshot"])
                snapshot = version.method_snapshot or repaired
    if snapshot is None:
        if batch_id and batch_context and batch_context.get("cooked_at"):
            raise DomainError(
                "HISTORICAL_METHOD_NOT_CAPTURED",
                "This cooked batch predates method capture. You can copy the current method onto this batch; its cooked record and batch ingredients will stay unchanged.",
                409,
                actions=_historical_method_recovery_actions(recipe.id, batch_id),
            )
        raise DomainError(
            "METHOD_NOT_AVAILABLE",
            "This recipe has no saved method yet.",
            404,
            actions=[{"kind": "extract_method", "label": "Create method draft"}],
        )
    return _method_view(
        db,
        recipe,
        version,
        snapshot,
        context,
        requested_servings=requested,
        batch_context=batch_context,
    )


@router.post(
    "/recipes/{recipe_id}/method/recover-historical",
    response_model=MethodViewOut,
)
def recover_historical_method(
    recipe_id: str,
    batch_id: str = Query(...),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    """Explicitly capture the current method for a cooked batch's old version."""

    recipe = db.scalar(
        select(Recipe)
        .where(Recipe.id == recipe_id)
        .with_for_update()
    )
    if (
        recipe is None
        or recipe.household_id != context.user.household_id
        or recipe.archived_at is not None
    ):
        raise NotFoundError("Recipe")
    batch = db.scalar(
        select(MealBatch)
        .join(MealPlan, MealPlan.id == MealBatch.meal_plan_id)
        .where(MealBatch.id == batch_id, MealPlan.household_id == context.user.household_id)
        .with_for_update()
    )
    if batch is None:
        raise NotFoundError("Meal batch")
    version = db.scalar(
        select(RecipeVersion)
        .where(RecipeVersion.id == batch.recipe_version_id)
        .with_for_update()
    )
    if version is None or version.recipe_id != recipe.id:
        raise DomainError("BATCH_RECIPE_MISMATCH", "That batch does not use this recipe.", 422)
    if not batch.cooked_at:
        raise DomainError(
            "HISTORICAL_METHOD_RECOVERY_NOT_REQUIRED",
            "This batch is not cooked, so its method can be captured normally.",
            409,
        )

    batch_context = _batch_context(db, batch)
    snapshot = version.method_snapshot
    if snapshot is not None:
        return _method_view(
            db,
            recipe,
            version,
            snapshot,
            context,
            requested_servings=Decimal(batch.servings),
            batch_context=batch_context,
        )

    latest = _latest_version(db, recipe.id)
    if latest is None:
        raise DomainError("CORRUPT_RECIPE", "The recipe has no version.", 500)
    current_snapshot = latest.method_snapshot
    if current_snapshot is None and recipe.source_type == "custom":
        locked_latest = db.scalar(
            select(RecipeVersion)
            .where(RecipeVersion.id == latest.id)
            .with_for_update()
        )
        if locked_latest is not None:
            db.expire(locked_latest, ["method_snapshot"])
            latest = locked_latest
            current_snapshot = latest.method_snapshot
        if current_snapshot is None:
            current_snapshot = _repair_custom_method_snapshot(
                db,
                latest,
                context.user.id,
            )
    if current_snapshot is None:
        raise DomainError(
            "METHOD_NOT_AVAILABLE",
            "Save the current recipe method before recovering this historical batch.",
            409,
            actions=[
                {
                    "kind": "current_method",
                    "label": "Open current recipe method",
                    "href": f"/recipes/{recipe.id}/method",
                }
            ],
        )

    if latest.id == version.id:
        snapshot = current_snapshot
    else:
        blocks = [dict(block) for block in (current_snapshot.source_blocks or [])]
        if not blocks and current_snapshot.source_text.strip():
            blocks = [
                {
                    "id": "block-1",
                    "position": 0,
                    "heading": None,
                    "text": current_snapshot.source_text,
                }
            ]
        if not blocks:
            raise DomainError(
                "METHOD_NOT_AVAILABLE",
                "The current recipe method has no written text to capture.",
                409,
            )
        snapshot = RecipeMethodSnapshot(
            recipe_version_id=version.id,
            **snapshot_values(
                blocks=blocks,
                ingredients=version.ingredients,
                source_kind=current_snapshot.source_kind,
                extractor_version="current-method-recovery",
                created_by_user_id=context.user.id,
                household_notes=current_snapshot.household_notes,
            ),
        )
        db.add(snapshot)
        db.flush()
    db.commit()
    db.expire(version, ["method_snapshot"])
    snapshot = version.method_snapshot or snapshot
    return _method_view(
        db,
        recipe,
        version,
        snapshot,
        context,
        requested_servings=Decimal(batch.servings),
        batch_context=batch_context,
    )


@router.post("/recipes/{recipe_id}/method/extract", response_model=MethodViewOut)
async def extract_saved_recipe_method(
    recipe_id: str,
    payload: MethodExtractRequest,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    recipe = _recipe_for_household(db, recipe_id, context.user.household_id)
    if not recipe.source_url:
        raise DomainError(
            "METHOD_SOURCE_REQUIRED",
            "Write or paste a method for this custom recipe.",
            422,
        )
    preview = await _create_preview(recipe.source_url, context, db, recipe_id=recipe.id)
    extracted = preview.extracted
    blocks = preview.blocks
    locked = db.scalar(select(Recipe).where(Recipe.id == recipe.id).with_for_update())
    if locked is None:
        raise NotFoundError("Recipe")
    if payload.expected_version is not None and locked.version != payload.expected_version:
        raise DomainError("VERSION_CONFLICT", "This recipe changed while the method was loading.", 409)
    previous = _latest_version(db, recipe.id)
    if previous is None:
        raise DomainError("CORRUPT_RECIPE", "The recipe has no version.", 500)
    if previous.method_snapshot is not None:
        _previews.pop(preview.token, None)
        return _method_view(
            db,
            recipe,
            previous,
            previous.method_snapshot,
            context,
            requested_servings=previous.yield_servings,
        )
    next_version, ingredients = _clone_version(db, previous)
    snapshot = RecipeMethodSnapshot(
        recipe_version_id=next_version.id,
        **snapshot_values(
            blocks=blocks,
            ingredients=ingredients,
            source_kind="publisher",
            extractor_version=extracted.extraction_method,
            created_by_user_id=context.user.id,
        ),
    )
    db.add(snapshot)
    locked.version += 1
    sync_recipe_versions_to_current_plans(
        db, context.user.household_id, {previous.id: next_version.id}
    )
    db.commit()
    _previews.pop(preview.token, None)
    return _method_view(
        db,
        locked,
        next_version,
        snapshot,
        context,
        requested_servings=next_version.yield_servings,
    )


@router.put("/recipes/{recipe_id}/method", response_model=MethodViewOut)
def update_recipe_method(
    recipe_id: str,
    payload: MethodUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    recipe = db.scalar(select(Recipe).where(Recipe.id == recipe_id).with_for_update())
    if (
        recipe is None
        or recipe.household_id != context.user.household_id
        or recipe.archived_at is not None
    ):
        raise NotFoundError("Recipe")
    if recipe.version != payload.expected_version:
        raise DomainError(
            "VERSION_CONFLICT",
            "This method changed in another session. Your draft has been kept for comparison.",
            409,
            actions=[{"kind": "compare_method", "label": "Compare with latest"}],
        )
    previous = _latest_version(db, recipe.id)
    if previous is None:
        raise DomainError("CORRUPT_RECIPE", "The recipe has no version.", 500)
    next_version, ingredients = _clone_version(db, previous)
    _validate_bindings(payload.method, ingredients)
    old_snapshot = previous.method_snapshot
    if old_snapshot is not None and old_snapshot.source_kind == "publisher":
        if payload.source_blocks is not None:
            raise DomainError(
                "PUBLISHER_SOURCE_READ_ONLY",
                "Imported publisher wording is read-only. Edit tags, summary actions or notes instead.",
                422,
            )
        blocks = list(old_snapshot.source_blocks or [])
        source_kind = old_snapshot.source_kind
        extractor_version = old_snapshot.extractor_version
    else:
        blocks = [item.model_dump(mode="json") for item in (payload.source_blocks or [])]
        if not blocks and old_snapshot is not None:
            blocks = list(old_snapshot.source_blocks or [])
        if not blocks:
            raise DomainError("METHOD_SOURCE_REQUIRED", "Write or paste method text first.", 422)
        source_kind = payload.source_kind or (old_snapshot.source_kind if old_snapshot else "custom")
        extractor_version = "user-authored"
    source_text = source_text_from_blocks(blocks)
    _, parsed_coverage, confidence = parse_method_document(blocks, ingredients)
    coverage = dict(old_snapshot.coverage or {}) if old_snapshot is not None else parsed_coverage
    unreviewed = sum(
        1
        for annotation in payload.method.annotations
        if annotation.kind == "action"
        and annotation.confidence < Decimal("0.65")
        and not annotation.accepted
    )
    coverage["unreviewed"] = unreviewed
    coverage["omitted"] = len(payload.method.omissions)
    coverage["represented"] = max(
        0,
        int(coverage.get("total_clauses", 0)) - coverage["omitted"] - unreviewed,
    )
    now = datetime.now(timezone.utc)
    snapshot = RecipeMethodSnapshot(
        recipe_version_id=next_version.id,
        source_kind=source_kind,
        source_text=source_text,
        source_blocks=blocks,
        source_checksum=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        extractor_version=extractor_version,
        parser_version=METHOD_PARSER_VERSION,
        status="reviewed" if payload.mark_reviewed else "needs_review",
        confidence=confidence,
        coverage=coverage,
        document=payload.method.model_dump(mode="json"),
        household_notes=payload.household_notes,
        created_by_user_id=context.user.id,
        reviewed_by_user_id=context.user.id if payload.mark_reviewed else None,
        reviewed_at=now if payload.mark_reviewed else None,
    )
    if recipe.source_type == "custom" and source_kind == "custom":
        next_version.custom_instructions = source_text
    db.add(snapshot)
    recipe.version += 1
    sync_recipe_versions_to_current_plans(
        db, context.user.household_id, {previous.id: next_version.id}
    )
    db.commit()
    return _method_view(
        db,
        recipe,
        next_version,
        snapshot,
        context,
        requested_servings=next_version.yield_servings,
    )


@router.post("/recipes/{recipe_id}/method/refresh-preview", response_model=MethodViewOut)
async def preview_method_refresh(
    recipe_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    recipe = _recipe_for_household(db, recipe_id, context.user.household_id)
    if not recipe.source_url:
        raise DomainError("METHOD_SOURCE_REQUIRED", "This recipe has no publisher source.", 422)
    preview = await _create_preview(recipe.source_url, context, db, recipe_id=recipe.id)
    latest = _latest_version(db, recipe.id)
    old_snapshot = latest.method_snapshot if latest else None
    view = _preview_view(preview, context, db)
    old_text = old_snapshot.source_text if old_snapshot else ""
    new_text = preview.snapshot.source_text
    return view.model_copy(
        update={
            "refresh_diff": {
                "changed": old_text != new_text,
                "old_checksum": old_snapshot.source_checksum if old_snapshot else None,
                "new_checksum": preview.snapshot.source_checksum,
                "old_block_count": len(old_snapshot.source_blocks or []) if old_snapshot else 0,
                "new_block_count": len(preview.blocks),
            }
        }
    )


@router.post("/recipes/{recipe_id}/method/refresh", response_model=MethodViewOut)
def apply_method_refresh(
    recipe_id: str,
    payload: MethodRefreshApply,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    preview = _preview_for_user(payload.preview_token, context)
    if preview.recipe_id != recipe_id:
        raise DomainError("METHOD_PREVIEW_MISMATCH", "That preview belongs to another recipe.", 422)
    recipe = db.scalar(select(Recipe).where(Recipe.id == recipe_id).with_for_update())
    if recipe is None or recipe.household_id != context.user.household_id:
        raise NotFoundError("Recipe")
    if recipe.version != payload.expected_version:
        raise DomainError("VERSION_CONFLICT", "This recipe changed before refresh was applied.", 409)
    previous = _latest_version(db, recipe.id)
    if previous is None:
        raise DomainError("CORRUPT_RECIPE", "The recipe has no version.", 500)
    next_version, ingredients = _clone_version(db, previous)
    snapshot = RecipeMethodSnapshot(
        recipe_version_id=next_version.id,
        **snapshot_values(
            blocks=preview.blocks,
            ingredients=ingredients,
            source_kind="publisher",
            extractor_version=preview.extracted.extraction_method,
            created_by_user_id=context.user.id,
            household_notes=(previous.method_snapshot.household_notes if previous.method_snapshot else None),
        ),
    )
    db.add(snapshot)
    recipe.version += 1
    sync_recipe_versions_to_current_plans(
        db, context.user.household_id, {previous.id: next_version.id}
    )
    db.commit()
    _previews.pop(payload.preview_token, None)
    return _method_view(
        db,
        recipe,
        next_version,
        snapshot,
        context,
        requested_servings=next_version.yield_servings,
    )
