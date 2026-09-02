from collections import defaultdict
from pathlib import Path

from app.models import (
    FoodNutrient,
    FoodRecord,
    Household,
    HouseholdFoodUnitConversion,
    HouseholdMember,
    PantryLot,
    Recipe,
    RecipeIngredient,
    RecipeVersion,
    SavedFood,
)
from app.services.selective_restore import (
    _component_tables,
    _counts,
    _insert_rows,
    _load_source_bundle,
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
