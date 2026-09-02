from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..errors import DomainError, NotFoundError
from ..models import (
    FoodNutrient,
    FoodRecord,
    HouseholdFoodUnitConversion,
    NutritionCalculation,
    Recipe,
    RecipeEligibility,
    RecipeVersion,
)
from .measurement_conversion import (
    convert_quantity_to_unit,
    measurement_dimension,
    resolve_measurement_profile,
)
from .quantities import canonical_quantity_unit


REQUIRED_NUTRIENTS = ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g")


@dataclass(frozen=True, slots=True)
class NutritionIssue:
    code: str
    message: str
    client_id: str | None = None


@dataclass(slots=True)
class NutritionConversionOption:
    kind: str
    source: str | None
    input_unit: str
    basis_amount_per_unit: Decimal | None
    basis_unit: str | None
    description: str
    requires_confirmation: bool = True


@dataclass(slots=True)
class IngredientNutritionResolution:
    client_id: str
    status: str
    food_record_id: str | None = None
    food_name: str | None = None
    label_basis: dict[str, Any] | None = None
    effective_amount: Decimal | None = None
    effective_unit: str | None = None
    formula: str | None = None
    contribution: dict[str, Decimal] = field(default_factory=dict)
    conversion_options: list[NutritionConversionOption] = field(default_factory=list)
    issues: list[NutritionIssue] = field(default_factory=list)
    persisted_contribution: dict[str, Any] | None = None
    assumptions: list[str] = field(default_factory=list)
    dataset_snapshot: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class NutritionResolution:
    complete: bool
    yield_servings: Decimal | None
    batch_values: dict[str, Decimal]
    per_serving_values: dict[str, Decimal]
    issues: list[NutritionIssue]
    ingredients: list[IngredientNutritionResolution]
    contributions: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    dataset_snapshot: dict[str, str] = field(default_factory=dict)


def _as_json(values: dict[str, Decimal]) -> dict[str, float]:
    return {key: round(float(value), 3) for key, value in values.items()}


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception:
        return None


def _value(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _client_id(row: Any, position: int) -> str:
    return str(_value(row, "client_id") or _value(row, "id") or f"ingredient-{position + 1}")


def _format_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def publisher_values(version: RecipeVersion) -> dict[str, Decimal] | None:
    """Return a complete publisher-reported per-serving nutrition set."""

    nutrition = version.publisher_nutrition
    if not isinstance(nutrition, dict):
        return None
    basis = str(nutrition.get("basis") or "").casefold().replace(" ", "")
    if "100g" in basis or "100ml" in basis:
        return None
    values: dict[str, Decimal] = {}
    for code in REQUIRED_NUTRIENTS:
        value = nutrition.get(code)
        if value is None:
            return None
        try:
            values[code] = Decimal(str(value))
        except Exception:
            return None
    return values


def _accessible_foods(
    db: Session,
    food_ids: set[str],
    household_id: str | None,
) -> dict[str, FoodRecord]:
    if not food_ids:
        return {}
    criteria = [FoodRecord.id.in_(food_ids)]
    if household_id is not None:
        criteria.append(
            or_(
                FoodRecord.owner_household_id.is_(None),
                FoodRecord.owner_household_id == household_id,
            )
        )
    return {
        food.id: food
        for food in db.scalars(select(FoodRecord).where(*criteria)).all()
    }


def _nutrients_by_food(
    db: Session, food_ids: Iterable[str]
) -> dict[str, dict[str, FoodNutrient]]:
    ids = list(food_ids)
    if not ids:
        return {}
    result: dict[str, dict[str, FoodNutrient]] = {}
    for row in db.scalars(
        select(FoodNutrient).where(FoodNutrient.food_record_id.in_(ids))
    ).all():
        result.setdefault(row.food_record_id, {})[row.code] = row
    return result


def _latest_conversion_memories(
    db: Session,
    household_id: str | None,
    food_ids: set[str],
    input_units: set[str],
) -> dict[tuple[str, str], HouseholdFoodUnitConversion]:
    if household_id is None or not food_ids or not input_units:
        return {}
    rows = db.scalars(
        select(HouseholdFoodUnitConversion)
        .where(
            HouseholdFoodUnitConversion.household_id == household_id,
            HouseholdFoodUnitConversion.food_record_id.in_(food_ids),
            HouseholdFoodUnitConversion.nutrition_input_unit.in_(input_units),
        )
        .order_by(
            HouseholdFoodUnitConversion.created_at.desc(),
            HouseholdFoodUnitConversion.id.desc(),
        )
    ).all()
    latest: dict[tuple[str, str], HouseholdFoodUnitConversion] = {}
    for row in rows:
        latest.setdefault((row.food_record_id, row.nutrition_input_unit), row)
    return latest


def _metadata_amount(metadata: dict[str, Any], prefix: str) -> tuple[Decimal, str] | None:
    amount = _decimal(metadata.get(f"{prefix}_amount"))
    unit = str(metadata.get(f"{prefix}_unit") or "").casefold()
    if amount is None or amount <= 0 or unit not in {"g", "ml"}:
        return None
    return amount, unit


def _conversion_options(
    food: FoodRecord,
    input_unit: str | None,
    memory: HouseholdFoodUnitConversion | None,
) -> list[NutritionConversionOption]:
    if not input_unit:
        return []
    options: list[NutritionConversionOption] = []
    if memory is not None:
        options.append(
            NutritionConversionOption(
                kind="remembered",
                source=memory.nutrition_conversion_source,
                input_unit=input_unit,
                basis_amount_per_unit=Decimal(memory.nutrition_basis_amount_per_unit),
                basis_unit=memory.nutrition_basis_unit,
                description=(
                    f"Remembered: 1 {input_unit} = "
                    f"{_format_decimal(Decimal(memory.nutrition_basis_amount_per_unit))} "
                    f"{memory.nutrition_basis_unit}"
                ),
            )
        )
    metadata = food.metadata_json if isinstance(food.metadata_json, dict) else {}
    for kind, source in (("package", "package"), ("serving", "serving")):
        amount = _metadata_amount(metadata, source)
        if amount is None:
            continue
        basis_amount, basis_unit = amount
        raw_description = str(
            metadata.get("quantity" if source == "package" else "serving_size") or ""
        ).strip()
        options.append(
            NutritionConversionOption(
                kind=kind,
                source=source,
                input_unit=input_unit,
                basis_amount_per_unit=basis_amount,
                basis_unit=basis_unit,
                description=(
                    f"{raw_description}: " if raw_description else ""
                )
                + f"1 {input_unit} = {_format_decimal(basis_amount)} {basis_unit}",
            )
        )
    options.append(
        NutritionConversionOption(
            kind="manual",
            source="manual",
            input_unit=input_unit,
            basis_amount_per_unit=None,
            basis_unit=food.basis_unit if food.basis_unit in {"g", "ml"} else None,
            description=f"Enter what 1 {input_unit} represents for nutrition.",
        )
    )
    return options


def _density_for(row: Any, food: FoodRecord) -> tuple[Decimal | None, str | None, str | None]:
    if food.density_g_per_ml is not None:
        return Decimal(food.density_g_per_ml), "food_density", "the matched food record"
    profile = resolve_measurement_profile(
        _value(row, "parsed_food_phrase"),
        _value(row, "food_phrase"),
        _value(row, "original_text"),
        food.name,
    )
    if profile is None:
        return None, None, None
    return profile.density_g_per_ml, "reviewed_density", profile.source_reference


def _convert_to_food_basis(
    amount: Decimal,
    amount_unit: str,
    food: FoodRecord,
    row: Any,
) -> tuple[Decimal | None, str | None, str | None]:
    """Return the food-basis amount and optional safe density provenance."""

    if amount_unit == food.basis_unit:
        return amount, None, None
    direct = convert_quantity_to_unit(amount, amount_unit, food.basis_unit, None)
    if direct is not None:
        return direct, None, None
    density, source, reference = _density_for(row, food)
    if density is None:
        return None, None, None
    converted = convert_quantity_to_unit(amount, amount_unit, food.basis_unit, density)
    return converted, source, reference


def _explicit_conversion(
    row: Any,
    input_unit: str | None,
) -> tuple[Decimal, str, str] | None:
    conversion_input = _value(row, "nutrition_input_unit")
    amount = _decimal(_value(row, "nutrition_basis_amount_per_unit"))
    basis_unit = _value(row, "nutrition_basis_unit")
    source = _value(row, "nutrition_conversion_source")
    values = (conversion_input, amount, basis_unit, source)
    if not any(value is not None for value in values):
        return None
    if (
        not conversion_input
        or amount is None
        or amount <= 0
        or basis_unit not in {"g", "ml"}
        or source not in {"package", "serving", "manual"}
        or input_unit is None
        or canonical_quantity_unit(str(conversion_input)) != input_unit
    ):
        return None
    return amount, str(basis_unit), str(source)


def _issue(code: str, message: str, client_id: str) -> NutritionIssue:
    return NutritionIssue(code=code, message=message, client_id=client_id)


def resolve_recipe_nutrition(
    db: Session,
    *,
    yield_servings: Decimal | None,
    ingredients: Iterable[Any],
    household_id: str | None,
    allow_legacy_quantity_grams: bool = False,
) -> NutritionResolution:
    """Resolve draft or persisted ingredient nutrition without mutating state.

    The same Decimal-based resolver powers the interactive preview and final
    NutritionCalculation persistence. It queries food and nutrient rows in
    bulk, and package/serving metadata is returned only as a confirmation
    option; it is never selected implicitly.
    """

    rows = list(ingredients)
    food_ids = {
        str(food_id)
        for row in rows
        if bool(_value(row, "included", True))
        and (food_id := _value(row, "food_record_id"))
    }
    input_units = {
        canonical_quantity_unit(str(unit))
        for row in rows
        if bool(_value(row, "included", True)) and (unit := _value(row, "unit"))
    }
    foods = _accessible_foods(db, food_ids, household_id)
    nutrients = _nutrients_by_food(db, foods)
    memories = _latest_conversion_memories(db, household_id, set(foods), input_units)

    totals = {code: Decimal("0") for code in REQUIRED_NUTRIENTS}
    issues: list[NutritionIssue] = []
    results: list[IngredientNutritionResolution] = []
    assumptions: list[str] = []
    dataset_snapshot: dict[str, str] = {}
    contributions: list[dict[str, Any]] = []

    if yield_servings is None or Decimal(yield_servings) <= 0:
        issues.append(
            NutritionIssue(
                code="MISSING_YIELD",
                message="Confirm a positive serving yield before calculating nutrition.",
            )
        )
    if not rows:
        issues.append(
            NutritionIssue(
                code="MISSING_INGREDIENTS",
                message="Add at least one ingredient before calculating nutrition.",
            )
        )

    for position, row in enumerate(rows):
        client_id = _client_id(row, position)
        if not bool(_value(row, "included", True)):
            results.append(IngredientNutritionResolution(client_id=client_id, status="excluded"))
            continue

        food_id = _value(row, "food_record_id")
        food = foods.get(str(food_id)) if food_id else None
        quantity = _decimal(_value(row, "quantity"))
        raw_unit = _value(row, "unit")
        input_unit = canonical_quantity_unit(str(raw_unit)) if raw_unit else None

        if quantity is None or not input_unit:
            row_issue = _issue(
                "MISSING_QUANTITY",
                "Enter an ingredient quantity and unit.",
                client_id,
            )
            result = IngredientNutritionResolution(
                client_id=client_id,
                status="missing_quantity",
                food_record_id=str(food_id) if food_id else None,
                issues=[row_issue],
            )
            issues.append(row_issue)
            results.append(result)
            continue

        if food is None:
            row_issue = _issue(
                "MISSING_MATCH",
                "Choose an available food match for this ingredient.",
                client_id,
            )
            result = IngredientNutritionResolution(
                client_id=client_id,
                status="missing_match",
                food_record_id=str(food_id) if food_id else None,
                issues=[row_issue],
            )
            issues.append(row_issue)
            results.append(result)
            continue

        label_basis = {"amount": Decimal(food.basis_amount), "unit": food.basis_unit}
        conversion_options = _conversion_options(
            food, input_unit, memories.get((food.id, input_unit))
        )
        row_issues: list[NutritionIssue] = []
        if bool(_value(row, "needs_review", False)):
            row_issues.append(
                _issue(
                    "NUTRITION_REVIEW_REQUIRED",
                    "Review this ingredient before using it in calculated nutrition.",
                    client_id,
                )
            )

        nutrient_map = nutrients.get(food.id, {})
        missing_nutrients = [
            code
            for code in REQUIRED_NUTRIENTS
            if code not in nutrient_map or nutrient_map[code].amount is None
        ]
        if missing_nutrients:
            row_issues.append(
                _issue(
                    "INCOMPLETE_FOOD_NUTRIENTS",
                    f"{food.name} is missing {', '.join(missing_nutrients)}.",
                    client_id,
                )
            )

        mapped = _explicit_conversion(row, input_unit)
        effective_amount: Decimal | None = None
        # Keep the explicitly confirmed mapping and a subsequent density
        # bridge separate.  A package mapping that happens to need a reviewed
        # density must still be auditable as a package confirmation.
        conversion_kind: str | None = None
        density_kind: str | None = None
        conversion_reference: str | None = None
        formula_prefix: str | None = None
        if mapped is not None:
            per_unit, mapped_unit, source = mapped
            converted, density_source, density_reference = _convert_to_food_basis(
                quantity * per_unit, mapped_unit, food, row
            )
            if converted is None:
                row_issues.append(
                    _issue(
                        "INCOMPATIBLE_UNITS",
                        f"The confirmed {mapped_unit} mapping cannot be converted to {food.basis_unit} for {food.name}.",
                        client_id,
                    )
                )
            else:
                effective_amount = converted
                conversion_kind = source
                conversion_reference = density_reference
                density_kind = density_source
                formula_prefix = (
                    f"{_format_decimal(quantity)} {input_unit} × "
                    f"{_format_decimal(per_unit)} {mapped_unit}/{input_unit}"
                )
        else:
            converted, density_source, density_reference = _convert_to_food_basis(
                quantity, input_unit, food, row
            )
            if converted is not None:
                effective_amount = converted
                conversion_kind = density_source or "direct"
                conversion_reference = density_reference
                formula_prefix = f"{_format_decimal(quantity)} {input_unit}"
            # A parser-derived gram amount is not a confirmation that a can,
            # packet, or other count unit represents that amount. Retain the
            # old fallback only for a mass measure, which remains safe to
            # interpret as grams; legacy count rows deliberately stay drafts.
            elif (
                allow_legacy_quantity_grams
                and food.basis_unit == "g"
                and measurement_dimension(input_unit) == "mass"
            ):
                legacy_grams = _decimal(_value(row, "quantity_grams"))
                if legacy_grams is not None:
                    effective_amount = legacy_grams
                    conversion_kind = "legacy_quantity_grams"
                    formula_prefix = f"{_format_decimal(legacy_grams)} g (legacy parsed amount)"
            if effective_amount is None:
                if measurement_dimension(input_unit) in {"mass", "volume"}:
                    row_issues.append(
                        _issue(
                            "INCOMPATIBLE_UNITS",
                            f"{input_unit} cannot be converted safely to {food.basis_unit} for {food.name}.",
                            client_id,
                        )
                    )
                else:
                    row_issues.append(
                        _issue(
                            "MISSING_CONVERSION",
                            f"Confirm what 1 {input_unit} represents for nutrition.",
                            client_id,
                        )
                    )

        if row_issues or effective_amount is None:
            status_by_code = {
                "MISSING_CONVERSION": "missing_conversion",
                "INCOMPATIBLE_UNITS": "incompatible_units",
                "INCOMPLETE_FOOD_NUTRIENTS": "incomplete_nutrients",
                "NUTRITION_REVIEW_REQUIRED": "needs_review",
            }
            result = IngredientNutritionResolution(
                client_id=client_id,
                status=next(
                    (status_by_code[item.code] for item in row_issues if item.code in status_by_code),
                    "unresolved",
                ),
                food_record_id=food.id,
                food_name=food.name,
                label_basis=label_basis,
                conversion_options=conversion_options,
                issues=row_issues,
            )
            issues.extend(row_issues)
            results.append(result)
            continue

        factor = effective_amount / Decimal(food.basis_amount)
        values = {
            code: Decimal(nutrient_map[code].amount) * factor
            for code in REQUIRED_NUTRIENTS
        }
        for code, value in values.items():
            totals[code] += value
        energy_label = nutrient_map["energy_kcal"]
        formula = (
            f"{formula_prefix} × {_format_decimal(Decimal(energy_label.amount))} "
            f"{energy_label.unit}/{_format_decimal(Decimal(food.basis_amount))} {food.basis_unit} "
            f"= {_format_decimal(values['energy_kcal'])} {energy_label.unit} batch"
        )
        if yield_servings is not None and Decimal(yield_servings) > 0:
            formula += (
                f" ÷ {_format_decimal(Decimal(yield_servings))} servings = "
                f"{_format_decimal(values['energy_kcal'] / Decimal(yield_servings))} "
                f"{energy_label.unit}/serving"
            )
        row_assumptions: list[str] = []
        if conversion_kind == "legacy_quantity_grams":
            row_assumptions.append("Used the legacy parsed gram amount saved with this recipe ingredient.")
        elif conversion_kind in {"package", "serving", "manual"}:
            row_assumptions.append(
                f"Used the confirmed {conversion_kind} mapping for {food.name}."
            )
        elif conversion_kind == "food_density":
            row_assumptions.append(
                f"Converted using the density saved on the matched food record for {food.name}."
            )
        elif conversion_kind == "reviewed_density":
            row_assumptions.append(
                f"Converted using reviewed density data ({conversion_reference or 'reviewed profile'})."
            )
        if density_kind:
            row_assumptions.append(
                f"Converted the confirmed mapping with {density_kind.replace('_', ' ')} "
                f"({conversion_reference or 'reviewed profile'})."
            )
        contribution = {
            "ingredient_id": _value(row, "id"),
            "client_id": client_id,
            "original_text": _value(row, "original_text") or "",
            "food_record_id": food.id,
            "food_name": food.name,
            "amount": float(effective_amount),
            "unit": food.basis_unit,
            "formula": formula,
            "conversion_source": conversion_kind,
            "density_conversion_source": density_kind,
            "density_reference": conversion_reference if density_kind else None,
            "values": _as_json(values),
        }
        result = IngredientNutritionResolution(
            client_id=client_id,
            status="resolved",
            food_record_id=food.id,
            food_name=food.name,
            label_basis=label_basis,
            effective_amount=effective_amount,
            effective_unit=food.basis_unit,
            formula=formula,
            contribution=values,
            conversion_options=conversion_options,
            persisted_contribution=contribution,
            assumptions=row_assumptions,
            dataset_snapshot={food.provider: food.dataset_version},
        )
        results.append(result)
        contributions.append(contribution)
        assumptions.extend(row_assumptions)
        dataset_snapshot[food.provider] = food.dataset_version

    complete = not issues
    per_serving = (
        {code: value / Decimal(yield_servings) for code, value in totals.items()}
        if complete and yield_servings is not None and Decimal(yield_servings) > 0
        else {}
    )
    return NutritionResolution(
        complete=complete,
        yield_servings=Decimal(yield_servings) if yield_servings is not None else None,
        batch_values=totals,
        per_serving_values=per_serving,
        issues=issues,
        ingredients=results,
        contributions=contributions,
        assumptions=assumptions,
        dataset_snapshot=dataset_snapshot,
    )


def calculate_recipe(db: Session, recipe_version_id: str) -> NutritionCalculation:
    version = db.get(RecipeVersion, recipe_version_id)
    if version is None:
        raise NotFoundError("Recipe version")
    if not version.yield_servings or version.yield_servings <= 0:
        raise DomainError("MISSING_YIELD", "Confirm a positive serving yield before calculating")

    recipe = db.get(Recipe, version.recipe_id)
    reported_values = publisher_values(version)
    if reported_values is not None:
        totals = {
            code: value * Decimal(version.yield_servings)
            for code, value in reported_values.items()
        }
        source = recipe.publisher or recipe.source_url if recipe is not None else "recipe publisher"
        calculation = NutritionCalculation(
            recipe_version_id=version.id,
            status="publisher",
            total_values=_as_json(totals),
            per_serving_values=_as_json(reported_values),
            contributions=[],
            assumptions=[f"Per-serving nutrition reported by {source or 'the recipe website'} was used."],
            dataset_snapshot={
                "nutrition_source": "publisher",
                "publisher": source or "recipe website",
            },
        )
        db.add(calculation)
        if recipe is not None:
            recipe.eligibility = RecipeEligibility.PLANNER_READY.value
            recipe.version += 1
        db.flush()
        return calculation

    if recipe is not None and recipe.source_type == "url":
        raise DomainError(
            "PUBLISHER_NUTRITION_UNAVAILABLE",
            "The recipe website did not report a complete per-serving nutrition set",
        )

    if not version.ingredients:
        raise DomainError("MISSING_INGREDIENTS", "The recipe has no ingredients")

    resolution = resolve_recipe_nutrition(
        db,
        yield_servings=Decimal(version.yield_servings),
        ingredients=version.ingredients,
        household_id=recipe.household_id if recipe is not None else None,
        allow_legacy_quantity_grams=True,
    )
    if not resolution.complete:
        details = "; ".join(issue.message for issue in resolution.issues)
        raise DomainError("NUTRITION_REVIEW_REQUIRED", details)

    calculation = NutritionCalculation(
        recipe_version_id=version.id,
        status="complete",
        total_values=_as_json(resolution.batch_values),
        per_serving_values=_as_json(resolution.per_serving_values),
        contributions=resolution.contributions,
        assumptions=resolution.assumptions,
        dataset_snapshot=resolution.dataset_snapshot,
    )
    db.add(calculation)
    if recipe is not None:
        recipe.eligibility = RecipeEligibility.PLANNER_READY.value
        recipe.version += 1
    db.flush()
    return calculation


def latest_calculation(db: Session, recipe_version_id: str) -> NutritionCalculation | None:
    return db.scalar(
        select(NutritionCalculation)
        .where(NutritionCalculation.recipe_version_id == recipe_version_id)
        .order_by(NutritionCalculation.calculated_at.desc())
    )


def planning_values(db: Session, version: RecipeVersion | None) -> dict[str, Decimal] | None:
    """Return the authoritative per-serving values used by the planner.

    URL-imported publisher values stay authoritative even if a stale
    ingredient-based calculation exists. Custom recipes use a complete saved
    calculation snapshot, not live food metadata.
    """

    if version is None:
        return None
    recipe = db.get(Recipe, version.recipe_id)
    if recipe is not None and recipe.source_type == "url":
        return publisher_values(version)
    calculation = latest_calculation(db, version.id)
    if calculation is not None and isinstance(calculation.per_serving_values, dict):
        values: dict[str, Decimal] = {}
        for code in REQUIRED_NUTRIENTS:
            raw = calculation.per_serving_values.get(code)
            if raw is None:
                return publisher_values(version)
            try:
                values[code] = Decimal(str(raw))
            except Exception:
                return publisher_values(version)
        return values
    return publisher_values(version)
