from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    OWNER = "owner"
    COLLABORATOR = "collaborator"


class IngredientLocale(str, enum.Enum):
    UK = "uk"
    US = "us"


class TargetMode(str, enum.Enum):
    CALORIE = "calorie"
    MACROS = "macros"


class MealType(str, enum.Enum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class RecipeTag(str, enum.Enum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"
    SIDE = "side"


class RecipeEligibility(str, enum.Enum):
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    PLANNER_READY = "planner_ready"
    ARCHIVED = "archived"


class PublisherMetadataStatus(str, enum.Enum):
    NOT_APPLICABLE = "not_applicable"
    PENDING = "pending"
    REFRESHING = "refreshing"
    READY = "ready"
    FAILED = "failed"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PlanStatus(str, enum.Enum):
    DRAFT = "draft"
    GENERATING = "generating"
    READY = "ready"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class AuditMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Household(IdMixin, AuditMixin, Base):
    __tablename__ = "household"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/London")


class User(IdMixin, AuditMixin, Base):
    __tablename__ = "app_user"

    household_id: Mapped[str] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default=UserRole.COLLABORATOR.value)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    ingredient_locale: Mapped[str] = mapped_column(String(2), default=IngredientLocale.UK.value)
    member_id: Mapped[str | None] = mapped_column(ForeignKey("household_member.id", ondelete="SET NULL"), nullable=True)


class IngredientNameEquivalent(IdMixin, Base):
    __tablename__ = "ingredient_name_equivalent"
    __table_args__ = (UniqueConstraint("us_name", "uk_name"),)

    us_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    uk_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)


class IngredientNameOverride(IdMixin, AuditMixin, Base):
    __tablename__ = "ingredient_name_override"
    __table_args__ = (UniqueConstraint("household_id", "ingredient_key"),)

    household_id: Mapped[str] = mapped_column(
        ForeignKey("household.id", ondelete="CASCADE"), index=True
    )
    ingredient_key: Mapped[str] = mapped_column(String(240), nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)


class UserSession(IdMixin, Base):
    __tablename__ = "user_session"

    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseholdMember(IdMixin, AuditMixin, Base):
    __tablename__ = "household_member"

    household_id: Mapped[str] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TargetProfile(IdMixin, AuditMixin, Base):
    __tablename__ = "target_profile"

    member_id: Mapped[str] = mapped_column(ForeignKey("household_member.id", ondelete="CASCADE"), unique=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    tolerance_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("5"))
    calorie_target: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    protein_target_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    carbohydrate_target_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    fat_target_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    protein_min_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    protein_max_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    carbohydrate_min_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    carbohydrate_max_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    fat_min_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    fat_max_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))


class MealAllocation(IdMixin, Base):
    __tablename__ = "meal_allocation"
    __table_args__ = (UniqueConstraint("target_profile_id", "meal_type"),)

    target_profile_id: Mapped[str] = mapped_column(ForeignKey("target_profile.id", ondelete="CASCADE"), index=True)
    meal_type: Mapped[str] = mapped_column(String(40), nullable=False)
    percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)


class Restriction(IdMixin, Base):
    __tablename__ = "restriction"

    member_id: Mapped[str] = mapped_column(ForeignKey("household_member.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # allergy, exclude, dislike, prefer
    value: Mapped[str] = mapped_column(String(160), nullable=False)
    hard: Mapped[bool] = mapped_column(Boolean, default=False)


class Recipe(IdMixin, AuditMixin, Base):
    __tablename__ = "recipe"

    household_id: Mapped[str] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    eligibility: Mapped[str] = mapped_column(String(30), default=RecipeEligibility.DRAFT.value, index=True)
    source_type: Mapped[str] = mapped_column(String(30), default="custom")
    source_url: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(String(160))
    image_url: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publisher_metadata_status: Mapped[str] = mapped_column(
        String(30), default=PublisherMetadataStatus.NOT_APPLICABLE.value, index=True
    )
    publisher_metadata_attempts: Mapped[int] = mapped_column(Integer, default=0)
    publisher_metadata_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publisher_metadata_error: Mapped[str | None] = mapped_column(String(500))

    meal_type_tags: Mapped[list[RecipeMealType]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeMealType.meal_type"
    )
    publisher_tags: Mapped[list[RecipePublisherTag]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="RecipePublisherTag.label"
    )


class RecipeMealType(IdMixin, Base):
    __tablename__ = "recipe_meal_type"
    __table_args__ = (
        UniqueConstraint("recipe_id", "meal_type"),
        CheckConstraint(
            "meal_type IN ('breakfast', 'lunch', 'dinner', 'snack', 'side')",
            name="ck_recipe_meal_type_valid",
        ),
    )

    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"), index=True)
    meal_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    recipe: Mapped[Recipe] = relationship(back_populates="meal_type_tags")


class RecipePublisherTag(IdMixin, Base):
    __tablename__ = "recipe_publisher_tag"
    __table_args__ = (
        UniqueConstraint("recipe_id", "kind", "normalised_value"),
        Index("ix_recipe_publisher_tag_normalised_value", "normalised_value"),
    )

    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    normalised_value: Mapped[str] = mapped_column(String(160), nullable=False)

    recipe: Mapped[Recipe] = relationship(back_populates="publisher_tags")


class RecipeVersion(IdMixin, Base):
    __tablename__ = "recipe_version"
    __table_args__ = (UniqueConstraint("recipe_id", "version_number"),)

    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    yield_servings: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    custom_instructions: Mapped[str | None] = mapped_column(Text)
    source_checksum: Mapped[str | None] = mapped_column(String(64))
    publisher_nutrition: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ingredients: Mapped[list[RecipeIngredient]] = relationship(
        back_populates="recipe_version", cascade="all, delete-orphan", order_by="RecipeIngredient.position"
    )


class RecipeIngredient(IdMixin, Base):
    __tablename__ = "recipe_ingredient"

    recipe_version_id: Mapped[str] = mapped_column(ForeignKey("recipe_version.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    unit: Mapped[str | None] = mapped_column(String(40))
    quantity_grams: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    food_phrase: Mapped[str | None] = mapped_column(String(240))
    parsed_food_phrase: Mapped[str | None] = mapped_column(String(240))
    preparation: Mapped[str | None] = mapped_column(String(160))
    parser_version: Mapped[str | None] = mapped_column(String(80))
    name_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    name_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    parser_name_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    optional: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    shopping_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    food_record_id: Mapped[str | None] = mapped_column(ForeignKey("food_record.id", ondelete="SET NULL"), index=True)

    recipe_version: Mapped[RecipeVersion] = relationship(back_populates="ingredients")


class FoodRecord(IdMixin, AuditMixin, Base):
    __tablename__ = "food_record"
    __table_args__ = (UniqueConstraint("provider", "provider_record_id"),)

    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    provider_record_id: Mapped[str] = mapped_column(String(120), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    basis_amount: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("100"))
    basis_unit: Mapped[str] = mapped_column(String(20), default="g")
    density_g_per_ml: Mapped[Decimal | None] = mapped_column(Numeric(10, 5))
    metadata_json: Mapped[dict | None] = mapped_column(JSON)

    nutrients: Mapped[list[FoodNutrient]] = relationship(back_populates="food_record", cascade="all, delete-orphan")


class FoodNutrient(IdMixin, Base):
    __tablename__ = "food_nutrient"
    __table_args__ = (UniqueConstraint("food_record_id", "code"),)

    food_record_id: Mapped[str] = mapped_column(ForeignKey("food_record.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)  # energy_kcal, protein_g, carbohydrate_g, fat_g
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 5))
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    qualifier: Mapped[str | None] = mapped_column(String(40))

    food_record: Mapped[FoodRecord] = relationship(back_populates="nutrients")


class FoodAlias(IdMixin, Base):
    __tablename__ = "food_alias"
    __table_args__ = (UniqueConstraint("household_id", "phrase"),)

    household_id: Mapped[str] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), index=True)
    phrase: Mapped[str] = mapped_column(String(240), nullable=False)
    food_record_id: Mapped[str] = mapped_column(ForeignKey("food_record.id", ondelete="CASCADE"))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))


class NutritionCalculation(IdMixin, Base):
    __tablename__ = "nutrition_calculation"

    recipe_version_id: Mapped[str] = mapped_column(ForeignKey("recipe_version.id", ondelete="CASCADE"), index=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    total_values: Mapped[dict] = mapped_column(JSON, default=dict)
    per_serving_values: Mapped[dict] = mapped_column(JSON, default=dict)
    contributions: Mapped[list] = mapped_column(JSON, default=list)
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    dataset_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class Job(IdMixin, Base):
    __tablename__ = "job"

    household_id: Mapped[str] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default=JobStatus.QUEUED.value, index=True)
    stage: Mapped[str | None] = mapped_column(String(80))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MealPlan(IdMixin, AuditMixin, Base):
    __tablename__ = "meal_plan"

    household_id: Mapped[str] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=PlanStatus.DRAFT.value)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    diagnostics: Mapped[list] = mapped_column(JSON, default=list)


class MealBatch(IdMixin, Base):
    __tablename__ = "meal_batch"

    meal_plan_id: Mapped[str] = mapped_column(ForeignKey("meal_plan.id", ondelete="CASCADE"), index=True)
    recipe_version_id: Mapped[str] = mapped_column(ForeignKey("recipe_version.id", ondelete="RESTRICT"), index=True)
    servings: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    planned_cook_date: Mapped[date] = mapped_column(Date, nullable=False)
    cooked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cooked_weight_grams: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    parent_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("meal_batch.id", ondelete="CASCADE"), nullable=True, index=True
    )
    component_slot: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class MealOccurrence(IdMixin, AuditMixin, Base):
    __tablename__ = "meal_occurrence"
    __table_args__ = (
        UniqueConstraint("meal_plan_id", "meal_date", "meal_type", "component_slot"),
    )

    meal_plan_id: Mapped[str] = mapped_column(ForeignKey("meal_plan.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("meal_batch.id", ondelete="CASCADE"), index=True)
    meal_date: Mapped[date] = mapped_column(Date, nullable=False)
    meal_type: Mapped[str] = mapped_column(String(40), nullable=False)
    component_slot: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    unplanned_allowance: Mapped[bool] = mapped_column(Boolean, default=False)


class PortionAllocation(IdMixin, Base):
    __tablename__ = "portion_allocation"
    __table_args__ = (UniqueConstraint("meal_occurrence_id", "member_id"),)

    meal_occurrence_id: Mapped[str] = mapped_column(ForeignKey("meal_occurrence.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("household_member.id", ondelete="CASCADE"), index=True)
    servings: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)


class PantryLot(IdMixin, AuditMixin, Base):
    __tablename__ = "pantry_lot"

    household_id: Mapped[str] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), index=True)
    food_record_id: Mapped[str | None] = mapped_column(ForeignKey("food_record.id", ondelete="SET NULL"), index=True)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    initial_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    expires_on: Mapped[date | None] = mapped_column(Date)
    always_have: Mapped[bool] = mapped_column(Boolean, default=False)
    use_soon: Mapped[bool] = mapped_column(Boolean, default=False)


class PantryTransaction(IdMixin, Base):
    __tablename__ = "pantry_transaction"

    pantry_lot_id: Mapped[str] = mapped_column(ForeignKey("pantry_lot.id", ondelete="CASCADE"), index=True)
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    reason: Mapped[str] = mapped_column(String(60), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(40))
    reference_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PantryReservation(IdMixin, Base):
    __tablename__ = "pantry_reservation"
    __table_args__ = (UniqueConstraint("pantry_lot_id", "meal_batch_id"),)

    pantry_lot_id: Mapped[str] = mapped_column(ForeignKey("pantry_lot.id", ondelete="CASCADE"), index=True)
    meal_batch_id: Mapped[str] = mapped_column(ForeignKey("meal_batch.id", ondelete="CASCADE"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)


class ShoppingList(IdMixin, AuditMixin, Base):
    __tablename__ = "shopping_list"

    household_id: Mapped[str] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), index=True)
    meal_plan_id: Mapped[str | None] = mapped_column(ForeignKey("meal_plan.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    rebuild_recommended: Mapped[bool] = mapped_column(Boolean, default=False)


class ShoppingItem(IdMixin, AuditMixin, Base):
    __tablename__ = "shopping_item"

    shopping_list_id: Mapped[str] = mapped_column(ForeignKey("shopping_list.id", ondelete="CASCADE"), index=True)
    food_record_id: Mapped[str | None] = mapped_column(ForeignKey("food_record.id", ondelete="SET NULL"), index=True)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    exact_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    purchase_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    density_g_per_ml: Mapped[Decimal | None] = mapped_column(Numeric(10, 5))
    display_unit: Mapped[str | None] = mapped_column(String(30))
    category: Mapped[str] = mapped_column(String(80), default="Other")
    checked: Mapped[bool] = mapped_column(Boolean, default=False)
    manual: Mapped[bool] = mapped_column(Boolean, default=False)
    source_name_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    pantry_unit_conflicts: Mapped[list[dict]] = mapped_column(
        JSON, default=list, server_default="[]"
    )


Index("ix_recipe_household_title", Recipe.household_id, Recipe.title)
Index("ix_pantry_household_food", PantryLot.household_id, PantryLot.food_record_id)
