export type PlanEditGuestDraft = { count: number; mealTypes: string[]; mealGroups?: Record<string, string> }
export type PlanEditBoostDraft = {
  calories: string
  mealAllocations: Array<{ meal_type: string; percentage: number }>
}
export type PlanEditRecipeSelection = {
  recipeId: string
  recipeTitle: string
}
export type PlanEditCookDaySelection = PlanEditRecipeSelection & {
  mealDate: string
  mealType: string
  mealGroupKey?: string
}

export interface PlanEditDraft {
  planVersion: number
  removedDates: string[]
  guests: Record<string, PlanEditGuestDraft>
  boosts: Record<string, PlanEditBoostDraft>
  addedCookDays: Record<string, PlanEditCookDaySelection>
  removedCookDays: string[]
  recipeSwaps: Record<string, PlanEditRecipeSelection>
  mainSlots?: Array<{
    meal_date: string
    meal_type: string
    meal_group_key: string
    participant_member_ids: string[]
    batch_key: string
    food_safety_acknowledged: boolean
  }>
}

const storageKey = (planId: string) => `slop-plan-edit:${planId}`

export function readPlanEditDraft(planId: string): PlanEditDraft | null {
  try {
    const stored = sessionStorage.getItem(storageKey(planId))
    return stored ? JSON.parse(stored) as PlanEditDraft : null
  } catch {
    return null
  }
}

export function writePlanEditDraft(planId: string, draft: PlanEditDraft): void {
  sessionStorage.setItem(storageKey(planId), JSON.stringify(draft))
}

export function clearPlanEditDraft(planId: string): void {
  sessionStorage.removeItem(storageKey(planId))
}
