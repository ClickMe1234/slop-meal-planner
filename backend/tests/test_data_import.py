from decimal import Decimal

import pytest

from app.data_import.cofid import CofidCsvImporter, parse_nutrient
from app.data_import.errors import DatasetFormatError, ProviderConfigurationError
from app.data_import.persistence import persist_food_batch
from app.data_import.providers import OpenFoodFactsProvider, UsdaFoodDataCentralProvider
from app.models import FoodNutrient, FoodRecord
from sqlalchemy import select


COFID = """Food Code,Food Name,Description,Food Group,Energy (kcal),Protein (g),Fat (g),Carbohydrate (g),Fibre (g)\n\
11-001,Apple,raw fruit,Fruit,52,0.3,0.2,11.8,2.4\n\
11-002,Herb,leafy,Vegetables,Tr,<0.1,N,1.0,2.0\n"""


def test_cofid_normalisation_preserves_version_provenance_and_qualifiers():
    batch = CofidCsvImporter(
        dataset_version="CoFID 2021",
        source_uri="https://www.gov.uk/example/cofid.csv",
        license_name="Open Government Licence",
    ).from_text(COFID, checksum_sha256="abc123")
    assert len(batch.foods) == 2
    apple = batch.foods[0]
    assert apple.provider_record_id == "11-001"
    assert apple.dataset_version == "CoFID 2021"
    assert apple.nutrients[0].amount == Decimal("52")
    herb = batch.foods[1]
    assert herb.nutrients[0].amount is None
    assert herb.nutrients[0].qualifier == "trace"
    assert herb.nutrients[1].amount == Decimal("0.1")
    assert herb.nutrients[1].qualifier == "<"
    assert herb.nutrients[2].amount is None
    assert herb.nutrients[2].qualifier == "not_available"
    assert batch.provenance.checksum_sha256 == "abc123"


def test_cofid_rejects_unrecognised_structure():
    with pytest.raises(DatasetFormatError):
        CofidCsvImporter(dataset_version="x", source_uri="local").from_text("id,label\n1,test\n")


def test_usda_provider_normalises_known_nutrients_and_requires_key_for_fetch_client():
    provider = UsdaFoodDataCentralProvider(dataset_version="FDC 2026-01")
    with pytest.raises(ProviderConfigurationError):
        provider.require_api_key()
    food = provider.normalise_record(
        {
            "fdcId": 123,
            "description": "Lentils, cooked",
            "dataType": "Foundation",
            "foodNutrients": [
                {"nutrient": {"id": 1062}, "amount": 486},
                {"nutrient": {"id": 1003}, "amount": 9.02},
            ],
        }
    )
    assert food.provider_record_id == "123"
    assert {n.code for n in food.nutrients} == {"energy_kcal", "protein_g"}
    energy = next(n for n in food.nutrients if n.code == "energy_kcal")
    assert energy.amount.quantize(Decimal("0.1")) == Decimal("116.2")


def test_open_food_facts_provider_uses_per_100g_product_values():
    food = OpenFoodFactsProvider(dataset_version="OFF snapshot 2026-07").normalise_record(
        {
            "code": "5000123456789",
            "product": {
                "code": "5000123456789",
                "product_name": "Baked beans",
                "brands": "Example",
                "nutriments": {
                    "energy-kcal_100g": 81,
                    "proteins_100g": 4.7,
                    "carbohydrates_100g": 12.5,
                    "fat_100g": 0.4,
                },
            },
        }
    )
    assert food.basis_amount == Decimal("100")
    assert food.basis_unit == "g"
    assert next(n for n in food.nutrients if n.code == "protein_g").amount == Decimal("4.7")


def test_open_food_facts_provider_normalises_package_and_serving_units():
    food = OpenFoodFactsProvider().normalise_record(
        {
            "code": "12345678",
            "product_name_en": "Fruit drink",
            "product_quantity": 1.5,
            "product_quantity_unit": "l",
            "serving_size": "250 ml",
            "image_front_url": "https://images.openfoodfacts.org/images/products/12345678/front_en.3.400.jpg",
            "nutriments": {
                "energy-kcal_100g": 42,
                "proteins_100g": 0,
                "carbohydrates_100g": 10,
                "fat_100g": 0,
            },
        }
    )
    assert food.basis_unit == "ml"
    assert food.metadata["package_amount"] == "1500.0"
    assert food.metadata["package_unit"] == "ml"
    assert food.metadata["serving_amount"] == "250"
    assert food.metadata["source_url"].endswith("/12345678")
    assert food.metadata["image_url"] == "https://images.openfoodfacts.org/images/products/12345678/front_en.3.400.jpg"


def test_persistence_upsert_replaces_old_nutrients_and_records_provenance(db):
    first = CofidCsvImporter(dataset_version="2021", source_uri="source-a").from_text(
        "Food Code,Food Name,Energy (kcal),Protein (g)\n1,Apple,52,0.3\n",
        checksum_sha256="old",
    )
    result = persist_food_batch(db, first)
    db.commit()
    assert (result.created, result.updated) == (1, 0)

    second = CofidCsvImporter(dataset_version="2024", source_uri="source-b").from_text(
        "Food Code,Food Name,Energy (kcal),Fat (g)\n1,Apple,50,0.2\n",
        checksum_sha256="new",
    )
    result = persist_food_batch(db, second)
    db.commit()
    record = db.scalar(select(FoodRecord).where(FoodRecord.provider_record_id == "1"))
    nutrients = db.scalars(select(FoodNutrient).where(FoodNutrient.food_record_id == record.id)).all()
    assert (result.created, result.updated) == (0, 1)
    assert record.dataset_version == "2024"
    assert record.metadata_json["dataset_provenance"]["checksum_sha256"] == "new"
    assert {nutrient.code for nutrient in nutrients} == {"energy_kcal", "fat_g"}
