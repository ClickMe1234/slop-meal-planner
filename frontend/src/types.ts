export type ThemeChoice = 'light' | 'dark' | 'system'
export type MealKind = 'Breakfast' | 'Lunch' | 'Dinner' | 'Snack'
export type NutritionBasis = 'per_serving' | 'per_100g' | 'recipe_total'
export type RecipeState = 'ready' | 'source_estimate' | 'no_nutrition' | 'needs_review' | 'calculating'

export interface Nutrition {
  calories: number
  protein: number
  carbs: number
  fat: number
  basis: NutritionBasis
}

export interface Recipe {
  id: string
  title: string
  source: string
  sourceUrl: string
  imageUrl?: string
  yield?: number
  nutrition?: Nutrition
  nutritionSource?: 'publisher' | 'calculated'
  publisherNutrition?: Nutrition
  state: RecipeState
  mealKinds: MealKind[]
  reviewCount?: number
  ingredients?: string[]
}

export interface PlannedMeal {
  id: string
  kind: MealKind
  title: string
  source: string
  portions: number
  nutrition: Nutrition
  batchLabel?: string
  locked?: boolean
}

export interface DayPlan {
  date: string
  day: string
  shortDate: string
  meals: PlannedMeal[]
  targetCalories: number
}

export interface PantryItem {
  id: string
  name: string
  quantity: number
  unit: string
  reserved: number
  category: string
  expires?: string
  staple?: boolean
}

export interface ShoppingItem {
  id: string
  name: string
  buy: string
  exact: string
  pantryUsed?: string
  category: string
  checked: boolean
  manual?: boolean
  updatedAt: number
}

export interface JobStatus {
  id: string
  status: 'queued' | 'running' | 'awaiting_review' | 'succeeded' | 'failed'
  stage?: string
  progress?: number
  detail?: string
  result?: { recipe_id?: string; recipe_version_id?: string; review_reasons?: string[] }
  error_detail?: string
}
