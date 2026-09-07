from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.models import (
    FoodNutrient,
    FoodRecord,
    Household,
    HouseholdFoodUnitConversion,
    HouseholdMember,
    MealBatch,
    MealOccurrence,
    MealPlan,
    PantryLot,
    PlanStatus,
    PortionAllocation,
    Recipe,
    RecipeIngredient,
    RecipeVersion,
    SavedFood,
    ShoppingItem,
    ShoppingList,
)
from app.services.selective_restore import (
    _component_tables,
    _counts,
    _insert_rows,
    _load_source_bundle,
    _prepare_historical_id_maps,
    _row_data,
    list_archives,
)


def test_source_bundle_scopes_household_and_keeps_linked_food_records(db):
    source = Household(name="Source", timezone="Europe/London")
    other = Household(name="Other", timezone="Europe/London")
    db.add_all([source, other])
    db.flush()

    member = HouseholdMember(household_id=source.id, name="Alex")
    recipe = Recipe(household_id=source.id, title="Source soup")
    food = FoodRecord(
        owner_household_id=source.id,
        provider="manual",
        provider_record_id="source-food",
        dataset_version="test",
        name="Soup vegetables",
    )
    db.add_all([member, recipe, food])
    db.flush()
    version = RecipeVersion(recipe_id=recipe.id, version_number=1, title="Source soup", yield_servings=4)
    db.add(version)
    db.flush()
    db.add_all([
        RecipeIngredient(recipe_version_id=version.id, position=1, original_text="2 carrots", food_record_id=food.id),
        FoodNutrient(food_record_id=food.id, code="energy_kcal", amount=40, unit="kcal"),
        SavedFood(household_id=source.id, food_record_id=food.id, display_name="Soup vegetables"),
        PantryLot(household_id=source.id, food_record_id=food.id, display_name="Soup vegetables", initial_quantity=2, unit="kg"),
        Recipe(household_id=other.id, title="Other recipe"),
    ])
    db.add(
        HouseholdFoodUnitConversion(
            household_id=source.id,
            food_record_id=food.id,
            nutrition_input_unit="can",
            nutrition_basis_amount_per_unit=400,
            nutrition_basis_unit="g",
            nutrition_conversion_source="package",
        )
    )
    db.commit()

    bundle = _load_source_bundle(db, source.id)
    assert bundle.household["name"] == "Source"
    assert [row["title"] for row in bundle.tables["recipe"]] == ["Source soup"]
    assert [row["name"] for row in bundle.tables["food_record"]] == ["Soup vegetables"]
    assert _counts(bundle)["recipes"]["recipes"] == 1
    assert _component_tables({"recipes"}, bundle.tables) >= {"recipe", "recipe_version", "food_record", "food_nutrient"}
    assert "saved_food" not in _component_tables({"recipes"}, bundle.tables)
    assert "household_food_unit_conversion" not in _component_tables({"recipes"}, bundle.tables)
    assert "household_food_unit_conversion" in _component_tables({"ingredients"}, bundle.tables)
    assert bundle.tables["household_food_unit_conversion"][0]["nutrition_input_unit"] == "can"


def test_insert_rows_remaps_household_and_is_idempotent(db):
    source = Household(name="Source", timezone="Europe/London")
    target = Household(name="Target", timezone="Europe/London")
    db.add_all([source, target])
    db.flush()
    member = HouseholdMember(household_id=source.id, name="Alex")
    recipe = Recipe(household_id=source.id, title="Source recipe")
    db.add_all([member, recipe])
    db.flush()

    maps = defaultdict(dict)
    maps["household"][source.id] = target.id
    rows = [{"id": "source-member-id", "household_id": source.id, "name": member.name, "active": True, "created_at": member.created_at.isoformat(), "updated_at": member.updated_at.isoformat(), "version": 1}]
    assert _insert_rows(db, HouseholdMember, rows, maps, target.id, source.id) == 1
    imported = db.get(HouseholdMember, "source-member-id")
    assert imported is not None
    assert imported.household_id == target.id
    assert _insert_rows(db, HouseholdMember, rows, maps, target.id, source.id) == 0


def test_same_household_restore_clones_live_plan_and_shopping_as_history(db):
    household = Household(name="Current household", timezone="Europe/London")
    db.add(household)
    db.flush()
    member = HouseholdMember(household_id=household.id, name="Alex")
    recipe = Recipe(household_id=household.id, title="Current dinner")
    db.add_all([member, recipe])
    db.flush()
    version = RecipeVersion(
        recipe_id=recipe.id,
        version_number=1,
        title="Current dinner",
        yield_servings=2,
    )
    db.add(version)
    db.flush()
    plan = MealPlan(
        household_id=household.id,
        name="Current week",
        start_date=date(2026, 9, 7),
        end_date=date(2026, 9, 13),
        status=PlanStatus.ACCEPTED.value,
        diagnostics=[],
    )
    db.add(plan)
    db.flush()
    batch = MealBatch(
        meal_plan_id=plan.id,
        recipe_version_id=version.id,
        servings=Decimal("2"),
        planned_cook_date=plan.start_date,
    )
    db.add(batch)
    db.flush()
    occurrence = MealOccurrence(
        meal_plan_id=plan.id,
        batch_id=batch.id,
        meal_date=plan.start_date,
        meal_type="dinner",
        meal_group_key="shared",
        component_slot=0,
    )
    shopping = ShoppingList(
        household_id=household.id,
        meal_plan_id=plan.id,
        name="Current shop",
        active=True,
    )
    db.add_all([occurrence, shopping])
    db.flush()
    portion = PortionAllocation(
        meal_occurrence_id=occurrence.id,
        member_id=member.id,
        servings=Decimal("1"),
    )
    item = ShoppingItem(
        shopping_list_id=shopping.id,
        display_name="Carrots",
        exact_quantity=Decimal("2"),
        purchase_quantity=Decimal("2"),
        unit="item",
        source_ingredients=[{"meal_plan_id": plan.id, "meal_batch_id": batch.id}],
    )
    db.add_all([portion, item])
    db.commit()

    tables = {
        "meal_plan": [_row_data(plan)],
        "meal_batch": [_row_data(batch)],
        "meal_occurrence": [_row_data(occurrence)],
        "portion_allocation": [_row_data(portion)],
        "shopping_list": [_row_data(shopping)],
        "shopping_item": [_row_data(item)],
    }
    include = set(tables)
    maps = defaultdict(dict)
    maps["household"][household.id] = household.id
    maps["recipe_version"][version.id] = version.id
    maps["household_member"][member.id] = member.id
    _prepare_historical_id_maps(tables, include, maps, household.id)

    models = (MealPlan, MealBatch, MealOccurrence, PortionAllocation, ShoppingList, ShoppingItem)
    for model in models:
        assert _insert_rows(
            db,
            model,
            tables[model.__tablename__],
            maps,
            household.id,
            household.id,
        ) == 1
    db.commit()

    assert maps["meal_plan"][plan.id] != plan.id
    assert maps["shopping_list"][shopping.id] != shopping.id
    assert db.get(MealPlan, plan.id).status == PlanStatus.ACCEPTED.value
    assert db.get(ShoppingList, shopping.id).active is True

    restored_plan = db.get(MealPlan, maps["meal_plan"][plan.id])
    restored_batch = db.get(MealBatch, maps["meal_batch"][batch.id])
    restored_occurrence = db.get(MealOccurrence, maps["meal_occurrence"][occurrence.id])
    restored_portion = db.get(PortionAllocation, maps["portion_allocation"][portion.id])
    restored_list = db.get(ShoppingList, maps["shopping_list"][shopping.id])
    restored_item = db.get(ShoppingItem, maps["shopping_item"][item.id])
    assert restored_plan.status == PlanStatus.SUPERSEDED.value
    assert restored_plan.accepted_at is None
    assert restored_batch.meal_plan_id == restored_plan.id
    assert restored_occurrence.meal_plan_id == restored_plan.id
    assert restored_occurrence.batch_id == restored_batch.id
    assert restored_portion.meal_occurrence_id == restored_occurrence.id
    assert restored_list.active is False
    assert restored_list.rebuild_recommended is True
    assert restored_list.meal_plan_id == restored_plan.id
    assert restored_item.shopping_list_id == restored_list.id
    assert restored_item.source_ingredients == [
        {"meal_plan_id": restored_plan.id, "meal_batch_id": restored_batch.id}
    ]

    # Replaying the same archive with a fresh mapping still finds the
    # deterministic historical clones instead of creating a second snapshot.
    repeat_maps = defaultdict(dict)
    repeat_maps["household"][household.id] = household.id
    repeat_maps["recipe_version"][version.id] = version.id
    repeat_maps["household_member"][member.id] = member.id
    _prepare_historical_id_maps(tables, include, repeat_maps, household.id)
    for model in models:
        assert _insert_rows(
            db,
            model,
            tables[model.__tablename__],
            repeat_maps,
            household.id,
            household.id,
        ) == 0
    assert repeat_maps["meal_plan"][plan.id] == restored_plan.id
    assert repeat_maps["shopping_list"][shopping.id] == restored_list.id


def test_list_archives_only_returns_timestamped_database_archives(tmp_path: Path, monkeypatch):
    root = tmp_path / "backups"
    complete = root / "daily" / "20260724-120000"
    incomplete = root / "daily" / ".20260724-120001.incomplete"
    complete.mkdir(parents=True)
    incomplete.mkdir(parents=True)
    (complete / "database.dump").write_bytes(b"dump")
    (complete / "manifest.txt").write_text("created_at=20260724-120000\ntier=daily\n", encoding="utf-8")
    monkeypatch.setenv("BACKUP_ROOT", str(root))

    archives = list_archives()
    assert len(archives) == 1
    assert archives[0]["archive"] == "daily/20260724-120000"
    assert archives[0]["files"]["database_dump"] is True
