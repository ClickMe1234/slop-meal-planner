from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from .discovery.errors import InvalidUrlError
from .discovery.urls import canonicalize_url
from .models import IngredientLocale, JobStatus, MealType, PlanStatus, RecipeEligibility, RecipeTag, TargetMode, UserRole

MACRO_MINIMUM_TOLERANCE_G = Decimal("10")
BoundedIdentifier = Annotated[str, StringConstraints(min_length=1, max_length=80)]
BoundedTerm = Annotated[str, StringConstraints(min_length=1, max_length=160)]


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class VersionedUpdate(APIModel):
    expected_version: int = Field(ge=1)


class SetupRequest(APIModel):
    setup_token: str = Field(min_length=1, max_length=256)
    household_name: str = Field(min_length=1, max_length=160)
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=200)


class LoginRequest(APIModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class UserOut(APIModel):
    id: str
    username: str
    role: UserRole
    active: bool
    must_change_password: bool
    ingredient_locale: IngredientLocale
    member_id: str | None


class UserPreferencesUpdate(APIModel):
    ingredient_locale: IngredientLocale


class AuthOut(APIModel):
    user: UserOut
    csrf_token: str


class CollaboratorCreate(APIModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    temporary_password: str = Field(min_length=12, max_length=200)
    member_id: str | None = None


class PasswordChange(APIModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=12, max_length=200)


class IntegrationCredentialUpdate(APIModel):
    api_key: str = Field(min_length=8, max_length=200, pattern=r"^\S+$")


RestoreComponent = Literal[
    "household",
    "users",
    "recipes",
    "ingredients",
    "pantry",
    "shopping",
    "plans",
]


class RestorePreviewRequest(APIModel):
    archive: str = Field(min_length=1, max_length=80)
    source_household_id: str | None = None


class RestoreRequest(RestorePreviewRequest):
    components: list[RestoreComponent] = Field(min_length=1, max_length=7)


class MemberCreate(APIModel):
    name: str = Field(min_length=1, max_length=120)


class MemberUpdate(VersionedUpdate):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    active: bool | None = None


class MemberOut(APIModel):
    id: str
    name: str
    active: bool
    version: int


class MealAllocationIn(APIModel):
    meal_type: str = Field(min_length=1, max_length=40)
    percentage: Decimal = Field(gt=0, le=100)


class TargetProfileIn(APIModel):
    mode: TargetMode
    tolerance_percent: Decimal = Field(default=Decimal("5"), gt=0, le=25)
    calorie_target: Decimal | None = Field(default=None, gt=0)
    protein_target_g: Decimal | None = Field(default=None, ge=0)
    carbohydrate_target_g: Decimal | None = Field(default=None, ge=0)
    fat_target_g: Decimal | None = Field(default=None, ge=0)
    protein_min_g: Decimal | None = Field(default=Decimal("0"), ge=0)
    protein_max_g: Decimal | None = Field(default=None, ge=0)
    carbohydrate_min_g: Decimal | None = Field(default=Decimal("0"), ge=0)
    carbohydrate_max_g: Decimal | None = Field(default=None, ge=0)
    fat_min_g: Decimal | None = Field(default=Decimal("0"), ge=0)
    fat_max_g: Decimal | None = Field(default=None, ge=0)
    allocations: list[MealAllocationIn] = Field(
        default_factory=lambda: [
            MealAllocationIn(meal_type="breakfast", percentage=25),
            MealAllocationIn(meal_type="lunch", percentage=30),
            MealAllocationIn(meal_type="dinner", percentage=35),
            MealAllocationIn(meal_type="snack", percentage=10),
        ],
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def validate_mode_and_ranges(self):
        macro_targets = (self.protein_target_g, self.carbohydrate_target_g, self.fat_target_g)
        if self.mode == TargetMode.CALORIE:
            if self.calorie_target is None:
                raise ValueError("calorie_target is required in calorie mode")
            if any(value is not None for value in macro_targets):
                raise ValueError("macro targets cannot be set in calorie mode; use macro minimums/maximums")
        else:
            if self.calorie_target is not None:
                raise ValueError("calorie_target cannot be set in macro mode")
            if any(value is None for value in macro_targets):
                raise ValueError("protein, carbohydrate and fat targets are required in macro mode")

        for low, high, name in (
            (self.protein_min_g, self.protein_max_g, "protein"),
            (self.carbohydrate_min_g, self.carbohydrate_max_g, "carbohydrate"),
            (self.fat_min_g, self.fat_max_g, "fat"),
        ):
            if low is not None and high is not None and low > high:
                raise ValueError(f"{name} minimum cannot exceed maximum")

        if not self.allocations or sum(item.percentage for item in self.allocations) != 100:
            raise ValueError("enabled meal allocations must total 100 percent")
        if len({item.meal_type.lower() for item in self.allocations}) != len(self.allocations):
            raise ValueError("meal allocation names must be unique")

        if self.mode == TargetMode.CALORIE and self.calorie_target is not None:
            calorie_low = self.calorie_target * (Decimal("1") - self.tolerance_percent / 100)
            calorie_high = self.calorie_target * (Decimal("1") + self.tolerance_percent / 100)
            implied_min = (
                max((self.protein_min_g or 0) - MACRO_MINIMUM_TOLERANCE_G, 0) * 4
                + max((self.carbohydrate_min_g or 0) - MACRO_MINIMUM_TOLERANCE_G, 0) * 4
                + max((self.fat_min_g or 0) - MACRO_MINIMUM_TOLERANCE_G, 0) * 9
            )
            if implied_min > calorie_high:
                raise ValueError("macro minimums imply more energy than the calorie tolerance permits")
            if all(v is not None for v in (self.protein_max_g, self.carbohydrate_max_g, self.fat_max_g)):
                implied_max = self.protein_max_g * 4 + self.carbohydrate_max_g * 4 + self.fat_max_g * 9
                if implied_max < calorie_low:
                    raise ValueError("macro maximums imply less energy than the calorie tolerance requires")
        return self


class TargetProfileOut(TargetProfileIn):
    id: str
    member_id: str
    version: int


class RestrictionIn(APIModel):
    kind: Literal["allergy", "exclude", "dislike", "prefer"]
    value: str = Field(min_length=1, max_length=160)
    hard: bool = False


class RecipeIngredientIn(APIModel):
    original_text: str = Field(min_length=1, max_length=1000)
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=80)
    quantity_grams: Decimal | None = Field(default=None, ge=0)
    food_phrase: str | None = Field(default=None, max_length=300)
    preparation: str | None = Field(default=None, max_length=300)
    included: bool = True
    optional: bool = False
    needs_review: bool = False
    shopping_excluded: bool = False
    food_record_id: str | None = None

    @model_validator(mode="after")
    def optional_defaults_to_excluded(self):
        if self.optional and "included" not in self.model_fields_set:
            self.included = False
        return self


class RecipeCreate(APIModel):
    title: str = Field(min_length=1, max_length=300)
    yield_servings: Decimal | None = Field(default=None, gt=0)
    source_type: Literal["custom", "url"] = "custom"
    source_url: str | None = Field(default=None, max_length=4096)
    publisher: str | None = Field(default=None, max_length=300)
    image_url: str | None = Field(default=None, max_length=4096)
    custom_instructions: str | None = Field(default=None, max_length=20_000)
    publisher_nutrition: dict[str, Any] | None = None
    meal_types: list[RecipeTag] = Field(default_factory=list, max_length=20)
    ingredients: list[RecipeIngredientIn] = Field(default_factory=list, max_length=500)

    @field_validator("source_url", "image_url")
    @classmethod
    def canonicalize_recipe_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return canonicalize_url(value)
        except InvalidUrlError as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="after")
    def custom_instruction_policy(self):
        if self.source_type != "custom" and self.custom_instructions:
            raise ValueError("publisher cooking instructions are not stored")
        if self.source_type == "url" and not self.source_url:
            raise ValueError("source_url is required for URL recipes")
        if len(set(self.meal_types)) != len(self.meal_types):
            raise ValueError("recipe meal types must be unique")
        return self


class RecipeReviewUpdate(VersionedUpdate):
    title: str = Field(min_length=1, max_length=300)
    yield_servings: Decimal = Field(gt=0)
    meal_types: list[RecipeTag] | None = Field(default=None, max_length=20)
    ingredients: list[RecipeIngredientIn] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_meal_types(self):
        if self.meal_types is not None and len(set(self.meal_types)) != len(self.meal_types):
            raise ValueError("recipe meal types must be unique")
        return self


class PublisherTagOut(APIModel):
    kind: str
    label: str


class RecipeSummary(APIModel):
    id: str
    title: str
    eligibility: RecipeEligibility
    source_type: str
    source_url: str | None
    publisher: str | None
    image_url: str | None
    version: int
    yield_servings: Decimal | None = None
    publisher_nutrition: dict[str, Any] | None = None
    calculated_nutrition: dict[str, Any] | None = None
    nutrition_method: str | None = None
    review_count: int = 0
    meal_types: list[RecipeTag] = Field(default_factory=list)
    planner_eligible: bool = False
    planner_warnings: list[str] = Field(default_factory=list)
    publisher_tags: list[PublisherTagOut] = Field(default_factory=list)
    publisher_categories: list[str] = Field(default_factory=list)
    publisher_metadata_status: str = "not_applicable"


class RecipeDetail(RecipeSummary):
    recipe_version_id: str
    version_number: int
    yield_servings: Decimal | None
    custom_instructions: str | None
    ingredients: list[dict[str, Any]]


class FoodNutrientIn(APIModel):
    code: Literal["energy_kcal", "protein_g", "carbohydrate_g", "fat_g"]
    amount: Decimal = Field(ge=0)
    unit: str
    qualifier: str | None = None


class FoodRecordCreate(APIModel):
    provider: str = Field(min_length=1, max_length=40)
    provider_record_id: str = Field(min_length=1, max_length=120)
    dataset_version: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=300)
    basis_amount: Decimal = Field(default=100, gt=0)
    basis_unit: Literal["g", "ml"] = "g"
    density_g_per_ml: Decimal | None = Field(default=None, gt=0)
    nutrients: list[FoodNutrientIn] = Field(min_length=1, max_length=32)


class FoodRecordOut(APIModel):
    id: str
    provider: str
    provider_record_id: str
    dataset_version: str
    name: str
    basis_amount: Decimal
    basis_unit: str
    density_g_per_ml: Decimal | None
    nutrients: list[dict[str, Any]]


class FoodLookupSearch(APIModel):
    query: str = Field(min_length=2, max_length=200)
    page: int = Field(default=1, ge=1, le=20)

    @model_validator(mode="after")
    def normalize_query(self):
        self.query = " ".join(self.query.split())
        if len(self.query) < 2:
            raise ValueError("enter at least two characters")
        return self


class FoodLookupOut(APIModel):
    provider: str
    provider_record_id: str
    name: str
    brand: str | None = None
    barcode: str | None = None
    basis_amount: Decimal = Decimal("100")
    basis_unit: Literal["g", "ml"]
    nutrients: dict[str, Decimal | None]
    complete: bool
    package_amount: Decimal | None = None
    package_unit: Literal["g", "ml"] | None = None
    serving_amount: Decimal | None = None
    serving_unit: Literal["g", "ml"] | None = None
    source_url: str | None = None
    image_url: str | None = None
    attribution: str | None = None
    warnings: list[str] = Field(default_factory=list)


class FoodLookupSearchOut(APIModel):
    items: list[FoodLookupOut]
    page: int
    has_more: bool = False
    remote_error: str | None = None


class SavedFoodCreate(APIModel):
    source_type: Literal["food_record", "open_food_facts", "manual"]
    food_record_id: str | None = None
    barcode: str | None = Field(default=None, max_length=40)
    display_name: str | None = Field(default=None, max_length=300)
    basis_amount: Decimal = Field(default=100, gt=0)
    basis_unit: Literal["g", "ml"] = "g"
    nutrients: list[FoodNutrientIn] = Field(default_factory=list, max_length=32)
    serving_amount: Decimal | None = Field(default=None, gt=0)
    serving_unit: Literal["g", "ml"] | None = None
    planner_enabled: bool = False
    meal_types: list[RecipeTag] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_source_and_planner(self):
        if self.display_name is not None:
            self.display_name = self.display_name.strip()
        if self.source_type == "manual" and (not self.display_name or not self.nutrients):
            raise ValueError("manual foods require a name and nutrition values")
        if self.source_type == "open_food_facts" and not self.barcode:
            raise ValueError("an Open Food Facts barcode is required")
        if self.source_type == "food_record" and not self.food_record_id:
            raise ValueError("a food record is required")
        if self.planner_enabled and (
            self.serving_amount is None or self.serving_unit is None or not self.meal_types
        ):
            raise ValueError("planner foods require a serving and at least one meal type")
        if len(set(self.meal_types)) != len(self.meal_types):
            raise ValueError("meal types must be unique")
        return self


class SavedFoodUpdate(VersionedUpdate):
    display_name: str = Field(min_length=1, max_length=300)
    serving_amount: Decimal | None = Field(default=None, gt=0)
    serving_unit: Literal["g", "ml"] | None = None
    planner_enabled: bool = False
    meal_types: list[RecipeTag] = Field(default_factory=list, max_length=20)
    basis_amount: Decimal | None = Field(default=None, gt=0)
    basis_unit: Literal["g", "ml"] | None = None
    nutrients: list[FoodNutrientIn] | None = None

    @model_validator(mode="after")
    def validate_planner(self):
        self.display_name = self.display_name.strip()
        if not self.display_name:
            raise ValueError("display name cannot be blank")
        if (self.serving_amount is None) != (self.serving_unit is None):
            raise ValueError("serving amount and unit must be supplied together")
        if self.planner_enabled and (
            self.serving_amount is None or self.serving_unit is None or not self.meal_types
        ):
            raise ValueError("planner foods require a serving and at least one meal type")
        if len(set(self.meal_types)) != len(self.meal_types):
            raise ValueError("meal types must be unique")
        if self.nutrients is not None and (self.basis_amount is None or self.basis_unit is None):
            raise ValueError("nutrition corrections require a basis")
        return self


class SavedFoodOut(APIModel):
    id: str
    display_name: str
    food_record_id: str
    provider: str
    provider_record_id: str
    barcode: str | None = None
    brand: str | None = None
    dataset_version: str
    basis_amount: Decimal
    basis_unit: str
    nutrients: dict[str, Decimal | None]
    serving_amount: Decimal | None
    serving_unit: str | None
    planner_enabled: bool
    planner_recipe_id: str | None
    meal_types: list[RecipeTag] = Field(default_factory=list)
    package_amount: Decimal | None = None
    package_unit: str | None = None
    source_url: str | None = None
    image_url: str | None = None
    attribution: str | None = None
    warnings: list[str] = Field(default_factory=list)
    version: int


class NutritionCalculationOut(APIModel):
    id: str
    recipe_version_id: str
    status: str
    total_values: dict[str, Any]
    per_serving_values: dict[str, Any]
    contributions: list[dict[str, Any]]
    assumptions: list[str]


class ImportRequest(APIModel):
    url: str = Field(min_length=1, max_length=4096)

    @field_validator("url")
    @classmethod
    def canonicalize_import_url(cls, value: str) -> str:
        try:
            return canonicalize_url(value)
        except InvalidUrlError as exc:
            raise ValueError(str(exc)) from exc


class JobOut(APIModel):
    id: str
    kind: str
    status: JobStatus
    stage: str | None
    progress: int
    result: dict[str, Any] | None
    error_code: str | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime


class PlanSlotIn(APIModel):
    meal_date: date
    meal_type: MealType
    participant_member_ids: list[BoundedIdentifier] = Field(min_length=1, max_length=50)
    # Slots sharing a key are cooked as one batch and allocated across dates.
    # Omit the key to cook that occurrence separately.
    batch_key: str | None = Field(default=None, max_length=80)
    food_safety_acknowledged: bool = False


class MealCalorieBoostAllocationIn(APIModel):
    meal_type: MealType
    percentage: int = Field(ge=0, le=100)


class DayCalorieBoostIn(APIModel):
    meal_date: date
    member_id: str
    calories: Decimal = Field(gt=0, le=10000)
    meal_allocations: list[MealCalorieBoostAllocationIn] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_meal_allocations(self):
        meal_types = [item.meal_type for item in self.meal_allocations]
        if len(meal_types) != len(set(meal_types)):
            raise ValueError("calorie boost meal types must be unique")
        if self.meal_allocations and sum(item.percentage for item in self.meal_allocations) != 100:
            raise ValueError("calorie boost meal allocations must total 100 percent")
        return self


class GuestDayIn(APIModel):
    meal_date: date
    guest_count: int = Field(gt=0, le=50)
    meal_types: list[MealType] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_meal_types(self):
        if len(self.meal_types) != len(set(self.meal_types)):
            raise ValueError("guest meal types must be unique")
        return self


class PlanGenerateRequest(APIModel):
    name: str = Field(min_length=1, max_length=160)
    start_date: date | None = None
    end_date: date | None = None
    slots: list[PlanSlotIn] = Field(min_length=1, max_length=250)
    recipe_ids: list[BoundedIdentifier] = Field(default_factory=list, max_length=500)
    must_use_food_record_ids: list[BoundedIdentifier] = Field(default_factory=list, max_length=200)
    prefer_food_record_ids: list[BoundedIdentifier] = Field(default_factory=list, max_length=200)
    exclude_food_record_ids: list[BoundedIdentifier] = Field(default_factory=list, max_length=200)
    must_use_ingredient_terms: list[BoundedTerm] = Field(default_factory=list, max_length=200)
    prefer_ingredient_terms: list[BoundedTerm] = Field(default_factory=list, max_length=200)
    exclude_ingredient_terms: list[BoundedTerm] = Field(default_factory=list, max_length=200)
    calorie_boosts: list[DayCalorieBoostIn] = Field(default_factory=list, max_length=250)
    guest_days: list[GuestDayIn] = Field(default_factory=list, max_length=250)
    ignore_nutrition_tolerances: bool = False

    @model_validator(mode="after")
    def validate_planning_period(self):
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("start_date and end_date must be supplied together")
        if self.start_date is not None and self.end_date is not None:
            if self.start_date > self.end_date:
                raise ValueError("start_date cannot be after end_date")
            if (self.end_date - self.start_date).days > 31:
                raise ValueError("planning periods cannot exceed 32 days")
            if any(
                slot.meal_date < self.start_date or slot.meal_date > self.end_date
                for slot in self.slots
            ):
                raise ValueError("every meal slot must be inside the planning period")
            if any(
                boost.meal_date < self.start_date or boost.meal_date > self.end_date
                for boost in self.calorie_boosts
            ):
                raise ValueError("every calorie boost must be inside the planning period")
            if any(
                guest_day.meal_date < self.start_date or guest_day.meal_date > self.end_date
                for guest_day in self.guest_days
            ):
                raise ValueError("every guest day must be inside the planning period")
        boost_keys = [(boost.meal_date, boost.member_id) for boost in self.calorie_boosts]
        if len(boost_keys) != len(set(boost_keys)):
            raise ValueError("a member can only have one calorie boost per day")
        guest_dates = [guest_day.meal_date for guest_day in self.guest_days]
        if len(guest_dates) != len(set(guest_dates)):
            raise ValueError("a date can only have one guest count")
        return self


class PlanOut(APIModel):
    id: str
    name: str
    start_date: date
    end_date: date
    status: PlanStatus
    diagnostics: list[dict[str, Any]]
    calorie_boosts: list[dict[str, Any]]
    guest_days: list[dict[str, Any]]
    version: int


class PlanRecipeReplaceRequest(APIModel):
    recipe_id: str
    expected_plan_version: int = Field(ge=1)
    ignore_nutrition_tolerances: bool = False


class PlanSideCreateRequest(APIModel):
    recipe_id: str
    expected_plan_version: int = Field(ge=1)
    component_slot: int | None = Field(default=None, ge=1, le=2)
    ignore_nutrition_tolerances: bool = False


class PlanSideRemoveRequest(APIModel):
    expected_plan_version: int = Field(ge=1)
    ignore_nutrition_tolerances: bool = False


class BatchCookedWeightUpdate(APIModel):
    cooked_weight_grams: Decimal | None = Field(default=None, gt=0)


class PantryLotCreate(APIModel):
    display_name: str = Field(min_length=1, max_length=240)
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=30)
    food_record_id: str | None = None
    expires_on: date | None = None
    always_have: bool = False
    use_soon: bool = False


class PantryAdjustment(APIModel):
    quantity_delta: Decimal
    reason: str = Field(min_length=1, max_length=60)


class PantryLotPatch(VersionedUpdate):
    display_name: str = Field(min_length=1, max_length=240)
    quantity: Decimal = Field(ge=0)
    use_soon: bool | None = None

    @model_validator(mode="after")
    def strip_display_name(self):
        self.display_name = self.display_name.strip()
        if not self.display_name:
            raise ValueError("pantry item name cannot be blank")
        return self


class PantryLotOut(APIModel):
    id: str
    display_name: str
    food_record_id: str | None
    initial_quantity: Decimal
    unit: str
    expires_on: date | None
    always_have: bool
    use_soon: bool
    on_hand_quantity: Decimal
    reserved_quantity: Decimal
    usable_quantity: Decimal
    initial_quantity_display: str
    on_hand_quantity_display: str
    reserved_quantity_display: str
    usable_quantity_display: str
    version: int


class PantryMatchCandidate(APIModel):
    food_record_id: str
    display_name: str
    confidence: float


class PantryMatchSuggestion(APIModel):
    pantry_lot_id: str
    candidates: list[PantryMatchCandidate]


class PantryMatchConfirmation(VersionedUpdate):
    food_record_id: str


class PantryBatchDeleteRequest(APIModel):
    item_ids: list[str] = Field(min_length=1, max_length=200)


class PantryBatchDeleteBlocked(APIModel):
    id: str
    display_name: str
    reason: str


class PantryBatchDeleteOut(APIModel):
    deleted_ids: list[str]
    blocked: list[PantryBatchDeleteBlocked]


class ShoppingBuildRequest(APIModel):
    meal_plan_id: str
    name: str = "Current shopping list"


class ShoppingItemCreate(APIModel):
    display_name: str
    exact_quantity: Decimal = Field(gt=0)
    purchase_quantity: Decimal = Field(gt=0)
    unit: str
    category: str = "Other"


class ShoppingItemPatch(VersionedUpdate):
    checked: bool | None = None
    purchase_quantity: Decimal | None = Field(default=None, gt=0)
    category: str | None = None
    display_unit: str | None = None


class ShoppingItemNameUpdate(APIModel):
    display_name: str = Field(min_length=1, max_length=240)
    expected_display_name: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def strip_names(self):
        self.display_name = self.display_name.strip()
        self.expected_display_name = self.expected_display_name.strip()
        if not self.display_name or not self.expected_display_name:
            raise ValueError("shopping item names cannot be blank")
        return self


class ShoppingQuantityOption(APIModel):
    unit: str
    exact_quantity: Decimal
    purchase_quantity: Decimal
    exact_quantity_display: str
    purchase_quantity_display: str
    approximate: bool = False


class ShoppingPantryUnitConflict(APIModel):
    pantry_lot_id: str
    display_name: str
    usable_quantity: Decimal
    unit: str
    usable_quantity_display: str


class ShoppingPantryMatchSuggestion(APIModel):
    pantry_lot_id: str
    display_name: str
    usable_quantity: Decimal
    unit: str
    usable_quantity_display: str
    confidence: float


class ShoppingPantryConfirmedMatch(ShoppingPantryMatchSuggestion):
    fuzzy: bool


class ShoppingPantryMatchRequest(VersionedUpdate):
    pantry_lot_id: str
    decision: Literal["match", "reject", "undo"]


class ShoppingPantryReviewRequest(VersionedUpdate):
    decision: Literal["buy", "use"]
    pantry_lot_id: str | None = None
    pantry_quantity: Decimal | None = Field(default=None, gt=0)
    requirement_quantity: Decimal | None = Field(default=None, gt=0)
    requirement_unit: str | None = None

    @model_validator(mode="after")
    def require_usage_amounts(self):
        if self.decision == "use" and (
            not self.pantry_lot_id
            or self.pantry_quantity is None
            or self.requirement_quantity is None
            or not self.requirement_unit
        ):
            raise ValueError(
                "pantry lot, pantry quantity, requirement quantity and unit are required"
            )
        return self


class ShoppingItemOut(APIModel):
    id: str
    display_name: str
    exact_quantity: Decimal
    purchase_quantity: Decimal
    exact_quantity_display: str
    purchase_quantity_display: str
    unit: str
    available_units: list[str]
    quantity_options: list[ShoppingQuantityOption]
    category: str
    checked: bool
    manual: bool
    pantry_unit_conflicts: list[ShoppingPantryUnitConflict]
    pantry_match_suggestions: list[ShoppingPantryMatchSuggestion]
    pantry_confirmed_matches: list[ShoppingPantryConfirmedMatch]
    version: int


class ShoppingPantryReviewOut(APIModel):
    removed: bool
    item: ShoppingItemOut | None = None
    pantry_item: PantryLotOut | None = None


class ShoppingPantryMatchOut(APIModel):
    removed: bool
    item: ShoppingItemOut | None = None
    pantry_item: PantryLotOut


class ShoppingListOut(APIModel):
    id: str
    name: str
    meal_plan_id: str | None
    active: bool
    rebuild_recommended: bool
    version: int
    items: list[ShoppingItemOut]


class ProblemDetail(APIModel):
    type: str = "about:blank"
    title: str
    status: int
    code: str
    detail: str
    field_errors: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str | None = None
