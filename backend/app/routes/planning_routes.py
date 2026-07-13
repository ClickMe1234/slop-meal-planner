from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import re

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

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
from ..schemas import PlanGenerateRequest, PlanOut, PlanRecipeReplaceRequest
from ..services.nutrition import publisher_values
from ..services.pantry import reserve_plan_batches
from ..services.planner import (
    ParticipantTarget,
    PlannerInfeasibleError,
    RecipeCandidate,
    choose_shared_recipe,
)
from ..services.shopping import build_shopping_list

router = APIRouter(prefix="/meal-plans", tags=["meal planning"])


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
    return _candidate_from_version(recipe, version)


def _candidate_from_version(
    recipe: Recipe, version: RecipeVersion | None
) -> RecipeCandidate | None:
    if version is None or not version.yield_servings:
        return None
    nutrition = publisher_values(version)
    if nutrition is None:
        return None
    included_ingredients = [item for item in version.ingredients if item.included]
    return RecipeCandidate(
        recipe_id=recipe.id,
        recipe_version_id=version.id,
        nutrition=nutrition,
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
            }
    return {
        "must_use_food_record_ids": [],
        "prefer_food_record_ids": [],
        "exclude_food_record_ids": [],
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
    covered_foods: set[str] = set()
    remediation_occurrence: MealOccurrence | None = None
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
                _candidate_from_version(recipe, version)
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
                            "Confirm the recipe yield and publisher nutrition, then return to the plan."
                        ),
                        "recipe_id": recipe.id,
                        "batch_id": batch.id,
                    }
                )
            raise DomainError(
                "INVALID_BATCH",
                "A planned recipe no longer has complete publisher nutrition and a serving yield",
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
        meal_types = {occurrence.meal_type for occurrence in occurrences}
        for meal_type in meal_types:
            tagged = db.scalar(
                select(RecipeMealType.id).where(
                    RecipeMealType.recipe_id == recipe.id,
                    RecipeMealType.meal_type == meal_type,
                )
            )
            if tagged is None:
                raise DomainError(
                    "RECIPE_MEAL_TYPE_REVIEW_REQUIRED",
                    f"{recipe.title} is no longer tagged for {meal_type}",
                    actions=[
                        {
                            "kind": "review_recipe",
                            "label": f"Tag {recipe.title} for {meal_type}",
                            "href": f"/recipes/{recipe.id}/review",
                            "suggestion": (
                                f"Add the {meal_type} meal tag, then return and accept the plan again."
                            ),
                            "recipe_id": recipe.id,
                            "recipe_version_id": candidate.recipe_version_id,
                            "batch_id": batch.id,
                        }
                    ],
                )
        if candidate.food_record_ids & excluded_foods:
            occurrence = occurrences[0]
            raise DomainError(
                "PLAN_EXCLUDED_INGREDIENT",
                f"{recipe.title} now contains an ingredient excluded from this plan",
                actions=[
                    {
                        "kind": "replace_recipe",
                        "label": "Choose another recipe",
                        "href": (
                            f"/plan/{plan.id}/occurrences/{occurrence.id}/recipes"
                            f"?mealType={occurrence.meal_type}"
                        ),
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
                        "href": (
                            f"/plan/{plan.id}/occurrences/{occurrence.id}/recipes"
                            f"?mealType={occurrence.meal_type}"
                        ),
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
    missing_must_use = set(guidance["must_use_food_record_ids"]) - covered_foods
    if missing_must_use:
        actions = []
        if remediation_occurrence is not None:
            actions.append(
                {
                    "kind": "replace_recipe",
                    "label": "Choose a recipe using it",
                    "href": (
                        f"/plan/{plan.id}/occurrences/{remediation_occurrence.id}/recipes"
                        f"?mealType={remediation_occurrence.meal_type}"
                    ),
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
    db: Session, member_id: str, meal_type: str, household_id: str
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
    return ParticipantTarget(
        member_id=member.id,
        mode=target.mode,
        allocation=Decimal(allocation.percentage),
        calorie_target=target.calorie_target,
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


@router.post("/generate", response_model=PlanOut, status_code=201)
def generate_plan(
    payload: PlanGenerateRequest,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    if not payload.slots:
        raise DomainError("NO_PLAN_SLOTS", "At least one meal slot is required")
    slot_keys = [(slot.meal_date, slot.meal_type.casefold()) for slot in payload.slots]
    if len(set(slot_keys)) != len(slot_keys):
        raise DomainError("DUPLICATE_PLAN_SLOT", "A date and meal type can only be planned once")
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

    dates = [slot.meal_date for slot in payload.slots]
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
        }
    ]
    for key, slots in grouped_slots.items():
        if len({slot.meal_type.casefold() for slot in slots}) != 1:
            raise DomainError("INVALID_BATCH_GROUP", f"Batch {key} mixes different meal types")
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
        candidate = _candidate_from_version(recipe, version)
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
            _target_for(db, member_id, slot.meal_type, context.user.household_id)
            for member_id in member_ids
        ]
        if not participants:
            raise DomainError("NO_PARTICIPANTS", "Every planned meal needs a participant")
        hard_terms, preferred_terms, disliked_terms = _restriction_terms(db, member_ids)
        meal_type = slot.meal_type.casefold()
        candidates = list(candidates_by_meal_type.get(meal_type, []))
        if excluded_foods:
            candidates = [
                candidate
                for candidate in candidates
                if not candidate.food_record_ids & excluded_foods
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
            candidate for candidate in safe_candidates if candidate.food_record_ids & remaining_must_use
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
                    preferred_terms=preferred_terms,
                    disliked_terms=disliked_terms,
                )
            except PlannerInfeasibleError:
                if not unused_candidates:
                    raise
                choice = choose_shared_recipe(
                    candidates_for_choice,
                    participants,
                    preferred_food_record_ids=preferred_foods,
                    prior_recipe_uses=recipe_uses,
                    preferred_terms=preferred_terms,
                    disliked_terms=disliked_terms,
                )
        except PlannerInfeasibleError as exc:
            raise DomainError(
                "NUTRITION_TARGET_INFEASIBLE",
                f"{slot.meal_date} {slot.meal_type}: {exc}",
                422,
            ) from exc
        remaining_must_use -= choice.candidate.food_record_ids
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
            )
            db.add(occurrence)
            db.flush()
            for member_id in grouped_slot.participant_member_ids:
                db.add(
                    PortionAllocation(
                        meal_occurrence_id=occurrence.id,
                        member_id=member_id,
                        servings=choice.portions[member_id],
                    )
                )
    if remaining_must_use:
        raise DomainError(
            "MUST_USE_INGREDIENT_INFEASIBLE",
            "No feasible selected recipe covers every must-use ingredient",
            422,
        )
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
        .order_by(MealOccurrence.meal_date, MealOccurrence.meal_type)
    ).all()
    items = []
    daily_totals: dict = defaultdict(lambda: defaultdict(Decimal))
    daily_member_totals: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(Decimal)))
    for occurrence in occurrences:
        batch = db.get(MealBatch, occurrence.batch_id)
        version = db.get(RecipeVersion, batch.recipe_version_id)
        recipe = db.get(Recipe, version.recipe_id)
        nutrition = publisher_values(version)
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
                "locked": occurrence.locked,
                "batch_id": batch.id,
                "recipe_id": recipe.id,
                "recipe_title": recipe.title,
                "source_url": recipe.source_url,
                "batch_servings": batch.servings,
                "planned_cook_date": batch.planned_cook_date,
                "nutrition_per_serving": (
                    {key: float(value) for key, value in nutrition.items()}
                    if nutrition
                    else None
                ),
                "cooked_at": batch.cooked_at,
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
            "The selected recipe needs complete publisher nutrition, a yield and the matching meal tag",
        )
    batch = db.get(MealBatch, occurrence.batch_id)
    batch_occurrences = db.scalars(
        select(MealOccurrence)
        .where(MealOccurrence.batch_id == batch.id)
        .order_by(MealOccurrence.meal_date)
    ).all()
    if len({item.meal_type for item in batch_occurrences}) != 1:
        raise DomainError("INVALID_BATCH", "The selected batch mixes meal types")
    allocations_by_occurrence: dict[str, list[PortionAllocation]] = {}
    member_ids: set[str] = set()
    for item in batch_occurrences:
        allocations = db.scalars(
            select(PortionAllocation).where(
                PortionAllocation.meal_occurrence_id == item.id
            )
        ).all()
        allocations_by_occurrence[item.id] = list(allocations)
        member_ids.update(allocation.member_id for allocation in allocations)
    participants = [
        _target_for(db, member_id, occurrence.meal_type, context.user.household_id)
        for member_id in sorted(member_ids)
    ]
    _, preferred_terms, disliked_terms = _restriction_terms(
        db, sorted(member_ids)
    )
    _validate_mutable_plan_constraints(
        db,
        plan,
        replacement_batch_id=batch.id,
        replacement_candidate=candidate,
    )
    try:
        choice = choose_shared_recipe(
            [candidate],
            participants,
            preferred_terms=preferred_terms,
            disliked_terms=disliked_terms,
        )
    except PlannerInfeasibleError as exc:
        raise DomainError("NUTRITION_TARGET_INFEASIBLE", str(exc), 422) from exc
    total_servings = Decimal("0")
    for allocations in allocations_by_occurrence.values():
        for allocation in allocations:
            allocation.servings = choice.portions[allocation.member_id]
            total_servings += choice.portions[allocation.member_id]
    batch.recipe_version_id = candidate.recipe_version_id
    batch.servings = total_servings
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
    if batch.cooked_at:
        return
    reservations = db.scalars(
        select(PantryReservation).where(PantryReservation.meal_batch_id == batch.id)
    ).all()
    for reservation in reservations:
        db.add(
            PantryTransaction(
                pantry_lot_id=reservation.pantry_lot_id,
                quantity_delta=-Decimal(reservation.quantity),
                reason="meal_batch_cooked",
                reference_type="meal_batch",
                reference_id=batch.id,
            )
        )
        db.delete(reservation)
    batch.cooked_at = datetime.now(timezone.utc)
    db.commit()
