from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re


@dataclass(frozen=True)
class RecipeCandidate:
    recipe_id: str
    recipe_version_id: str
    nutrition: dict[str, Decimal]
    minimum_servings: Decimal | None = None
    serving_increment: Decimal | None = None
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


@dataclass(frozen=True)
class PlanPortionVariable:
    key: str
    member_id: str
    dates: tuple[str, ...]
    nutrition: dict[str, Decimal]
    current: Decimal
    allowed: tuple[Decimal, ...]
    meal_type: str = ""
    component_slot: int = 0
    meal_target: ParticipantTarget | None = None


PORTIONS = tuple(Decimal("0.5") + Decimal("0.25") * i for i in range(7))
BOOST_PORTIONS = tuple(Decimal("0.5") + Decimal("0.25") * i for i in range(23))
SIDE_PORTIONS = tuple(Decimal("0.25") + Decimal("0.25") * i for i in range(8))
MACRO_MINIMUM_TOLERANCE_G = Decimal("10")
BOOSTED_MEAL_TARGET_WEIGHT = Decimal("10")


class PlannerInfeasibleError(ValueError):
    """No shared recipe/portion combination satisfies every hard boundary."""


def recipe_portions(
    standard_portions: tuple[Decimal, ...],
    minimum_servings: Decimal | None,
    serving_increment: Decimal | None,
) -> tuple[Decimal, ...]:
    """Return recipe-specific portions without changing legacy defaults."""
    if minimum_servings is None and serving_increment is None:
        return standard_portions
    if minimum_servings is None or serving_increment is None or serving_increment <= 0:
        raise ValueError("Recipe serving constraints are incomplete or invalid")
    maximum = standard_portions[-1]
    portions: list[Decimal] = []
    portion = minimum_servings
    while portion <= maximum:
        portions.append(portion)
        portion += serving_increment
    return tuple(portions)


def _target_values(target: ParticipantTarget) -> dict[str, Decimal]:
    if target.mode == "calorie":
        return {"energy_kcal": Decimal(target.calorie_target or 0) * target.allocation / 100}
    return {
        "protein_g": Decimal(target.protein_target_g or 0) * target.allocation / 100,
        "carbohydrate_g": Decimal(target.carbohydrate_target_g or 0) * target.allocation / 100,
        "fat_g": Decimal(target.fat_target_g or 0) * target.allocation / 100,
    }


def _minimum_values(target: ParticipantTarget) -> dict[str, Decimal]:
    """Return allocated calorie-mode minimums that should influence ranking."""
    if target.mode != "calorie":
        return {}
    return {
        nutrient: Decimal(value) * target.allocation / 100
        for nutrient, value in (
            ("protein_g", target.protein_min_g),
            ("carbohydrate_g", target.carbohydrate_min_g),
            ("fat_g", target.fat_min_g),
        )
        if value is not None and value > 0
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
            allocated_low = None
            if low is not None and low > 0:
                allocated_low = max(
                    (low - MACRO_MINIMUM_TOLERANCE_G) * target.allocation / Decimal("100"),
                    Decimal("0"),
                )
            if allocated_low is not None and actual < allocated_low:
                return False
            if high is not None and actual > high * target.allocation / Decimal("100"):
                return False
    return True


def _display_decimal(value: Decimal) -> str:
    return f"{value:f}".rstrip("0").rstrip(".") if "." in f"{value:f}" else f"{value:f}"


def aggregate_nutrition_issues(
    targets: list[ParticipantTarget], nutrition: dict[str, Decimal]
) -> list[dict[str, str]]:
    """Return structured hard-bound failures for a participant's planned meals.

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
    issues: list[dict[str, str]] = []
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
            unit = "kcal" if nutrient == "energy_kcal" else "g"
            issues.append({
                "nutrient": labels[nutrient],
                "actual": _display_decimal(actual),
                "low": _display_decimal(low),
                "high": _display_decimal(high),
                "kind": "range",
                "message": (
                    f"{labels[nutrient].capitalize()}: {_display_decimal(actual)} {unit} "
                    f"(allowed {_display_decimal(low)}–{_display_decimal(high)} {unit})"
                ),
            })

    if targets[0].mode == "calorie":
        allocation = sum((target.allocation for target in targets), Decimal("0"))
        first = targets[0]
        for nutrient, low_daily, high_daily in (
            ("protein_g", first.protein_min_g, first.protein_max_g),
            ("carbohydrate_g", first.carbohydrate_min_g, first.carbohydrate_max_g),
            ("fat_g", first.fat_min_g, first.fat_max_g),
        ):
            actual = nutrition.get(nutrient, Decimal("0"))
            low = None
            if low_daily is not None and low_daily > 0:
                allocated_minimum = low_daily * allocation / Decimal("100")
                allocated_tolerance = MACRO_MINIMUM_TOLERANCE_G * allocation / Decimal("100")
                low = max(allocated_minimum - allocated_tolerance, Decimal("0"))
            high = high_daily * allocation / Decimal("100") if high_daily is not None else None
            if low is not None and actual < low:
                issues.append({
                    "nutrient": labels[nutrient],
                    "actual": _display_decimal(actual),
                    "low": _display_decimal(low),
                    "kind": "minimum",
                    "message": (
                        f"{labels[nutrient].capitalize()}: {_display_decimal(actual)} g "
                        f"(minimum {_display_decimal(low)} g after tolerance)"
                    ),
                })
            if high is not None and actual > high:
                issues.append({
                    "nutrient": labels[nutrient],
                    "actual": _display_decimal(actual),
                    "high": _display_decimal(high),
                    "kind": "maximum",
                    "message": (
                        f"{labels[nutrient].capitalize()}: {_display_decimal(actual)} g "
                        f"(maximum {_display_decimal(high)} g)"
                    ),
                })
    return issues


def aggregate_nutrition_violations(
    targets: list[ParticipantTarget], nutrition: dict[str, Decimal]
) -> list[str]:
    return [issue["message"] for issue in aggregate_nutrition_issues(targets, nutrition)]


def _portion_plan_score(
    variables: list[PlanPortionVariable],
    portions: dict[str, Decimal],
    daily_targets: dict[tuple[str, str], list[ParticipantTarget]],
) -> tuple[Decimal, bool]:
    nutrition: dict[tuple[str, str], dict[str, Decimal]] = {}
    meal_nutrition: dict[tuple[str, str, str], dict[str, Decimal]] = {}
    meal_targets: dict[tuple[str, str, str], ParticipantTarget] = {}
    for variable in variables:
        portion = portions[variable.key]
        for meal_date in variable.dates:
            key = (meal_date, variable.member_id)
            totals = nutrition.setdefault(key, {})
            meal_key = (meal_date, variable.member_id, variable.meal_type)
            meal_totals = meal_nutrition.setdefault(meal_key, {})
            for nutrient, amount in variable.nutrition.items():
                totals[nutrient] = totals.get(nutrient, Decimal("0")) + amount * portion
                meal_totals[nutrient] = (
                    meal_totals.get(nutrient, Decimal("0")) + amount * portion
                )
            if variable.meal_target is not None:
                meal_targets[meal_key] = variable.meal_target

    score = Decimal("0")
    feasible = True
    for key, targets in daily_targets.items():
        actual = nutrition.get(key, {})
        expected: dict[str, Decimal] = {}
        for target in targets:
            for nutrient, value in _target_values(target).items():
                expected[nutrient] = expected.get(nutrient, Decimal("0")) + value
        for nutrient, target_value in expected.items():
            value = actual.get(nutrient, Decimal("0"))
            score += abs(value - target_value) / max(target_value, Decimal("1"))

        issues = aggregate_nutrition_issues(targets, actual)
        if issues:
            feasible = False
            # Hard-bound distance dominates the ordinary closeness objective.
            for issue in issues:
                value = Decimal(issue["actual"])
                if "low" in issue and value < Decimal(issue["low"]):
                    score += Decimal("1000") * (
                        Decimal(issue["low"]) - value
                    ) / max(Decimal(issue["low"]), Decimal("1"))
                if "high" in issue and value > Decimal(issue["high"]):
                    score += Decimal("1000") * (
                        value - Decimal(issue["high"])
                    ) / max(Decimal(issue["high"]), Decimal("1"))

    # Explicit boost sliders are a distribution instruction, not merely a list
    # of meals allowed to grow. Keep the daily nutrition bounds authoritative,
    # while strongly preferring each selected meal's allocated calorie target.
    for key, target in meal_targets.items():
        actual = meal_nutrition.get(key, {})
        for nutrient, target_value in _target_values(target).items():
            value = actual.get(nutrient, Decimal("0"))
            score += BOOSTED_MEAL_TARGET_WEIGHT * (
                abs(value - target_value) / max(target_value, Decimal("1"))
            )

    score += sum(
        (abs(portions[variable.key] - Decimal("1")) / Decimal("1000") for variable in variables),
        Decimal("0"),
    )
    return score, feasible


def rebalance_plan_portions(
    variables: list[PlanPortionVariable],
    daily_targets: dict[tuple[str, str], list[ParticipantTarget]],
    *,
    enforce_nutrition_bounds: bool = True,
) -> dict[str, Decimal]:
    """Re-quantify fixed recipes together while respecting shared batch portions.

    A variable is one occurrence/member serving amount. Several deterministic
    starts make the discrete coordinate search resilient without making plan
    edits depend on an optional external solver. Semantic meal ordering keeps
    otherwise identical days stable instead of letting random record IDs decide
    which of several near-equivalent portion combinations wins.
    """
    if not variables:
        return {}

    starts: list[dict[str, Decimal]] = []
    for mode in ("current", "one", "minimum", "maximum"):
        start: dict[str, Decimal] = {}
        for variable in variables:
            if mode == "current" and variable.current in variable.allowed:
                start[variable.key] = variable.current
            elif mode == "minimum":
                start[variable.key] = variable.allowed[0]
            elif mode == "maximum":
                start[variable.key] = variable.allowed[-1]
            else:
                start[variable.key] = min(
                    variable.allowed, key=lambda value: abs(value - Decimal("1"))
                )
        starts.append(start)

    best_portions: dict[str, Decimal] | None = None
    best_score: Decimal | None = None
    best_feasible = False
    meal_order = {"breakfast": 0, "lunch": 1, "dinner": 2, "snack": 3}
    ordered = sorted(
        variables,
        key=lambda item: (
            item.dates,
            item.member_id,
            meal_order.get(item.meal_type, len(meal_order)),
            item.component_slot,
            item.key,
        ),
    )
    for portions in starts:
        for _ in range(12):
            changed = False
            for variable in ordered:
                current_value = portions[variable.key]
                candidate_value = min(
                    variable.allowed,
                    key=lambda value: (
                        _portion_plan_score(
                            variables,
                            {**portions, variable.key: value},
                            daily_targets,
                        )[0],
                        abs(value - current_value),
                        value,
                    ),
                )
                if candidate_value != current_value:
                    portions[variable.key] = candidate_value
                    changed = True
            if not changed:
                break
        score, feasible = _portion_plan_score(variables, portions, daily_targets)
        if (
            best_portions is None
            or (feasible and not best_feasible)
            or (feasible == best_feasible and (best_score is None or score < best_score))
        ):
            best_portions = dict(portions)
            best_score = score
            best_feasible = feasible

    if best_portions is None or (enforce_nutrition_bounds and not best_feasible):
        raise PlannerInfeasibleError(
            "No whole-plan serving combination meets every daily nutrition tolerance"
        )
    return best_portions


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
        allowed_portions = recipe_portions(
            PORTIONS, candidate.minimum_servings, candidate.serving_increment
        )
        portions: dict[str, Decimal] = {}
        score = Decimal("0")
        candidate_is_feasible = True
        for participant in participants:
            targets = _target_values(participant)
            minimums = _minimum_values(participant)
            best_portion: Decimal | None = None
            best_error: Decimal | None = None
            for portion in allowed_portions:
                if enforce_nutrition_bounds and not _within_hard_bounds(
                    participant, candidate.nutrition, portion
                ):
                    continue
                error = Decimal("0")
                for key, target_value in targets.items():
                    actual = candidate.nutrition.get(key, Decimal("0")) * portion
                    denominator = max(target_value, Decimal("1"))
                    error += abs(actual - target_value) / denominator
                # A minimum is one-sided: shortage makes a choice worse, while
                # exceeding it is not penalised. Zero preserves calorie-only ranking.
                for key, minimum in minimums.items():
                    actual = candidate.nutrition.get(key, Decimal("0")) * portion
                    error += max(minimum - actual, Decimal("0")) / minimum
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
            "No recipe and allowed serving combination meets every participant's nutrition tolerance"
        )
    return best
