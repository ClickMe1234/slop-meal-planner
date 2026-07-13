from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .errors import DatasetFormatError
from .models import DatasetProvenance, FoodDataBatch, NormalizedFood, NutrientValue


def _header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


HEADER_ALIASES = {
    "id": ("food code", "food id", "code"),
    "name": ("food name", "name"),
    "description": ("description", "food description"),
    "group": ("food group", "group"),
    "energy_kcal": ("energy kcal", "energy kcal kcal", "energy kilocalories"),
    "energy_kj": ("energy kj", "energy kj kj", "energy kilojoules"),
    "protein_g": ("protein g", "protein"),
    "carbohydrate_g": ("carbohydrate g", "carbohydrate"),
    "fat_g": ("fat g", "fat"),
    "fibre_g": ("fibre g", "fiber g", "fibre", "fiber"),
}


def _find_header(headers: Iterable[str], logical_name: str) -> str | None:
    normalised = {_header(value): value for value in headers}
    for alias in HEADER_ALIASES[logical_name]:
        if alias in normalised:
            return normalised[alias]
    # CoFID releases sometimes append footnote numbers to otherwise stable names.
    for alias in HEADER_ALIASES[logical_name]:
        match = next((original for key, original in normalised.items() if key.startswith(f"{alias} ")), None)
        if match:
            return match
    return None


def parse_nutrient(value: object) -> tuple[Decimal | None, str | None]:
    """Parse a dataset cell without turning absent/trace values into zero."""

    text = str(value or "").strip().replace(",", ".")
    if not text or text.casefold() in {"n", "na", "n/a", "nd", "not determined", "-"}:
        return None, "not_available" if text else None
    if text.casefold() in {"tr", "trace"}:
        return None, "trace"
    qualifier = None
    if text.startswith(("<", ">")):
        qualifier, text = text[0], text[1:].strip()
    try:
        return Decimal(text), qualifier
    except InvalidOperation:
        return None, f"unparsed:{str(value).strip()}"


class CofidCsvImporter:
    provider = "cofid"

    def __init__(self, *, dataset_version: str, source_uri: str, license_name: str | None = None) -> None:
        if not dataset_version.strip():
            raise ValueError("A CoFID dataset version is required for reproducibility")
        self.dataset_version = dataset_version.strip()
        self.source_uri = source_uri
        self.license_name = license_name

    def from_path(self, path: str | Path, *, encoding: str = "utf-8-sig") -> FoodDataBatch:
        data = Path(path).read_bytes()
        checksum = hashlib.sha256(data).hexdigest()
        text = data.decode(encoding)
        return self.from_text(text, checksum_sha256=checksum)

    def from_text(self, text: str, *, checksum_sha256: str | None = None) -> FoodDataBatch:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise DatasetFormatError("The CoFID file has no header row")
        columns = {name: _find_header(reader.fieldnames, name) for name in HEADER_ALIASES}
        if not columns["id"] or not columns["name"]:
            raise DatasetFormatError("The CoFID file must contain food-code and food-name columns")
        if not any(columns[name] for name in ("energy_kcal", "energy_kj", "protein_g", "carbohydrate_g", "fat_g")):
            raise DatasetFormatError("No supported nutrient columns were found in the CoFID file")

        foods: list[NormalizedFood] = []
        warnings: list[str] = []
        seen: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            record_id = str(row.get(columns["id"] or "", "")).strip()
            name = str(row.get(columns["name"] or "", "")).strip()
            if not record_id or not name:
                warnings.append(f"Row {line_number} was skipped because its code or name was empty")
                continue
            if record_id in seen:
                warnings.append(f"Row {line_number} duplicated food code {record_id} and was skipped")
                continue
            seen.add(record_id)

            nutrient_values: list[NutrientValue] = []
            # Keep the conventional UK label order so exports are predictable.
            for code in ("energy_kcal", "protein_g", "fat_g", "carbohydrate_g", "fibre_g"):
                column = columns.get(code)
                if not column:
                    continue
                amount, qualifier = parse_nutrient(row.get(column))
                nutrient_values.append(NutrientValue(code, amount, "kcal" if code == "energy_kcal" else "g", qualifier))
            if columns["energy_kcal"] is None and columns["energy_kj"]:
                amount_kj, qualifier = parse_nutrient(row.get(columns["energy_kj"] or ""))
                amount_kcal = amount_kj / Decimal("4.184") if amount_kj is not None else None
                nutrient_values.append(NutrientValue("energy_kcal", amount_kcal, "kcal", qualifier or "converted_from_kj"))

            metadata = {
                key: str(row.get(column, "")).strip()
                for key, column in (("description", columns["description"]), ("food_group", columns["group"]))
                if column and str(row.get(column, "")).strip()
            }
            foods.append(
                NormalizedFood(
                    provider=self.provider,
                    provider_record_id=record_id,
                    dataset_version=self.dataset_version,
                    name=name,
                    nutrients=tuple(nutrient_values),
                    metadata=metadata,
                )
            )

        return FoodDataBatch(
            provenance=DatasetProvenance(
                provider=self.provider,
                dataset_version=self.dataset_version,
                source_uri=self.source_uri,
                checksum_sha256=checksum_sha256,
                license_name=self.license_name,
            ),
            foods=tuple(foods),
            warnings=tuple(warnings),
        )
