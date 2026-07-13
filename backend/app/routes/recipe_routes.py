from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ..auth import AuthContext, get_auth_context, require_csrf, require_owner
from ..db import get_db
from ..config import get_settings
from ..errors import DomainError, NotFoundError
from ..discovery import canonicalize_url
from ..discovery.errors import DiscoveryError
from ..models import (
    FoodNutrient,
    FoodRecord,
    Job,
    JobStatus,
    MealBatch,
    MealPlan,
    MealType,
    PantryReservation,
    PlanStatus,
    Recipe,
    RecipeEligibility,
    RecipeIngredient,
    RecipeMealType,
    RecipeVersion,
    ShoppingList,
)
from ..schemas import (
    FoodRecordCreate,
    FoodRecordOut,
    ImportRequest,
    JobOut,
    NutritionCalculationOut,
    RecipeCreate,
    RecipeDetail,
    RecipeReviewUpdate,
    RecipeSummary,
)
from ..services.food_search import fetch_and_cache_usda_foods, normalise_food_query
from ..services.ingredients import parse_ingredient
from ..services.nutrition import calculate_recipe, latest_calculation, publisher_values
from ..services.pantry import reserve_plan_batches

router = APIRouter(tags=["recipes and food data"])


def _latest_version(db: Session, recipe_id: str) -> RecipeVersion | None:
    return db.scalar(
        select(RecipeVersion)
        .where(RecipeVersion.recipe_id == recipe_id)
        .order_by(RecipeVersion.version_number.desc())
    )


def _meal_types(db: Session, recipe: Recipe) -> list[MealType]:
    return [
        MealType(value)
        for value in db.scalars(
            select(RecipeMealType.meal_type)
            .where(RecipeMealType.recipe_id == recipe.id)
            .order_by(RecipeMealType.meal_type)
        ).all()
    ]


def _replace_meal_types(db: Session, recipe: Recipe, meal_types: list[MealType]) -> None:
    db.execute(delete(RecipeMealType).where(RecipeMealType.recipe_id == recipe.id))
    for meal_type in meal_types:
        db.add(RecipeMealType(recipe_id=recipe.id, meal_type=meal_type.value))


def _recipe_detail(db: Session, recipe: Recipe) -> RecipeDetail:
    version = _latest_version(db, recipe.id)
    if version is None:
        raise DomainError("CORRUPT_RECIPE", "The recipe has no version", 500)
    ingredients = []
    for row in version.ingredients:
        item = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        # Drafts created before ingredient parsing was introduced are enriched
        # on read. Saving the review persists these fields in the next immutable
        # recipe version without rewriting the historical import.
        if recipe.source_type == "url" and row.quantity is None and row.unit is None:
            parsed = parse_ingredient(row.original_text)
            item.update(
                quantity=parsed.quantity,
                unit=parsed.unit,
                quantity_grams=parsed.quantity_grams,
                food_phrase=(
                    parsed.food_phrase
                    if not row.food_phrase or row.food_phrase == row.original_text
                    else row.food_phrase
                ),
                preparation=row.preparation or parsed.preparation,
                optional=row.optional or parsed.optional,
                included=row.included and not parsed.optional,
            )
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
    if reported_values is None or not version.yield_servings:
        planner_warnings.append(
            "Complete publisher-reported per-serving nutrition and a serving yield are required."
        )
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
        publisher_nutrition=version.publisher_nutrition,
        calculated_nutrition=nutrition_values,
        nutrition_method=nutrition_method,
        review_count=(
            0
            if recipe.source_type == "url"
            else sum(1 for ingredient in version.ingredients if ingredient.included and ingredient.needs_review)
        ),
        meal_types=meal_types,
        planner_eligible=(
            effective_eligibility == RecipeEligibility.PLANNER_READY
            and reported_values is not None
            and bool(version.yield_servings)
            and bool(meal_types)
        ),
        planner_warnings=planner_warnings,
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
    meal_type: MealType | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    conditions = [Recipe.household_id == context.user.household_id, Recipe.archived_at.is_(None)]
    if q.strip():
        conditions.append(func.lower(Recipe.title).contains(q.strip().lower()))
    if meal_type is not None:
        conditions.append(
            Recipe.meal_type_tags.any(RecipeMealType.meal_type == meal_type.value)
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
            _recipe_detail(db, recipe).model_dump(
                mode="json",
                include=set(RecipeSummary.model_fields),
            )
            for recipe in recipes
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.post("/recipes", response_model=RecipeDetail, status_code=201)
def create_recipe(
    payload: RecipeCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    eligibility = RecipeEligibility.NEEDS_REVIEW.value
    if payload.yield_servings and payload.ingredients and not any(i.needs_review for i in payload.ingredients):
        eligibility = RecipeEligibility.DRAFT.value
    recipe = Recipe(
        household_id=context.user.household_id,
        title=payload.title,
        source_type=payload.source_type,
        source_url=payload.source_url,
        publisher=payload.publisher,
        image_url=payload.image_url,
        eligibility=eligibility,
    )
    db.add(recipe)
    db.flush()
    for meal_type in payload.meal_types:
        db.add(RecipeMealType(recipe_id=recipe.id, meal_type=meal_type.value))
    version = RecipeVersion(
        recipe_id=recipe.id,
        version_number=1,
        title=payload.title,
        yield_servings=payload.yield_servings,
        custom_instructions=payload.custom_instructions,
        publisher_nutrition=payload.publisher_nutrition,
    )
    db.add(version)
    db.flush()
    for position, item in enumerate(payload.ingredients):
        db.add(RecipeIngredient(recipe_version_id=version.id, position=position, **item.model_dump()))
    if publisher_values(version) is not None and version.yield_servings:
        recipe.eligibility = RecipeEligibility.PLANNER_READY.value
    db.commit()
    db.refresh(recipe)
    return _recipe_detail(db, recipe)


def _resync_plan_batches_after_review(
    db: Session,
    household_id: str,
    previous_version_id: str,
    next_version_id: str,
) -> None:
    """Move editable plans to the reviewed version without touching completed shopping."""

    batches = db.scalars(
        select(MealBatch)
        .join(MealPlan, MealPlan.id == MealBatch.meal_plan_id)
        .where(
            MealBatch.recipe_version_id == previous_version_id,
            MealPlan.household_id == household_id,
            MealPlan.status.in_([PlanStatus.READY.value, PlanStatus.ACCEPTED.value]),
        )
    ).all()
    plan_ids = sorted({batch.meal_plan_id for batch in batches})
    plans = {
        plan.id: plan
        for plan in db.scalars(
            select(MealPlan)
            .where(MealPlan.id.in_(plan_ids))
            .order_by(MealPlan.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    }
    # A replacement may have completed while this review waited for a plan
    # lock. Refresh the batches and only move those still using the reviewed
    # version so the newer choice is never overwritten.
    batch_ids = [batch.id for batch in batches]
    batches = db.scalars(
        select(MealBatch)
        .where(
            MealBatch.id.in_(batch_ids),
            MealBatch.recipe_version_id == previous_version_id,
        )
        .execution_options(populate_existing=True)
    ).all()
    reserve_again: list[MealBatch] = []
    changed_plans: set[str] = set()
    for batch in batches:
        plan = plans.get(batch.meal_plan_id)
        if plan is None or plan.status not in {
            PlanStatus.READY.value,
            PlanStatus.ACCEPTED.value,
        }:
            continue
        if plan.status == PlanStatus.ACCEPTED.value:
            has_shopping_list = db.scalar(
                select(ShoppingList.id).where(ShoppingList.meal_plan_id == plan.id).limit(1)
            )
            if has_shopping_list:
                continue
            db.execute(
                delete(PantryReservation).where(PantryReservation.meal_batch_id == batch.id)
            )
            reserve_again.append(batch)
        batch.recipe_version_id = next_version_id
        changed_plans.add(plan.id)
    for plan_id in changed_plans:
        plans[plan_id].version += 1
    if reserve_again:
        db.flush()
        reserve_plan_batches(db, household_id, reserve_again)


@router.get("/recipes/{recipe_id}", response_model=RecipeDetail)
def get_recipe(
    recipe_id: str,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.household_id != context.user.household_id:
        raise NotFoundError("Recipe")
    return _recipe_detail(db, recipe)


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
    if recipe is None or recipe.household_id != context.user.household_id:
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
        custom_instructions=previous.custom_instructions,
        source_checksum=previous.source_checksum,
        publisher_nutrition=previous.publisher_nutrition,
    )
    db.add(next_version)
    db.flush()
    for position, item in enumerate(payload.ingredients):
        db.add(
            RecipeIngredient(
                recipe_version_id=next_version.id,
                position=position,
                **item.model_dump(),
            )
        )
    if payload.meal_types is not None:
        _replace_meal_types(db, recipe, payload.meal_types)
    recipe.title = payload.title
    recipe.eligibility = (
        RecipeEligibility.PLANNER_READY.value
        if publisher_values(next_version) is not None
        else RecipeEligibility.DRAFT.value
    )
    recipe.version += 1
    _resync_plan_batches_after_review(
        db,
        context.user.household_id,
        previous.id,
        next_version.id,
    )
    db.commit()
    db.refresh(recipe)
    return _recipe_detail(db, recipe)


@router.post("/recipes/{recipe_id}/calculate", response_model=NutritionCalculationOut)
def calculate(
    recipe_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.household_id != context.user.household_id:
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
    _: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    cleaned_query = normalise_food_query(q.strip()) if q.strip() else ""
    conditions = []
    if cleaned_query:
        terms = tuple(dict.fromkeys(cleaned_query.lower().split()))
        conditions.append(or_(*(func.lower(FoodRecord.name).contains(term) for term in terms)))
    total = db.scalar(select(func.count(FoodRecord.id)).where(*conditions)) or 0
    remote_error = None
    settings = get_settings()
    if cleaned_query and total < 3 and settings.remote_food_search_enabled:
        try:
            fetch_and_cache_usda_foods(db, cleaned_query, api_key=settings.usda_api_key)
            total = db.scalar(select(func.count(FoodRecord.id)).where(*conditions)) or 0
        except Exception:
            remote_error = "FoodData Central could not be reached. Existing local matches are still shown."
    rows = db.scalars(
        select(FoodRecord)
        .where(*conditions)
        .order_by(FoodRecord.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = []
    for food in rows:
        items.append(
            FoodRecordOut(
                **{column.name: getattr(food, column.name) for column in food.__table__.columns},
                nutrients=[
                    {column.name: getattr(n, column.name) for column in n.__table__.columns}
                    for n in food.nutrients
                ],
            ).model_dump(mode="json")
        )
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "remote_error": remote_error,
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
