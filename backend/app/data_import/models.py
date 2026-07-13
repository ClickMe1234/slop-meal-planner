from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class NutrientValue:
    code: str
    amount: Decimal | None
    unit: str
    qualifier: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedFood:
    provider: str
    provider_record_id: str
    dataset_version: str
    name: str
    basis_amount: Decimal = Decimal("100")
    basis_unit: str = "g"
    density_g_per_ml: Decimal | None = None
    nutrients: tuple[NutrientValue, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DatasetProvenance:
    provider: str
    dataset_version: str
    source_uri: str
    checksum_sha256: str | None = None
    license_name: str | None = None
    imported_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class FoodDataBatch:
    provenance: DatasetProvenance
    foods: tuple[NormalizedFood, ...]
    warnings: tuple[str, ...] = ()
