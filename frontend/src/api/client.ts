import type { JobStatus } from '../types'

const baseUrl = import.meta.env.VITE_API_URL ?? ''
const csrfStorageKey = 'slop-csrf'

let csrfToken = sessionStorage.getItem(csrfStorageKey)

export interface ApiAction {
  kind?: string
  label?: string
  href?: string
  recipe_id?: string
  recipe_version_id?: string
  ingredient_id?: string
  batch_id?: string
  suggestion?: string
  current_display_name?: string
}

export interface ApiNutritionViolation {
  nutrient: string
  actual: string
  low?: string
  high?: string
  kind: 'range' | 'minimum' | 'maximum'
  message: string
}

export interface ApiNutritionIssue {
  date: string
  member: string
  violations: ApiNutritionViolation[]
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    public actions: ApiAction[] = [],
    public issues: ApiNutritionIssue[] = [],
  ) {
    super(message)
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const method = (options?.method ?? 'GET').toUpperCase()
  if (!csrfToken && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrfResponse = await fetch(`${baseUrl}/api/v1/auth/csrf`, { credentials: 'same-origin' })
    if (csrfResponse.ok) {
      const refreshed = await csrfResponse.json() as { csrf_token: string }
      csrfToken = refreshed.csrf_token
      sessionStorage.setItem(csrfStorageKey, csrfToken)
    }
  }
  const response = await fetch(`${baseUrl}/api/v1${path}`, {
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...(csrfToken && !['GET', 'HEAD', 'OPTIONS'].includes(method) ? { 'X-CSRF-Token': csrfToken } : {}),
      ...options?.headers
    },
    ...options
  })
  if (!response.ok) {
    const problem = await response.json().catch(() => null) as { detail?: string; code?: string; action?: ApiAction; actions?: ApiAction[]; issues?: ApiNutritionIssue[] } | null
    throw new ApiError(
      response.status,
      problem?.detail ?? 'The request could not be completed.',
      problem?.code,
      problem?.actions ?? (problem?.action ? [problem.action] : []),
      problem?.issues ?? [],
    )
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>
}

async function listAllRecipes(
  query = '',
  mealType?: BackendMealType | BackendMealType[],
  publisherCategories: string[] = [],
  publisherCategoryMatch: RecipeCategoryMatchMode = 'any',
): Promise<{ items: BackendRecipe[]; total: number }> {
  const items: BackendRecipe[] = []
  let page = 1
  let total = 0
  do {
    const result = await request<{ items: BackendRecipe[]; total: number }>(
      `/recipes?q=${encodeURIComponent(query)}&page=${page}&page_size=100&publisher_category_match=${publisherCategoryMatch}${(Array.isArray(mealType) ? mealType : mealType ? [mealType] : []).map(value => `&meal_type=${encodeURIComponent(value)}`).join('')}${publisherCategories.map(value => `&publisher_category=${encodeURIComponent(value)}`).join('')}`,
    )
    total = result.total
    if (!result.items.length) break
    items.push(...result.items)
    page += 1
  } while (items.length < total)
  return { items, total }
}

export const api = {
  setupStatus: () => request<{ setup_required: boolean }>('/auth/setup-status'),
  setup: async (payload: { setup_token: string; household_name: string; username: string; password: string }) => {
    const result = await request<{ user: { id: string; username: string; member_id?: string; must_change_password: boolean }; csrf_token: string }>('/auth/setup', { method: 'POST', body: JSON.stringify(payload) })
    csrfToken = result.csrf_token
    sessionStorage.setItem(csrfStorageKey, csrfToken)
    return result
  },
  login: async (username: string, password: string) => {
    const result = await request<{ user: { id: string; username: string; member_id?: string; must_change_password: boolean }; csrf_token: string }>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
    csrfToken = result.csrf_token
    sessionStorage.setItem(csrfStorageKey, csrfToken)
    return result
  },
  logout: async () => {
    await request<void>('/auth/logout', { method: 'POST' })
    csrfToken = null
    sessionStorage.removeItem(csrfStorageKey)
  },
  me: () => request<{ id: string; username: string; role: 'owner' | 'collaborator'; member_id?: string; must_change_password: boolean; ingredient_locale: IngredientLocale }>('/auth/me'),
  updateMe: (ingredientLocale: IngredientLocale) => request('/auth/me', { method: 'PATCH', body: JSON.stringify({ ingredient_locale: ingredientLocale }) }),
  changePassword: (currentPassword: string, newPassword: string) => request<void>('/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) }),
  setTarget: (memberId: string, payload: Record<string, unknown>) => request(`/household-members/${memberId}/target`, { method: 'PUT', body: JSON.stringify(payload) }),
  listMembers: () => request<BackendMember[]>('/household-members'),
  listTargets: () => request<BackendTarget[]>('/household-members/targets'),
  createMember: (name: string) => request<BackendMember>('/household-members', { method: 'POST', body: JSON.stringify({ name }) }),
  updateMember: (memberId: string, payload: { expected_version: number; name?: string; active?: boolean }) => request<BackendMember>(`/household-members/${memberId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  getTarget: (memberId: string) => request<BackendTarget>(`/household-members/${memberId}/target`),
  listRestrictions: (memberId: string) => request<BackendRestriction[]>(`/household-members/${memberId}/restrictions`),
  addRestriction: (memberId: string, payload: { kind: BackendRestriction['kind']; value: string; hard?: boolean }) => request<BackendRestriction>(`/household-members/${memberId}/restrictions`, { method: 'POST', body: JSON.stringify(payload) }),
  deleteRestriction: (memberId: string, restrictionId: string) => request<void>(`/household-members/${memberId}/restrictions/${restrictionId}`, { method: 'DELETE' }),
  listRecipes: listAllRecipes,
  createRecipe: (payload: Record<string, unknown>) => request<BackendRecipeDetail>('/recipes', { method: 'POST', body: JSON.stringify(payload) }),
  getRecipe: (id: string) => request<BackendRecipeDetail>(`/recipes/${id}`),
  saveRecipeReview: (id: string, payload: { expected_version: number; title: string; yield_servings: number; meal_types?: BackendMealType[]; ingredients: Array<Record<string, unknown>> }) => request<BackendRecipeDetail>(`/recipes/${id}/review`, { method: 'PUT', body: JSON.stringify(payload) }),
  searchRecipeIngredients: (query = '') => request<{ items: BackendRecipeIngredientChoice[]; total: number }>(`/recipe-ingredients?q=${encodeURIComponent(query)}`),
  recipeCategories: () => request<RecipeCategoryResponse>('/recipe-discovery/categories'),
  searchRemote: (query: string, requestKey: string, sources: RecipeSourceKey[], publisherCategories: string[] = [], publisherCategoryMatch: RecipeCategoryMatchMode = 'any') => request<DiscoveryResponse>(`/recipe-discovery?q=${encodeURIComponent(query)}&request_key=${encodeURIComponent(requestKey)}&sources=${encodeURIComponent(sources.join(','))}&publisher_category_match=${publisherCategoryMatch}${publisherCategories.map(value => `&publisher_category=${encodeURIComponent(value)}`).join('')}`),
  nutritionPreview: (url: string) => request<DiscoveryNutritionPreview>(`/recipe-discovery/nutrition-preview?url=${encodeURIComponent(url)}`),
  startImport: (url: string) => request<JobStatus>('/recipe-imports', { method: 'POST', body: JSON.stringify({ url }) }),
  calculateRecipe: (id: string) => request<{ per_serving_values: Record<string, number> }>(`/recipes/${id}/calculate`, { method: 'POST' }),
  job: (id: string) => request<JobStatus>(`/jobs/${id}`),
  listPantry: () => request<BackendPantryItem[]>('/pantry-items'),
  pantryMatchSuggestions: () => request<BackendPantryMatchSuggestion[]>('/pantry-match-suggestions'),
  addPantry: (payload: { display_name: string; quantity: number; unit: string; always_have?: boolean }) => request<BackendPantryItem>('/pantry-items', { method: 'POST', body: JSON.stringify(payload) }),
  updatePantry: (itemId: string, payload: { expected_version: number; display_name: string; quantity: number; use_soon?: boolean }) => request<BackendPantryItem>(`/pantry-items/${itemId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deletePantry: (itemId: string) => request<void>(`/pantry-items/${itemId}`, { method: 'DELETE' }),
  batchDeletePantry: (itemIds: string[]) => request<BackendPantryBatchDeleteResult>('/pantry-items/batch-delete', { method: 'POST', body: JSON.stringify({ item_ids: itemIds }) }),
  confirmPantryMatch: (itemId: string, payload: { expected_version: number; food_record_id: string }) => request<BackendPantryItem>(`/pantry-items/${itemId}/food-match`, { method: 'PUT', body: JSON.stringify(payload) }),
  activeShoppingList: () => request<BackendShoppingList>('/shopping-lists/active'),
  patchShoppingItem: (listId: string, itemId: string, payload: { expected_version: number; checked?: boolean; display_unit?: string }) => request<BackendShoppingItem>(`/shopping-lists/${listId}/items/${itemId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  confirmShoppingPantryMatch: (listId: string, itemId: string, payload: { expected_version: number; pantry_lot_id: string; decision: 'match' | 'reject' | 'undo' }) => request<BackendShoppingPantryMatchResult>(`/shopping-lists/${listId}/items/${itemId}/pantry-match`, { method: 'POST', body: JSON.stringify(payload) }),
  resolveShoppingPantryReview: (listId: string, itemId: string, payload: { expected_version: number; decision: 'buy' | 'use'; pantry_lot_id?: string; pantry_quantity?: number; requirement_quantity?: number; requirement_unit?: string }) => request<BackendShoppingPantryReviewResult>(`/shopping-lists/${listId}/items/${itemId}/pantry-review`, { method: 'POST', body: JSON.stringify(payload) }),
  renameShoppingItem: (listId: string, itemId: string, payload: { display_name: string; expected_display_name: string }) => request<BackendShoppingItem>(`/shopping-lists/${listId}/items/${itemId}/name`, { method: 'PUT', body: JSON.stringify(payload) }),
  addShoppingItem: (listId: string, payload: { display_name: string; exact_quantity: number; purchase_quantity: number; unit: string; category: string }) => request<BackendShoppingItem>(`/shopping-lists/${listId}/items`, { method: 'POST', body: JSON.stringify(payload) }),
  addPurchasedToPantry: (listId: string) => request<BackendPantryItem[]>(`/shopping-lists/${listId}/add-purchased-to-pantry`, { method: 'POST' }),
  generatePlan: (payload: Record<string, unknown>) => request<BackendPlan>('/meal-plans/generate', { method: 'POST', body: JSON.stringify(payload) }),
  listPlans: () => request<BackendPlan[]>('/meal-plans'),
  getPlan: (id: string) => request<BackendPlanDetail>(`/meal-plans/${id}`),
  replacePlanRecipe: (planId: string, occurrenceId: string, recipeId: string, expectedPlanVersion: number, ignoreNutritionTolerances = false) => request<BackendPlanDetail>(`/meal-plans/${planId}/occurrences/${occurrenceId}/recipe`, { method: 'PUT', body: JSON.stringify({ recipe_id: recipeId, expected_plan_version: expectedPlanVersion, ignore_nutrition_tolerances: ignoreNutritionTolerances }) }),
  addPlanSide: (planId: string, batchId: string, recipeId: string, expectedPlanVersion: number, componentSlot?: number, ignoreNutritionTolerances = false) => request<BackendPlanDetail>(`/meal-plans/${planId}/batches/${batchId}/sides`, { method: 'POST', body: JSON.stringify({ recipe_id: recipeId, expected_plan_version: expectedPlanVersion, component_slot: componentSlot, ignore_nutrition_tolerances: ignoreNutritionTolerances }) }),
  removePlanSide: (planId: string, sideBatchId: string, expectedPlanVersion: number, ignoreNutritionTolerances = false) => request<BackendPlanDetail>(`/meal-plans/${planId}/batches/${sideBatchId}/sides`, { method: 'DELETE', body: JSON.stringify({ expected_plan_version: expectedPlanVersion, ignore_nutrition_tolerances: ignoreNutritionTolerances }) }),
  acceptPlan: (id: string) => request<BackendPlan>(`/meal-plans/${id}/accept`, { method: 'POST' }),
  markBatchCooked: (planId: string, batchId: string) => request<void>(`/meal-plans/${planId}/batches/${batchId}/cooked`, { method: 'POST' }),
  unmarkBatchCooked: (planId: string, batchId: string) => request<void>(`/meal-plans/${planId}/batches/${batchId}/cooked`, { method: 'DELETE' }),
  updateBatchCookedWeight: (planId: string, batchId: string, cookedWeightGrams: number | null) => request<void>(`/meal-plans/${planId}/batches/${batchId}/cooked-weight`, { method: 'PATCH', body: JSON.stringify({ cooked_weight_grams: cookedWeightGrams }) }),
  buildShoppingList: (planId: string) => request<BackendShoppingList>('/shopping-lists/build', { method: 'POST', body: JSON.stringify({ meal_plan_id: planId, name: 'Current shopping list' }) }),
  backupStatus: () => request<BackendBackupStatus>('/system/backups'),
  createBackup: () => request<BackendBackupStatus>('/system/backups', { method: 'POST' })
}

export const isDemoMode = import.meta.env.VITE_DEMO_MODE !== 'false'

export type BackendMealType = 'breakfast' | 'lunch' | 'dinner' | 'snack' | 'side'
export type IngredientLocale = 'uk' | 'us'

export interface BackendRecipeIngredientChoice {
  id: string
  term: string
  name: string
  recipes: Array<{ id: string; title: string }>
}

export interface BackendRecipe {
  id: string
  title: string
  eligibility: 'draft' | 'needs_review' | 'planner_ready' | 'archived'
  source_type: string
  source_url?: string
  publisher?: string
  image_url?: string
  version: number
  yield_servings?: number
  publisher_nutrition?: {
    basis?: string
    energy_kcal?: number
    protein_g?: number
    carbohydrate_g?: number
    fat_g?: number
  }
  calculated_nutrition?: Record<string, number>
  nutrition_method?: 'publisher' | 'complete'
  review_count?: number
  meal_types: BackendMealType[]
  planner_eligible: boolean
  planner_warnings: string[]
  publisher_tags?: Array<{ kind: string; label: string }>
  publisher_categories?: string[]
  publisher_metadata_status?: 'not_applicable' | 'pending' | 'refreshing' | 'ready' | 'failed'
}

export interface BackendRecipeDetail extends BackendRecipe {
  recipe_version_id: string
  version_number: number
  yield_servings?: number
  ingredients: Array<{
    id: string
    original_text: string
    quantity?: number
    unit?: string
    quantity_grams?: number
    food_phrase?: string
    parsed_food_phrase?: string
    preparation?: string
    name_confidence?: number
    included: boolean
    optional: boolean
    needs_review: boolean
    shopping_excluded: boolean
    food_record_id?: string
  }>
}

export interface BackendFood {
  id: string
  name: string
  provider: string
  dataset_version: string
  basis_unit: string
}

export interface BackendMember {
  id: string
  name: string
  active: boolean
  version: number
}

export interface BackendTarget {
  id: string
  member_id: string
  mode: 'calorie' | 'macros'
  calorie_target?: number
  protein_target_g?: number
  carbohydrate_target_g?: number
  fat_target_g?: number
  protein_min_g?: number
  protein_max_g?: number
  carbohydrate_min_g?: number
  carbohydrate_max_g?: number
  fat_min_g?: number
  fat_max_g?: number
  tolerance_percent: number
  allocations: Array<{ meal_type: string; percentage: number }>
  version: number
}

export interface BackendRestriction {
  id: string
  member_id: string
  kind: 'allergy' | 'exclude' | 'dislike' | 'prefer'
  value: string
  hard: boolean
}

export interface BackendBackupStatus {
  available: boolean
  last_backup?: string | null
  tier?: string | null
  application_version?: string | null
  schema_revision?: string | null
}

export interface DiscoveryResult {
  source: string
  title: string
  url: string
  image_url?: string
  publisher_nutrition?: {
    basis?: string
    energy_kcal?: number
    protein_g?: number
    carbohydrate_g?: number
    fat_g?: number
  }
  already_saved: boolean
  star_rating?: number
  rating_count?: number
  matched_categories?: string[]
}

export interface DiscoveryResponse {
  results: DiscoveryResult[]
  sources: Array<{ source: string; error_code?: string; error_message?: string; warnings?: string[] }>
  superseded: boolean
  cache_hit: boolean
  debounce_ms: number
}

export interface DiscoveryNutritionPreview {
  url: string
  publisher?: string
  yield_servings?: number
  publisher_nutrition?: DiscoveryResult['publisher_nutrition']
}

export type RecipeSourceKey = 'good_food' | 'allrecipes'
export type RecipeCategoryMatchMode = 'any' | 'all'

export interface RecipeCategoryOption {
  key: string
  label: string
  rank: number
  confidence: 'high' | 'medium'
  providers: Record<RecipeSourceKey, 'category_page' | 'search_fallback'>
}

export interface RecipeCategoryResponse {
  maximum_selected: number
  match: RecipeCategoryMatchMode
  items: RecipeCategoryOption[]
}

export interface BackendPantryItem {
  id: string
  food_record_id?: string
  display_name: string
  initial_quantity: number | string
  unit: string
  expires_on?: string
  always_have: boolean
  use_soon: boolean
  on_hand_quantity: number | string
  reserved_quantity: number | string
  usable_quantity: number | string
  initial_quantity_display: string
  on_hand_quantity_display: string
  reserved_quantity_display: string
  usable_quantity_display: string
  version: number
}

export interface BackendPantryMatchCandidate {
  food_record_id: string
  display_name: string
  confidence: number
}

export interface BackendPantryMatchSuggestion {
  pantry_lot_id: string
  candidates: BackendPantryMatchCandidate[]
}

export interface BackendPantryBatchDeleteResult {
  deleted_ids: string[]
  blocked: Array<{ id: string; display_name: string; reason: 'reserved_by_plan' | 'not_found' }>
}

export interface BackendShoppingItem {
  id: string
  display_name: string
  exact_quantity: number | string
  purchase_quantity: number | string
  exact_quantity_display: string
  purchase_quantity_display: string
  unit: string
  available_units?: string[]
  quantity_options?: BackendShoppingQuantityOption[]
  category: string
  checked: boolean
  manual: boolean
  pantry_unit_conflicts?: BackendShoppingPantryUnitConflict[]
  pantry_match_suggestions?: BackendShoppingPantryMatchSuggestion[]
  pantry_confirmed_matches?: BackendShoppingPantryConfirmedMatch[]
  version: number
}

export interface BackendShoppingPantryUnitConflict {
  pantry_lot_id: string
  display_name: string
  usable_quantity: number | string
  unit: string
  usable_quantity_display: string
}

export interface BackendShoppingPantryMatchSuggestion extends BackendShoppingPantryUnitConflict {
  confidence: number
}

export interface BackendShoppingPantryConfirmedMatch extends BackendShoppingPantryMatchSuggestion {
  fuzzy: boolean
}

export interface BackendShoppingPantryReviewResult {
  removed: boolean
  item?: BackendShoppingItem
  pantry_item?: BackendPantryItem
}

export interface BackendShoppingPantryMatchResult {
  removed: boolean
  item?: BackendShoppingItem
  pantry_item: BackendPantryItem
}

export interface BackendShoppingQuantityOption {
  unit: string
  exact_quantity: number | string
  purchase_quantity: number | string
  exact_quantity_display: string
  purchase_quantity_display: string
  approximate: boolean
}

export interface BackendShoppingList {
  id: string
  meal_plan_id?: string | null
  name: string
  active: boolean
  rebuild_recommended: boolean
  version: number
  items: BackendShoppingItem[]
}

export interface BackendPlan {
  id: string
  name: string
  start_date: string
  end_date: string
  status: 'draft' | 'generating' | 'ready' | 'accepted' | 'superseded'
  diagnostics: Array<Record<string, unknown>>
  version: number
}

export interface BackendPlanDetail {
  plan: BackendPlan
  occurrences: Array<{
    id: string
    meal_date: string
    meal_type: string
    batch_id: string
    parent_batch_id?: string
    component_slot: number
    recipe_id: string
    recipe_title: string
    source_url?: string
    image_url?: string
    batch_servings: number
    planned_cook_date?: string
    nutrition_per_serving?: Record<string, number>
    cooked_at?: string
    cooked_weight_grams?: number | null
    serving_weight_grams?: number | null
    portions: Array<{ member_id: string; servings: number }>
  }>
  daily_nutrition?: Array<{
    meal_date: string
    totals: Record<string, number>
    members: Array<{ member_id: string; totals: Record<string, number> }>
  }>
}
