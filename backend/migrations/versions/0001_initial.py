"""Create the initial meal planner schema.

Revision ID: 0001_initial
Revises:

This file is a frozen representation of the model metadata at Git revision
9980af3b001b93fc9d336f2fd01326b731212371. It must never import live application
models: doing so makes old migrations change whenever a model changes.
"""

import sqlalchemy as sa
from alembic import op


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "food_record",
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("provider_record_id", sa.String(120), nullable=False),
        sa.Column("dataset_version", sa.String(80), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("basis_amount", sa.Numeric(10, 4), nullable=False),
        sa.Column("basis_unit", sa.String(20), nullable=False),
        sa.Column("density_g_per_ml", sa.Numeric(10, 5)),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_record_id"),
    )
    op.create_index(op.f("ix_food_record_name"), "food_record", ["name"])
    op.create_index(op.f("ix_food_record_provider"), "food_record", ["provider"])

    op.create_table(
        "household",
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "food_nutrient",
        sa.Column("food_record_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("amount", sa.Numeric(14, 5)),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("qualifier", sa.String(40)),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["food_record_id"], ["food_record.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("food_record_id", "code"),
    )
    op.create_index(op.f("ix_food_nutrient_food_record_id"), "food_nutrient", ["food_record_id"])
    op.create_table(
        "household_member",
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_household_member_household_id"), "household_member", ["household_id"])
    op.create_table(
        "meal_plan",
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_meal_plan_household_id"), "meal_plan", ["household_id"])
    op.create_table(
        "pantry_lot",
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("food_record_id", sa.String(36)),
        sa.Column("display_name", sa.String(240), nullable=False),
        sa.Column("initial_quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("expires_on", sa.Date()),
        sa.Column("always_have", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["food_record_id"], ["food_record.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pantry_household_food", "pantry_lot", ["household_id", "food_record_id"])
    op.create_index(op.f("ix_pantry_lot_food_record_id"), "pantry_lot", ["food_record_id"])
    op.create_index(op.f("ix_pantry_lot_household_id"), "pantry_lot", ["household_id"])
    op.create_table(
        "recipe",
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("eligibility", sa.String(30), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("publisher", sa.String(160)),
        sa.Column("image_url", sa.Text()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recipe_eligibility"), "recipe", ["eligibility"])
    op.create_index(op.f("ix_recipe_household_id"), "recipe", ["household_id"])
    op.create_index("ix_recipe_household_title", "recipe", ["household_id", "title"])
    op.create_index(op.f("ix_recipe_title"), "recipe", ["title"])
    op.create_table(
        "app_user",
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("member_id", sa.String(36)),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["member_id"], ["household_member.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_app_user_household_id"), "app_user", ["household_id"])
    op.create_table(
        "pantry_transaction",
        sa.Column("pantry_lot_id", sa.String(36), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(14, 4), nullable=False),
        sa.Column("reason", sa.String(60), nullable=False),
        sa.Column("reference_type", sa.String(40)),
        sa.Column("reference_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["pantry_lot_id"], ["pantry_lot.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pantry_transaction_pantry_lot_id"), "pantry_transaction", ["pantry_lot_id"])
    op.create_table(
        "recipe_version",
        sa.Column("recipe_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("yield_servings", sa.Numeric(8, 2)),
        sa.Column("custom_instructions", sa.Text()),
        sa.Column("source_checksum", sa.String(64)),
        sa.Column("publisher_nutrition", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipe.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_id", "version_number"),
    )
    op.create_index(op.f("ix_recipe_version_recipe_id"), "recipe_version", ["recipe_id"])
    op.create_table(
        "restriction",
        sa.Column("member_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("value", sa.String(160), nullable=False),
        sa.Column("hard", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["household_member.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_restriction_member_id"), "restriction", ["member_id"])
    op.create_table(
        "shopping_list",
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("meal_plan_id", sa.String(36)),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meal_plan_id"], ["meal_plan.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_shopping_list_household_id"), "shopping_list", ["household_id"])
    op.create_index(op.f("ix_shopping_list_meal_plan_id"), "shopping_list", ["meal_plan_id"])
    op.create_table(
        "target_profile",
        sa.Column("member_id", sa.String(36), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("tolerance_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("calorie_target", sa.Numeric(8, 2)),
        sa.Column("protein_target_g", sa.Numeric(8, 2)),
        sa.Column("carbohydrate_target_g", sa.Numeric(8, 2)),
        sa.Column("fat_target_g", sa.Numeric(8, 2)),
        sa.Column("protein_min_g", sa.Numeric(8, 2)),
        sa.Column("protein_max_g", sa.Numeric(8, 2)),
        sa.Column("carbohydrate_min_g", sa.Numeric(8, 2)),
        sa.Column("carbohydrate_max_g", sa.Numeric(8, 2)),
        sa.Column("fat_min_g", sa.Numeric(8, 2)),
        sa.Column("fat_max_g", sa.Numeric(8, 2)),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["household_member.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("member_id"),
    )
    op.create_table(
        "food_alias",
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("phrase", sa.String(240), nullable=False),
        sa.Column("food_record_id", sa.String(36), nullable=False),
        sa.Column("reviewed_by", sa.String(36)),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["food_record_id"], ["food_record.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "phrase"),
    )
    op.create_index(op.f("ix_food_alias_household_id"), "food_alias", ["household_id"])
    op.create_table(
        "job",
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36)),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("stage", sa.String(80)),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_detail", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_job_household_id"), "job", ["household_id"])
    op.create_index(op.f("ix_job_kind"), "job", ["kind"])
    op.create_index(op.f("ix_job_status"), "job", ["status"])
    op.create_table(
        "meal_allocation",
        sa.Column("target_profile_id", sa.String(36), nullable=False),
        sa.Column("meal_type", sa.String(40), nullable=False),
        sa.Column("percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["target_profile_id"], ["target_profile.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_profile_id", "meal_type"),
    )
    op.create_index(op.f("ix_meal_allocation_target_profile_id"), "meal_allocation", ["target_profile_id"])
    op.create_table(
        "meal_batch",
        sa.Column("meal_plan_id", sa.String(36), nullable=False),
        sa.Column("recipe_version_id", sa.String(36), nullable=False),
        sa.Column("servings", sa.Numeric(10, 2), nullable=False),
        sa.Column("planned_cook_date", sa.Date(), nullable=False),
        sa.Column("cooked_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["meal_plan_id"], ["meal_plan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipe_version_id"], ["recipe_version.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_meal_batch_meal_plan_id"), "meal_batch", ["meal_plan_id"])
    op.create_index(op.f("ix_meal_batch_recipe_version_id"), "meal_batch", ["recipe_version_id"])
    op.create_table(
        "nutrition_calculation",
        sa.Column("recipe_version_id", sa.String(36), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("total_values", sa.JSON(), nullable=False),
        sa.Column("per_serving_values", sa.JSON(), nullable=False),
        sa.Column("contributions", sa.JSON(), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("dataset_snapshot", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["recipe_version_id"], ["recipe_version.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_nutrition_calculation_recipe_version_id"),
        "nutrition_calculation",
        ["recipe_version_id"],
    )
    op.create_table(
        "recipe_ingredient",
        sa.Column("recipe_version_id", sa.String(36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 4)),
        sa.Column("unit", sa.String(40)),
        sa.Column("quantity_grams", sa.Numeric(12, 4)),
        sa.Column("food_phrase", sa.String(240)),
        sa.Column("preparation", sa.String(160)),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("optional", sa.Boolean(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("food_record_id", sa.String(36)),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["food_record_id"], ["food_record.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recipe_version_id"], ["recipe_version.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recipe_ingredient_food_record_id"), "recipe_ingredient", ["food_record_id"])
    op.create_index(
        op.f("ix_recipe_ingredient_recipe_version_id"),
        "recipe_ingredient",
        ["recipe_version_id"],
    )
    op.create_table(
        "shopping_item",
        sa.Column("shopping_list_id", sa.String(36), nullable=False),
        sa.Column("food_record_id", sa.String(36)),
        sa.Column("display_name", sa.String(240), nullable=False),
        sa.Column("exact_quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("purchase_quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("checked", sa.Boolean(), nullable=False),
        sa.Column("manual", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["food_record_id"], ["food_record.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shopping_list_id"], ["shopping_list.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_shopping_item_food_record_id"), "shopping_item", ["food_record_id"])
    op.create_index(op.f("ix_shopping_item_shopping_list_id"), "shopping_item", ["shopping_list_id"])
    op.create_table(
        "user_session",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_user_session_expires_at"), "user_session", ["expires_at"])
    op.create_index(op.f("ix_user_session_user_id"), "user_session", ["user_id"])
    op.create_table(
        "meal_occurrence",
        sa.Column("meal_plan_id", sa.String(36), nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("meal_date", sa.Date(), nullable=False),
        sa.Column("meal_type", sa.String(40), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("unplanned_allowance", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["meal_batch.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meal_plan_id"], ["meal_plan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meal_plan_id", "meal_date", "meal_type"),
    )
    op.create_index(op.f("ix_meal_occurrence_batch_id"), "meal_occurrence", ["batch_id"])
    op.create_index(op.f("ix_meal_occurrence_meal_plan_id"), "meal_occurrence", ["meal_plan_id"])
    op.create_table(
        "pantry_reservation",
        sa.Column("pantry_lot_id", sa.String(36), nullable=False),
        sa.Column("meal_batch_id", sa.String(36), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["meal_batch_id"], ["meal_batch.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pantry_lot_id"], ["pantry_lot.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pantry_lot_id", "meal_batch_id"),
    )
    op.create_index(
        op.f("ix_pantry_reservation_meal_batch_id"),
        "pantry_reservation",
        ["meal_batch_id"],
    )
    op.create_index(
        op.f("ix_pantry_reservation_pantry_lot_id"),
        "pantry_reservation",
        ["pantry_lot_id"],
    )
    op.create_table(
        "portion_allocation",
        sa.Column("meal_occurrence_id", sa.String(36), nullable=False),
        sa.Column("member_id", sa.String(36), nullable=False),
        sa.Column("servings", sa.Numeric(6, 2), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["meal_occurrence_id"], ["meal_occurrence.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["member_id"], ["household_member.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meal_occurrence_id", "member_id"),
    )
    op.create_index(
        op.f("ix_portion_allocation_meal_occurrence_id"),
        "portion_allocation",
        ["meal_occurrence_id"],
    )
    op.create_index(op.f("ix_portion_allocation_member_id"), "portion_allocation", ["member_id"])


def downgrade() -> None:
    # Dropping a table also drops its indexes; reverse dependency order keeps
    # this portable across PostgreSQL and SQLite.
    for table_name in (
        "portion_allocation",
        "pantry_reservation",
        "meal_occurrence",
        "user_session",
        "shopping_item",
        "recipe_ingredient",
        "nutrition_calculation",
        "meal_batch",
        "meal_allocation",
        "job",
        "food_alias",
        "target_profile",
        "shopping_list",
        "restriction",
        "recipe_version",
        "pantry_transaction",
        "app_user",
        "recipe",
        "pantry_lot",
        "meal_plan",
        "household_member",
        "food_nutrient",
        "household",
        "food_record",
    ):
        op.drop_table(table_name)
