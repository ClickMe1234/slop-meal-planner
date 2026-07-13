from datetime import datetime, timezone
from decimal import Decimal
import re

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import AuthContext, get_auth_context, require_csrf
from ..db import get_db
from ..errors import DomainError, NotFoundError
from ..models import (
    HouseholdMember,
    MealAllocation,
    MealBatch,
    MealOccurrence,
    MealPlan,
    NutritionCalculation,
    PantryLot,
    PantryReservation,
    PantryTransaction,
    PlanStatus,
    PortionAllocation,
    Recipe,
    RecipeEligibility,
    RecipeVersion,
    Restriction,
    TargetProfile,
)
from ..schemas import PlanGenerateRequest, PlanOut
from ..services.nutrition import latest_calculation
from ..services.pantry import reserve_plan_batches
from ..services.planner import (
    ParticipantTarget,
    PlannerInfeasibleError,
    RecipeCandidate,
    choose_shared_recipe,
)

router = APIRouter(prefix="/meal-plans", tags=["meal planning"])


def _candidate(db: Session, recipe: Recipe) -> RecipeCandidate | None:
    version = db.scalar(
        select(RecipeVersion)
        .where(RecipeVersion.recipe_id == recipe.id)
        .order_by(RecipeVersion.version_number.desc())
    )
    if version is None:
        return None
    calculation = latest_calculation(db, version.id)
    if calculation is None or calculation.status != "complete":
        return None
    return RecipeCandidate(
        recipe_id=recipe.id,
        recipe_version_id=version.id,
        nutrition={key: Decimal(str(value)) for key, value in calculation.per_serving_values.items()},
        food_record_ids=frozenset(
            item.food_record_id
            for item in version.ingredients
            if item.included and item.food_record_id
        ),
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
    recipes = db.scalars(
        select(Recipe).where(
            Recipe.id.in_(payload.recipe_ids),
            Recipe.household_id == context.user.household_id,
            Recipe.eligibility == RecipeEligibility.PLANNER_READY.value,
        )
    ).all()
    candidates = [candidate for recipe in recipes if (candidate := _candidate(db, recipe))]
    excluded_foods = frozenset(payload.exclude_food_record_ids)
    if excluded_foods:
        candidates = [candidate for candidate in candidates if not candidate.food_record_ids & excluded_foods]
    if not candidates:
        raise DomainError("NO_ELIGIBLE_RECIPES", "No selected recipe is planner-ready")
    remaining_must_use = set(payload.must_use_food_record_ids)
    preferred_foods = frozenset(payload.prefer_food_record_ids)

    dates = [slot.meal_date for slot in payload.slots]
    grouped_slots: dict[str, list] = {}
    for index, slot in enumerate(payload.slots):
        key = slot.batch_key.strip() if slot.batch_key and slot.batch_key.strip() else f"slot-{index}"
        grouped_slots.setdefault(key, []).append(slot)
    diagnostics: list[dict] = []
    for key, slots in grouped_slots.items():
        if len({slot.meal_type.casefold() for slot in slots}) != 1:
            raise DomainError("INVALID_BATCH_GROUP", f"Batch {key} mixes different meal types")
        participant_sets = {tuple(sorted(slot.participant_member_ids)) for slot in slots}
        if len(participant_sets) != 1:
            raise DomainError("INVALID_BATCH_GROUP", f"Batch {key} changes participants between dates")
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
        start_date=min(dates),
        end_date=max(dates),
        status=PlanStatus.GENERATING.value,
        diagnostics=diagnostics,
    )
    db.add(plan)
    db.flush()
    recipe_uses: dict[str, int] = {}
    for batch_key, slots in grouped_slots.items():
        slot = slots[0]
        participants = [
            _target_for(db, member_id, slot.meal_type, context.user.household_id)
            for member_id in slot.participant_member_ids
        ]
        if not participants:
            raise DomainError("NO_PARTICIPANTS", "Every planned meal needs a participant")
        hard_terms = {
            restriction.value.lower()
            for restriction in db.scalars(
                select(Restriction).where(
                    Restriction.member_id.in_(slot.participant_member_ids),
                    Restriction.hard.is_(True),
                )
            ).all()
        }
        safe_candidates = []
        for candidate in candidates:
            version = db.get(RecipeVersion, candidate.recipe_version_id)
            ingredient_text = " ".join(
                (item.food_phrase or item.original_text).lower() for item in version.ingredients
            )
            if not any(
                re.search(rf"\b{re.escape(term)}\b", ingredient_text)
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
        try:
            choice = choose_shared_recipe(
                candidates_for_choice,
                participants,
                preferred_food_record_ids=preferred_foods,
                prior_recipe_uses=recipe_uses,
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
            servings=sum(choice.portions.values(), Decimal("0")) * len(slots),
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
            for member_id, servings in choice.portions.items():
                db.add(
                    PortionAllocation(
                        meal_occurrence_id=occurrence.id,
                        member_id=member_id,
                        servings=servings,
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


@router.get("/{plan_id}")
def get_plan(
    plan_id: str,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    plan = db.get(MealPlan, plan_id)
    if plan is None or plan.household_id != context.user.household_id:
        raise NotFoundError("Meal plan")
    occurrences = db.scalars(
        select(MealOccurrence)
        .where(MealOccurrence.meal_plan_id == plan.id)
        .order_by(MealOccurrence.meal_date, MealOccurrence.meal_type)
    ).all()
    items = []
    for occurrence in occurrences:
        batch = db.get(MealBatch, occurrence.batch_id)
        version = db.get(RecipeVersion, batch.recipe_version_id)
        recipe = db.get(Recipe, version.recipe_id)
        calculation = latest_calculation(db, version.id)
        portions = db.scalars(
            select(PortionAllocation).where(
                PortionAllocation.meal_occurrence_id == occurrence.id
            )
        ).all()
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
                "nutrition_per_serving": calculation.per_serving_values if calculation else None,
                "cooked_at": batch.cooked_at,
                "portions": [
                    {"member_id": portion.member_id, "servings": portion.servings}
                    for portion in portions
                ],
            }
        )
    return {"plan": PlanOut.model_validate(plan), "occurrences": items}


@router.post("/{plan_id}/accept", response_model=PlanOut)
def accept_plan(
    plan_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    plan = db.get(MealPlan, plan_id)
    if plan is None or plan.household_id != context.user.household_id:
        raise NotFoundError("Meal plan")
    if plan.status != PlanStatus.READY.value:
        raise DomainError("PLAN_NOT_READY", "Only a ready plan can be accepted")
    plan.status = PlanStatus.ACCEPTED.value
    plan.accepted_at = datetime.now(timezone.utc)
    plan.version += 1
    batches = db.scalars(select(MealBatch).where(MealBatch.meal_plan_id == plan.id)).all()
    reserve_plan_batches(db, context.user.household_id, list(batches))
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
