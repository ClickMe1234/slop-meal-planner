import type { JobStatus } from '../types'

const baseUrl = import.meta.env.VITE_API_URL ?? ''
const csrfStorageKey = 'savour-csrf'

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
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    public actions: ApiAction[] = [],
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
    const problem = await response.json().catch(() => null) as { detail?: string; code?: string; action?: ApiAction; actions?: ApiAction[] } | null
    throw new ApiError(
      response.status,
      problem?.detail ?? 'The request could not be completed.',
      problem?.code,
      problem?.actions ?? (problem?.action ? [problem.action] : []),
    )
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>
}

async function listAllRecipes(query = '', mealType?: BackendMealType): Promise<{ items: BackendRecipe[]; total: number }> {
  const items: BackendRecipe[] = []
  let page = 1
  let total = 0
  do {
    const result = await request<{ items: BackendRecipe[]; total: number }>(
      `/recipes?q=${encodeURIComponent(query)}&page=${page}&page_size=100${mealType ? `&meal_type=${encodeURIComponent(mealType)}` : ''}`,
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
  me: () => request<{ id: string; username: string; role: 'owner' | 'collaborator'; member_id?: string; must_change_password: boolean }>('/auth/me'),
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
  searchFoods: (query = '') => request<{ items: BackendFood[]; total: number; remote_error?: string }>(`/foods?q=${encodeURIComponent(query)}&page_size=100`),
  searchRemote: (query: string, requestKey: string, sources: RecipeSourceKey[]) => request<DiscoveryResponse>(`/recipe-discovery?q=${encodeURIComponent(query)}&request_key=${encodeURIComponent(requestKey)}&sources=${encodeURIComponent(sources.join(','))}`),
  nutritionPreview: (url: string) => request<DiscoveryNutritionPreview>(`/recipe-discovery/nutrition-preview?url=${encodeURIComponent(url)}`),
  startImport: (url: string) => request<JobStatus>('/recipe-imports', { method: 'POST', body: JSON.stringify({ url }) }),
  calculateRecipe: (id: string) => request<{ per_serving_values: Record<string, number> }>(`/recipes/${id}/calculate`, { method: 'POST' }),
  job: (id: string) => request<JobStatus>(`/jobs/${id}`),
  listPantry: () => request<BackendPantryItem[]>('/pantry-items'),
  addPantry: (payload: { display_name: string; quantity: number; unit: string; always_have?: boolean }) => request<BackendPantryItem>('/pantry-items', { method: 'POST', body: JSON.stringify(payload) }),
  activeShoppingList: () => request<BackendShoppingList>('/shopping-lists/active'),
  patchShoppingItem: (listId: string, itemId: string, payload: { expected_version: number; checked?: boolean }) => request<BackendShoppingItem>(`/shopping-lists/${listId}/items/${itemId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  addShoppingItem: (listId: string, payload: { display_name: string; exact_quantity: number; purchase_quantity: number; unit: string; category: string }) => request<BackendShoppingItem>(`/shopping-lists/${listId}/items`, { method: 'POST', body: JSON.stringify(payload) }),
  addPurchasedToPantry: (listId: string) => request<BackendPantryItem[]>(`/shopping-lists/${listId}/add-purchased-to-pantry`, { method: 'POST' }),
  generatePlan: (payload: Record<string, unknown>) => request<BackendPlan>('/meal-plans/generate', { method: 'POST', body: JSON.stringify(payload) }),
  listPlans: () => request<BackendPlan[]>('/meal-plans'),
  getPlan: (id: string) => request<BackendPlanDetail>(`/meal-plans/${id}`),
  replacePlanRecipe: (planId: string, occurrenceId: string, recipeId: string, expectedPlanVersion: number, ignoreNutritionTolerances = false) => request<BackendPlanDetail>(`/meal-plans/${planId}/occurrences/${occurrenceId}/recipe`, { method: 'PUT', body: JSON.stringify({ recipe_id: recipeId, expected_plan_version: expectedPlanVersion, ignore_nutrition_tolerances: ignoreNutritionTolerances }) }),
  acceptPlan: (id: string) => request<BackendPlan>(`/meal-plans/${id}/accept`, { method: 'POST' }),
  markBatchCooked: (planId: string, batchId: string) => request<void>(`/meal-plans/${planId}/batches/${batchId}/cooked`, { method: 'POST' }),
  buildShoppingList: (planId: string) => request<BackendShoppingList>('/shopping-lists/build', { method: 'POST', body: JSON.stringify({ meal_plan_id: planId, name: 'Current shopping list' }) }),
  backupStatus: () => request<BackendBackupStatus>('/system/backups'),
  createBackup: () => request<BackendBackupStatus>('/system/backups', { method: 'POST' })
}

export const isDemoMode = import.meta.env.VITE_DEMO_MODE !== 'false'

export type BackendMealType = 'breakfast' | 'lunch' | 'dinner' | 'snack'

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
    preparation?: string
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
}

export interface DiscoveryResponse {
  results: DiscoveryResult[]
  sources: Array<{ source: string; error_code?: string; error_message?: string }>
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

export interface BackendPantryItem {
  id: string
  display_name: string
  initial_quantity: number
  unit: string
  expires_on?: string
  always_have: boolean
  on_hand_quantity: number
  reserved_quantity: number
  usable_quantity: number
  version: number
}

export interface BackendShoppingItem {
  id: string
  display_name: string
  exact_quantity: number
  purchase_quantity: number
  unit: string
  category: string
  checked: boolean
  manual: boolean
  version: number
}

export interface BackendShoppingList {
  id: string
  name: string
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
    recipe_id: string
    recipe_title: string
    source_url?: string
    batch_servings: number
    planned_cook_date?: string
    nutrition_per_serving?: Record<string, number>
    cooked_at?: string
    portions: Array<{ member_id: string; servings: number }>
  }>
  daily_nutrition?: Array<{
    meal_date: string
    totals: Record<string, number>
    members: Array<{ member_id: string; totals: Record<string, number> }>
  }>
}
