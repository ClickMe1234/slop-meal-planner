import type { BackendPlanDetail } from '../api/client'
import type { Nutrition } from '../types'

export const MEAL_TYPES = ['breakfast', 'lunch', 'dinner', 'snack'] as const

export type MealType = typeof MEAL_TYPES[number]
export type AttendanceOverrides = Record<string, boolean>
export type CookStarts = Record<string, boolean>

export function compareMealTypes(left: string, right: string): number {
  const leftIndex = MEAL_TYPES.indexOf(left as MealType)
  const rightIndex = MEAL_TYPES.indexOf(right as MealType)
  return (leftIndex === -1 ? MEAL_TYPES.length : leftIndex)
    - (rightIndex === -1 ? MEAL_TYPES.length : rightIndex)
}

export interface PlannerDate {
  iso: string
  weekday: string
  shortDate: string
}

export interface PlannerSlot {
  meal_date: string
  meal_type: MealType
  participant_member_ids: string[]
  batch_key: string
  food_safety_acknowledged: boolean
}

export interface IngredientChoice {
  id: string
  term: string
  name: string
}

export type IngredientGuidance = Record<'must' | 'prefer' | 'exclude', IngredientChoice[]>

export const emptyIngredientGuidance = (): IngredientGuidance => ({
  must: [],
  prefer: [],
  exclude: [],
})

export function capitalise(value: string): string {
  return value ? `${value[0].toUpperCase()}${value.slice(1)}` : value
}

export function addDays(isoDate: string, amount: number): string {
  const [year, month, day] = isoDate.split('-').map(Number)
  const value = new Date(Date.UTC(year, month - 1, day))
  value.setUTCDate(value.getUTCDate() + amount)
  return value.toISOString().slice(0, 10)
}

export function plannerDates(startDate: string, days: number): PlannerDate[] {
  if (!startDate || days < 1) return []
  return Array.from({ length: days }, (_, index) => {
    const iso = addDays(startDate, index)
    const value = new Date(`${iso}T12:00:00`)
    return {
      iso,
      weekday: value.toLocaleDateString(undefined, { weekday: 'short' }),
      shortDate: value.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }),
    }
  })
}

export function attendanceKey(date: string, mealType: MealType, memberId: string): string {
  return `${date}:${mealType}:${memberId}`
}

export function cookStartKey(date: string, mealType: MealType): string {
  return `${date}:${mealType}`
}

export function isAttending(
  overrides: AttendanceOverrides,
  date: string,
  mealType: MealType,
  memberId: string,
): boolean {
  return overrides[attendanceKey(date, mealType, memberId)] ?? true
}

export function participantsFor(
  overrides: AttendanceOverrides,
  date: string,
  mealType: MealType,
  selectedMemberIds: string[],
): string[] {
  return selectedMemberIds.filter(memberId => isAttending(overrides, date, mealType, memberId))
}

export function firstPlannedDate(
  dates: PlannerDate[],
  mealType: MealType,
  selectedMemberIds: string[],
  attendance: AttendanceOverrides,
): string | undefined {
  return dates.find(date => participantsFor(attendance, date.iso, mealType, selectedMemberIds).length > 0)?.iso
}

export function buildPlanSlots({
  dates,
  selectedMemberIds,
  attendance,
  cookStarts,
  foodSafetyAcknowledged,
}: {
  dates: PlannerDate[]
  selectedMemberIds: string[]
  attendance: AttendanceOverrides
  cookStarts: CookStarts
  foodSafetyAcknowledged: boolean
}): PlannerSlot[] {
  const slots: PlannerSlot[] = []

  for (const mealType of MEAL_TYPES) {
    let batchKey = ''
    for (const date of dates) {
      const participants = participantsFor(attendance, date.iso, mealType, selectedMemberIds)
      if (!participants.length) continue
      if (!batchKey || cookStarts[cookStartKey(date.iso, mealType)]) {
        batchKey = `${mealType}-${date.iso}`
      }
      slots.push({
        meal_date: date.iso,
        meal_type: mealType,
        participant_member_ids: participants,
        batch_key: batchKey,
        food_safety_acknowledged: foodSafetyAcknowledged,
      })
    }
  }

  return slots.sort((left, right) => left.meal_date.localeCompare(right.meal_date)
    || compareMealTypes(left.meal_type, right.meal_type))
}

export function hasLongBatch(slots: PlannerSlot[]): boolean {
  const batches = new Map<string, string[]>()
  for (const slot of slots) {
    const dates = batches.get(slot.batch_key) ?? []
    dates.push(slot.meal_date)
    batches.set(slot.batch_key, dates)
  }
  return [...batches.values()].some(dates => {
    const ordered = [...dates].sort()
    const start = new Date(`${ordered[0]}T12:00:00`).getTime()
    const end = new Date(`${ordered.at(-1)}T12:00:00`).getTime()
    return end - start > 2 * 24 * 60 * 60 * 1000
  })
}

export function batchCount(slots: PlannerSlot[]): number {
  return new Set(slots.map(slot => slot.batch_key)).size
}

export function formatDateRange(dates: PlannerDate[]): string {
  if (!dates.length) return 'No dates selected'
  if (dates.length === 1) return dates[0].shortDate
  return `${dates[0].shortDate} – ${dates.at(-1)?.shortDate}`
}

function nutritionValue(values: Record<string, number> | undefined, ...keys: string[]): number {
  for (const key of keys) {
    const value = Number(values?.[key])
    if (Number.isFinite(value)) return value
  }
  return 0
}

export function occurrenceServings(occurrence: BackendPlanDetail['occurrences'][number]): number {
  return occurrence.portions.reduce((sum, portion) => sum + Number(portion.servings || 0), 0)
}

export function totalNutrition(occurrences: BackendPlanDetail['occurrences']): Nutrition {
  return occurrences.reduce<Nutrition>((total, occurrence) => {
    const servings = occurrenceServings(occurrence)
    const values = occurrence.nutrition_per_serving
    return {
      calories: total.calories + nutritionValue(values, 'energy_kcal', 'calories') * servings,
      protein: total.protein + nutritionValue(values, 'protein_g', 'protein') * servings,
      carbs: total.carbs + nutritionValue(values, 'carbohydrate_g', 'carbs_g', 'carbs') * servings,
      fat: total.fat + nutritionValue(values, 'fat_g', 'fat') * servings,
      basis: 'recipe_total',
    }
  }, { calories: 0, protein: 0, carbs: 0, fat: 0, basis: 'recipe_total' })
}

export function memberNutritionTotals(occurrences: BackendPlanDetail['occurrences']): Array<{ memberId: string; nutrition: Nutrition }> {
  const totals = new Map<string, Nutrition>()
  for (const occurrence of occurrences) {
    const values = occurrence.nutrition_per_serving
    for (const portion of occurrence.portions) {
      const servings = Number(portion.servings || 0)
      const current = totals.get(portion.member_id) ?? { calories: 0, protein: 0, carbs: 0, fat: 0, basis: 'recipe_total' as const }
      totals.set(portion.member_id, {
        calories: current.calories + nutritionValue(values, 'energy_kcal', 'calories') * servings,
        protein: current.protein + nutritionValue(values, 'protein_g', 'protein') * servings,
        carbs: current.carbs + nutritionValue(values, 'carbohydrate_g', 'carbs_g', 'carbs') * servings,
        fat: current.fat + nutritionValue(values, 'fat_g', 'fat') * servings,
        basis: 'recipe_total',
      })
    }
  }
  return Array.from(totals, ([memberId, nutrition]) => ({ memberId, nutrition }))
}

const demoPlanStorageKey = 'savour-demo-plan'

export function storeDemoPlan(plan: BackendPlanDetail): void {
  sessionStorage.setItem(demoPlanStorageKey, JSON.stringify(plan))
}

export function readDemoPlan(): BackendPlanDetail | null {
  try {
    const stored = sessionStorage.getItem(demoPlanStorageKey)
    return stored ? JSON.parse(stored) as BackendPlanDetail : null
  } catch {
    return null
  }
}
