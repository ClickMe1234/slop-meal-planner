import { describe, expect, it } from 'vitest'
import type { BackendPlanDetail } from '../api/client'
import {
  attendanceKey,
  buildPlanSlots,
  calorieBoostEntries,
  calorieBoostKey,
  compareMealTypes,
  cookStartKey,
  hasLongBatch,
  guestDayEntries,
  memberNutritionTotals,
  plannerDates,
  totalNutrition,
} from './planner'

describe('planner helpers', () => {
  it('orders meal types consistently for display', () => {
    expect(['breakfast', 'dinner', 'lunch', 'snack'].sort(compareMealTypes)).toEqual([
      'breakfast',
      'lunch',
      'dinner',
      'snack',
    ])
  })
  it('serialises only positive in-range day adjustments', () => {
    const dates = plannerDates('2026-07-13', 2)
    expect(calorieBoostEntries(dates, ['alex'], {
      [calorieBoostKey('2026-07-13', 'alex')]: 1400,
      [calorieBoostKey('2026-07-14', 'alex')]: 0,
      [calorieBoostKey('2026-07-15', 'alex')]: 900,
    })).toEqual([{ meal_date: '2026-07-13', member_id: 'alex', calories: 1400 }])
    expect(guestDayEntries(dates, { '2026-07-13': 2, '2026-07-14': 0 })).toEqual([
      { meal_date: '2026-07-13', guest_count: 2 },
    ])
  })
  it('builds dated attendance slots and starts a new recipe only on selected cook days', () => {
    const dates = plannerDates('2026-07-13', 4)
    const slots = buildPlanSlots({
      dates,
      selectedMemberIds: ['alex', 'sam'],
      attendance: {
        [attendanceKey('2026-07-14', 'lunch', 'sam')]: false,
        [attendanceKey('2026-07-16', 'lunch', 'alex')]: false,
      },
      cookStarts: { [cookStartKey('2026-07-15', 'lunch')]: true },
      foodSafetyAcknowledged: false,
    })
    const lunches = slots.filter(slot => slot.meal_type === 'lunch')

    expect(lunches.map(slot => [slot.meal_date, slot.participant_member_ids, slot.batch_key])).toEqual([
      ['2026-07-13', ['alex', 'sam'], 'lunch-2026-07-13'],
      ['2026-07-14', ['alex'], 'lunch-2026-07-13'],
      ['2026-07-15', ['alex', 'sam'], 'lunch-2026-07-15'],
      ['2026-07-16', ['sam'], 'lunch-2026-07-15'],
    ])
  })

  it('flags batches spanning more than 48 hours', () => {
    const slots = buildPlanSlots({
      dates: plannerDates('2026-07-13', 4),
      selectedMemberIds: ['alex'],
      attendance: {},
      cookStarts: {},
      foodSafetyAcknowledged: false,
    })

    expect(hasLongBatch(slots)).toBe(true)
    expect(hasLongBatch(slots.filter(slot => slot.meal_date !== '2026-07-16'))).toBe(false)
  })

  it('totals calories and macros using every assigned portion', () => {
    const occurrences = [{
      id: 'occurrence',
      meal_date: '2026-07-13',
      meal_type: 'lunch',
      batch_id: 'batch',
      component_slot: 0,
      recipe_id: 'recipe',
      recipe_title: 'Lunch',
      batch_servings: 3,
      nutrition_per_serving: { energy_kcal: 500, protein_g: 30, carbohydrate_g: 40, fat_g: 15 },
      portions: [{ member_id: 'alex', servings: 1 }, { member_id: 'sam', servings: 0.5 }],
    }] satisfies BackendPlanDetail['occurrences']

    expect(totalNutrition(occurrences)).toEqual({
      calories: 750,
      protein: 45,
      carbs: 60,
      fat: 22.5,
      basis: 'recipe_total',
    })
  })

  it('keeps each household member nutrition total separate', () => {
    const occurrences = [{
      id: 'occurrence',
      meal_date: '2026-07-13',
      meal_type: 'lunch',
      batch_id: 'batch',
      component_slot: 0,
      recipe_id: 'recipe',
      recipe_title: 'Lunch',
      batch_servings: 1.5,
      nutrition_per_serving: { energy_kcal: 500, protein_g: 30, carbohydrate_g: 40, fat_g: 15 },
      portions: [{ member_id: 'alex', servings: 1 }, { member_id: 'sam', servings: 0.5 }],
    }] satisfies BackendPlanDetail['occurrences']

    expect(memberNutritionTotals(occurrences)).toEqual([
      { memberId: 'alex', nutrition: { calories: 500, protein: 30, carbs: 40, fat: 15, basis: 'recipe_total' } },
      { memberId: 'sam', nutrition: { calories: 250, protein: 15, carbs: 20, fat: 7.5, basis: 'recipe_total' } },
    ])
  })
})
