"""Add regional ingredient names and user preference.

Revision ID: 0004_ingredient_names
Revises: 0003_meal_plan_sides
"""

import uuid

import sqlalchemy as sa
from alembic import op


revision = "0004_ingredient_names"
down_revision = "0003_meal_plan_sides"
branch_labels = None
depends_on = None


PAIRS = [
    ("all-purpose flour", "plain flour", 10),
    ("cake flour", "plain flour", 20),
    ("baking soda", "bicarbonate of soda", 10),
    ("brown sugar", "light brown sugar", 10),
    ("cane syrup", "golden syrup", 20),
    ("corn syrup", "golden syrup", 10),
    ("cornstarch", "cornflour", 10),
    ("dark corn syrup", "treacle", 10),
    ("molasses", "treacle", 20),
    ("half and half", "single cream", 10),
    ("heavy cream", "double cream", 10),
    ("light corn syrup", "glucose syrup", 10),
    ("non-fat milk", "skimmed milk", 10),
    ("powdered sugar", "icing sugar", 10),
    ("reduced-fat milk", "semi-skimmed milk", 10),
    ("self-rising flour", "self-raising flour", 10),
    ("shortening", "vegetable fat", 10),
    ("superfine sugar", "caster sugar", 10),
    ("whole wheat flour", "wholemeal flour", 10),
    ("arugula", "rocket", 10),
    ("bell pepper", "red pepper", 10),
    ("beets", "beetroot", 10),
    ("cilantro", "coriander", 10),
    ("eggplant", "aubergine", 10),
    ("green beans", "runner beans", 10),
    ("rutabaga", "swede", 10),
    ("scallions", "spring onions", 10),
    ("snow peas", "mange tout", 10),
    ("zucchini", "courgette", 10),
    ("canola oil", "rapeseed oil", 10),
    ("garbanzo beans", "chickpeas", 10),
    ("kosher salt", "sea salt", 10),
    ("lima beans", "butter beans", 10),
    ("pine kernels", "pine nuts", 10),
]


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("ingredient_locale", sa.String(length=2), server_default="uk", nullable=False),
    )
    table = op.create_table(
        "ingredient_name_equivalent",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("us_name", sa.String(length=160), nullable=False),
        sa.Column("uk_name", sa.String(length=160), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
        sa.UniqueConstraint("us_name", "uk_name"),
    )
    op.create_index(op.f("ix_ingredient_name_equivalent_us_name"), table.name, ["us_name"])
    op.create_index(op.f("ix_ingredient_name_equivalent_uk_name"), table.name, ["uk_name"])
    op.bulk_insert(
        table,
        [
            {"id": str(uuid.uuid4()), "us_name": us_name, "uk_name": uk_name, "priority": priority}
            for us_name, uk_name, priority in PAIRS
        ],
    )


def downgrade() -> None:
    op.drop_table("ingredient_name_equivalent")
    op.drop_column("app_user", "ingredient_locale")
