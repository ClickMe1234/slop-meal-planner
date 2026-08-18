from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..errors import DomainError
from ..models import (
    MealBatch,
    MealOccurrence,
    MealPlan,
    NutritionCalculation,
    PantryReservation,
    PlanStatus,
    PortionAllocation,
    Recipe,
    RecipeIngredient,
    RecipeVersion,
    ShoppingList,
)
from .pantry import reserve_plan_batches
from .shopping import build_shopping_list
from .recipe_methods import clone_method_snapshot
from .planner import BOOST_PORTIONS, SIDE_PORTIONS, recipe_portions


@dataclass(frozen=True, slots=True)
class PlanSyncResult:
    plans_updated: int = 0
    shopping_list_rebuilt: bool = False
    shopping_list_id: str | None = None
    cooked_batches_unchanged: int = 0


def _reconcile_batch_servings(
    db: Session, batch: MealBatch, version: RecipeVersion
) -> None:
    """Move uncooked allocations onto a replacement version's valid sequence."""
    if version.minimum_servings is None or version.serving_increment is None:
        return
    allowed = recipe_portions(
        SIDE_PORTIONS if batch.parent_batch_id is not None else BOOST_PORTIONS,
        Decimal(version.minimum_servings),
        Decimal(version.serving_increment),
    )
    occurrences = db.scalars(
        select(MealOccurrence)
        .where(MealOccurrence.batch_id == batch.id)
        .order_by(MealOccurrence.meal_date, MealOccurrence.id)
    ).all()
    batch_servings = Decimal("0")
    for occurrence in occurrences:
        allocations = db.scalars(
            select(PortionAllocation)
            .where(PortionAllocation.meal_occurrence_id == occurrence.id)
            .order_by(PortionAllocation.member_id)
        ).all()
        old_largest = max(
            (Decimal(allocation.servings) for allocation in allocations),
            default=Decimal("0"),
        )
        for allocation in allocations:
            current = Decimal(allocation.servings)
            allocation.servings = min(
                allowed,
                key=lambda value: (abs(value - current), value),
            )
        new_largest = max(
            (Decimal(allocation.servings) for allocation in allocations),
            default=Decimal("0"),
        )
        if old_largest > 0 and occurrence.guest_servings:
            occurrence.guest_servings = (
                Decimal(occurrence.guest_servings) * new_largest / old_largest
            )
        batch_servings += sum(
            (Decimal(allocation.servings) for allocation in allocations),
            Decimal("0"),
        ) + Decimal(occurrence.guest_servings)
    batch.servings = batch_servings


def clone_recipe_version_for_shopping(
    db: Session,
    recipe: Recipe,
    previous: RecipeVersion,
    changes: dict[str, dict[str, object]],
) -> RecipeVersion:
    """Clone an immutable recipe version while changing shopping-facing fields."""

    next_version = RecipeVersion(
        recipe_id=recipe.id,
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
    for ingredient in previous.ingredients:
        values = {
            column.name: getattr(ingredient, column.name)
            for column in ingredient.__table__.columns
            if column.name not in {"id", "recipe_version_id"}
        }
        change = changes.get(ingredient.id)
        if change:
            values.update(
                quantity=Decimal(str(change["quantity"])),
                unit=str(change["unit"]),
                food_phrase=str(change["food_phrase"]),
                name_overridden=True,
                shopping_measurement_overridden=True,
                shopping_group_key=change.get("shopping_group_key"),
            )
            if change.get("quantity_grams") is not None:
                values["quantity_grams"] = Decimal(str(change["quantity_grams"]))
        db.add(
            RecipeIngredient(
                recipe_version_id=next_version.id,
                **values,
            )
        )
    if previous.method_snapshot is not None:
        db.add(
            clone_method_snapshot(
                previous.method_snapshot,
                recipe_version_id=next_version.id,
                created_by_user_id=None,
            )
        )
    previous_calculation = db.scalar(
        select(NutritionCalculation)
        .where(NutritionCalculation.recipe_version_id == previous.id)
        .order_by(NutritionCalculation.calculated_at.desc())
    )
    if previous_calculation is not None:
        db.add(
            NutritionCalculation(
                recipe_version_id=next_version.id,
                status=previous_calculation.status,
                total_values=dict(previous_calculation.total_values or {}),
                per_serving_values=dict(previous_calculation.per_serving_values or {}),
                contributions=list(previous_calculation.contributions or []),
                assumptions=[
                    *(previous_calculation.assumptions or []),
                    "Shopping representation changed without changing the physical ingredient amount.",
                ],
                dataset_snapshot=dict(previous_calculation.dataset_snapshot or {}),
            )
        )
    recipe.version += 1
    db.flush()
    return next_version


def sync_recipe_versions_to_current_plans(
    db: Session,
    household_id: str,
    replacements: dict[str, str],
) -> PlanSyncResult:
    if not replacements:
        return PlanSyncResult()
    batches = db.scalars(
        select(MealBatch)
        .join(MealPlan, MealPlan.id == MealBatch.meal_plan_id)
        .where(
            MealBatch.recipe_version_id.in_(list(replacements)),
            MealPlan.household_id == household_id,
            MealPlan.status.in_(
                [PlanStatus.READY.value, PlanStatus.ACCEPTED.value]
            ),
        )
        .order_by(MealBatch.meal_plan_id, MealBatch.id)
    ).all()
    plan_ids = sorted({batch.meal_plan_id for batch in batches})
    if not plan_ids:
        return PlanSyncResult()
    plans = {
        plan.id: plan
        for plan in db.scalars(
            select(MealPlan)
            .where(MealPlan.id.in_(plan_ids))
            .order_by(MealPlan.id)
            .with_for_update()
        ).all()
    }
    changed_plan_ids: set[str] = set()
    accepted_changed_ids: set[str] = set()
    cooked_unchanged = 0
    for batch in batches:
        plan = plans.get(batch.meal_plan_id)
        if plan is None:
            continue
        if plan.status == PlanStatus.ACCEPTED.value and batch.cooked_at is not None:
            cooked_unchanged += 1
            continue
        replacement = replacements.get(batch.recipe_version_id)
        if replacement is None:
            continue
        batch.recipe_version_id = replacement
        replacement_version = db.get(RecipeVersion, replacement)
        if replacement_version is None:
            raise DomainError(
                "INVALID_RECIPE_VERSION",
                "A replacement recipe version no longer exists",
                409,
            )
        _reconcile_batch_servings(db, batch, replacement_version)
        changed_plan_ids.add(plan.id)
        if plan.status == PlanStatus.ACCEPTED.value:
            accepted_changed_ids.add(plan.id)
    for plan_id in changed_plan_ids:
        plans[plan_id].version += 1
    if not accepted_changed_ids:
        db.flush()
        return PlanSyncResult(
            plans_updated=len(changed_plan_ids),
            cooked_batches_unchanged=cooked_unchanged,
        )
    if len(accepted_changed_ids) > 1:
        raise DomainError(
            "MULTIPLE_ACCEPTED_PLANS",
            "Only one accepted plan can be synchronised at a time",
            409,
        )
    accepted_id = next(iter(accepted_changed_ids))
    active_list = db.scalar(
        select(ShoppingList)
        .where(
            ShoppingList.household_id == household_id,
            ShoppingList.meal_plan_id == accepted_id,
            ShoppingList.active.is_(True),
        )
        .with_for_update()
    )
    if active_list is None:
        db.flush()
        return PlanSyncResult(
            plans_updated=len(changed_plan_ids),
            cooked_batches_unchanged=cooked_unchanged,
        )
    plan_batches = db.scalars(
        select(MealBatch)
        .where(MealBatch.meal_plan_id == accepted_id)
        .order_by(MealBatch.planned_cook_date, MealBatch.id)
    ).all()
    batch_ids = [batch.id for batch in plan_batches]
    if batch_ids:
        db.execute(
            delete(PantryReservation).where(
                PantryReservation.meal_batch_id.in_(batch_ids)
            )
        )
    db.flush()
    reserve_plan_batches(
        db,
        household_id,
        [batch for batch in plan_batches if batch.cooked_at is None],
    )
    rebuilt = build_shopping_list(
        db,
        household_id,
        accepted_id,
        active_list.name,
    )
    db.flush()
    return PlanSyncResult(
        plans_updated=len(changed_plan_ids),
        shopping_list_rebuilt=True,
        shopping_list_id=rebuilt.id,
        cooked_batches_unchanged=cooked_unchanged,
    )
