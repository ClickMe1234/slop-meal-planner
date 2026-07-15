from app.db import SessionLocal
from app.services.ingredient_reparse import reparse_stale_imported_ingredients


def main() -> None:
    with SessionLocal() as db:
        result = reparse_stale_imported_ingredients(db)
        db.commit()
    print(
        "Ingredient reparse: "
        f"scanned={result.scanned} changed={result.changed} "
        f"flagged={result.flagged} lists_marked={result.lists_marked}"
    )


if __name__ == "__main__":
    main()
