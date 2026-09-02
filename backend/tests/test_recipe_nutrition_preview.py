from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.models import (
    FoodNutrient,
    FoodRecord,
    Household,
    HouseholdFoodUnitConversion,
    MealBatch,
    MealPlan,
    NutritionCalculation,
    Recipe,
    RecipeMealType,
    RecipeVersion,
)
from app.services.nutrition import resolve_recipe_nutrition


NUTRIENTS = (
    ("energy_kcal", Decimal("84"), "kcal"),
    ("protein_g", Decimal("4.8"), "g"),
    ("carbohydrate_g", Decimal("12"), "g"),
    ("fat_g", Decimal("0.5"), "g"),
)


def _headers(owner):
    return {"X-CSRF-Token": owner["csrf_token"]}


def _food(session_factory, *, metadata=None):
    with session_factory() as db:
        food = FoodRecord(
            provider="test",
            provider_record_id="beans-preview",
            dataset_version="fixture-1",
            name="Tinned beans",
            basis_amount=Decimal("100"),
            basis_unit="g",
            metadata_json=metadata or {},
        )
        db.add(food)
        db.flush()
        for code, amount, unit in NUTRIENTS:
            db.add(FoodNutrient(food_record_id=food.id, code=code, amount=amount, unit=unit))
        db.commit()
        return food.id


def _preview_payload(food_id, *, mapping=None, quantity=2, yield_servings=4):
    row = {
        "client_id": "beans-row",
        "original_text": f"{quantity} cans tinned beans",
        "quantity": quantity,
        "unit": "cans",
        "included": True,
        "food_record_id": food_id,
    }
    if mapping:
        row.update(mapping)
    return {"yield_servings": yield_servings, "ingredients": [row]}


def test_preview_uses_confirmed_package_mapping_without_writing(client, owner, session_factory):
    food_id = _food(
        session_factory,
        metadata={
            "package_amount": "400",
            "package_unit": "g",
            "quantity": "400 g can",
            "serving_amount": "200",
            "serving_unit": "g",
            "serving_size": "200 g (half can)",
        },
    )
    with session_factory() as db:
        calculations_before = db.scalar(select(func.count(NutritionCalculation.id)))
        memories_before = db.scalar(select(func.count(HouseholdFoodUnitConversion.id)))

    response = client.post(
        "/api/v1/recipes/nutrition-preview",
        json=_preview_payload(
            food_id,
            mapping={
                "nutrition_input_unit": "can",
                "nutrition_basis_amount_per_unit": 400,
                "nutrition_basis_unit": "g",
                "nutrition_conversion_source": "package",
            },
        ),
    )

    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["complete"] is True
    assert Decimal(str(preview["batch_values"]["energy_kcal"])) == Decimal("672")
    assert Decimal(str(preview["per_serving_values"]["energy_kcal"])) == Decimal("168")
    row = preview["ingredients"][0]
    assert row["status"] == "resolved"
    assert Decimal(str(row["effective_amount"])) == Decimal("800")
    assert row["effective_unit"] == "g"
    assert row["formula"] == (
        "2 can × 400 g/can × 84 kcal/100 g = 672 kcal batch "
        "÷ 4 servings = 168 kcal/serving"
    )

    with session_factory() as db:
        assert db.scalar(select(func.count(NutritionCalculation.id))) == calculations_before
        assert db.scalar(select(func.count(HouseholdFoodUnitConversion.id))) == memories_before


def test_preview_scales_amount_and_yield_independently(client, owner, session_factory):
    food_id = _food(session_factory)
    mapping = {
        "nutrition_input_unit": "can",
        "nutrition_basis_amount_per_unit": 400,
        "nutrition_basis_unit": "g",
        "nutrition_conversion_source": "package",
    }
    baseline = client.post(
        "/api/v1/recipes/nutrition-preview",
        json=_preview_payload(food_id, mapping=mapping, quantity=2, yield_servings=4),
    )
    more_ingredients = client.post(
        "/api/v1/recipes/nutrition-preview",
        json=_preview_payload(food_id, mapping=mapping, quantity=3, yield_servings=4),
    )
    fewer_servings = client.post(
        "/api/v1/recipes/nutrition-preview",
        json=_preview_payload(food_id, mapping=mapping, quantity=2, yield_servings=2),
    )

    assert baseline.status_code == more_ingredients.status_code == fewer_servings.status_code == 200
    assert Decimal(str(baseline.json()["batch_values"]["energy_kcal"])) == Decimal("672")
    assert Decimal(str(more_ingredients.json()["batch_values"]["energy_kcal"])) == Decimal("1008")
    assert Decimal(str(more_ingredients.json()["per_serving_values"]["energy_kcal"])) == Decimal("252")
    assert Decimal(str(fewer_servings.json()["batch_values"]["energy_kcal"])) == Decimal("672")
    assert Decimal(str(fewer_servings.json()["per_serving_values"]["energy_kcal"])) == Decimal("336")


def test_preview_serializes_reviewed_density_provenance(client, owner, session_factory):
    with session_factory() as db:
        food = FoodRecord(
            provider="test",
            provider_record_id="plain-flour-preview",
            dataset_version="fixture-1",
            name="Plain flour",
            basis_amount=Decimal("100"),
            basis_unit="g",
        )
        db.add(food)
        db.flush()
        for code, amount, unit in NUTRIENTS:
            db.add(FoodNutrient(food_record_id=food.id, code=code, amount=amount, unit=unit))
        db.commit()
        food_id = food.id

    response = client.post(
        "/api/v1/recipes/nutrition-preview",
        json={
            "yield_servings": 2,
            "ingredients": [{
                "client_id": "flour-row",
                "original_text": "1 cup plain flour",
                "quantity": 1,
                "unit": "cup",
                "included": True,
                "food_record_id": food_id,
            }],
        },
    )

    assert response.status_code == 200, response.text
    row = response.json()["ingredients"][0]
    assert row["status"] == "resolved"
    assert any("reviewed density" in assumption.casefold() for assumption in row["assumptions"])


def test_legacy_count_gram_hint_stays_unresolved_until_confirmed(session_factory):
    food_id = _food(session_factory)
    with session_factory() as db:
        household = Household(name="Preview household")
        db.add(household)
        db.flush()
        result = resolve_recipe_nutrition(
            db,
            yield_servings=Decimal("4"),
            household_id=household.id,
            allow_legacy_quantity_grams=True,
            ingredients=[
                {
                    "client_id": "legacy-cans",
                    "original_text": "2 cans tinned beans",
                    "quantity": Decimal("2"),
                    "unit": "can",
                    "quantity_grams": Decimal("800"),
                    "included": True,
                    "food_record_id": food_id,
                }
            ],
        )

    assert result.complete is False
    assert result.ingredients[0].status == "missing_conversion"
    assert [issue.code for issue in result.issues] == ["MISSING_CONVERSION"]


def test_preview_offers_household_memory_but_never_applies_it_implicitly(
    client, owner, session_factory
):
    food_id = _food(session_factory)
    with session_factory() as db:
        # Setup creates a household even before a recipe has been saved.
        household = db.scalars(select(Household).order_by(Household.created_at)).first()
        other = Household(name="Other household")
        db.add(other)
        db.flush()
        db.add(
            HouseholdFoodUnitConversion(
                household_id=other.id,
                food_record_id=food_id,
                nutrition_input_unit="can",
                nutrition_basis_amount_per_unit=Decimal("450"),
                nutrition_basis_unit="g",
                nutrition_conversion_source="manual",
            )
        )
        db.commit()
        household_id = household.id

    first = client.post("/api/v1/recipes/nutrition-preview", json=_preview_payload(food_id))
    assert first.status_code == 200, first.text
    first_row = first.json()["ingredients"][0]
    assert first.json()["complete"] is False
    assert {issue["code"] for issue in first.json()["issues"]} == {"MISSING_CONVERSION"}
    assert all(option["kind"] != "remembered" for option in first_row["conversion_options"])

    with session_factory() as db:
        db.add(
            HouseholdFoodUnitConversion(
                household_id=household_id,
                food_record_id=food_id,
                nutrition_input_unit="can",
                nutrition_basis_amount_per_unit=Decimal("400"),
                nutrition_basis_unit="g",
                nutrition_conversion_source="package",
            )
        )
        db.commit()

    second = client.post("/api/v1/recipes/nutrition-preview", json=_preview_payload(food_id))
    assert second.status_code == 200, second.text
    options = second.json()["ingredients"][0]["conversion_options"]
    assert options[0]["kind"] == "remembered"
    assert Decimal(str(options[0]["basis_amount_per_unit"])) == Decimal("400")
    # A remembered mapping remains a suggested, confirmable option.
    assert second.json()["complete"] is False


def test_custom_save_snapshots_mapping_and_keeps_incomplete_edits_off_current_plans(
    client, owner, session_factory
):
    food_id = _food(session_factory)
    created = client.post(
        "/api/v1/recipes",
        headers=_headers(owner),
        json={"title": "Beans", "source_type": "custom", "ingredients": []},
    )
    assert created.status_code == 201, created.text

    saved = client.put(
        f"/api/v1/recipes/{created.json()['id']}",
        headers=_headers(owner),
        json={
            "expected_version": created.json()["version"],
            "title": "Beans",
            "yield_servings": 4,
            "meal_types": ["dinner"],
            "ingredients": [
                {
                    "original_text": "2 cans tinned beans",
                    "quantity": 2,
                    "unit": "can",
                    "food_record_id": food_id,
                    "nutrition_input_unit": "can",
                    "nutrition_basis_amount_per_unit": 400,
                    "nutrition_basis_unit": "g",
                    "nutrition_conversion_source": "package",
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    complete = saved.json()
    assert complete["planner_eligible"] is True
    assert Decimal(str(complete["calculated_nutrition"]["energy_kcal"])) == Decimal("168")

    with session_factory() as db:
        recipe = db.get(Recipe, complete["id"])
        original_version = db.get(RecipeVersion, complete["recipe_version_id"])
        assert original_version is not None
        assert original_version.ingredients[0].nutrition_basis_amount_per_unit == Decimal("400")
        assert db.scalar(select(func.count(HouseholdFoodUnitConversion.id))) == 1
        plan = MealPlan(
            household_id=recipe.household_id,
            name="Current plan",
            start_date=date(2026, 9, 2),
            end_date=date(2026, 9, 2),
            status="ready",
        )
        db.add(plan)
        db.flush()
        batch = MealBatch(
            meal_plan_id=plan.id,
            recipe_version_id=original_version.id,
            servings=Decimal("4"),
            planned_cook_date=plan.start_date,
        )
        db.add(batch)
        db.commit()
        original_version_id = original_version.id
        batch_id = batch.id

    draft = client.put(
        f"/api/v1/recipes/{complete['id']}",
        headers=_headers(owner),
        json={
            "expected_version": complete["version"],
            "title": "Beans draft correction",
            "yield_servings": None,
            "meal_types": [],
            "ingredients": [
                {
                    "original_text": "2 cans tinned beans",
                    "quantity": 2,
                    "unit": "can",
                    "food_record_id": food_id,
                    "nutrition_input_unit": "can",
                    "nutrition_basis_amount_per_unit": 450,
                    "nutrition_basis_unit": "g",
                    "nutrition_conversion_source": "manual",
                }
            ],
        },
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["planner_eligible"] is False
    assert draft.json()["plan_sync"]["plans_updated"] == 0

    with session_factory() as db:
        assert db.get(MealBatch, batch_id).recipe_version_id == original_version_id
        recipe = db.get(Recipe, complete["id"])
        assert recipe.title == "Beans"
        assert db.scalars(
            select(RecipeMealType.meal_type).where(RecipeMealType.recipe_id == recipe.id)
        ).all() == ["dinner"]
        assert db.scalar(select(func.count(HouseholdFoodUnitConversion.id))) == 1
        original_calculation = db.scalar(
            select(NutritionCalculation)
            .where(NutritionCalculation.recipe_version_id == original_version_id)
        )
        assert Decimal(str(original_calculation.per_serving_values["energy_kcal"])) == Decimal("168")


def test_mapping_correction_appends_history_without_mutating_old_recipe_snapshot(
    client, owner, session_factory
):
    food_id = _food(session_factory)
    created = client.post(
        "/api/v1/recipes",
        headers=_headers(owner),
        json={"title": "Beans", "source_type": "custom", "ingredients": []},
    )
    assert created.status_code == 201, created.text

    first = client.put(
        f"/api/v1/recipes/{created.json()['id']}",
        headers=_headers(owner),
        json={
            "expected_version": created.json()["version"],
            "title": "Beans",
            "yield_servings": 4,
            "ingredients": [
                {
                    "original_text": "1 can tinned beans",
                    "quantity": 1,
                    "unit": "can",
                    "food_record_id": food_id,
                    "nutrition_input_unit": "can",
                    "nutrition_basis_amount_per_unit": 400,
                    "nutrition_basis_unit": "g",
                    "nutrition_conversion_source": "package",
                }
            ],
        },
    )
    assert first.status_code == 200, first.text
    second = client.put(
        f"/api/v1/recipes/{created.json()['id']}",
        headers=_headers(owner),
        json={
            "expected_version": first.json()["version"],
            "title": "Beans",
            "yield_servings": 4,
            "ingredients": [
                {
                    "original_text": "1 can tinned beans",
                    "quantity": 1,
                    "unit": "can",
                    "food_record_id": food_id,
                    "nutrition_input_unit": "can",
                    "nutrition_basis_amount_per_unit": 450,
                    "nutrition_basis_unit": "g",
                    "nutrition_conversion_source": "manual",
                }
            ],
        },
    )
    assert second.status_code == 200, second.text

    with session_factory() as db:
        versions = db.scalars(
            select(RecipeVersion)
            .where(RecipeVersion.recipe_id == created.json()["id"])
            .order_by(RecipeVersion.version_number)
        ).all()
        assert versions[-2].ingredients[0].nutrition_basis_amount_per_unit == Decimal("400")
        assert versions[-2].ingredients[0].nutrition_conversion_source == "package"
        assert versions[-1].ingredients[0].nutrition_basis_amount_per_unit == Decimal("450")
        memories = db.scalars(
            select(HouseholdFoodUnitConversion)
            .where(HouseholdFoodUnitConversion.food_record_id == food_id)
        ).all()
        assert len(memories) == 2
        assert {memory.nutrition_basis_amount_per_unit for memory in memories} == {
            Decimal("400"),
            Decimal("450"),
        }
