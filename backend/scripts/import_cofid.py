from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.data_import.cofid import CofidCsvImporter
from app.data_import.persistence import persist_food_batch


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Import a versioned CoFID CSV into the food catalogue")
    result.add_argument("csv_path")
    result.add_argument("--dataset-version", required=True, help="Published CoFID release/version label")
    result.add_argument("--source-uri", required=True, help="Where this exact dataset was obtained")
    result.add_argument("--license-name")
    result.add_argument(
        "--database-url",
        default=os.getenv("MEAL_PLANNER_DATABASE_URL") or os.getenv("DATABASE_URL"),
    )
    result.add_argument("--dry-run", action="store_true", help="Validate and summarise without changing PostgreSQL")
    return result


def main() -> int:
    args = parser().parse_args()
    importer = CofidCsvImporter(
        dataset_version=args.dataset_version,
        source_uri=args.source_uri,
        license_name=args.license_name,
    )
    batch = importer.from_path(args.csv_path)
    output = {
        "provider": batch.provenance.provider,
        "dataset_version": batch.provenance.dataset_version,
        "checksum_sha256": batch.provenance.checksum_sha256,
        "foods_read": len(batch.foods),
        "warnings": list(batch.warnings),
        "dry_run": args.dry_run,
    }
    if not args.dry_run:
        if not args.database_url:
            raise SystemExit("DATABASE_URL or --database-url is required unless --dry-run is used")
        engine = create_engine(args.database_url)
        with Session(engine) as session, session.begin():
            persisted = persist_food_batch(session, batch)
        output.update(created=persisted.created, updated=persisted.updated)
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
