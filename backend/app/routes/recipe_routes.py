from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.orm import Session

from ..auth import AuthContext, get_auth_context, require_csrf, require_owner
from ..db import get_db
from ..config import get_settings
from ..errors import DomainError, NotFoundError
from ..discovery import canonicalize_url
from ..discovery.categories import (
    CATEGORY_BY_KEY,
    categories_for_normalised_tags,
    validate_category_keys,
)
from ..discovery.errors import DiscoveryError
from ..models import (
    FoodNutrient,
    FoodRecord,
    Job,
    JobStatus,
    NutritionCalculation,
    RecipeTag,
    Recipe,
    RecipeEligibility,
    RecipeIngredient,
    RecipeMealType,
    RecipeMethodSnapshot,
    RecipePublisherTag,
    RecipeVersion,
    PublisherMetadataStatus,
)
from ..schemas import (
    FoodRecordCreate,
    FoodRecordOut,
    ImportRequest,
    JobOut,
    NutritionCalculationOut,
    RecipeCreate,
    RecipeDetail,
    RecipeIngredientIn,
    RecipePlanSyncOut,
    RecipeReviewUpdate,
    RecipeServingConstraintsUpdate,
    RecipeSummary,
)
from ..services.food_search import (
    FoodDataCentralConfigurationError,
    FoodDataCentralRateLimited,
    FoodDataCentralUnavailable,
    fetch_and_cache_usda_foods,
    normalise_food_query,
)
from ..services.ingredient_names import (
    household_name_overrides,
    ingredient_name_keys,
    preferred_ingredient_name,
    remember_ingredient_name,
)
from ..services.ingredients import PARSER_VERSION, parse_ingredient
from ..services.integration_credentials import effective_usda_key
from ..services.regional_ingredients import convert_ingredient_text, equivalent_terms, query_for_locale
from ..services.nutrition import calculate_recipe, latest_calculation, publisher_values
from ..services.recipe_plan_sync import sync_recipe_versions_to_current_plans
from ..services.recipe_methods import clone_method_snapshot, snapshot_values
from ..services.saved_foods import accessible_food_record

router = APIRouter(tags=["recipes and food data"])


def _latest_version(db: Session, recipe_id: str) -> RecipeVersion | None:
    return db.scalar(
        select(RecipeVersion)
        .where(RecipeVersion.recipe_id == recipe_id)
        .order_by(RecipeVersion.version_number.desc())
    )


def _meal_types(db: Session, recipe: Recipe) -> list[RecipeTag]:
    return [
        RecipeTag(value)
        for value in db.scalars(
            select(RecipeMealType.meal_type)
            .where(RecipeMealType.recipe_id == recipe.id)
            .order_by(RecipeMealType.meal_type)
        ).all()
    ]


def _replace_meal_types(db: Session, recipe: Recipe, meal_types: list[RecipeTag]) -> None:
    db.execute(delete(RecipeMealType).where(RecipeMealType.recipe_id == recipe.id))
    for meal_type in meal_types:
        db.add(RecipeMealType(recipe_id=recipe.id, meal_type=meal_type.value))


def _publisher_tag_data(db: Session, recipe: Recipe) -> tuple[list[dict[str, str]], list[str]]:
    rows = db.scalars(
        select(RecipePublisherTag)
        .where(RecipePublisherTag.recipe_id == recipe.id)
        .order_by(RecipePublisherTag.kind, RecipePublisherTag.label)
    ).all()
    tags = [{"kind": row.kind, "label": row.label} for row in rows]
    categories = list(categories_for_normalised_tags({row.normalised_value for row in rows}))
    return tags, categories


def _normalised_name(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _ingredient_values(
    db: Session,
    household_id: str,
    row: RecipeIngredientIn,
    *,
    reviewed: bool,
) -> dict:
    if row.food_record_id:
        accessible_food_record(db, row.food_record_id, household_id)
    parsed = parse_ingredient(row.original_text)
    automatic_name = convert_ingredient_text(db, parsed.food_phrase, "uk") or parsed.food_phrase
    submitted_name = convert_ingredient_text(db, row.food_phrase, "uk") if row.food_phrase else None
    original_name = convert_ingredient_text(db, row.original_text, "uk") or row.original_text
    keys = ingredient_name_keys(db, automatic_name)
    explicitly_changed = bool(
        submitted_name
        and _normalised_name(submitted_name)
        not in {_normalised_name(original_name), _normalised_name(automatic_name)}
    )
    if explicitly_changed:
        display_name = remember_ingredient_name(db, household_id, keys, submitted_name or automatic_name)
        remembered = True
    else:
        display_name, remembered = preferred_ingredient_name(
            db, household_id, keys, automatic_name
        )
    values = row.model_dump()
    if not values.get("lineage_id"):
        values.pop("lineage_id", None)
    if values["quantity"] is None and values["unit"] is None:
        values["quantity"] = parsed.quantity
        values["unit"] = parsed.unit
    if values["quantity_grams"] is None:
        values["quantity_grams"] = parsed.quantity_grams
    values.update(
        food_phrase=display_name,
        parsed_food_phrase=automatic_name,
        preparation=row.preparation or parsed.preparation,
        parser_version=PARSER_VERSION,
        name_confidence=(
            Decimal(str(round(parsed.name_confidence, 4)))
            if parsed.name_confidence is not None
            else None
        ),
        name_overridden=remembered,
        parser_name_keys=keys,
        optional=row.optional or parsed.optional,
        included=row.included and not (parsed.optional and "included" not in row.model_fields_set),
        needs_review=False if reviewed or remembered else parsed.needs_review,
    )
    return values


def _recipe_detail(db: Session, recipe: Recipe, ingredient_locale: str = "uk") -> RecipeDetail:
    version = _latest_version(db, recipe.id)
    if version is None:
        raise DomainError("CORRUPT_RECIPE", "The recipe has no version", 500)
    name_overrides = household_name_overrides(db, recipe.household_id)
    ingredients = []
    for row in version.ingredients:
        item = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        # Drafts created before ingredient parsing was introduced are enriched
        # on read. Saving the review persists these fields in the next immutable
        # recipe version without rewriting the historical import.
        if row.parser_version != PARSER_VERSION:
            parsed = parse_ingredient(row.original_text)
            calculated_amount = parsed.quantity_calculated
            automatic_name = convert_ingredient_text(db, parsed.food_phrase, "uk") or parsed.food_phrase
            keys = ingredient_name_keys(db, automatic_name, row.food_phrase)
            display_name, remembered = preferred_ingredient_name(
                db,
                recipe.household_id,
                keys,
                automatic_name,
                overrides=name_overrides,
            )
            item.update(
                quantity=(
                    parsed.quantity
                    if calculated_amount
                    else row.quantity if row.quantity is not None else parsed.quantity
                ),
                unit=(
                    parsed.unit
                    if calculated_amount
                    else row.unit if row.unit is not None else parsed.unit
                ),
                quantity_grams=(
                    parsed.quantity_grams
                    if calculated_amount
                    else row.quantity_grams
                    if row.quantity_grams is not None
                    else parsed.quantity_grams
                ),
                food_phrase=row.food_phrase if row.name_overridden else display_name,
                parsed_food_phrase=automatic_name,
                preparation=row.preparation or parsed.preparation,
                parser_version=PARSER_VERSION,
                name_confidence=parsed.name_confidence,
                name_overridden=row.name_overridden or remembered,
                parser_name_keys=keys,
                optional=row.optional or parsed.optional,
                included=row.included and not parsed.optional,
                needs_review=(
                    False if row.name_overridden or remembered else parsed.needs_review
                ),
            )
        keys = list(
            item.get("parser_name_keys")
            or ingredient_name_keys(
                db,
                item.get("parsed_food_phrase"),
                item.get("food_phrase"),
            )
        )
        display_name, remembered = preferred_ingredient_name(
            db,
            recipe.household_id,
            keys,
            item.get("food_phrase") or item.get("parsed_food_phrase") or row.original_text,
            overrides=name_overrides,
        )
        if remembered:
            item["food_phrase"] = display_name
            item["name_overridden"] = True
            item["needs_review"] = False
        item["original_text"] = convert_ingredient_text(db, item["original_text"], ingredient_locale)
        item["food_phrase"] = convert_ingredient_text(db, item.get("food_phrase"), ingredient_locale)
        item["parsed_food_phrase"] = convert_ingredient_text(
            db, item.get("parsed_food_phrase"), ingredient_locale
        )
        for field in ("quantity", "quantity_grams", "name_confidence"):
            if isinstance(item.get(field), Decimal):
                plain = format(item[field], "f")
                if "." in plain:
                    plain = plain.rstrip("0").rstrip(".")
                item[field] = Decimal(plain or "0")
        ingredients.append(item)
    reported_values = publisher_values(version)
    calculation = latest_calculation(db, version.id)
    nutrition_values = (
        {key: float(value) for key, value in reported_values.items()}
        if reported_values
        else (
            calculation.per_serving_values
            if calculation is not None and calculation.status == "complete"
            else None
        )
    )
    nutrition_method = (
        "publisher"
        if reported_values is not None
        else ("complete" if calculation is not None and calculation.status == "complete" else None)
    )
    effective_eligibility = (
        RecipeEligibility.PLANNER_READY
        if reported_values is not None and version.yield_servings
        else recipe.eligibility
    )
    meal_types = _meal_types(db, recipe)
    planner_warnings = []
    if not meal_types:
        planner_warnings.append(
            "Choose at least one meal type before this recipe can be used for meal planning."
        )
    if nutrition_values is None or not version.yield_servings:
        planner_warnings.append(
            "Complete per-serving nutrition and a serving yield are required."
        )
    review_count = sum(
        1 for ingredient in ingredients if ingredient["included"] and ingredient["needs_review"]
    )
    if review_count:
        planner_warnings.append(
            f"Confirm {review_count} uncertain ingredient name"
            f"{'s' if review_count != 1 else ''} before creating the shopping list."
        )
    publisher_tags, publisher_categories = _publisher_tag_data(db, recipe)
    summary = RecipeSummary(
        id=recipe.id,
        title=recipe.title,
        eligibility=effective_eligibility,
        source_type=recipe.source_type,
        source_url=recipe.source_url,
        publisher=recipe.publisher,
        image_url=recipe.image_url,
        version=recipe.version,
        yield_servings=version.yield_servings,
        minimum_servings=version.minimum_servings,
        serving_increment=version.serving_increment,
        publisher_nutrition=version.publisher_nutrition,
        calculated_nutrition=nutrition_values,
        nutrition_method=nutrition_method,
        review_count=review_count,
        meal_types=meal_types,
        planner_eligible=(
            effective_eligibility == RecipeEligibility.PLANNER_READY
            and nutrition_values is not None
            and bool(version.yield_servings)
            and bool(meal_types)
        ),
        planner_warnings=planner_warnings,
        publisher_tags=publisher_tags,
        publisher_categories=publisher_categories,
        publisher_metadata_status=recipe.publisher_metadata_status,
        method_available=version.method_snapshot is not None,
        method_status=version.method_snapshot.status if version.method_snapshot is not None else None,
    )
    return RecipeDetail(
        **summary.model_dump(),
        recipe_version_id=version.id,
        version_number=version.version_number,
        custom_instructions=version.custom_instructions,
        ingredients=ingredients,
    )


@router.get("/recipes", response_model=dict)
def list_recipes(
    q: str = Query(default="", max_length=200),
    meal_type: list[RecipeTag] = Query(default=[]),
    publisher_category: list[str] = Query(default=[]),
    publisher_category_match: Literal["any", "all"] = Query(default="any"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    include_food: bool = Query(default=False),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    try:
        selected_categories = validate_category_keys(publisher_category)
    except ValueError as exc:
        raise DomainError("TOO_MANY_RECIPE_CATEGORIES", str(exc), 422) from exc
    except KeyError as exc:
        raise DomainError("UNKNOWN_RECIPE_CATEGORY", f"Unknown recipe category: {exc.args[0]}", 422) from exc
    conditions = [Recipe.household_id == context.user.household_id, Recipe.archived_at.is_(None)]
    if not include_food:
        conditions.append(Recipe.source_type != "food")
    if q.strip():
        search_terms = equivalent_terms(db, q.strip())
        ingredient_match = exists(
            select(RecipeIngredient.id)
            .join(RecipeVersion, RecipeVersion.id == RecipeIngredient.recipe_version_id)
            .where(
                RecipeVersion.recipe_id == Recipe.id,
                or_(
                    *(
                        or_(
                            func.lower(RecipeIngredient.original_text).contains(term),
                            func.lower(RecipeIngredient.food_phrase).contains(term),
                        )
                        for term in search_terms
                    )
                ),
            )
        )
        conditions.append(
            or_(
                *(func.lower(Recipe.title).contains(term) for term in search_terms),
                ingredient_match,
                exists(
                    select(RecipePublisherTag.id).where(
                        RecipePublisherTag.recipe_id == Recipe.id,
                        or_(
                            *(RecipePublisherTag.normalised_value.contains(term) for term in search_terms)
                        ),
                    )
                ),
            )
        )
    if meal_type:
        conditions.append(
            Recipe.meal_type_tags.any(
                RecipeMealType.meal_type.in_([item.value for item in meal_type])
            )
        )
    if selected_categories:
        category_aliases = [CATEGORY_BY_KEY[key].normalised_aliases for key in selected_categories]
        if publisher_category_match == "all":
            conditions.extend(
                exists(
                    select(RecipePublisherTag.id).where(
                        RecipePublisherTag.recipe_id == Recipe.id,
                        RecipePublisherTag.normalised_value.in_(aliases),
                    )
                )
                for aliases in category_aliases
            )
        else:
            aliases = set().union(*category_aliases)
            conditions.append(
                exists(
                    select(RecipePublisherTag.id).where(
                        RecipePublisherTag.recipe_id == Recipe.id,
                        RecipePublisherTag.normalised_value.in_(aliases),
                    )
                )
            )
    total = db.scalar(select(func.count(Recipe.id)).where(*conditions)) or 0
    recipes = db.scalars(
        select(Recipe)
        .where(*conditions)
        .order_by(Recipe.title)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [
            _recipe_detail(db, recipe, context.user.ingredient_locale).model_dump(
                mode="json",
                include=set(RecipeSummary.model_fields),
            )
            for recipe in recipes
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/recipe-ingredients", response_model=dict)
def list_recipe_ingredients(
    q: str = Query(default="", max_length=200),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    """Return distinct ingredients from the household's current saved recipes."""

    recipes = db.scalars(
        select(Recipe)
        .where(
            Recipe.household_id == context.user.household_id,
            Recipe.archived_at.is_(None),
        )
        .order_by(Recipe.title)
    ).all()
    query_terms = equivalent_terms(db, q.strip()) if q.strip() else []
    ingredients: dict[str, dict] = {}
    for recipe in recipes:
        version = _latest_version(db, recipe.id)
        if version is None:
            continue
        for ingredient in version.ingredients:
            phrase = " ".join(
                (ingredient.food_phrase or ingredient.original_text or "").strip().split()
            )
            if not ingredient.included or not phrase:
                continue
            normalised = phrase.casefold()
            display_name = convert_ingredient_text(
                db, phrase, context.user.ingredient_locale
            )
            searchable = " ".join(
                {
                    normalised,
                    display_name.casefold(),
                    (convert_ingredient_text(db, phrase, "uk") or phrase).casefold(),
                    (convert_ingredient_text(db, phrase, "us") or phrase).casefold(),
                }
            )
            if query_terms and not any(term in searchable for term in query_terms):
                continue
            result = ingredients.setdefault(
                normalised,
                {
                    "id": normalised,
                    "term": normalised,
                    "name": display_name,
                    "recipes": [],
                },
            )
            if not any(item["id"] == recipe.id for item in result["recipes"]):
                result["recipes"].append({"id": recipe.id, "title": recipe.title})

    items = sorted(ingredients.values(), key=lambda item: item["name"].casefold())
    return {"items": items, "total": len(items)}


@router.post("/recipes", response_model=RecipeDetail, status_code=201)
def create_recipe(
    payload: RecipeCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    ingredient_values = [
        _ingredient_values(
            db,
            context.user.household_id,
            item,
            reviewed=False,
        )
        for item in payload.ingredients
    ]
    recipe = Recipe(
        household_id=context.user.household_id,
        title=payload.title,
        source_type=payload.source_type,
        source_url=payload.source_url,
        publisher=payload.publisher,
        image_url=payload.image_url,
        eligibility=RecipeEligibility.DRAFT.value,
        publisher_metadata_status=(
            PublisherMetadataStatus.PENDING.value
            if payload.source_type == "url"
            else PublisherMetadataStatus.NOT_APPLICABLE.value
        ),
    )
    db.add(recipe)
    db.flush()
    for meal_type in payload.meal_types:
        db.add(RecipeMealType(recipe_id=recipe.id, meal_type=meal_type.value))
    instruction_text = payload.custom_instructions.strip() if payload.custom_instructions else None
    version = RecipeVersion(
        recipe_id=recipe.id,
        version_number=1,
        title=payload.title,
        yield_servings=payload.yield_servings,
        minimum_servings=payload.minimum_servings,
        serving_increment=payload.serving_increment,
        custom_instructions=instruction_text,
        publisher_nutrition=payload.publisher_nutrition,
    )
    db.add(version)
    db.flush()
    created_ingredients = []
    for position, item in enumerate(ingredient_values):
        ingredient = RecipeIngredient(recipe_version_id=version.id, position=position, **item)
        db.add(ingredient)
        created_ingredients.append(ingredient)
    db.flush()
    if instruction_text:
        blocks = [
            {
                "id": "block-1",
                "position": 0,
                "heading": None,
                "text": instruction_text,
            }
        ]
        db.add(
            RecipeMethodSnapshot(
                recipe_version_id=version.id,
                **snapshot_values(
                    blocks=blocks,
                    ingredients=created_ingredients,
                    source_kind="custom" if payload.source_type == "custom" else "manual_paste",
                    extractor_version="user-authored",
                    created_by_user_id=context.user.id,
                ),
            )
        )
    if payload.source_type == "custom":
        try:
            calculate_recipe(db, version.id)
        except DomainError as exc:
            if exc.code not in {
                "MISSING_YIELD",
                "MISSING_INGREDIENTS",
                "NUTRITION_REVIEW_REQUIRED",
            }:
                raise
            recipe.eligibility = RecipeEligibility.DRAFT.value
    elif publisher_values(version) is not None and version.yield_servings:
        recipe.eligibility = RecipeEligibility.PLANNER_READY.value
    db.commit()
    db.refresh(recipe)
    return _recipe_detail(db, recipe, context.user.ingredient_locale)


@router.get("/recipes/{recipe_id}", response_model=RecipeDetail)
def get_recipe(
    recipe_id: str,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    recipe = db.get(Recipe, recipe_id)
    if (
        recipe is None
        or recipe.household_id != context.user.household_id
        or recipe.archived_at is not None
    ):
        raise NotFoundError("Recipe")
    return _recipe_detail(db, recipe, context.user.ingredient_locale)


@router.delete("/recipes/{recipe_id}", status_code=204)
def delete_recipe(
    recipe_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    recipe = db.get(Recipe, recipe_id)
    if (
        recipe is None
        or recipe.household_id != context.user.household_id
        or recipe.archived_at is not None
    ):
        raise NotFoundError("Recipe")
    recipe.archived_at = datetime.now(timezone.utc)
    recipe.eligibility = RecipeEligibility.ARCHIVED.value
    recipe.version += 1
    db.commit()


@router.put("/recipes/{recipe_id}/review", response_model=RecipeDetail)
def save_recipe_review(
    recipe_id: str,
    payload: RecipeReviewUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    """Save reviewed fields as a new immutable recipe version."""

    recipe = db.scalar(
        select(Recipe).where(Recipe.id == recipe_id).with_for_update()
    )
    if (
        recipe is None
        or recipe.household_id != context.user.household_id
        or recipe.archived_at is not None
    ):
        raise NotFoundError("Recipe")
    if recipe.version != payload.expected_version:
        raise DomainError(
            "VERSION_CONFLICT",
            "This recipe changed while you were reviewing it. Reload before saving.",
            409,
        )
    previous = _latest_version(db, recipe.id)
    if previous is None:
        raise DomainError("CORRUPT_RECIPE", "The recipe has no version", 500)
    next_version = RecipeVersion(
        recipe_id=recipe.id,
        version_number=previous.version_number + 1,
        title=payload.title,
        yield_servings=payload.yield_servings,
        minimum_servings=(
            payload.minimum_servings
            if "minimum_servings" in payload.model_fields_set
            else previous.minimum_servings
        ),
        serving_increment=(
            payload.serving_increment
            if "serving_increment" in payload.model_fields_set
            else previous.serving_increment
        ),
        custom_instructions=previous.custom_instructions,
        source_checksum=previous.source_checksum,
        publisher_nutrition=previous.publisher_nutrition,
    )
    db.add(next_version)
    db.flush()
    ingredient_values = []
    for position, item in enumerate(payload.ingredients):
        values = _ingredient_values(
            db,
            context.user.household_id,
            item,
            reviewed=True,
        )
        if "lineage_id" not in values and position < len(previous.ingredients):
            values["lineage_id"] = previous.ingredients[position].lineage_id
        ingredient_values.append(values)
    new_ingredients = []
    for position, item in enumerate(ingredient_values):
        ingredient = RecipeIngredient(
            recipe_version_id=next_version.id,
            position=position,
            **item,
        )
        db.add(
            ingredient
        )
        new_ingredients.append(ingredient)
    db.flush()
    if previous.method_snapshot is not None:
        old_lineages = {item.lineage_id for item in previous.ingredients}
        new_lineages = {item.lineage_id for item in new_ingredients}
        db.add(
            clone_method_snapshot(
                previous.method_snapshot,
                recipe_version_id=next_version.id,
                created_by_user_id=context.user.id,
                force_needs_review=old_lineages != new_lineages,
            )
        )
    if payload.meal_types is not None:
        _replace_meal_types(db, recipe, payload.meal_types)
    recipe.title = payload.title
    recipe.eligibility = RecipeEligibility.DRAFT.value
    db.flush()
    if recipe.source_type == "custom":
        try:
            calculate_recipe(db, next_version.id)
        except DomainError as exc:
            if exc.code not in {
                "MISSING_YIELD",
                "MISSING_INGREDIENTS",
                "NUTRITION_REVIEW_REQUIRED",
            }:
                raise
    elif publisher_values(next_version) is not None:
        recipe.eligibility = RecipeEligibility.PLANNER_READY.value
    recipe.version += 1
    sync = sync_recipe_versions_to_current_plans(
        db,
        context.user.household_id,
        {previous.id: next_version.id},
    )
    db.commit()
    db.refresh(recipe)
    detail = _recipe_detail(db, recipe, context.user.ingredient_locale)
    return detail.model_copy(
        update={
            "plan_sync": RecipePlanSyncOut(
                plans_updated=sync.plans_updated,
                shopping_list_rebuilt=sync.shopping_list_rebuilt,
                shopping_list_id=sync.shopping_list_id,
                cooked_batches_unchanged=sync.cooked_batches_unchanged,
            )
        }
    )


@router.put("/recipes/{recipe_id}/serving-constraints", response_model=RecipeDetail)
def save_recipe_serving_constraints(
    recipe_id: str,
    payload: RecipeServingConstraintsUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    """Update only planner serving constraints as a new immutable version."""

    recipe = db.scalar(
        select(Recipe).where(Recipe.id == recipe_id).with_for_update()
    )
    if (
        recipe is None
        or recipe.household_id != context.user.household_id
        or recipe.archived_at is not None
    ):
        raise NotFoundError("Recipe")
    if recipe.version != payload.expected_version:
        raise DomainError(
            "VERSION_CONFLICT",
            "This recipe changed while you were editing its serving limits. Reload before saving.",
            409,
        )
    previous = _latest_version(db, recipe.id)
    if previous is None:
        raise DomainError("CORRUPT_RECIPE", "The recipe has no version", 500)

    next_version = RecipeVersion(
        recipe_id=recipe.id,
        version_number=previous.version_number + 1,
        title=previous.title,
        yield_servings=previous.yield_servings,
        minimum_servings=payload.minimum_servings,
        serving_increment=payload.serving_increment,
        custom_instructions=previous.custom_instructions,
        source_checksum=previous.source_checksum,
        publisher_nutrition=previous.publisher_nutrition,
    )
    db.add(next_version)
    db.flush()
    for ingredient in previous.ingredients:
        values = {
            column.name: getattr(ingredient, column.name)
            for column in ingredient.__table__.columns
            if column.name not in {"id", "recipe_version_id"}
        }
        db.add(RecipeIngredient(recipe_version_id=next_version.id, **values))
    if previous.method_snapshot is not None:
        db.add(
            clone_method_snapshot(
                previous.method_snapshot,
                recipe_version_id=next_version.id,
                created_by_user_id=context.user.id,
            )
        )
    previous_calculation = latest_calculation(db, previous.id)
    if previous_calculation is not None:
        db.add(
            NutritionCalculation(
                recipe_version_id=next_version.id,
                status=previous_calculation.status,
                total_values=dict(previous_calculation.total_values or {}),
                per_serving_values=dict(previous_calculation.per_serving_values or {}),
                contributions=list(previous_calculation.contributions or []),
                assumptions=list(previous_calculation.assumptions or []),
                dataset_snapshot=dict(previous_calculation.dataset_snapshot or {}),
            )
        )
    recipe.version += 1
    sync = sync_recipe_versions_to_current_plans(
        db,
        context.user.household_id,
        {previous.id: next_version.id},
    )
    db.commit()
    db.refresh(recipe)
    detail = _recipe_detail(db, recipe, context.user.ingredient_locale)
    return detail.model_copy(
        update={
            "plan_sync": RecipePlanSyncOut(
                plans_updated=sync.plans_updated,
                shopping_list_rebuilt=sync.shopping_list_rebuilt,
                shopping_list_id=sync.shopping_list_id,
                cooked_batches_unchanged=sync.cooked_batches_unchanged,
            )
        }
    )


@router.post("/recipes/{recipe_id}/calculate", response_model=NutritionCalculationOut)
def calculate(
    recipe_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    recipe = db.get(Recipe, recipe_id)
    if (
        recipe is None
        or recipe.household_id != context.user.household_id
        or recipe.archived_at is not None
    ):
        raise NotFoundError("Recipe")
    version = _latest_version(db, recipe.id)
    calculation = calculate_recipe(db, version.id)
    db.commit()
    db.refresh(calculation)
    return calculation


@router.post("/recipe-imports", response_model=JobOut, status_code=202)
def create_import(
    payload: ImportRequest,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    try:
        canonical_url = canonicalize_url(payload.url)
    except DiscoveryError as exc:
        raise DomainError("INVALID_URL", str(exc), 422) from exc
    job = Job(
        household_id=context.user.household_id,
        user_id=context.user.id,
        kind="recipe_import",
        status=JobStatus.QUEUED.value,
        stage="queued",
        payload={"url": canonical_url},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        from ..worker import process_recipe_import

        process_recipe_import.delay(job.id)
    except Exception as exc:
        # The persisted job remains queued and can be retried when a worker is available.
        if exc.__class__.__module__.split(".")[0] not in {"celery", "kombu", "redis"} and not isinstance(
            exc, (ImportError, ConnectionError, OSError)
        ):
            raise
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: str,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if job is None or job.household_id != context.user.household_id:
        raise NotFoundError("Job")
    return job


@router.get("/foods", response_model=dict)
def search_foods(
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    cleaned_query = normalise_food_query(q.strip()) if q.strip() else ""
    conditions = [
        or_(
            FoodRecord.owner_household_id.is_(None),
            FoodRecord.owner_household_id == context.user.household_id,
        )
    ]
    if cleaned_query:
        terms = equivalent_terms(db, cleaned_query)
        conditions.append(or_(*(
            and_(*(func.lower(FoodRecord.name).contains(token) for token in term.split()))
            for term in terms
        )))
    total = db.scalar(select(func.count(FoodRecord.id)).where(*conditions)) or 0
    remote_error = None
    remote_error_code = None
    settings = get_settings()
    if cleaned_query and total < 3 and settings.remote_food_search_enabled:
        usda_api_key, usda_key_source = effective_usda_key(
            db, context.user.household_id, settings
        )
        try:
            fetch_and_cache_usda_foods(
                db,
                query_for_locale(db, cleaned_query, "us"),
                api_key=usda_api_key,
            )
            total = db.scalar(select(func.count(FoodRecord.id)).where(*conditions)) or 0
        except FoodDataCentralConfigurationError:
            remote_error = "FoodData Central needs a USDA API key before general-food search can run."
            remote_error_code = "USDA_API_KEY_REQUIRED"
        except FoodDataCentralRateLimited:
            remote_error = (
                "FoodData Central's shared demo quota is exhausted. Add a free USDA API key to restore general-food search."
                if usda_key_source == "demo"
                else "FoodData Central is rate limited. Existing local matches are still shown."
            )
            remote_error_code = (
                "USDA_API_KEY_REQUIRED" if usda_key_source == "demo" else "USDA_RATE_LIMITED"
            )
        except FoodDataCentralUnavailable:
            remote_error = "FoodData Central could not be reached. Existing local matches are still shown."
            remote_error_code = "USDA_UNAVAILABLE"
    rows = db.scalars(
        select(FoodRecord)
        .where(*conditions)
        .order_by(FoodRecord.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = []
    for food in rows:
        item = FoodRecordOut(
                **{column.name: getattr(food, column.name) for column in food.__table__.columns},
                nutrients=[
                    {column.name: getattr(n, column.name) for column in n.__table__.columns}
                    for n in food.nutrients
                ],
            ).model_dump(mode="json")
        item["name"] = convert_ingredient_text(db, item["name"], context.user.ingredient_locale)
        items.append(item)
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "remote_error": remote_error,
        "remote_error_code": remote_error_code,
    }


@router.post("/foods", response_model=FoodRecordOut, status_code=201)
def create_food(
    payload: FoodRecordCreate,
    _: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    if db.scalar(
        select(FoodRecord).where(
            FoodRecord.provider == payload.provider,
            FoodRecord.provider_record_id == payload.provider_record_id,
        )
    ):
        raise DomainError("FOOD_ALREADY_EXISTS", "That provider food record already exists", 409)
    food = FoodRecord(**payload.model_dump(exclude={"nutrients"}))
    db.add(food)
    db.flush()
    for nutrient in payload.nutrients:
        db.add(FoodNutrient(food_record_id=food.id, **nutrient.model_dump()))
    db.commit()
    db.refresh(food)
    return FoodRecordOut(
        **{column.name: getattr(food, column.name) for column in food.__table__.columns},
        nutrients=[
            {column.name: getattr(n, column.name) for column in n.__table__.columns}
            for n in food.nutrients
        ],
    )
