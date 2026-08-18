from collections import defaultdict, deque
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import re
import threading
import time

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import flag_modified

from ..auth import AuthContext, get_auth_context, require_csrf
from ..db import get_db
from ..errors import ConflictError, DomainError, NotFoundError
from ..models import (
    HouseholdMember,
    Household,
    MealAllocation,
    MealBatch,
    MealOccurrence,
    MealPlan,
    PantryLot,
    PantryReservation,
    PantryTransaction,
    PlanStatus,
    PortionAllocation,
    Recipe,
    RecipeMealType,
    RecipeVersion,
    Restriction,
    ShoppingList,
    TargetProfile,
)
from ..schemas import (
    BatchCookedWeightUpdate,
    PlanGenerateRequest,
    PlanOut,
    PlanPreservingEditRequest,
    PlanRecipeReplaceRequest,
    PlanSideCreateRequest,
    PlanSideRemoveRequest,
)
from ..services.nutrition import planning_values
from ..services.pantry import reserve_plan_batches
from ..services.planner import (
    ParticipantTarget,
    PlanPortionVariable,
    PlannerInfeasibleError,
    BOOST_PORTIONS,
    PORTIONS,
    RecipeCandidate,
    SIDE_PORTIONS,
    aggregate_nutrition_issues,
    choose_shared_recipe,
    recipe_portions,
    rebalance_plan_portions,
)
from ..services.regional_ingredients import equivalent_terms
from ..services.shopping import build_shopping_list

router = APIRouter(prefix="/meal-plans", tags=["meal planning"])
_generation_lock = threading.Lock()
_active_generation_households: set[str] = set()
_generation_attempts: dict[str, deque[float]] = defaultdict(deque)


def limit_plan_generation(
    context: AuthContext = Depends(require_csrf),
):
    """Allow one bounded generation per household and ten starts per minute."""

    now = time.monotonic()
    with _generation_lock:
        attempts = _generation_attempts[context.user.household_id]
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= 10:
            raise DomainError(
                "PLAN_RATE_LIMITED",
                "Too many meal plans were started. Wait before trying again.",
                429,
            )
        if context.user.household_id in _active_generation_households:
            raise DomainError(
                "PLAN_ALREADY_RUNNING",
                "A meal plan is already being generated for this household.",
                409,
            )
        attempts.append(now)
        _active_generation_households.add(context.user.household_id)
    try:
        yield context
    finally:
        with _generation_lock:
            _active_generation_households.discard(context.user.household_id)


def _candidate(db: Session, recipe: Recipe, meal_type: str) -> RecipeCandidate | None:
    tagged = db.scalar(
        select(RecipeMealType.id).where(
            RecipeMealType.recipe_id == recipe.id,
            RecipeMealType.meal_type == meal_type.casefold(),
        )
    )
    if tagged is None:
        return None
    version = db.scalar(
        select(RecipeVersion)
        .where(RecipeVersion.recipe_id == recipe.id)
        .order_by(RecipeVersion.version_number.desc())
    )
    return _candidate_from_version(db, recipe, version)


def _side_tags(meal_type: str) -> tuple[str, ...]:
    return ("snack",) if meal_type.casefold() == "snack" else ("side", "snack")


def _side_candidate(
    db: Session, recipe: Recipe, meal_type: str
) -> RecipeCandidate | None:
    tagged = db.scalar(
        select(RecipeMealType.id).where(
            RecipeMealType.recipe_id == recipe.id,
            RecipeMealType.meal_type.in_(_side_tags(meal_type)),
        )
    )
    if tagged is None:
        return None
    version = db.scalar(
        select(RecipeVersion)
        .where(RecipeVersion.recipe_id == recipe.id)
        .order_by(RecipeVersion.version_number.desc())
    )
    return _candidate_from_version(db, recipe, version)


def _candidate_from_version(
    db: Session, recipe: Recipe, version: RecipeVersion | None
) -> RecipeCandidate | None:
    if version is None or not version.yield_servings:
        return None
    nutrition = planning_values(db, version)
    if nutrition is None:
        return None
    included_ingredients = [item for item in version.ingredients if item.included]
    return RecipeCandidate(
        recipe_id=recipe.id,
        recipe_version_id=version.id,
        nutrition=nutrition,
        minimum_servings=version.minimum_servings,
        serving_increment=version.serving_increment,
        food_record_ids=frozenset(
            item.food_record_id
            for item in included_ingredients
            if item.food_record_id
        ),
        ingredient_text=" ".join(
            (item.food_phrase or item.original_text).casefold()
            for item in included_ingredients
        ),
    )


def _restriction_terms(
    db: Session, member_ids: list[str]
) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    if not member_ids:
        return frozenset(), frozenset(), frozenset()
    restrictions = db.scalars(
        select(Restriction).where(Restriction.member_id.in_(member_ids))
    ).all()
    hard = frozenset(
        restriction.value.strip().casefold()
        for restriction in restrictions
        if restriction.hard and restriction.value.strip()
    )
    preferred = frozenset(
        restriction.value.strip().casefold()
        for restriction in restrictions
        if restriction.kind == "prefer" and restriction.value.strip()
    )
    disliked = frozenset(
        restriction.value.strip().casefold()
        for restriction in restrictions
        if restriction.kind == "dislike" and restriction.value.strip()
    )
    return hard, preferred, disliked


def _normalise_ingredient_terms(values: list[str]) -> frozenset[str]:
    return frozenset(
        " ".join(value.casefold().split()) for value in values if value.strip()
    )


def _expanded_ingredient_terms(db: Session, values: list[str]) -> frozenset[str]:
    return _normalise_ingredient_terms(
        [term for value in values for term in equivalent_terms(db, value)]
    )


def _matching_ingredient_terms(
    candidate: RecipeCandidate, terms: frozenset[str]
) -> frozenset[str]:
    return frozenset(
        term
        for term in terms
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", candidate.ingredient_text)
    )


def _plan_guidance(plan: MealPlan) -> dict[str, list[str]]:
    for diagnostic in plan.diagnostics or []:
        if isinstance(diagnostic, dict) and diagnostic.get("code") == "GENERATION_GUIDANCE":
            return {
                "must_use_food_record_ids": list(
                    diagnostic.get("must_use_food_record_ids") or []
                ),
                "prefer_food_record_ids": list(
                    diagnostic.get("prefer_food_record_ids") or []
                ),
                "exclude_food_record_ids": list(
                    diagnostic.get("exclude_food_record_ids") or []
                ),
                "must_use_ingredient_terms": list(
                    diagnostic.get("must_use_ingredient_terms") or []
                ),
                "prefer_ingredient_terms": list(
                    diagnostic.get("prefer_ingredient_terms") or []
                ),
                "exclude_ingredient_terms": list(
                    diagnostic.get("exclude_ingredient_terms") or []
                ),
            }
    return {
        "must_use_food_record_ids": [],
        "prefer_food_record_ids": [],
        "exclude_food_record_ids": [],
        "must_use_ingredient_terms": [],
        "prefer_ingredient_terms": [],
        "exclude_ingredient_terms": [],
    }


def _validate_mutable_plan_constraints(
    db: Session,
    plan: MealPlan,
    *,
    replacement_batch_id: str | None = None,
    replacement_candidate: RecipeCandidate | None = None,
) -> None:
    """Recheck mutable tags, ingredients and household rules before plan changes."""

    guidance = _plan_guidance(plan)
    excluded_foods = frozenset(guidance["exclude_food_record_ids"])
    excluded_terms = _expanded_ingredient_terms(
        db, guidance["exclude_ingredient_terms"]
    )
    must_use_terms = _normalise_ingredient_terms(
        guidance["must_use_ingredient_terms"]
    )
    covered_foods: set[str] = set()
    covered_terms: set[str] = set()
    remediation_occurrence: MealOccurrence | None = None
    remediation_batch: MealBatch | None = None

    def picker_href(batch: MealBatch, occurrence: MealOccurrence) -> str:
        if batch.parent_batch_id is not None:
            return (
                f"/plan/{plan.id}/batches/{batch.parent_batch_id}/sides/"
                f"{batch.component_slot}/recipes?mealType={occurrence.meal_type}"
            )
        return (
            f"/plan/{plan.id}/occurrences/{occurrence.id}/recipes"
            f"?mealType={occurrence.meal_type}"
        )
    batches = db.scalars(
        select(MealBatch).where(MealBatch.meal_plan_id == plan.id)
    ).all()
    for batch in batches:
        if batch.id == replacement_batch_id and replacement_candidate is not None:
            candidate = replacement_candidate
            recipe = db.get(Recipe, candidate.recipe_id)
        else:
            version = db.get(RecipeVersion, batch.recipe_version_id)
            recipe = db.get(Recipe, version.recipe_id) if version is not None else None
            candidate = (
                _candidate_from_version(db, recipe, version)
                if recipe is not None
                else None
            )
        if recipe is None or candidate is None:
            actions = []
            if recipe is not None:
                actions.append(
                    {
                        "kind": "review_recipe",
                        "label": f"Review {recipe.title}",
                        "href": f"/recipes/{recipe.id}/review",
                        "suggestion": (
                            "Confirm the recipe yield and complete nutrition, then return to the plan."
                        ),
                        "recipe_id": recipe.id,
                        "batch_id": batch.id,
                    }
                )
            raise DomainError(
                "INVALID_BATCH",
                "A planned recipe no longer has complete nutrition and a serving yield",
                actions=actions,
            )
        occurrences = db.scalars(
            select(MealOccurrence).where(MealOccurrence.batch_id == batch.id)
        ).all()
        if not occurrences:
            raise DomainError(
                "INVALID_BATCH", "A planned recipe batch no longer has any meal occurrences"
            )
        if remediation_occurrence is None:
            remediation_occurrence = occurrences[0]
            remediation_batch = batch
        meal_types = {occurrence.meal_type for occurrence in occurrences}
        for meal_type in meal_types:
            required_tags = (
                _side_tags(meal_type) if batch.parent_batch_id is not None else (meal_type,)
            )
            tagged = db.scalar(
                select(RecipeMealType.id).where(
                    RecipeMealType.recipe_id == recipe.id,
                    RecipeMealType.meal_type.in_(required_tags),
                )
            )
            if tagged is None:
                tag_description = " or ".join(required_tags)
                raise DomainError(
                    "RECIPE_MEAL_TYPE_REVIEW_REQUIRED",
                    f"{recipe.title} is no longer tagged for {tag_description}",
                    actions=[
                        {
                            "kind": "review_recipe",
                            "label": f"Update tags for {recipe.title}",
                            "href": f"/recipes/{recipe.id}/review",
                            "suggestion": (
                                f"Add a {tag_description} tag, then return and accept the plan again."
                            ),
                            "recipe_id": recipe.id,
                            "recipe_version_id": candidate.recipe_version_id,
                            "batch_id": batch.id,
                        }
                    ],
                )
        if (
            candidate.food_record_ids & excluded_foods
            or _matching_ingredient_terms(candidate, excluded_terms)
        ):
            occurrence = occurrences[0]
            raise DomainError(
                "PLAN_EXCLUDED_INGREDIENT",
                f"{recipe.title} now contains an ingredient excluded from this plan",
                actions=[
                    {
                        "kind": "replace_recipe",
                        "label": "Choose another recipe",
                        "href": picker_href(batch, occurrence),
                        "suggestion": (
                            "Choose a recipe that does not contain the plan-specific exclusion."
                        ),
                        "recipe_id": recipe.id,
                        "recipe_version_id": candidate.recipe_version_id,
                        "batch_id": batch.id,
                    }
                ],
            )
        member_ids = sorted(
            {
                allocation.member_id
                for occurrence in occurrences
                for allocation in db.scalars(
                    select(PortionAllocation).where(
                        PortionAllocation.meal_occurrence_id == occurrence.id
                    )
                ).all()
            }
        )
        hard_terms, _, _ = _restriction_terms(db, member_ids)
        matched_hard_terms = [
            term
            for term in hard_terms
            if re.search(rf"\b{re.escape(term)}\b", candidate.ingredient_text)
        ]
        if matched_hard_terms:
            occurrence = occurrences[0]
            raise DomainError(
                "RECIPE_RESTRICTED",
                f"{recipe.title} conflicts with a participating member's hard restriction",
                actions=[
                    {
                        "kind": "replace_recipe",
                        "label": "Choose a safe recipe",
                        "href": picker_href(batch, occurrence),
                        "suggestion": (
                            "Choose another recipe that respects the household restriction."
                        ),
                        "recipe_id": recipe.id,
                        "recipe_version_id": candidate.recipe_version_id,
                        "batch_id": batch.id,
                    }
                ],
            )
        covered_foods.update(candidate.food_record_ids)
        covered_terms.update(
            _matching_ingredient_terms(
                candidate,
                must_use_terms,
            )
        )
    missing_must_use = set(guidance["must_use_food_record_ids"]) - covered_foods
    missing_must_use_terms = (
        must_use_terms - covered_terms
    )
    if missing_must_use or missing_must_use_terms:
        actions = []
        if remediation_occurrence is not None and remediation_batch is not None:
            actions.append(
                {
                    "kind": "replace_recipe",
                    "label": "Choose a recipe using it",
                    "href": picker_href(remediation_batch, remediation_occurrence),
                    "suggestion": (
                        "Choose a recipe that restores the missing must-use ingredient, "
                        "or build the plan again without that requirement."
                    ),
                }
            )
        raise DomainError(
            "MUST_USE_INGREDIENT_INFEASIBLE",
            "This change would remove the only planned use of a must-use ingredient",
            actions=actions,
        )


def _target_for(
    db: Session,
    member_id: str,
    meal_type: str,
    household_id: str,
    daily_calorie_boost: Decimal = Decimal("0"),
    meal_calorie_boost: Decimal = Decimal("0"),
) -> ParticipantTarget:
    member = db.get(HouseholdMember, member_id)
    if member is None or member.household_id != household_id or not member.active:
        raise DomainError("INVALID_PARTICIPANT", "A meal participant is invalid")
    target = db.scalar(select(TargetProfile).where(TargetProfile.member_id == member.id))
    if target is None:
        raise DomainError("MISSING_TARGET", f"{member.name} has no nutrition target")
    allocation = db.scalar(
        select(MealAllocation).where(
            MealAllocation.target_profile_id == target.id,
            MealAllocation.meal_type == meal_type.lower(),
        )
    )
    if allocation is None:
        raise DomainError("MISSING_MEAL_ALLOCATION", f"No target allocation exists for {meal_type}")
    if (daily_calorie_boost or meal_calorie_boost) and target.mode != "calorie":
        raise DomainError(
            "CALORIE_BOOST_REQUIRES_CALORIE_TARGET",
            f"{member.name} uses macro targets, so a calorie boost cannot be applied",
            422,
        )
    allocation_percentage = Decimal(allocation.percentage)
    equivalent_daily_boost = daily_calorie_boost
    if meal_calorie_boost:
        equivalent_daily_boost += meal_calorie_boost * Decimal("100") / allocation_percentage
    return ParticipantTarget(
        member_id=member.id,
        mode=target.mode,
        allocation=allocation_percentage,
        calorie_target=(
            Decimal(target.calorie_target or 0) + equivalent_daily_boost
            if target.mode == "calorie"
            else target.calorie_target
        ),
        protein_target_g=target.protein_target_g,
        carbohydrate_target_g=target.carbohydrate_target_g,
        fat_target_g=target.fat_target_g,
        tolerance_percent=Decimal(target.tolerance_percent),
        protein_min_g=target.protein_min_g,
        protein_max_g=target.protein_max_g,
        carbohydrate_min_g=target.carbohydrate_min_g,
        carbohydrate_max_g=target.carbohydrate_max_g,
        fat_min_g=target.fat_min_g,
        fat_max_g=target.fat_max_g,
    )


def _calorie_boost_maps(
    plan: MealPlan,
) -> tuple[dict[tuple[str, str], Decimal], dict[tuple[str, str, str], Decimal]]:
    daily: dict[tuple[str, str], Decimal] = {}
    by_meal: dict[tuple[str, str, str], Decimal] = {}
    for item in plan.calorie_boosts or []:
        calories = Decimal(str(item["calories"]))
        allocations = item.get("meal_allocations") or []
        if not allocations:
            daily[(item["meal_date"], item["member_id"])] = calories
            continue
        for allocation in allocations:
            by_meal[(item["meal_date"], item["member_id"], allocation["meal_type"])] = (
                calories * Decimal(str(allocation["percentage"])) / Decimal("100")
            )
    return daily, by_meal


def _guest_count_map(plan: MealPlan) -> dict[tuple[str, str, str], int]:
    result: dict[tuple[str, str, str], int] = {}
    for item in plan.guest_days or []:
        if item.get("meal_groups"):
            for group in item["meal_groups"]:
                result[
                    (item["meal_date"], group["meal_type"], group["meal_group_key"])
                ] = int(item["guest_count"])
        else:
            for meal_type in item.get("meal_types") or ["*"]:
                result[(item["meal_date"], meal_type, "*")] = int(
                    item["guest_count"]
                )
    return result


def _guest_payload(guest_day) -> dict:
    data = guest_day.model_dump(mode="json")
    if not data.get("meal_groups"):
        data.pop("meal_groups", None)
    return data


def _rebalance_plan(
    db: Session,
    plan: MealPlan,
    *,
    ignore_nutrition_tolerances: bool,
    infeasible_detail: str = "The selected meal combination could not meet every daily nutrition target.",
) -> None:
    """Quantify every fixed recipe together after the plan composition changes."""
    batches = db.scalars(
        select(MealBatch).where(MealBatch.meal_plan_id == plan.id)
    ).all()
    variables: list[PlanPortionVariable] = []
    allocations_by_variable: dict[str, list[PortionAllocation]] = {}
    daily_targets: dict[tuple[str, str], list[ParticipantTarget]] = defaultdict(list)
    daily_calorie_boosts, meal_calorie_boosts = _calorie_boost_maps(plan)

    for batch in batches:
        version = db.get(RecipeVersion, batch.recipe_version_id)
        nutrition = planning_values(db, version)
        if version is None or nutrition is None:
            raise DomainError(
                "INVALID_BATCH",
                "A planned recipe no longer has complete nutrition",
            )
        occurrences = db.scalars(
            select(MealOccurrence)
            .where(MealOccurrence.batch_id == batch.id)
            .order_by(MealOccurrence.meal_date)
        ).all()
        for occurrence in occurrences:
            allocations = db.scalars(
                select(PortionAllocation).where(
                    PortionAllocation.meal_occurrence_id == occurrence.id
                )
            ).all()
            for allocation in allocations:
                date_text = occurrence.meal_date.isoformat()
                explicit_meal_boost = meal_calorie_boosts.get(
                    (date_text, allocation.member_id, occurrence.meal_type),
                    Decimal("0"),
                )
                participant_target = None
                if batch.parent_batch_id is None:
                    participant_target = _target_for(
                        db,
                        allocation.member_id,
                        occurrence.meal_type,
                        plan.household_id,
                        daily_calorie_boosts.get(
                            (date_text, allocation.member_id), Decimal("0")
                        ),
                        explicit_meal_boost,
                    )
                    daily_targets[(date_text, allocation.member_id)].append(
                        participant_target
                    )
                key = f"{occurrence.id}:{allocation.member_id}"
                standard_portions = (
                    SIDE_PORTIONS
                    if batch.parent_batch_id is not None
                    else BOOST_PORTIONS
                    if daily_calorie_boosts.get(
                        (date_text, allocation.member_id), Decimal("0")
                    ) > 0
                    or explicit_meal_boost > 0
                    else PORTIONS
                )
                variables.append(
                    PlanPortionVariable(
                        key=key,
                        member_id=allocation.member_id,
                        dates=(date_text,),
                        nutrition=nutrition,
                        current=Decimal(allocation.servings),
                        allowed=(
                            (Decimal(allocation.servings),)
                            if batch.cooked_at is not None
                            else recipe_portions(
                                standard_portions,
                                version.minimum_servings,
                                version.serving_increment,
                            )
                        ),
                        meal_type=occurrence.meal_type,
                        component_slot=batch.component_slot,
                        meal_target=(
                            participant_target if explicit_meal_boost > 0 else None
                        ),
                    )
                )
                allocations_by_variable[key] = [allocation]

    portions = rebalance_plan_portions(
        variables, daily_targets, enforce_nutrition_bounds=False
    )
    daily_nutrition: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )
    for variable in variables:
        portion = portions[variable.key]
        for date_text in variable.dates:
            for nutrient, amount in variable.nutrition.items():
                daily_nutrition[(date_text, variable.member_id)][nutrient] += amount * portion

    failures: list[dict] = []
    if not ignore_nutrition_tolerances:
        for (date_text, member_id), targets in daily_targets.items():
            violations = aggregate_nutrition_issues(
                targets, daily_nutrition[(date_text, member_id)]
            )
            if violations:
                member = db.get(HouseholdMember, member_id)
                failures.append(
                    {
                        "date": date_text,
                        "member": member.name if member else member_id,
                        "violations": violations,
                    }
                )
    if failures:
        raise DomainError(
            "NUTRITION_TARGET_INFEASIBLE",
            infeasible_detail,
            422,
            actions=[
                {
                    "kind": "retry_best_effort",
                    "label": "Continue anyway",
                    "suggestion": "Use the closest whole-plan portions for these recipes.",
                }
            ],
            issues=failures,
        )

    for variable in variables:
        for allocation in allocations_by_variable[variable.key]:
            allocation.servings = portions[variable.key]
    guest_counts = _guest_count_map(plan)
    for occurrence in db.scalars(
        select(MealOccurrence).where(MealOccurrence.meal_plan_id == plan.id)
    ).all():
        allocations = db.scalars(
            select(PortionAllocation).where(
                PortionAllocation.meal_occurrence_id == occurrence.id
            )
        ).all()
        largest_household_portion = max(
            (Decimal(allocation.servings) for allocation in allocations),
            default=Decimal("0"),
        )
        occurrence.guest_servings = (
            Decimal(
                guest_counts.get(
                    (
                        occurrence.meal_date.isoformat(),
                        occurrence.meal_type,
                        occurrence.meal_group_key,
                    ),
                    guest_counts.get(
                        (occurrence.meal_date.isoformat(), occurrence.meal_type, "*"),
                        guest_counts.get(
                            (occurrence.meal_date.isoformat(), "*", "*"), 0
                        ),
                    ),
                )
            )
            * largest_household_portion
        )
    for batch in batches:
        if batch.cooked_at is not None:
            continue
        batch.servings = sum(
            (
                sum(
                    (
                        Decimal(allocation.servings)
                        for allocation in db.scalars(
                            select(PortionAllocation).where(
                                PortionAllocation.meal_occurrence_id == occurrence.id
                            )
                        ).all()
                    ),
                    Decimal("0"),
                )
                + Decimal(occurrence.guest_servings)
                for occurrence in db.scalars(
                    select(MealOccurrence).where(MealOccurrence.batch_id == batch.id)
                ).all()
            ),
            Decimal("0"),
        )


def _normalised_boosts(items: list[dict], dates: set[str]) -> dict[tuple[str, str], tuple]:
    return {
        (str(item["meal_date"]), str(item["member_id"])): (
            Decimal(str(item["calories"])),
            tuple(
                sorted(
                    (
                        str(allocation["meal_type"]),
                        int(allocation["percentage"]),
                    )
                    for allocation in item.get("meal_allocations") or []
                )
            ),
        )
        for item in items
        if str(item["meal_date"]) in dates
    }


def _normalised_guests(items: list[dict], dates: set[str]) -> dict[str, tuple]:
    return {
        str(item["meal_date"]): (
            int(item["guest_count"]),
            tuple(sorted(str(meal_type) for meal_type in item.get("meal_types") or [])),
            tuple(
                sorted(
                    (
                        str(group["meal_type"]),
                        str(group["meal_group_key"]),
                    )
                    for group in item.get("meal_groups") or []
                )
            ),
        )
        for item in items
        if str(item["meal_date"]) in dates
    }


def _selected_main_recipe_candidate(
    db: Session,
    plan: MealPlan,
    recipe_id: str,
    meal_type: str,
) -> RecipeCandidate:
    recipe = db.get(Recipe, recipe_id)
    if (
        recipe is None
        or recipe.household_id != plan.household_id
        or recipe.archived_at is not None
    ):
        raise NotFoundError("Recipe")
    tagged = db.scalar(
        select(RecipeMealType.id).where(
            RecipeMealType.recipe_id == recipe.id,
            RecipeMealType.meal_type == meal_type,
        )
    )
    if tagged is None:
        raise DomainError(
            "RECIPE_MEAL_TYPE_MISMATCH",
            f"Choose a recipe tagged for {meal_type}",
            422,
        )
    candidate = _candidate(db, recipe, meal_type)
    if candidate is None:
        raise DomainError(
            "RECIPE_NOT_PLANNER_READY",
            "The selected recipe needs complete nutrition, a yield and the matching meal tag",
            422,
        )
    return candidate


def _batch_tree_is_cooked(db: Session, batch: MealBatch) -> bool:
    if batch.cooked_at is not None:
        return True
    return db.scalar(
        select(MealBatch.id)
        .where(
            MealBatch.parent_batch_id == batch.id,
            MealBatch.cooked_at.is_not(None),
        )
        .limit(1)
    ) is not None


def _split_batch_for_new_cook_day(
    db: Session,
    plan: MealPlan,
    meal_date: date,
    meal_type: str,
    meal_group_key: str,
    recipe_id: str,
) -> None:
    boundary = db.scalar(
        select(MealOccurrence).where(
            MealOccurrence.meal_plan_id == plan.id,
            MealOccurrence.meal_date == meal_date,
            MealOccurrence.meal_type == meal_type,
            MealOccurrence.meal_group_key == meal_group_key,
            MealOccurrence.component_slot == 0,
        )
    )
    if boundary is None:
        raise DomainError(
            "INVALID_COOK_DAY",
            "A new cooking day must start on an existing planned meal",
            422,
        )
    old_batch = db.get(MealBatch, boundary.batch_id)
    if old_batch is None or old_batch.parent_batch_id is not None:
        raise DomainError("INVALID_COOK_DAY", "The selected meal batch is invalid", 422)
    if _batch_tree_is_cooked(db, old_batch):
        raise DomainError(
            "COOKED_DAY_LOCKED",
            "A cooked batch cannot be split into a new cooking day",
            409,
        )
    if old_batch.planned_cook_date == meal_date:
        raise DomainError(
            "COOK_DAY_EXISTS",
            "This meal already starts a new cooking batch on that day",
            409,
        )

    moving = db.scalars(
        select(MealOccurrence)
        .where(
            MealOccurrence.batch_id == old_batch.id,
            MealOccurrence.meal_date >= meal_date,
            MealOccurrence.component_slot == 0,
        )
        .order_by(MealOccurrence.meal_date)
    ).all()
    if not moving:
        raise DomainError("INVALID_COOK_DAY", "No meals follow this cooking day", 422)
    candidate = _selected_main_recipe_candidate(db, plan, recipe_id, meal_type)
    old_version = db.get(RecipeVersion, old_batch.recipe_version_id)
    if old_version is not None and old_version.recipe_id == candidate.recipe_id:
        raise DomainError(
            "COOK_DAY_RECIPE_UNCHANGED",
            "Choose a different recipe for the new cooking day",
            422,
        )
    new_batch = MealBatch(
        meal_plan_id=plan.id,
        recipe_version_id=candidate.recipe_version_id,
        servings=Decimal("1"),
        planned_cook_date=meal_date,
    )
    db.add(new_batch)
    db.flush()
    for occurrence in moving:
        occurrence.batch_id = new_batch.id

    side_batches = db.scalars(
        select(MealBatch).where(MealBatch.parent_batch_id == old_batch.id)
    ).all()
    for side_batch in side_batches:
        side_occurrences = db.scalars(
            select(MealOccurrence)
            .where(MealOccurrence.batch_id == side_batch.id)
            .order_by(MealOccurrence.meal_date)
        ).all()
        moving_sides = [
            occurrence
            for occurrence in side_occurrences
            if occurrence.meal_date >= meal_date
        ]
        if not moving_sides:
            continue
        if len(moving_sides) == len(side_occurrences):
            side_batch.parent_batch_id = new_batch.id
            side_batch.planned_cook_date = meal_date
            continue
        new_side_batch = MealBatch(
            meal_plan_id=plan.id,
            recipe_version_id=side_batch.recipe_version_id,
            servings=Decimal("1"),
            planned_cook_date=meal_date,
            parent_batch_id=new_batch.id,
            component_slot=side_batch.component_slot,
        )
        db.add(new_side_batch)
        db.flush()
        for occurrence in moving_sides:
            occurrence.batch_id = new_side_batch.id
    db.flush()


def _remove_cook_day(
    db: Session,
    plan: MealPlan,
    meal_date: date,
    meal_type: str,
    meal_group_key: str,
) -> None:
    boundary = db.scalar(
        select(MealOccurrence).where(
            MealOccurrence.meal_plan_id == plan.id,
            MealOccurrence.meal_date == meal_date,
            MealOccurrence.meal_type == meal_type,
            MealOccurrence.meal_group_key == meal_group_key,
            MealOccurrence.component_slot == 0,
        )
    )
    if boundary is None:
        raise DomainError("INVALID_COOK_DAY", "The cooking day no longer exists", 422)
    current_batch = db.get(MealBatch, boundary.batch_id)
    if current_batch is None or current_batch.planned_cook_date != meal_date:
        raise DomainError(
            "COOK_DAY_NOT_BOUNDARY",
            "Only the first day of a cooking batch can be removed",
            422,
        )
    previous = db.scalar(
        select(MealOccurrence)
        .where(
            MealOccurrence.meal_plan_id == plan.id,
            MealOccurrence.meal_type == meal_type,
            MealOccurrence.meal_group_key == meal_group_key,
            MealOccurrence.component_slot == 0,
            MealOccurrence.meal_date < meal_date,
        )
        .order_by(MealOccurrence.meal_date.desc())
        .limit(1)
    )
    if previous is None:
        raise DomainError(
            "FIRST_COOK_DAY_REQUIRED",
            "The first cooking day for a meal cannot be removed",
            422,
        )
    previous_batch = db.get(MealBatch, previous.batch_id)
    if (
        _batch_tree_is_cooked(db, current_batch)
        or previous_batch is None
        or _batch_tree_is_cooked(db, previous_batch)
    ):
        raise DomainError(
            "COOKED_DAY_LOCKED",
            "A cooking boundary involving a cooked batch cannot be removed",
            409,
        )

    moving_main = db.scalars(
        select(MealOccurrence)
        .where(MealOccurrence.batch_id == current_batch.id)
        .order_by(MealOccurrence.meal_date)
    ).all()
    current_sides = db.scalars(
        select(MealBatch).where(MealBatch.parent_batch_id == current_batch.id)
    ).all()
    for side_batch in current_sides:
        side_occurrence_ids = list(
            db.scalars(
                select(MealOccurrence.id).where(
                    MealOccurrence.batch_id == side_batch.id
                )
            ).all()
        )
        if side_occurrence_ids:
            db.execute(
                delete(PortionAllocation).where(
                    PortionAllocation.meal_occurrence_id.in_(side_occurrence_ids)
                )
            )
            db.execute(
                delete(MealOccurrence).where(
                    MealOccurrence.id.in_(side_occurrence_ids)
                )
            )
        db.delete(side_batch)
    db.flush()

    previous_sides = db.scalars(
        select(MealBatch).where(MealBatch.parent_batch_id == previous_batch.id)
    ).all()
    for occurrence in moving_main:
        occurrence.batch_id = previous_batch.id
        main_allocations = db.scalars(
            select(PortionAllocation).where(
                PortionAllocation.meal_occurrence_id == occurrence.id
            )
        ).all()
        for side_batch in previous_sides:
            side_occurrence = MealOccurrence(
                meal_plan_id=plan.id,
                batch_id=side_batch.id,
                meal_date=occurrence.meal_date,
                meal_type=occurrence.meal_type,
                meal_group_key=occurrence.meal_group_key,
                component_slot=side_batch.component_slot,
            )
            db.add(side_occurrence)
            db.flush()
            for allocation in main_allocations:
                db.add(
                    PortionAllocation(
                        meal_occurrence_id=side_occurrence.id,
                        member_id=allocation.member_id,
                        servings=Decimal("0.25"),
                    )
                )
    db.flush()
    db.delete(current_batch)
    db.flush()


@router.post("/generate", response_model=PlanOut, status_code=201)
def generate_plan(
    payload: PlanGenerateRequest,
    context: AuthContext = Depends(limit_plan_generation),
    db: Session = Depends(get_db),
):
    if not payload.slots:
        raise DomainError("NO_PLAN_SLOTS", "At least one meal slot is required")
    slot_keys = [
        (slot.meal_date, slot.meal_type.casefold(), slot.meal_group_key)
        for slot in payload.slots
    ]
    if len(set(slot_keys)) != len(slot_keys):
        raise DomainError(
            "DUPLICATE_PLAN_SLOT",
            "A date, meal type and meal group can only be planned once",
        )
    participant_slots = [
        (slot.meal_date, slot.meal_type.casefold(), member_id)
        for slot in payload.slots
        for member_id in slot.participant_member_ids
    ]
    if len(participant_slots) != len(set(participant_slots)):
        raise DomainError(
            "DUPLICATE_MEAL_PARTICIPANT",
            "A household member can only belong to one recipe group per meal",
            422,
        )
    participant_days = {
        (slot.meal_date, member_id)
        for slot in payload.slots
        for member_id in slot.participant_member_ids
    }
    for boost in payload.calorie_boosts:
        if (boost.meal_date, boost.member_id) not in participant_days:
            raise DomainError(
                "INVALID_CALORIE_BOOST",
                "A calorie boost must belong to someone eating on that date",
                422,
            )
        attended_meals = {
            slot.meal_type
            for slot in payload.slots
            if slot.meal_date == boost.meal_date
            and boost.member_id in slot.participant_member_ids
        }
        if any(item.meal_type not in attended_meals for item in boost.meal_allocations):
            raise DomainError(
                "INVALID_CALORIE_BOOST_MEAL",
                "Calorie boosts can only be assigned to meals that person is eating",
                422,
            )
    planned_dates = {slot.meal_date for slot in payload.slots}
    for guest_day in payload.guest_days:
        if guest_day.meal_date not in planned_dates:
            raise DomainError(
                "INVALID_GUEST_DAY",
                "Guests can only be added to a date with at least one planned meal",
                422,
            )
        planned_meals = {
            slot.meal_type
            for slot in payload.slots
            if slot.meal_date == guest_day.meal_date
        }
        if any(meal_type not in planned_meals for meal_type in guest_day.meal_types):
            raise DomainError(
                "INVALID_GUEST_MEAL",
                "Guests can only attend meals that are planned for that date",
                422,
            )
        for assignment in guest_day.meal_groups:
            if not any(
                slot.meal_date == guest_day.meal_date
                and slot.meal_type == assignment.meal_type
                and slot.meal_group_key == assignment.meal_group_key
                for slot in payload.slots
            ):
                raise DomainError(
                    "INVALID_GUEST_MEAL_GROUP",
                    "Guests must join a recipe group planned for that meal",
                    422,
                )
    recipe_conditions = [
        Recipe.household_id == context.user.household_id,
        Recipe.archived_at.is_(None),
    ]
    if payload.recipe_ids:
        recipe_conditions.append(Recipe.id.in_(payload.recipe_ids))
    recipes = db.scalars(
        select(Recipe)
        .options(selectinload(Recipe.meal_type_tags))
        .where(*recipe_conditions)
    ).all()
    if not recipes:
        raise DomainError("NO_ELIGIBLE_RECIPES", "No selected recipe is planner-ready")
    excluded_foods = frozenset(payload.exclude_food_record_ids)
    remaining_must_use = set(payload.must_use_food_record_ids)
    preferred_foods = frozenset(payload.prefer_food_record_ids)
    excluded_ingredient_terms = _expanded_ingredient_terms(
        db, payload.exclude_ingredient_terms
    )
    remaining_must_use_terms = set(
        _normalise_ingredient_terms(payload.must_use_ingredient_terms)
    )
    preferred_ingredient_terms = _expanded_ingredient_terms(
        db, payload.prefer_ingredient_terms
    )

    dates = [slot.meal_date for slot in payload.slots]
    daily_calorie_boosts: dict[tuple[str, str], Decimal] = {}
    meal_calorie_boosts: dict[tuple[str, str, str], Decimal] = {}
    for boost in payload.calorie_boosts:
        date_text = boost.meal_date.isoformat()
        if not boost.meal_allocations:
            daily_calorie_boosts[(date_text, boost.member_id)] = Decimal(boost.calories)
            continue
        for allocation in boost.meal_allocations:
            meal_calorie_boosts[(date_text, boost.member_id, allocation.meal_type)] = (
                Decimal(boost.calories)
                * Decimal(allocation.percentage)
                / Decimal("100")
            )
    grouped_slots: dict[str, list] = {}
    for index, slot in enumerate(payload.slots):
        key = slot.batch_key.strip() if slot.batch_key and slot.batch_key.strip() else f"slot-{index}"
        grouped_slots.setdefault(key, []).append(slot)
    diagnostics: list[dict] = [
        {
            "code": "GENERATION_GUIDANCE",
            "must_use_food_record_ids": list(payload.must_use_food_record_ids),
            "prefer_food_record_ids": list(payload.prefer_food_record_ids),
            "exclude_food_record_ids": list(payload.exclude_food_record_ids),
            "must_use_ingredient_terms": list(payload.must_use_ingredient_terms),
            "prefer_ingredient_terms": list(payload.prefer_ingredient_terms),
            "exclude_ingredient_terms": list(payload.exclude_ingredient_terms),
        }
    ]
    for key, slots in grouped_slots.items():
        if len({slot.meal_type.casefold() for slot in slots}) != 1:
            raise DomainError("INVALID_BATCH_GROUP", f"Batch {key} mixes different meal types")
        if len({slot.meal_group_key for slot in slots}) != 1:
            raise DomainError(
                "INVALID_BATCH_GROUP", f"Batch {key} mixes different meal groups"
            )
        if any(
            len(slot.participant_member_ids) != len(set(slot.participant_member_ids))
            for slot in slots
        ):
            raise DomainError(
                "DUPLICATE_PARTICIPANT", f"Batch {key} contains a participant more than once"
            )
        cook_date = min(slot.meal_date for slot in slots)
        last_date = max(slot.meal_date for slot in slots)
        if (last_date - cook_date).days > 2:
            if not any(slot.food_safety_acknowledged for slot in slots):
                raise DomainError(
                    "LEFTOVER_ACKNOWLEDGEMENT_REQUIRED",
                    f"Batch {key} allocates cooked food beyond 48 hours; acknowledge the warning to continue",
                    422,
                )
            diagnostics.append(
                {
                    "code": "LEFTOVER_WINDOW_ACKNOWLEDGED",
                    "batch_key": key,
                    "cook_date": cook_date.isoformat(),
                    "last_date": last_date.isoformat(),
                }
            )
    plan = MealPlan(
        household_id=context.user.household_id,
        name=payload.name,
        start_date=payload.start_date or min(dates),
        end_date=payload.end_date or max(dates),
        status=PlanStatus.GENERATING.value,
        diagnostics=diagnostics,
        calorie_boosts=[boost.model_dump(mode="json") for boost in payload.calorie_boosts],
        guest_days=[_guest_payload(guest_day) for guest_day in payload.guest_days],
    )
    db.add(plan)
    db.flush()
    base_candidates: dict[str, RecipeCandidate] = {}
    for recipe in recipes:
        version = db.scalar(
            select(RecipeVersion)
            .where(RecipeVersion.recipe_id == recipe.id)
            .order_by(RecipeVersion.version_number.desc())
        )
        candidate = _candidate_from_version(db, recipe, version)
        if candidate is not None:
            base_candidates[recipe.id] = candidate
    candidates_by_meal_type = {
        meal_type: [
            base_candidates[recipe.id]
            for recipe in recipes
            if recipe.id in base_candidates
            and meal_type in {tag.meal_type for tag in recipe.meal_type_tags}
        ]
        for meal_type in {slot.meal_type.casefold() for slot in payload.slots}
    }
    recipe_uses: dict[str, int] = {}
    daily_targets: dict[tuple, list[ParticipantTarget]] = defaultdict(list)
    daily_nutrition: dict[tuple, dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )
    for batch_key, slots in grouped_slots.items():
        slot = slots[0]
        member_ids = sorted(
            {
                member_id
                for grouped_slot in slots
                for member_id in grouped_slot.participant_member_ids
            }
        )
        participants = [
            _target_for(
                db,
                member_id,
                slot.meal_type,
                context.user.household_id,
                sum(
                    (
                        daily_calorie_boosts.get(
                            (grouped_slot.meal_date.isoformat(), member_id),
                            Decimal("0"),
                        )
                        for grouped_slot in slots
                        if member_id in grouped_slot.participant_member_ids
                    ),
                    Decimal("0"),
                )
                / max(
                    1,
                    sum(
                        member_id in grouped_slot.participant_member_ids
                        for grouped_slot in slots
                    ),
                ),
                sum(
                    (
                        meal_calorie_boosts.get(
                            (
                                grouped_slot.meal_date.isoformat(),
                                member_id,
                                grouped_slot.meal_type,
                            ),
                            Decimal("0"),
                        )
                        for grouped_slot in slots
                        if member_id in grouped_slot.participant_member_ids
                    ),
                    Decimal("0"),
                )
                / max(
                    1,
                    sum(
                        member_id in grouped_slot.participant_member_ids
                        for grouped_slot in slots
                    ),
                ),
            )
            for member_id in member_ids
        ]
        if not participants:
            raise DomainError("NO_PARTICIPANTS", "Every planned meal needs a participant")
        hard_terms, preferred_terms, disliked_terms = _restriction_terms(db, member_ids)
        meal_type = slot.meal_type.casefold()
        candidates = list(candidates_by_meal_type.get(meal_type, []))
        if excluded_foods or excluded_ingredient_terms:
            candidates = [
                candidate
                for candidate in candidates
                if not candidate.food_record_ids & excluded_foods
                and not _matching_ingredient_terms(
                    candidate, excluded_ingredient_terms
                )
            ]
        if not candidates:
            raise DomainError(
                "NO_ELIGIBLE_RECIPES",
                f"No planner-ready {meal_type} recipe has the required meal tag",
            )
        safe_candidates = []
        for candidate in candidates:
            if not any(
                re.search(rf"\b{re.escape(term)}\b", candidate.ingredient_text)
                for term in hard_terms
            ):
                safe_candidates.append(candidate)
        if not safe_candidates:
            raise DomainError(
                "ALLERGY_FILTER_REMOVED_ALL",
                f"Hard restrictions removed every recipe for {slot.meal_date} {slot.meal_type}",
            )
        must_use_candidates = [
            candidate
            for candidate in safe_candidates
            if candidate.food_record_ids & remaining_must_use
            or _matching_ingredient_terms(
                candidate, frozenset(remaining_must_use_terms)
            )
        ]
        candidates_for_choice = must_use_candidates or safe_candidates
        unused_candidates = [
            candidate
            for candidate in candidates_for_choice
            if candidate.recipe_id not in recipe_uses
        ]
        try:
            try:
                choice = choose_shared_recipe(
                    unused_candidates or candidates_for_choice,
                    participants,
                    preferred_food_record_ids=preferred_foods,
                    prior_recipe_uses=recipe_uses,
                    preferred_terms=preferred_terms | preferred_ingredient_terms,
                    disliked_terms=disliked_terms,
                    # Allocations are soft meal-level targets. Hard nutrition
                    # bounds are checked after all of the day's meals combine.
                    enforce_nutrition_bounds=False,
                )
            except PlannerInfeasibleError:
                if not unused_candidates:
                    raise
                choice = choose_shared_recipe(
                    candidates_for_choice,
                    participants,
                    preferred_food_record_ids=preferred_foods,
                    prior_recipe_uses=recipe_uses,
                    preferred_terms=preferred_terms | preferred_ingredient_terms,
                    disliked_terms=disliked_terms,
                    enforce_nutrition_bounds=False,
                )
        except PlannerInfeasibleError as exc:
            raise DomainError(
                "NUTRITION_TARGET_INFEASIBLE",
                f"{slot.meal_date} {slot.meal_type}: {exc}",
                422,
                actions=[
                    {
                        "kind": "retry_best_effort",
                        "label": "Continue anyway",
                        "suggestion": "Choose the closest available portions without enforcing nutrition tolerances.",
                    }
                ],
            ) from exc
        if payload.ignore_nutrition_tolerances:
            diagnostics.append(
                {
                    "code": "NUTRITION_TOLERANCE_RELAXED",
                    "batch_key": batch_key,
                    "meal_type": meal_type,
                    "cook_date": min(item.meal_date for item in slots).isoformat(),
                }
            )
        remaining_must_use -= choice.candidate.food_record_ids
        remaining_must_use_terms -= _matching_ingredient_terms(
            choice.candidate, frozenset(remaining_must_use_terms)
        )
        recipe_uses[choice.candidate.recipe_id] = (
            recipe_uses.get(choice.candidate.recipe_id, 0) + len(slots)
        )
        batch = MealBatch(
            meal_plan_id=plan.id,
            recipe_version_id=choice.candidate.recipe_version_id,
            servings=sum(
                (
                    choice.portions[member_id]
                    for grouped_slot in slots
                    for member_id in grouped_slot.participant_member_ids
                ),
                Decimal("0"),
            ),
            planned_cook_date=min(item.meal_date for item in slots),
        )
        db.add(batch)
        db.flush()
        for grouped_slot in slots:
            occurrence = MealOccurrence(
                meal_plan_id=plan.id,
                batch_id=batch.id,
                meal_date=grouped_slot.meal_date,
                meal_type=grouped_slot.meal_type.lower(),
                meal_group_key=grouped_slot.meal_group_key,
            )
            db.add(occurrence)
            db.flush()
            for member_id in grouped_slot.participant_member_ids:
                participant = _target_for(
                    db,
                    member_id,
                    grouped_slot.meal_type,
                    context.user.household_id,
                    daily_calorie_boosts.get(
                        (grouped_slot.meal_date.isoformat(), member_id), Decimal("0")
                    ),
                    meal_calorie_boosts.get(
                        (
                            grouped_slot.meal_date.isoformat(),
                            member_id,
                            grouped_slot.meal_type,
                        ),
                        Decimal("0"),
                    ),
                )
                daily_key = (grouped_slot.meal_date, member_id)
                daily_targets[daily_key].append(participant)
                for nutrient, value in choice.candidate.nutrition.items():
                    daily_nutrition[daily_key][nutrient] += (
                        value * choice.portions[member_id]
                    )
                db.add(
                    PortionAllocation(
                        meal_occurrence_id=occurrence.id,
                        member_id=member_id,
                        servings=choice.portions[member_id],
                    )
                )
    if remaining_must_use or remaining_must_use_terms:
        raise DomainError(
            "MUST_USE_INGREDIENT_INFEASIBLE",
            "No feasible selected recipe covers every must-use ingredient",
            422,
        )
    # Test and production sessions may disable autoflush. Persist the final
    # occurrence allocations before the whole-plan rebalancer queries them.
    db.flush()
    _rebalance_plan(
        db,
        plan,
        ignore_nutrition_tolerances=payload.ignore_nutrition_tolerances,
        infeasible_detail="The available recipes could not meet every daily nutrition target.",
    )
    plan.diagnostics = list(diagnostics)
    flag_modified(plan, "diagnostics")
    plan.status = PlanStatus.READY.value
    db.commit()
    db.refresh(plan)
    return plan


@router.get("", response_model=list[PlanOut])
def list_plans(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
):
    return db.scalars(
        select(MealPlan)
        .where(MealPlan.household_id == context.user.household_id)
        .order_by(MealPlan.start_date.desc())
    ).all()


def _plan_detail(db: Session, plan: MealPlan) -> dict:
    occurrences = db.scalars(
        select(MealOccurrence)
        .where(MealOccurrence.meal_plan_id == plan.id)
        .order_by(
            MealOccurrence.meal_date,
            MealOccurrence.meal_type,
            MealOccurrence.component_slot,
        )
    ).all()
    items = []
    daily_totals: dict = defaultdict(lambda: defaultdict(Decimal))
    daily_member_totals: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(Decimal)))
    for occurrence in occurrences:
        batch = db.get(MealBatch, occurrence.batch_id)
        version = db.get(RecipeVersion, batch.recipe_version_id)
        recipe = db.get(Recipe, version.recipe_id)
        nutrition = planning_values(db, version)
        portions = db.scalars(
            select(PortionAllocation).where(
                PortionAllocation.meal_occurrence_id == occurrence.id
            )
        ).all()
        if nutrition:
            for portion in portions:
                for nutrient, per_serving in nutrition.items():
                    amount = Decimal(per_serving) * Decimal(portion.servings)
                    daily_totals[occurrence.meal_date][nutrient] += amount
                    daily_member_totals[occurrence.meal_date][portion.member_id][nutrient] += amount
        items.append(
            {
                "id": occurrence.id,
                "meal_date": occurrence.meal_date,
                "meal_type": occurrence.meal_type,
                "meal_group_key": occurrence.meal_group_key,
                "locked": occurrence.locked,
                "batch_id": batch.id,
                "parent_batch_id": batch.parent_batch_id,
                "component_slot": occurrence.component_slot,
                "guest_servings": occurrence.guest_servings,
                "recipe_id": recipe.id,
                "recipe_title": recipe.title,
                "source_url": recipe.source_url,
                "image_url": recipe.image_url,
                "batch_servings": batch.servings,
                "planned_cook_date": batch.planned_cook_date,
                "nutrition_per_serving": (
                    {key: float(value) for key, value in nutrition.items()}
                    if nutrition
                    else None
                ),
                "cooked_at": batch.cooked_at,
                "cooked_weight_grams": batch.cooked_weight_grams,
                "serving_weight_grams": (
                    int(
                        (Decimal(batch.cooked_weight_grams) / Decimal(batch.servings)).quantize(
                            Decimal("1"), rounding=ROUND_HALF_UP
                        )
                    )
                    if batch.cooked_weight_grams is not None and batch.servings > 0
                    else None
                ),
                "portions": [
                    {"member_id": portion.member_id, "servings": portion.servings}
                    for portion in portions
                ],
            }
        )
    daily_nutrition = []
    for meal_date in sorted(daily_totals):
        daily_nutrition.append(
            {
                "meal_date": meal_date,
                "totals": {
                    key: round(float(value), 3)
                    for key, value in daily_totals[meal_date].items()
                },
                "members": [
                    {
                        "member_id": member_id,
                        "totals": {
                            key: round(float(value), 3)
                            for key, value in totals.items()
                        },
                    }
                    for member_id, totals in sorted(
                        daily_member_totals[meal_date].items()
                    )
                ],
            }
        )
    return {
        "plan": PlanOut.model_validate(plan),
        "occurrences": items,
        "daily_nutrition": daily_nutrition,
    }


def _automatic_group_choice(
    db: Session,
    plan: MealPlan,
    meal_type: str,
    member_ids: list[str],
) -> RecipeCandidate:
    recipes = list(
        db.scalars(
            select(Recipe)
            .join(RecipeMealType, RecipeMealType.recipe_id == Recipe.id)
            .where(
                Recipe.household_id == plan.household_id,
                Recipe.archived_at.is_(None),
                RecipeMealType.meal_type == meal_type,
            )
            .order_by(Recipe.title, Recipe.id)
        ).all()
    )
    candidates = [
        candidate
        for recipe in recipes
        if (candidate := _candidate(db, recipe, meal_type)) is not None
    ]
    hard_terms, preferred_terms, disliked_terms = _restriction_terms(db, member_ids)
    safe = [
        candidate
        for candidate in candidates
        if not any(
            re.search(rf"\b{re.escape(term)}\b", candidate.ingredient_text)
            for term in hard_terms
        )
    ]
    if not safe:
        raise DomainError(
            "NO_ELIGIBLE_RECIPES",
            f"No planner-ready {meal_type} recipe is safe for this meal group",
            422,
        )
    participants = [
        _target_for(db, member_id, meal_type, plan.household_id)
        for member_id in member_ids
    ]
    try:
        return choose_shared_recipe(
            safe,
            participants,
            preferred_terms=preferred_terms,
            disliked_terms=disliked_terms,
            enforce_nutrition_bounds=False,
        ).candidate
    except PlannerInfeasibleError as exc:
        raise DomainError(
            "NUTRITION_TARGET_INFEASIBLE",
            f"No {meal_type} recipe can be allocated across this meal group",
            422,
        ) from exc


def _regroup_plan_slots(db: Session, plan: MealPlan, slots: list) -> None:
    current = list(
        db.scalars(
            select(MealOccurrence).where(
                MealOccurrence.meal_plan_id == plan.id,
                MealOccurrence.component_slot == 0,
            )
        ).all()
    )
    current_attendance: dict[tuple[date, str], set[str]] = defaultdict(set)
    current_partitions: dict[tuple[date, str], set[tuple[str, tuple[str, ...]]]] = (
        defaultdict(set)
    )
    for occurrence in current:
        members = tuple(
            sorted(
                db.scalars(
                    select(PortionAllocation.member_id).where(
                        PortionAllocation.meal_occurrence_id == occurrence.id
                    )
                ).all()
            )
        )
        key = (occurrence.meal_date, occurrence.meal_type)
        current_attendance[key].update(members)
        current_partitions[key].add((occurrence.meal_group_key, members))

    desired_attendance: dict[tuple[date, str], set[str]] = defaultdict(set)
    desired_partitions: dict[tuple[date, str], set[tuple[str, tuple[str, ...]]]] = (
        defaultdict(set)
    )
    slot_keys: set[tuple[date, str, str]] = set()
    participant_keys: set[tuple[date, str, str]] = set()
    for slot in slots:
        key = (slot.meal_date, slot.meal_type.value, slot.meal_group_key)
        if key in slot_keys:
            raise DomainError(
                "DUPLICATE_PLAN_SLOT",
                "A date, meal type and meal group can only be edited once",
                422,
            )
        slot_keys.add(key)
        members = tuple(sorted(slot.participant_member_ids))
        desired_partitions[(slot.meal_date, slot.meal_type.value)].add(
            (slot.meal_group_key, members)
        )
        for member_id in members:
            participant_key = (slot.meal_date, slot.meal_type.value, member_id)
            if participant_key in participant_keys:
                raise DomainError(
                    "DUPLICATE_MEAL_PARTICIPANT",
                    "A household member can only belong to one recipe group per meal",
                    422,
                )
            participant_keys.add(participant_key)
            desired_attendance[(slot.meal_date, slot.meal_type.value)].add(member_id)
    if desired_attendance != current_attendance:
        raise DomainError(
            "ATTENDANCE_CHANGE_NOT_SUPPORTED",
            "Meal groups may redistribute existing attendees but cannot add or remove attendance",
            422,
        )

    changed_meals = {
        key
        for key in current_partitions
        if current_partitions[key] != desired_partitions.get(key, set())
    }
    for occurrence in current:
        if (occurrence.meal_date, occurrence.meal_type) not in changed_meals:
            continue
        batch = db.get(MealBatch, occurrence.batch_id)
        if batch is not None and _batch_tree_is_cooked(db, batch):
            raise DomainError(
                "COOKED_DAY_LOCKED",
                "A cooked batch and its leftover meals cannot be regrouped",
                409,
            )

    existing_batches = {
        batch.id: batch
        for batch in db.scalars(
            select(MealBatch).where(MealBatch.meal_plan_id == plan.id)
        ).all()
        if batch.parent_batch_id is None
    }
    grouped_slots: dict[str, list] = defaultdict(list)
    for slot in slots:
        grouped_slots[slot.batch_key].append(slot)
    resolved_batches: dict[str, MealBatch] = {}
    replaced_batches: list[str] = []
    for batch_key, batch_slots in grouped_slots.items():
        meal_types = {slot.meal_type.value for slot in batch_slots}
        group_keys = {slot.meal_group_key for slot in batch_slots}
        if len(meal_types) != 1 or len(group_keys) != 1:
            raise DomainError(
                "INVALID_BATCH_GROUP",
                "A cooking batch cannot mix meal types or meal groups",
                422,
            )
        ordered_dates = sorted(slot.meal_date for slot in batch_slots)
        if (ordered_dates[-1] - ordered_dates[0]).days > 2 and not any(
            slot.food_safety_acknowledged for slot in batch_slots
        ):
            raise DomainError(
                "LEFTOVER_ACKNOWLEDGEMENT_REQUIRED",
                "A regrouped batch extends beyond 48 hours; acknowledge the food-safety warning",
                422,
            )
        batch = existing_batches.get(batch_key)
        member_ids = sorted(
            {
                member_id
                for slot in batch_slots
                for member_id in slot.participant_member_ids
            }
        )
        if batch is None:
            candidate = _automatic_group_choice(
                db, plan, next(iter(meal_types)), member_ids
            )
            batch = MealBatch(
                meal_plan_id=plan.id,
                recipe_version_id=candidate.recipe_version_id,
                servings=Decimal("1"),
                planned_cook_date=ordered_dates[0],
            )
            db.add(batch)
            db.flush()
            replaced_batches.append(batch.id)
        resolved_batches[batch_key] = batch

    current_by_key = {
        (item.meal_date, item.meal_type, item.meal_group_key): item for item in current
    }
    retained_ids: set[str] = set()
    for slot in slots:
        identity = (slot.meal_date, slot.meal_type.value, slot.meal_group_key)
        occurrence = current_by_key.get(identity)
        batch = resolved_batches[slot.batch_key]
        if occurrence is None:
            occurrence = MealOccurrence(
                meal_plan_id=plan.id,
                batch_id=batch.id,
                meal_date=slot.meal_date,
                meal_type=slot.meal_type.value,
                meal_group_key=slot.meal_group_key,
            )
            db.add(occurrence)
            db.flush()
        else:
            occurrence.batch_id = batch.id
        retained_ids.add(occurrence.id)
        db.execute(
            delete(PortionAllocation).where(
                PortionAllocation.meal_occurrence_id == occurrence.id
            )
        )
        for member_id in slot.participant_member_ids:
            db.add(
                PortionAllocation(
                    meal_occurrence_id=occurrence.id,
                    member_id=member_id,
                    servings=Decimal("1"),
                )
            )

    removed = [item for item in current if item.id not in retained_ids]
    for occurrence in removed:
        child_batch_ids = list(
            db.scalars(
                select(MealBatch.id).where(
                    MealBatch.parent_batch_id == occurrence.batch_id
                )
            ).all()
        )
        if child_batch_ids:
            side_occurrences = list(
                db.scalars(
                    select(MealOccurrence).where(
                        MealOccurrence.batch_id.in_(child_batch_ids),
                        MealOccurrence.meal_date == occurrence.meal_date,
                        MealOccurrence.meal_group_key == occurrence.meal_group_key,
                    )
                ).all()
            )
            for side in side_occurrences:
                db.execute(
                    delete(PortionAllocation).where(
                        PortionAllocation.meal_occurrence_id == side.id
                    )
                )
                db.delete(side)
        db.execute(
            delete(PortionAllocation).where(
                PortionAllocation.meal_occurrence_id == occurrence.id
            )
        )
        db.delete(occurrence)
    db.flush()

    # Keep compatible side batches aligned with their main group's membership.
    for main in db.scalars(
        select(MealOccurrence).where(
            MealOccurrence.meal_plan_id == plan.id,
            MealOccurrence.component_slot == 0,
        )
    ).all():
        members = list(
            db.scalars(
                select(PortionAllocation.member_id).where(
                    PortionAllocation.meal_occurrence_id == main.id
                )
            ).all()
        )
        for side_batch in db.scalars(
            select(MealBatch).where(MealBatch.parent_batch_id == main.batch_id)
        ).all():
            side = db.scalar(
                select(MealOccurrence).where(
                    MealOccurrence.batch_id == side_batch.id,
                    MealOccurrence.meal_date == main.meal_date,
                    MealOccurrence.meal_group_key == main.meal_group_key,
                )
            )
            if side is None:
                side = MealOccurrence(
                    meal_plan_id=plan.id,
                    batch_id=side_batch.id,
                    meal_date=main.meal_date,
                    meal_type=main.meal_type,
                    meal_group_key=main.meal_group_key,
                    component_slot=side_batch.component_slot,
                )
                db.add(side)
                db.flush()
            db.execute(
                delete(PortionAllocation).where(
                    PortionAllocation.meal_occurrence_id == side.id
                )
            )
            for member_id in members:
                db.add(
                    PortionAllocation(
                        meal_occurrence_id=side.id,
                        member_id=member_id,
                        servings=Decimal("0.25"),
                    )
                )
    db.flush()

    batches = list(
        db.scalars(select(MealBatch).where(MealBatch.meal_plan_id == plan.id)).all()
    )
    for batch in sorted(batches, key=lambda item: item.parent_batch_id is None):
        batch_occurrences = list(
            db.scalars(
                select(MealOccurrence).where(MealOccurrence.batch_id == batch.id)
            ).all()
        )
        if not batch_occurrences:
            db.delete(batch)
            continue
        batch.planned_cook_date = min(item.meal_date for item in batch_occurrences)

    # Re-select a main recipe only when changed members make the current one unsafe.
    for batch in resolved_batches.values():
        occurrences = list(
            db.scalars(
                select(MealOccurrence).where(
                    MealOccurrence.batch_id == batch.id,
                    MealOccurrence.component_slot == 0,
                )
            ).all()
        )
        if not occurrences:
            continue
        member_ids = sorted(
            {
                member_id
                for occurrence in occurrences
                for member_id in db.scalars(
                    select(PortionAllocation.member_id).where(
                        PortionAllocation.meal_occurrence_id == occurrence.id
                    )
                ).all()
            }
        )
        version = db.get(RecipeVersion, batch.recipe_version_id)
        recipe = db.get(Recipe, version.recipe_id) if version else None
        candidate = _candidate_from_version(db, recipe, version) if recipe else None
        hard_terms, _, _ = _restriction_terms(db, member_ids)
        unsafe = candidate is None or any(
            re.search(rf"\b{re.escape(term)}\b", candidate.ingredient_text)
            for term in hard_terms
        )
        if unsafe:
            replacement = _automatic_group_choice(
                db, plan, occurrences[0].meal_type, member_ids
            )
            batch.recipe_version_id = replacement.recipe_version_id
            replaced_batches.append(batch.id)
    if replaced_batches:
        plan.diagnostics = [
            *(plan.diagnostics or []),
            {
                "code": "MEAL_GROUP_RECIPES_SELECTED",
                "batch_ids": sorted(set(replaced_batches)),
            },
        ]
        flag_modified(plan, "diagnostics")
    db.flush()


@router.get("/{plan_id}")
def get_plan(
    plan_id: str,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    plan = db.get(MealPlan, plan_id)
    if plan is None or plan.household_id != context.user.household_id:
        raise NotFoundError("Meal plan")
    return _plan_detail(db, plan)


@router.put("/{plan_id}/preserving-edit")
def edit_plan_preserving_recipes(
    plan_id: str,
    payload: PlanPreservingEditRequest,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    plan = db.scalar(
        select(MealPlan).where(MealPlan.id == plan_id).with_for_update()
    )
    if plan is None or plan.household_id != context.user.household_id:
        raise NotFoundError("Meal plan")
    if plan.status not in {PlanStatus.READY.value, PlanStatus.ACCEPTED.value}:
        raise DomainError(
            "PLAN_NOT_EDITABLE",
            "Only a ready or accepted meal plan can be edited",
            409,
        )
    if plan.version != payload.expected_plan_version:
        raise ConflictError("The meal plan changed while you were editing it. Reload and try again.")

    occurrences = db.scalars(
        select(MealOccurrence).where(MealOccurrence.meal_plan_id == plan.id)
    ).all()
    planned_dates = {occurrence.meal_date for occurrence in occurrences}
    removed_dates = set(payload.removed_dates)
    if not removed_dates.issubset(planned_dates):
        raise DomainError(
            "INVALID_REMOVED_DAY",
            "Only dates currently present in the meal plan can be removed",
            422,
        )
    remaining_dates = planned_dates - removed_dates
    if not remaining_dates:
        raise DomainError(
            "EMPTY_PLAN",
            "A meal plan must keep at least one planned day",
            422,
        )

    batch_by_id = {
        batch.id: batch
        for batch in db.scalars(
            select(MealBatch).where(MealBatch.meal_plan_id == plan.id)
        ).all()
    }
    cooked_dates = {
        occurrence.meal_date.isoformat()
        for occurrence in occurrences
        if batch_by_id[occurrence.batch_id].cooked_at is not None
    }
    if cooked_dates & {item.isoformat() for item in removed_dates}:
        raise DomainError(
            "COOKED_DAY_LOCKED",
            "A day containing a cooked batch cannot be removed",
            409,
        )

    boost_payload = [
        item.model_dump(mode="json") for item in payload.calorie_boosts
    ]
    guest_payload = [_guest_payload(item) for item in payload.guest_days]
    if _normalised_boosts(plan.calorie_boosts or [], cooked_dates) != _normalised_boosts(
        boost_payload, cooked_dates
    ) or _normalised_guests(plan.guest_days or [], cooked_dates) != _normalised_guests(
        guest_payload, cooked_dates
    ):
        raise DomainError(
            "COOKED_DAY_LOCKED",
            "Guests and calorie boosts cannot be changed after a meal batch is cooked",
            409,
        )

    remaining_date_text = {item.isoformat() for item in remaining_dates}
    if any(
        item.meal_date.isoformat() not in remaining_date_text
        for item in [*payload.calorie_boosts, *payload.guest_days]
    ):
        raise DomainError(
            "EDIT_OUTSIDE_PLAN",
            "Guests and calorie boosts must belong to a day kept in the plan",
            422,
        )
    participant_days = {
        (occurrence.meal_date, allocation.member_id)
        for occurrence in occurrences
        if occurrence.meal_date in remaining_dates
        for allocation in db.scalars(
            select(PortionAllocation).where(
                PortionAllocation.meal_occurrence_id == occurrence.id
            )
        ).all()
    }
    for boost in payload.calorie_boosts:
        if (boost.meal_date, boost.member_id) not in participant_days:
            raise DomainError(
                "INVALID_CALORIE_BOOST",
                "A calorie boost must belong to someone eating on that date",
                422,
            )
        attended_meals = {
            occurrence.meal_type
            for occurrence in occurrences
            if occurrence.meal_date == boost.meal_date
            and db.scalar(
                select(PortionAllocation.id).where(
                    PortionAllocation.meal_occurrence_id == occurrence.id,
                    PortionAllocation.member_id == boost.member_id,
                )
            )
            is not None
        }
        if any(
            allocation.meal_type not in attended_meals
            for allocation in boost.meal_allocations
        ):
            raise DomainError(
                "INVALID_CALORIE_BOOST_MEAL",
                "Calorie boosts can only be assigned to meals that person is eating",
                422,
            )
    for guest_day in payload.guest_days:
        planned_meals = {
            occurrence.meal_type
            for occurrence in occurrences
            if occurrence.meal_date == guest_day.meal_date
        }
        if any(meal_type not in planned_meals for meal_type in guest_day.meal_types):
            raise DomainError(
                "INVALID_GUEST_MEAL",
                "Guests can only attend meals planned for that date",
                422,
            )
        for assignment in guest_day.meal_groups:
            matches_group = (
                any(
                    slot.meal_date == guest_day.meal_date
                    and slot.meal_type == assignment.meal_type
                    and slot.meal_group_key == assignment.meal_group_key
                    for slot in payload.main_slots
                )
                if payload.main_slots is not None
                else any(
                    occurrence.meal_date == guest_day.meal_date
                    and occurrence.meal_type == assignment.meal_type
                    and occurrence.meal_group_key == assignment.meal_group_key
                    for occurrence in occurrences
                )
            )
            if not matches_group:
                raise DomainError(
                    "INVALID_GUEST_MEAL_GROUP",
                    "Guests must join a recipe group planned for that meal",
                    422,
                )

    if removed_dates:
        removed_occurrence_ids = [
            occurrence.id
            for occurrence in occurrences
            if occurrence.meal_date in removed_dates
        ]
        db.execute(
            delete(PortionAllocation).where(
                PortionAllocation.meal_occurrence_id.in_(removed_occurrence_ids)
            )
        )
        db.execute(
            delete(MealOccurrence).where(
                MealOccurrence.id.in_(removed_occurrence_ids)
            )
        )
        db.flush()
        batches = db.scalars(
            select(MealBatch).where(MealBatch.meal_plan_id == plan.id)
        ).all()
        empty_batches = [
            batch
            for batch in batches
            if db.scalar(
                select(MealOccurrence.id)
                .where(MealOccurrence.batch_id == batch.id)
                .limit(1)
            )
            is None
        ]
        for batch in sorted(
            empty_batches, key=lambda item: item.parent_batch_id is None
        ):
            db.delete(batch)
        db.flush()
        for batch in db.scalars(
            select(MealBatch).where(MealBatch.meal_plan_id == plan.id)
        ).all():
            first_remaining_date = db.scalar(
                select(MealOccurrence.meal_date)
                .where(MealOccurrence.batch_id == batch.id)
                .order_by(MealOccurrence.meal_date)
                .limit(1)
            )
            if first_remaining_date is not None:
                batch.planned_cook_date = first_remaining_date

    if payload.main_slots is not None:
        _regroup_plan_slots(db, plan, payload.main_slots)

    plan.calorie_boosts = boost_payload
    plan.guest_days = guest_payload
    flag_modified(plan, "calorie_boosts")
    flag_modified(plan, "guest_days")
    for cook_day in sorted(
        payload.removed_cook_days,
        key=lambda item: (item.meal_date, item.meal_type, item.meal_group_key),
    ):
        if cook_day.meal_date not in remaining_dates:
            raise DomainError(
                "INVALID_COOK_DAY",
                "A cooking day cannot be removed from a deleted date",
                422,
            )
        _remove_cook_day(
            db,
            plan,
            cook_day.meal_date,
            cook_day.meal_type,
            cook_day.meal_group_key,
        )
    for cook_day in sorted(
        payload.added_cook_days,
        key=lambda item: (item.meal_date, item.meal_type, item.meal_group_key),
    ):
        if cook_day.meal_date not in remaining_dates:
            raise DomainError(
                "INVALID_COOK_DAY",
                "A cooking day cannot be added to a removed date",
                422,
            )
        _split_batch_for_new_cook_day(
            db,
            plan,
            cook_day.meal_date,
            cook_day.meal_type,
            cook_day.meal_group_key,
            cook_day.recipe_id,
        )
    for swap in payload.recipe_swaps:
        batch = db.get(MealBatch, swap.batch_id)
        if (
            batch is None
            or batch.meal_plan_id != plan.id
            or batch.parent_batch_id is not None
        ):
            raise DomainError(
                "INVALID_RECIPE_SWAP",
                "The cooking batch selected for swapping no longer exists",
                422,
            )
        if _batch_tree_is_cooked(db, batch):
            raise DomainError(
                "COOKED_DAY_LOCKED",
                "A cooked batch cannot have its recipe swapped",
                409,
            )
        batch_occurrences = db.scalars(
            select(MealOccurrence)
            .where(MealOccurrence.batch_id == batch.id)
            .order_by(MealOccurrence.meal_date)
        ).all()
        if not batch_occurrences or len(
            {item.meal_type for item in batch_occurrences}
        ) != 1:
            raise DomainError("INVALID_BATCH", "The selected batch is invalid", 422)
        candidate = _selected_main_recipe_candidate(
            db,
            plan,
            swap.recipe_id,
            batch_occurrences[0].meal_type,
        )
        batch.recipe_version_id = candidate.recipe_version_id
    db.flush()

    plan.start_date = min(remaining_dates)
    plan.end_date = max(remaining_dates)
    _validate_mutable_plan_constraints(db, plan)
    _rebalance_plan(
        db,
        plan,
        ignore_nutrition_tolerances=payload.ignore_nutrition_tolerances,
        infeasible_detail=(
            "These recipes could not meet the updated calorie targets. "
            "Continue anyway to keep the same meals with the closest portions."
        ),
    )
    diagnostics = list(plan.diagnostics or [])
    diagnostics.append(
        {
            "code": "RECIPE_PRESERVING_EDIT",
            "removed_dates": sorted(item.isoformat() for item in removed_dates),
            "added_cook_days": [
                item.model_dump(mode="json") for item in payload.added_cook_days
            ],
            "removed_cook_days": [
                item.model_dump(mode="json") for item in payload.removed_cook_days
            ],
            "recipe_swaps": [
                item.model_dump(mode="json") for item in payload.recipe_swaps
            ],
            "meal_groups_updated": payload.main_slots is not None,
        }
    )
    plan.diagnostics = diagnostics
    flag_modified(plan, "diagnostics")
    plan.version += 1

    if plan.status == PlanStatus.ACCEPTED.value:
        db.scalar(
            select(Household)
            .where(Household.id == plan.household_id)
            .with_for_update()
        )
        future_batches = db.scalars(
            select(MealBatch).where(
                MealBatch.meal_plan_id == plan.id,
                MealBatch.cooked_at.is_(None),
            )
        ).all()
        future_batch_ids = [batch.id for batch in future_batches]
        if future_batch_ids:
            db.execute(
                delete(PantryReservation).where(
                    PantryReservation.meal_batch_id.in_(future_batch_ids)
                )
            )
        reserve_plan_batches(db, plan.household_id, list(future_batches))
        build_shopping_list(
            db,
            plan.household_id,
            plan.id,
            "Current shopping list",
        )

    db.commit()
    db.refresh(plan)
    return _plan_detail(db, plan)


@router.put("/{plan_id}/occurrences/{occurrence_id}/recipe")
def replace_occurrence_recipe(
    plan_id: str,
    occurrence_id: str,
    payload: PlanRecipeReplaceRequest,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    plan = db.scalar(
        select(MealPlan).where(MealPlan.id == plan_id).with_for_update()
    )
    occurrence = db.get(MealOccurrence, occurrence_id)
    if (
        plan is None
        or plan.household_id != context.user.household_id
        or occurrence is None
        or occurrence.meal_plan_id != plan.id
    ):
        raise NotFoundError("Meal occurrence")
    if plan.status != PlanStatus.READY.value:
        raise DomainError("PLAN_NOT_EDITABLE", "Only a ready plan can have a recipe replaced")
    if plan.version != payload.expected_plan_version:
        raise ConflictError("This plan changed while you were editing it. Reload before replacing a recipe.")
    if occurrence.component_slot != 0:
        raise DomainError(
            "SIDE_REPLACEMENT_ENDPOINT_REQUIRED",
            "Use the side picker to replace an added item",
        )
    recipe = db.get(Recipe, payload.recipe_id)
    if (
        recipe is None
        or recipe.household_id != context.user.household_id
        or recipe.archived_at is not None
    ):
        raise NotFoundError("Recipe")
    tagged = db.scalar(
        select(RecipeMealType.id).where(
            RecipeMealType.recipe_id == recipe.id,
            RecipeMealType.meal_type == occurrence.meal_type,
        )
    )
    if tagged is None:
        raise DomainError(
            "RECIPE_MEAL_TYPE_MISMATCH",
            f"Choose a recipe tagged for {occurrence.meal_type}",
        )
    candidate = _candidate(db, recipe, occurrence.meal_type)
    if candidate is None:
        raise DomainError(
            "RECIPE_NOT_PLANNER_READY",
            "The selected recipe needs complete nutrition, a yield and the matching meal tag",
        )
    batch = db.get(MealBatch, occurrence.batch_id)
    batch_occurrences = db.scalars(
        select(MealOccurrence)
        .where(MealOccurrence.batch_id == batch.id)
        .order_by(MealOccurrence.meal_date)
    ).all()
    if len({item.meal_type for item in batch_occurrences}) != 1:
        raise DomainError("INVALID_BATCH", "The selected batch mixes meal types")
    _validate_mutable_plan_constraints(
        db,
        plan,
        replacement_batch_id=batch.id,
        replacement_candidate=candidate,
    )
    batch.recipe_version_id = candidate.recipe_version_id
    _rebalance_plan(
        db,
        plan,
        ignore_nutrition_tolerances=payload.ignore_nutrition_tolerances,
    )
    if payload.ignore_nutrition_tolerances:
        plan.diagnostics = [
            *(plan.diagnostics or []),
            {
                "code": "REPLACEMENT_NUTRITION_TOLERANCE_RELAXED",
                "batch_id": batch.id,
                "recipe_id": recipe.id,
            },
        ]
        flag_modified(plan, "diagnostics")
    plan.version += 1
    db.commit()
    db.refresh(plan)
    return _plan_detail(db, plan)


@router.post("/{plan_id}/batches/{batch_id}/sides")
def add_or_replace_side(
    plan_id: str,
    batch_id: str,
    payload: PlanSideCreateRequest,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    plan = db.scalar(
        select(MealPlan).where(MealPlan.id == plan_id).with_for_update()
    )
    main_batch = db.get(MealBatch, batch_id)
    if (
        plan is None
        or plan.household_id != context.user.household_id
        or main_batch is None
        or main_batch.meal_plan_id != plan.id
        or main_batch.parent_batch_id is not None
    ):
        raise NotFoundError("Meal batch")
    if plan.status != PlanStatus.READY.value:
        raise DomainError("PLAN_NOT_EDITABLE", "Only a ready plan can have sides changed")
    if plan.version != payload.expected_plan_version:
        raise ConflictError("This plan changed while you were editing it. Reload before adding a side.")

    main_occurrences = db.scalars(
        select(MealOccurrence)
        .where(MealOccurrence.batch_id == main_batch.id)
        .order_by(MealOccurrence.meal_date)
    ).all()
    if not main_occurrences:
        raise DomainError("INVALID_BATCH", "The selected batch has no meal occurrences")
    meal_types = {occurrence.meal_type for occurrence in main_occurrences}
    if len(meal_types) != 1:
        raise DomainError("INVALID_BATCH", "The selected batch mixes meal types")
    meal_type = main_occurrences[0].meal_type

    recipe = db.get(Recipe, payload.recipe_id)
    if (
        recipe is None
        or recipe.household_id != context.user.household_id
        or recipe.archived_at is not None
    ):
        raise NotFoundError("Recipe")
    candidate = _side_candidate(db, recipe, meal_type)
    if candidate is None:
        allowed = "snack" if meal_type == "snack" else "side or snack"
        raise DomainError(
            "RECIPE_MEAL_TYPE_MISMATCH",
            f"Choose a planner-ready recipe tagged {allowed}",
        )

    existing_sides = db.scalars(
        select(MealBatch)
        .where(MealBatch.parent_batch_id == main_batch.id)
        .order_by(MealBatch.component_slot)
    ).all()
    by_slot = {batch.component_slot: batch for batch in existing_sides}
    component_slot = payload.component_slot
    if component_slot is None:
        component_slot = next((slot for slot in (1, 2) if slot not in by_slot), None)
    if component_slot is None:
        raise DomainError("SIDE_LIMIT_REACHED", "This batch already has two added items")

    side_batch = by_slot.get(component_slot)
    if side_batch is not None:
        side_batch.recipe_version_id = candidate.recipe_version_id
    else:
        side_batch = MealBatch(
            meal_plan_id=plan.id,
            recipe_version_id=candidate.recipe_version_id,
            servings=Decimal("0"),
            planned_cook_date=main_batch.planned_cook_date,
            parent_batch_id=main_batch.id,
            component_slot=component_slot,
        )
        db.add(side_batch)
        db.flush()
        for main_occurrence in main_occurrences:
            side_occurrence = MealOccurrence(
                meal_plan_id=plan.id,
                batch_id=side_batch.id,
                meal_date=main_occurrence.meal_date,
                meal_type=main_occurrence.meal_type,
                meal_group_key=main_occurrence.meal_group_key,
                component_slot=component_slot,
            )
            db.add(side_occurrence)
            db.flush()
            main_allocations = db.scalars(
                select(PortionAllocation).where(
                    PortionAllocation.meal_occurrence_id == main_occurrence.id
                )
            ).all()
            for allocation in main_allocations:
                db.add(
                    PortionAllocation(
                        meal_occurrence_id=side_occurrence.id,
                        member_id=allocation.member_id,
                        servings=Decimal("0.25"),
                    )
                )
    db.flush()
    _validate_mutable_plan_constraints(db, plan)
    _rebalance_plan(
        db,
        plan,
        ignore_nutrition_tolerances=payload.ignore_nutrition_tolerances,
    )
    if payload.ignore_nutrition_tolerances:
        plan.diagnostics = [
            *(plan.diagnostics or []),
            {
                "code": "SIDE_NUTRITION_TOLERANCE_RELAXED",
                "batch_id": side_batch.id,
                "parent_batch_id": main_batch.id,
            },
        ]
        flag_modified(plan, "diagnostics")
    plan.version += 1
    db.commit()
    db.refresh(plan)
    return _plan_detail(db, plan)


@router.delete("/{plan_id}/batches/{side_batch_id}/sides")
def remove_side(
    plan_id: str,
    side_batch_id: str,
    payload: PlanSideRemoveRequest,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    plan = db.scalar(
        select(MealPlan).where(MealPlan.id == plan_id).with_for_update()
    )
    side_batch = db.get(MealBatch, side_batch_id)
    if (
        plan is None
        or plan.household_id != context.user.household_id
        or side_batch is None
        or side_batch.meal_plan_id != plan.id
        or side_batch.parent_batch_id is None
    ):
        raise NotFoundError("Side batch")
    if plan.status != PlanStatus.READY.value:
        raise DomainError("PLAN_NOT_EDITABLE", "Only a ready plan can have sides changed")
    if plan.version != payload.expected_plan_version:
        raise ConflictError("This plan changed while you were editing it. Reload before removing the side.")

    occurrence_ids = db.scalars(
        select(MealOccurrence.id).where(MealOccurrence.batch_id == side_batch.id)
    ).all()
    if occurrence_ids:
        db.execute(
            delete(PortionAllocation).where(
                PortionAllocation.meal_occurrence_id.in_(occurrence_ids)
            )
        )
        db.execute(delete(MealOccurrence).where(MealOccurrence.id.in_(occurrence_ids)))
    db.delete(side_batch)
    db.flush()
    _validate_mutable_plan_constraints(db, plan)
    _rebalance_plan(
        db,
        plan,
        ignore_nutrition_tolerances=payload.ignore_nutrition_tolerances,
    )
    plan.version += 1
    db.commit()
    db.refresh(plan)
    return _plan_detail(db, plan)


@router.post("/{plan_id}/accept", response_model=PlanOut)
def accept_plan(
    plan_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    plan = db.scalar(
        select(MealPlan).where(MealPlan.id == plan_id).with_for_update()
    )
    if plan is None or plan.household_id != context.user.household_id:
        raise NotFoundError("Meal plan")
    # Serialise shopping-list activation across different plans belonging to
    # the same household, not only concurrent operations on this plan row.
    db.scalar(
        select(Household).where(Household.id == plan.household_id).with_for_update()
    )
    if plan.status not in {PlanStatus.READY.value, PlanStatus.ACCEPTED.value}:
        raise DomainError("PLAN_NOT_READY", "Only a ready plan can be accepted")
    existing_list = db.scalar(
        select(ShoppingList).where(ShoppingList.meal_plan_id == plan.id).limit(1)
    )
    if plan.status == PlanStatus.ACCEPTED.value and existing_list is not None:
        return plan
    _validate_mutable_plan_constraints(db, plan)
    previous_plans = db.scalars(
        select(MealPlan).where(
            MealPlan.household_id == plan.household_id,
            MealPlan.status == PlanStatus.ACCEPTED.value,
            MealPlan.id != plan.id,
        )
    ).all()
    for previous_plan in previous_plans:
        previous_batch_ids = db.scalars(
            select(MealBatch.id).where(MealBatch.meal_plan_id == previous_plan.id)
        ).all()
        if previous_batch_ids:
            db.execute(
                delete(PantryReservation).where(
                    PantryReservation.meal_batch_id.in_(previous_batch_ids)
                )
            )
        previous_plan.status = PlanStatus.SUPERSEDED.value
        previous_plan.version += 1
    batches = db.scalars(select(MealBatch).where(MealBatch.meal_plan_id == plan.id)).all()
    reserve_plan_batches(db, context.user.household_id, list(batches))
    # A READY plan may have a stale list from an older client that built one
    # before changing a batch. Always replace it during the atomic accept.
    if plan.status == PlanStatus.READY.value or existing_list is None:
        build_shopping_list(
            db,
            context.user.household_id,
            plan.id,
            "Current shopping list",
        )
    if plan.status == PlanStatus.READY.value:
        plan.status = PlanStatus.ACCEPTED.value
        plan.accepted_at = datetime.now(timezone.utc)
    plan.version += 1
    db.commit()
    db.refresh(plan)
    return plan


@router.post("/{plan_id}/batches/{batch_id}/cooked", status_code=204)
def mark_batch_cooked(
    plan_id: str,
    batch_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    plan = db.get(MealPlan, plan_id)
    batch = db.get(MealBatch, batch_id)
    if (
        plan is None
        or plan.household_id != context.user.household_id
        or batch is None
        or batch.meal_plan_id != plan.id
    ):
        raise NotFoundError("Meal batch")
    root_batch_id = batch.parent_batch_id or batch.id
    cooking_batches = db.scalars(
        select(MealBatch).where(
            (MealBatch.id == root_batch_id)
            | (MealBatch.parent_batch_id == root_batch_id)
        )
    ).all()
    cooked_at = datetime.now(timezone.utc)
    for cooking_batch in cooking_batches:
        if cooking_batch.cooked_at:
            continue
        reservations = db.scalars(
            select(PantryReservation).where(
                PantryReservation.meal_batch_id == cooking_batch.id
            )
        ).all()
        for reservation in reservations:
            db.add(
                PantryTransaction(
                    pantry_lot_id=reservation.pantry_lot_id,
                    quantity_delta=-Decimal(reservation.quantity),
                    reason="meal_batch_cooked",
                    reference_type="meal_batch",
                    reference_id=cooking_batch.id,
                )
            )
            db.delete(reservation)
        cooking_batch.cooked_at = cooked_at
    db.commit()


@router.patch("/{plan_id}/batches/{batch_id}/cooked-weight", status_code=204)
def update_batch_cooked_weight(
    plan_id: str,
    batch_id: str,
    payload: BatchCookedWeightUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    plan = db.get(MealPlan, plan_id)
    batch = db.get(MealBatch, batch_id)
    if (
        plan is None
        or plan.household_id != context.user.household_id
        or batch is None
        or batch.meal_plan_id != plan.id
    ):
        raise NotFoundError("Meal batch")
    if batch.cooked_at is None:
        raise DomainError(
            "BATCH_NOT_COOKED",
            "Mark this batch cooked before recording its finished weight",
        )
    batch.cooked_weight_grams = payload.cooked_weight_grams
    db.commit()


@router.delete("/{plan_id}/batches/{batch_id}/cooked", status_code=204)
def unmark_batch_cooked(
    plan_id: str,
    batch_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    plan = db.get(MealPlan, plan_id)
    batch = db.get(MealBatch, batch_id)
    if (
        plan is None
        or plan.household_id != context.user.household_id
        or batch is None
        or batch.meal_plan_id != plan.id
    ):
        raise NotFoundError("Meal batch")
    root_batch_id = batch.parent_batch_id or batch.id
    cooking_batches = db.scalars(
        select(MealBatch).where(
            (MealBatch.id == root_batch_id)
            | (MealBatch.parent_batch_id == root_batch_id)
        )
    ).all()
    for cooking_batch in cooking_batches:
        if not cooking_batch.cooked_at:
            continue
        transactions = db.scalars(
            select(PantryTransaction).where(
                PantryTransaction.reference_type == "meal_batch",
                PantryTransaction.reference_id == cooking_batch.id,
                PantryTransaction.reason.in_(
                    ("meal_batch_cooked", "meal_batch_uncooked")
                ),
            )
        ).all()
        net_by_lot: dict[str, Decimal] = defaultdict(Decimal)
        for transaction in transactions:
            net_by_lot[transaction.pantry_lot_id] += Decimal(transaction.quantity_delta)
        for pantry_lot_id, net_quantity in net_by_lot.items():
            restore_quantity = max(-net_quantity, Decimal("0"))
            if restore_quantity <= 0:
                continue
            lot = db.get(PantryLot, pantry_lot_id)
            if lot is None:
                continue
            db.add(
                PantryTransaction(
                    pantry_lot_id=pantry_lot_id,
                    quantity_delta=restore_quantity,
                    reason="meal_batch_uncooked",
                    reference_type="meal_batch",
                    reference_id=cooking_batch.id,
                )
            )
            reservation = db.scalar(
                select(PantryReservation).where(
                    PantryReservation.pantry_lot_id == pantry_lot_id,
                    PantryReservation.meal_batch_id == cooking_batch.id,
                )
            )
            if reservation is None:
                db.add(
                    PantryReservation(
                        pantry_lot_id=pantry_lot_id,
                        meal_batch_id=cooking_batch.id,
                        quantity=restore_quantity,
                        unit=lot.unit,
                    )
                )
            else:
                reservation.quantity = Decimal(reservation.quantity) + restore_quantity
        cooking_batch.cooked_at = None
        cooking_batch.cooked_weight_grams = None
    db.commit()
