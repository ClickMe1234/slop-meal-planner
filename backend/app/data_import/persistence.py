from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import FoodNutrient, FoodRecord
from .models import FoodDataBatch


@dataclass(frozen=True, slots=True)
class PersistenceResult:
    created: int
    updated: int


def persist_food_batch(session: Session, batch: FoodDataBatch) -> PersistenceResult:
    """Idempotently upsert a versioned normalized food batch.

    Nutrient rows are replaced because absence is meaningful: carrying a value
    forward from an older dataset would misrepresent current source data.
    """

    created = 0
    updated = 0
    provenance = batch.provenance
    provenance_metadata = {
        "source_uri": provenance.source_uri,
        "checksum_sha256": provenance.checksum_sha256,
        "license_name": provenance.license_name,
        "imported_at": provenance.imported_at.isoformat(),
    }
    for food in batch.foods:
        record = session.scalar(
            select(FoodRecord).where(
                FoodRecord.provider == food.provider,
                FoodRecord.provider_record_id == food.provider_record_id,
            )
        )
        metadata = {**food.metadata, "dataset_provenance": provenance_metadata}
        if record is None:
            record = FoodRecord(
                provider=food.provider,
                provider_record_id=food.provider_record_id,
                dataset_version=food.dataset_version,
                name=food.name,
                basis_amount=food.basis_amount,
                basis_unit=food.basis_unit,
                density_g_per_ml=food.density_g_per_ml,
                metadata_json=metadata,
            )
            session.add(record)
            session.flush()
            created += 1
        else:
            record.dataset_version = food.dataset_version
            record.name = food.name
            record.basis_amount = food.basis_amount
            record.basis_unit = food.basis_unit
            record.density_g_per_ml = food.density_g_per_ml
            record.metadata_json = metadata
            record.version += 1
            session.execute(delete(FoodNutrient).where(FoodNutrient.food_record_id == record.id))
            updated += 1
        for nutrient in food.nutrients:
            session.add(
                FoodNutrient(
                    food_record_id=record.id,
                    code=nutrient.code,
                    amount=nutrient.amount,
                    unit=nutrient.unit,
                    qualifier=nutrient.qualifier,
                )
            )
    session.flush()
    return PersistenceResult(created=created, updated=updated)
