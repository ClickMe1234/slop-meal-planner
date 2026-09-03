"""Select editor, planning, and plan-only recipe revisions consistently."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Recipe, RecipeVersion
from .nutrition import latest_calculation


def latest_editor_recipe_version(
    db: Session, recipe_id: str
) -> RecipeVersion | None:
    """Return the newest revision that belongs to the editable recipe."""

    return db.scalar(
        select(RecipeVersion)
        .where(
            RecipeVersion.recipe_id == recipe_id,
            RecipeVersion.is_shopping_snapshot.is_(False),
        )
        .order_by(RecipeVersion.version_number.desc())
    )


def latest_complete_custom_recipe_version(
    db: Session, recipe_id: str
) -> RecipeVersion | None:
    """Return the last complete editable custom revision for planner use."""

    versions = db.scalars(
        select(RecipeVersion)
        .where(
            RecipeVersion.recipe_id == recipe_id,
            RecipeVersion.is_shopping_snapshot.is_(False),
        )
        .order_by(RecipeVersion.version_number.desc())
    ).all()
    for version in versions:
        calculation = latest_calculation(db, version.id)
        if calculation is not None and calculation.status == "complete":
            return version
    return None


def latest_planning_recipe_version(
    db: Session, recipe: Recipe
) -> RecipeVersion | None:
    """Keep incomplete custom drafts from displacing their planner-safe version."""

    if recipe.source_type == "custom":
        return latest_complete_custom_recipe_version(db, recipe.id)
    return latest_editor_recipe_version(db, recipe.id)


def next_recipe_version_number(db: Session, recipe_id: str) -> int:
    """Allocate after every immutable revision, including plan-only snapshots."""

    return (
        db.scalar(
            select(func.max(RecipeVersion.version_number)).where(
                RecipeVersion.recipe_id == recipe_id
            )
        )
        or 0
    ) + 1
