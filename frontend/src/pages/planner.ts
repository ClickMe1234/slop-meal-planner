import type { BackendPlanDetail } from '../api/client'
import type { Nutrition } from '../types'

export const MEAL_TYPES = ['breakfast', 'lunch', 'dinner', 'snack'] as const

export type MealType = typeof MEAL_TYPES[number]
export type AttendanceOverrides = Record<string, boolean>
export type CookStarts = Record<string, boolean>
export type CalorieBoosts = Record<string, number>
export type CalorieBoostMealShares = Record<string, number>
export type GuestCounts = Record<string, number>
export type GuestMeals = Record<string, boolean>
export type GuestMealGroups = Record<string, string>

export interface PlannerMealGroup {
  group_key: string
  member_ids: string[]
}

export type MealGroupDefaults = Record<MealType, PlannerMealGroup[]>
export type MealGroupOverrides = Record<string, PlannerMealGroup[]>

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
  meal_group_key?: string
  participant_member_ids: string[]
  batch_key: string
  food_safety_acknowledged: boolean
}

export interface IngredientChoice {
  id: string
  term: string
  name: string
  recipes?: Array<{ id: string; title: string }>
}

export type IngredientGuidance = Record<'must' | 'prefer' | 'exclude', IngredientChoice[]>

export interface PlannerSetup {
  startDate: string
  days: number
  selectedMemberIds: string[]
  attendance: AttendanceOverrides
  cookStarts: CookStarts
  foodSafetyAcknowledged: boolean
  calorieBoosts: CalorieBoosts
  calorieBoostShares: CalorieBoostMealShares
  guestCounts: GuestCounts
  guestMeals: GuestMeals
  guestMealGroups: GuestMealGroups
  mealGroupOverrides: MealGroupOverrides
  ingredientGuidance: IngredientGuidance
}

export const emptyIngredientGuidance = (): IngredientGuidance => ({
  must: [],
  prefer: [],
  exclude: [],
})

export function plannerSetupFromPlan(detail: BackendPlanDetail): PlannerSetup {
  const main = detail.occurrences.filter(item => item.component_slot === 0)
  const selectedMemberIds = Array.from(new Set(
    main.flatMap(item => item.portions.map(portion => portion.member_id)),
  ))
  const dates = plannerDates(
    detail.plan.start_date,
    Math.max(1, Math.round((
      new Date(`${detail.plan.end_date}T12:00:00`).getTime()
      - new Date(`${detail.plan.start_date}T12:00:00`).getTime()
    ) / (24 * 60 * 60 * 1000)) + 1),
  )
  const attendance: AttendanceOverrides = {}
  const mealGroupOverrides: MealGroupOverrides = {}
  for (const date of dates) {
    for (const mealType of MEAL_TYPES) {
      const matching = main.filter(item => item.meal_date === date.iso && item.meal_type === mealType)
      for (const memberId of selectedMemberIds) {
        if (!matching.some(occurrence => occurrence.portions.some(portion => portion.member_id === memberId))) {
          attendance[attendanceKey(date.iso, mealType, memberId)] = false
        }
      }
      if (matching.length) {
        mealGroupOverrides[mealGroupOverrideKey(date.iso, mealType)] = matching.map(occurrence => ({
          group_key: occurrence.meal_group_key ?? 'shared',
          member_ids: occurrence.portions.map(portion => portion.member_id),
        }))
      }
    }
  }
  const batchDates = new Map<string, { mealType: MealType; mealGroupKey: string; dates: string[] }>()
  for (const occurrence of main) {
    if (!MEAL_TYPES.includes(occurrence.meal_type as MealType)) continue
    const batch = batchDates.get(occurrence.batch_id) ?? {
      mealType: occurrence.meal_type as MealType,
      mealGroupKey: occurrence.meal_group_key ?? 'shared',
      dates: [],
    }
    batch.dates.push(occurrence.meal_date)
    batchDates.set(occurrence.batch_id, batch)
  }
  const cookStarts: CookStarts = {}
  let foodSafetyAcknowledged = false
  for (const batch of batchDates.values()) {
    const ordered = [...batch.dates].sort()
    cookStarts[cookStartKey(ordered[0], batch.mealType, batch.mealGroupKey)] = true
    const start = new Date(`${ordered[0]}T12:00:00`).getTime()
    const end = new Date(`${ordered.at(-1)}T12:00:00`).getTime()
    if (end - start > 2 * 24 * 60 * 60 * 1000) foodSafetyAcknowledged = true
  }
  const calorieBoosts: CalorieBoosts = {}
  const calorieBoostShares: CalorieBoostMealShares = {}
  for (const boost of detail.plan.calorie_boosts ?? []) {
    calorieBoosts[calorieBoostKey(boost.meal_date, boost.member_id)] = Number(boost.calories)
    for (const allocation of boost.meal_allocations ?? []) {
      if (MEAL_TYPES.includes(allocation.meal_type as MealType)) {
        calorieBoostShares[calorieBoostMealKey(boost.meal_date, boost.member_id, allocation.meal_type as MealType)] = allocation.percentage
      }
    }
  }
  const guestCounts: GuestCounts = {}
  const guestMeals: GuestMeals = {}
  const guestMealGroups: GuestMealGroups = {}
  for (const day of detail.plan.guest_days ?? []) {
    guestCounts[day.meal_date] = day.guest_count
    for (const mealType of day.meal_types ?? []) {
      if (MEAL_TYPES.includes(mealType as MealType)) {
        guestMeals[guestMealKey(day.meal_date, mealType as MealType)] = true
      }
    }
    for (const assignment of day.meal_groups ?? []) {
      if (MEAL_TYPES.includes(assignment.meal_type as MealType)) {
        guestMeals[guestMealKey(day.meal_date, assignment.meal_type as MealType)] = true
        guestMealGroups[guestMealKey(day.meal_date, assignment.meal_type as MealType)] = assignment.meal_group_key
      }
    }
  }
  const diagnostic = detail.plan.diagnostics.find(item => item.code === 'GENERATION_GUIDANCE') ?? {}
  const guidance = (key: string): IngredientChoice[] => (
    Array.isArray(diagnostic[key]) ? diagnostic[key] : []
  ).filter((value): value is string => typeof value === 'string').map(term => ({
    id: `restored:${term}`,
    term,
    name: capitalise(term),
  }))
  return {
    startDate: detail.plan.start_date,
    days: dates.length,
    selectedMemberIds,
    attendance,
    cookStarts,
    foodSafetyAcknowledged,
    calorieBoosts,
    calorieBoostShares,
    guestCounts,
    guestMeals,
    guestMealGroups,
    mealGroupOverrides,
    ingredientGuidance: {
      must: guidance('must_use_ingredient_terms'),
      prefer: guidance('prefer_ingredient_terms'),
      exclude: guidance('exclude_ingredient_terms'),
    },
  }
}

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

export function cookStartKey(date: string, mealType: MealType, mealGroupKey = 'shared'): string {
  return mealGroupKey === 'shared' ? `${date}:${mealType}` : `${date}:${mealType}:${mealGroupKey}`
}

export function calorieBoostKey(date: string, memberId: string): string {
  return `${date}:${memberId}`
}

export function calorieBoostMealKey(date: string, memberId: string, mealType: MealType): string {
  return `${date}:${memberId}:${mealType}`
}

export function guestMealKey(date: string, mealType: MealType): string {
  return `${date}:${mealType}`
}

export function mealGroupOverrideKey(date: string, mealType: MealType): string {
  return `${date}:${mealType}`
}

export function mealGroupsFor(
  defaults: MealGroupDefaults | undefined,
  overrides: MealGroupOverrides,
  date: string,
  mealType: MealType,
  participants: string[],
): PlannerMealGroup[] {
  const configured = overrides[mealGroupOverrideKey(date, mealType)] ?? defaults?.[mealType] ?? [{ group_key: 'shared', member_ids: participants }]
  const attending = new Set(participants)
  const groups = configured.map(group => ({
    group_key: group.group_key,
    member_ids: group.member_ids.filter(memberId => attending.has(memberId)),
  })).filter(group => group.member_ids.length)
  const assigned = new Set(groups.flatMap(group => group.member_ids))
  const missing = participants.filter(memberId => !assigned.has(memberId))
  if (!groups.length) return participants.length ? [{ group_key: 'shared', member_ids: participants }] : []
  if (missing.length) groups[0] = { ...groups[0], member_ids: [...groups[0].member_ids, ...missing] }
  return groups
}

export function editableMealGroupsFor(
  defaults: MealGroupDefaults | undefined,
  overrides: MealGroupOverrides,
  date: string,
  mealType: MealType,
  participants: string[],
): PlannerMealGroup[] {
  if (!participants.length) return []
  const configured = overrides[mealGroupOverrideKey(date, mealType)]
  if (!configured) return mealGroupsFor(defaults, overrides, date, mealType, participants)

  const attending = new Set(participants)
  const groups = configured.slice(0, participants.length).map(group => ({
    ...group,
    member_ids: group.member_ids.filter(memberId => attending.has(memberId)),
  }))
  if (!groups.length) return [{ group_key: 'shared', member_ids: participants }]

  const assigned = new Set(groups.flatMap(group => group.member_ids))
  const missing = participants.filter(memberId => !assigned.has(memberId))
  if (missing.length) groups[0].member_ids.push(...missing)
  return groups
}

export function defaultBoostShares(mealTypes: MealType[]): Record<MealType, number> {
  const result = Object.fromEntries(MEAL_TYPES.map(mealType => [mealType, 0])) as Record<MealType, number>
  const focus = mealTypes.includes('snack') ? 'snack' : mealTypes.at(-1)
  if (focus) result[focus] = 100
  return result
}

export function boostSharesFor(
  date: string,
  memberId: string,
  mealTypes: MealType[],
  shares: CalorieBoostMealShares,
): Record<MealType, number> {
  const stored = Object.fromEntries(MEAL_TYPES.map(mealType => [
    mealType,
    mealTypes.includes(mealType) ? Number(shares[calorieBoostMealKey(date, memberId, mealType)] ?? 0) : 0,
  ])) as Record<MealType, number>
  const total = Object.values(stored).reduce((sum, value) => sum + Math.max(0, value), 0)
  if (!total) return defaultBoostShares(mealTypes)
  const normalised = Object.fromEntries(MEAL_TYPES.map(mealType => [
    mealType,
    mealTypes.includes(mealType) ? Math.round(Math.max(0, stored[mealType]) * 100 / total) : 0,
  ])) as Record<MealType, number>
  const difference = 100 - Object.values(normalised).reduce((sum, value) => sum + value, 0)
  const adjustmentMeal = [...mealTypes].sort((left, right) => normalised[right] - normalised[left])[0]
  if (adjustmentMeal) normalised[adjustmentMeal] += difference
  return normalised
}

export function rebalanceBoostShares(
  current: Record<MealType, number>,
  changedMeal: MealType,
  nextValue: number,
  activeMeals: MealType[],
): Record<MealType, number> {
  const result = { ...current }
  const bounded = Math.max(0, Math.min(100, Math.round(nextValue)))
  const delta = bounded - (result[changedMeal] ?? 0)
  result[changedMeal] = bounded
  const others = activeMeals.filter(mealType => mealType !== changedMeal)
  if (delta > 0) {
    let remaining = delta
    for (const mealType of [...others].sort((left, right) => result[right] - result[left])) {
      const amount = Math.min(result[mealType], remaining)
      result[mealType] -= amount
      remaining -= amount
    }
  } else if (delta < 0 && others.length) {
    const recipient = others.includes('snack') ? 'snack' : others.at(-1) as MealType
    result[recipient] += -delta
  }
  return result
}

export function calorieBoostEntries(
  dates: PlannerDate[],
  memberIds: string[],
  boosts: CalorieBoosts,
  shares: CalorieBoostMealShares = {},
  slots: PlannerSlot[] = [],
): Array<{ meal_date: string; member_id: string; calories: number; meal_allocations: Array<{ meal_type: MealType; percentage: number }> }> {
  return dates.flatMap(date => memberIds.flatMap(memberId => {
    const calories = Number(boosts[calorieBoostKey(date.iso, memberId)] ?? 0)
    const mealTypes = MEAL_TYPES.filter(mealType => slots.some(slot => slot.meal_date === date.iso && slot.meal_type === mealType && slot.participant_member_ids.includes(memberId)))
    const allocation = boostSharesFor(date.iso, memberId, mealTypes, shares)
    return Number.isFinite(calories) && calories > 0
      ? [{
          meal_date: date.iso,
          member_id: memberId,
          calories,
          meal_allocations: mealTypes.map(mealType => ({ meal_type: mealType, percentage: allocation[mealType] })).filter(item => item.percentage > 0),
        }]
      : []
  }))
}

export function guestDayEntries(
  dates: PlannerDate[],
  guests: GuestCounts,
  guestMeals: GuestMeals = {},
  slots: PlannerSlot[] = [],
  guestMealGroups: GuestMealGroups = {},
): Array<{ meal_date: string; guest_count: number; meal_types: MealType[]; meal_groups?: Array<{ meal_type: MealType; meal_group_key: string }> }> {
  return dates.flatMap(date => {
    const guestCount = Math.floor(Number(guests[date.iso] ?? 0))
    const plannedMeals = MEAL_TYPES.filter(mealType => slots.some(slot => slot.meal_date === date.iso && slot.meal_type === mealType))
    const explicitlySelected = plannedMeals.filter(mealType => guestMeals[guestMealKey(date.iso, mealType)])
    const mealTypes = explicitlySelected.length
      ? explicitlySelected
      : plannedMeals.includes('dinner') ? ['dinner' as MealType] : plannedMeals.slice(0, 1)
    return Number.isFinite(guestCount) && guestCount > 0
      ? (() => {
          const mealGroupAssignments = mealTypes.map(mealType => {
            const matching = slots.filter(slot => slot.meal_date === date.iso && slot.meal_type === mealType)
            const selected = matching.find(slot => (slot.meal_group_key ?? 'shared') === guestMealGroups[guestMealKey(date.iso, mealType)])
              ?? [...matching].sort((left, right) => right.participant_member_ids.length - left.participant_member_ids.length)[0]
            return { meal_type: mealType, meal_group_key: selected?.meal_group_key ?? 'shared' }
          })
          const hasSplitMeal = mealTypes.some(mealType => slots.filter(slot => slot.meal_date === date.iso && slot.meal_type === mealType).length > 1)
          return [{
          meal_date: date.iso,
          guest_count: guestCount,
          meal_types: mealTypes,
          ...(hasSplitMeal ? { meal_groups: mealGroupAssignments } : {}),
        }]
        })()
      : []
  })
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
  mealGroupDefaults,
  mealGroupOverrides = {},
}: {
  dates: PlannerDate[]
  selectedMemberIds: string[]
  attendance: AttendanceOverrides
  cookStarts: CookStarts
  foodSafetyAcknowledged: boolean
  mealGroupDefaults?: MealGroupDefaults
  mealGroupOverrides?: MealGroupOverrides
}): PlannerSlot[] {
  const slots: PlannerSlot[] = []

  for (const mealType of MEAL_TYPES) {
    const batchKeys: Record<string, string> = {}
    let previousGroupKeys = new Set<string>()
    for (const date of dates) {
      const participants = participantsFor(attendance, date.iso, mealType, selectedMemberIds)
      const groups = mealGroupsFor(mealGroupDefaults, mealGroupOverrides, date.iso, mealType, participants)
      for (const group of groups) {
        // A recipe lane cannot reuse a batch across a day where that lane was
        // not needed. Its first day after every gap is always a fresh cook.
        if (!batchKeys[group.group_key]
          || !previousGroupKeys.has(group.group_key)
          || cookStarts[cookStartKey(date.iso, mealType, group.group_key)]) {
          batchKeys[group.group_key] = group.group_key === 'shared'
            ? `${mealType}-${date.iso}`
            : `${mealType}-${group.group_key}-${date.iso}`
        }
        slots.push({
          meal_date: date.iso,
          meal_type: mealType,
          meal_group_key: group.group_key,
          participant_member_ids: group.member_ids,
          batch_key: batchKeys[group.group_key],
          food_safety_acknowledged: foodSafetyAcknowledged,
        })
      }
      previousGroupKeys = new Set(groups.map(group => group.group_key))
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
    + Number(occurrence.guest_servings || 0)
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

const demoPlanStorageKey = 'slop-demo-plan'

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
