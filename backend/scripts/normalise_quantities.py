from app.db import SessionLocal
from app.services.quantity_normalization import normalize_stored_quantities


def main() -> None:
    with SessionLocal() as db:
        result = normalize_stored_quantities(db)
        db.commit()
    print(
        "Quantity normalization: "
        f"pantry_lots={result.pantry_lots_changed} "
        f"transactions={result.transactions_changed} "
        f"reservations={result.reservations_changed} "
        f"reservations_removed={result.reservations_removed} "
        f"shopping_items={result.shopping_items_changed} "
        f"lists_marked={result.lists_marked}"
    )


if __name__ == "__main__":
    main()
