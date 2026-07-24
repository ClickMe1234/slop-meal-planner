"""Quarantine legacy recipe URLs that are unsafe to render.

Revision ID: 0017_quarantine_urls
Revises: 0016_plan_day_adjustments
"""

import sqlalchemy as sa
from alembic import op
from urllib.parse import urlsplit


revision = "0017_quarantine_urls"
down_revision = "0016_plan_day_adjustments"
branch_labels = None
depends_on = None


def _safe_url(value: str | None) -> str | None:
    if not value or len(value) > 4096:
        return None
    try:
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None
        parsed.port
    except (UnicodeError, ValueError):
        return None
    return value.strip()


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, source_url, image_url FROM recipe")
    ).mappings()
    for row in rows:
        values: dict[str, str | None] = {}
        for field in ("source_url", "image_url"):
            values[field] = _safe_url(row[field])
        connection.execute(
            sa.text(
                "UPDATE recipe SET source_url = :source_url, image_url = :image_url "
                "WHERE id = :id"
            ),
            {"id": row["id"], **values},
        )


def downgrade() -> None:
    # Unsafe values are deliberately not recoverable into the live table.
    pass
