from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re


@dataclass(frozen=True)
class RecipeCandidate:
    recipe_id: str
    recipe_version_id: str
    nutrition: dict[str, Decimal]
    food_record_ids: frozenset[str] = frozenset()
    ingredient_text: str = ""


@dataclass(frozen=True)
class ParticipantTarget:
    member_id: str
    mode: str
    allocation: Decimal
    calorie_target: Decimal | None
    protein_target_g: Decimal | None
    carbohydrate_target_g: Decimal | None
    fat_target_g: Decimal | None
    tolerance_percent: Decimal = Decimal("5")
    protein_min_g: Decimal | None = None
    protein_max_g: Decimal | None = None
    carbohydrate_min_g: Decimal | None = None
    carbohydrate_max_g: Decimal | None = None
    fat_min_g: Decimal | None = None
    fat_max_g: Decimal | None = None


@dataclass(frozen=True)
class PlannerChoice:
    candidate: RecipeCandidate
    portions: dict[str, Decimal]
    score: Decimal


PORTIONS = tuple(Decimal("0.5") + Decimal("0.25") * i for i in range(7))


class PlannerInfeasibleError(ValueError):
    """No shared recipe/portion combination satisfies every hard boundary."""


def _target_values(target: ParticipantTarget) -> dict[str, Decimal]:
    if target.mode == "calorie":
        return {"energy_kcal": Decimal(target.calorie_target or 0) * target.allocation / 100}
    return {
        "protein_g": Decimal(target.protein_target_g or 0) * target.allocation / 100,
        "carbohydrate_g": Decimal(target.carbohydrate_target_g or 0) * target.allocation / 100,
        "fat_g": Decimal(target.fat_target_g or 0) * target.allocation / 100,
    }


def _within_hard_bounds(
    target: ParticipantTarget, nutrition: dict[str, Decimal], portion: Decimal
) -> bool:
    tolerance = target.tolerance_percent / Decimal("100")
    for nutrient, expected in _target_values(target).items():
        actual = nutrition.get(nutrient, Decimal("0")) * portion
        if actual < expected * (Decimal("1") - tolerance):
            return False
        if actual > expected * (Decimal("1") + tolerance):
            return False

    # Calorie mode can additionally carry daily macro guardrails. Apply the
    # meal's allocation share to those bounds just as we do to calories.
    if target.mode == "calorie":
        for nutrient, low, high in (
            ("protein_g", target.protein_min_g, target.protein_max_g),
            ("carbohydrate_g", target.carbohydrate_min_g, target.carbohydrate_max_g),
            ("fat_g", target.fat_min_g, target.fat_max_g),
        ):
            actual = nutrition.get(nutrient, Decimal("0")) * portion
            if low is not None and actual < low * target.allocation / Decimal("100"):
                return False
            if high is not None and actual > high * target.allocation / Decimal("100"):
                return False
    return True


def aggregate_nutrition_violations(
    targets: list[ParticipantTarget], nutrition: dict[str, Decimal]
) -> list[str]:
    """Return hard-bound failures after combining a participant's planned meals.

    Meal allocations determine how much of the daily target is covered by the
    supplied targets, but are deliberately not enforced meal by meal.
    """
    if not targets:
        return []
    if len({target.member_id for target in targets}) != 1:
        raise ValueError("aggregate targets must belong to one participant")
    if len({target.mode for target in targets}) != 1:
        raise ValueError("aggregate targets must use one target mode")

    expected: dict[str, Decimal] = {}
    for target in targets:
        for nutrient, value in _target_values(target).items():
            expected[nutrient] = expected.get(nutrient, Decimal("0")) + value

    tolerance = targets[0].tolerance_percent / Decimal("100")
    violations: list[str] = []
    labels = {
        "energy_kcal": "calories",
        "protein_g": "protein",
        "carbohydrate_g": "carbohydrate",
        "fat_g": "fat",
    }
    for nutrient, target_value in expected.items():
        actual = nutrition.get(nutrient, Decimal("0"))
        low = target_value * (Decimal("1") - tolerance)
        high = target_value * (Decimal("1") + tolerance)
        if actual < low or actual > high:
            violations.append(
                f"{labels[nutrient]} {actual.normalize()} is outside "
                f"{low.normalize()}-{high.normalize()}"
            )

    if targets[0].mode == "calorie":
        allocation = sum((target.allocation for target in targets), Decimal("0"))
        first = targets[0]
        for nutrient, low_daily, high_daily in (
            ("protein_g", first.protein_min_g, first.protein_max_g),
            ("carbohydrate_g", first.carbohydrate_min_g, first.carbohydrate_max_g),
            ("fat_g", first.fat_min_g, first.fat_max_g),
        ):
            actual = nutrition.get(nutrient, Decimal("0"))
            low = low_daily * allocation / Decimal("100") if low_daily is not None else None
            high = high_daily * allocation / Decimal("100") if high_daily is not None else None
            if low is not None and actual < low:
                violations.append(
                    f"{labels[nutrient]} {actual.normalize()} is below {low.normalize()}"
                )
            if high is not None and actual > high:
                violations.append(
                    f"{labels[nutrient]} {actual.normalize()} is above {high.normalize()}"
                )
    return violations


def choose_shared_recipe(
    candidates: list[RecipeCandidate],
    participants: list[ParticipantTarget],
    preferred_food_record_ids: frozenset[str] = frozenset(),
    prior_recipe_uses: dict[str, int] | None = None,
    preferred_terms: frozenset[str] = frozenset(),
    disliked_terms: frozenset[str] = frozenset(),
    enforce_nutrition_bounds: bool = True,
) -> PlannerChoice:
    if not candidates:
        raise ValueError("No planner-ready recipe candidates")
    if not participants:
        raise ValueError("No participants")

    best: PlannerChoice | None = None
    for candidate in candidates:
        portions: dict[str, Decimal] = {}
        score = Decimal("0")
        candidate_is_feasible = True
        for participant in participants:
            targets = _target_values(participant)
            best_portion: Decimal | None = None
            best_error: Decimal | None = None
            for portion in PORTIONS:
                if enforce_nutrition_bounds and not _within_hard_bounds(
                    participant, candidate.nutrition, portion
                ):
                    continue
                error = Decimal("0")
                for key, target_value in targets.items():
                    actual = candidate.nutrition.get(key, Decimal("0")) * portion
                    denominator = max(target_value, Decimal("1"))
                    error += abs(actual - target_value) / denominator
                # Break nutrition ties in favour of an ordinary serving size.
                error += abs(portion - Decimal("1")) / Decimal("1000")
                if best_error is None or error < best_error:
                    best_portion, best_error = portion, error
            if best_portion is None or best_error is None:
                candidate_is_feasible = False
                break
            portions[participant.member_id] = best_portion
            score += best_error
        if not candidate_is_feasible:
            continue
        # Preferences influence ranking only; they never override hard targets.
        score -= Decimal("0.0001") * len(candidate.food_record_ids & preferred_food_record_ids)
        preferred_matches = sum(
            bool(re.search(rf"\b{re.escape(term)}\b", candidate.ingredient_text))
            for term in preferred_terms
        )
        disliked_matches = sum(
            bool(re.search(rf"\b{re.escape(term)}\b", candidate.ingredient_text))
            for term in disliked_terms
        )
        score -= Decimal("0.0001") * preferred_matches
        score += Decimal("0.0001") * disliked_matches
        # Variety is a soft objective. A repeated recipe remains available when
        # it is the only way to satisfy hard nutrition/restriction constraints.
        score += Decimal("0.01") * (prior_recipe_uses or {}).get(candidate.recipe_id, 0)
        choice = PlannerChoice(candidate=candidate, portions=portions, score=score)
        if best is None or choice.score < best.score:
            best = choice
    if best is None:
        raise PlannerInfeasibleError(
            "No recipe and quarter-portion combination meets every participant's nutrition tolerance"
        )
    return best
