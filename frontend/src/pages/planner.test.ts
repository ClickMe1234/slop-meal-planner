import { describe, expect, it } from 'vitest'
import type { BackendPlanDetail } from '../api/client'
import {
  attendanceKey,
  buildPlanSlots,
  calorieBoostEntries,
  calorieBoostKey,
  calorieBoostMealKey,
  boostSharesFor,
  compareMealTypes,
  cookStartKey,
  hasLongBatch,
  guestDayEntries,
  guestMealKey,
  rebalanceBoostShares,
  memberNutritionTotals,
  plannerDates,
  totalNutrition,
  plannerSetupFromPlan,
} from './planner'

describe('planner helpers', () => {
  it('reconstructs editable setup values from a generated plan', () => {
    const setup = plannerSetupFromPlan({
      plan: {
        id: 'plan',
        name: 'Existing week',
        start_date: '2026-08-03',
        end_date: '2026-08-06',
        status: 'accepted',
        version: 3,
        diagnostics: [{
          code: 'GENERATION_GUIDANCE',
          must_use_ingredient_terms: ['spinach'],
          prefer_ingredient_terms: ['beans'],
          exclude_ingredient_terms: ['peanuts'],
        }],
        calorie_boosts: [{
          meal_date: '2026-08-03',
          member_id: 'alex',
          calories: 400,
          meal_allocations: [{ meal_type: 'dinner', percentage: 100 }],
        }],
        guest_days: [{ meal_date: '2026-08-04', guest_count: 2, meal_types: ['dinner'] }],
      },
      occurrences: [
        { id: 'one', meal_date: '2026-08-03', meal_type: 'dinner', batch_id: 'batch-a', component_slot: 0, recipe_id: 'a', recipe_title: 'A', batch_servings: 2, portions: [{ member_id: 'alex', servings: 1 }, { member_id: 'sam', servings: 1 }] },
        { id: 'two', meal_date: '2026-08-04', meal_type: 'dinner', batch_id: 'batch-a', component_slot: 0, recipe_id: 'a', recipe_title: 'A', batch_servings: 2, portions: [{ member_id: 'alex', servings: 1 }] },
        { id: 'three', meal_date: '2026-08-06', meal_type: 'dinner', batch_id: 'batch-a', component_slot: 0, recipe_id: 'a', recipe_title: 'A', batch_servings: 2, portions: [{ member_id: 'alex', servings: 1 }] },
      ],
    })

    expect(setup.startDate).toBe('2026-08-03')
    expect(setup.days).toBe(4)
    expect(setup.selectedMemberIds).toEqual(['alex', 'sam'])
    expect(setup.attendance['2026-08-04:dinner:sam']).toBe(false)
    expect(setup.cookStarts['2026-08-03:dinner']).toBe(true)
    expect(setup.foodSafetyAcknowledged).toBe(true)
    expect(setup.calorieBoosts['2026-08-03:alex']).toBe(400)
    expect(setup.guestCounts['2026-08-04']).toBe(2)
    expect(setup.ingredientGuidance.must[0].term).toBe('spinach')
  })
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
    const slots = [{ meal_date: '2026-07-13', meal_type: 'dinner' as const, participant_member_ids: ['alex'], batch_key: 'dinner', food_safety_acknowledged: false }, { meal_date: '2026-07-13', meal_type: 'snack' as const, participant_member_ids: ['alex'], batch_key: 'snack', food_safety_acknowledged: false }]
    expect(calorieBoostEntries(dates, ['alex'], {
      [calorieBoostKey('2026-07-13', 'alex')]: 1400,
      [calorieBoostKey('2026-07-14', 'alex')]: 0,
      [calorieBoostKey('2026-07-15', 'alex')]: 900,
    }, { [calorieBoostMealKey('2026-07-13', 'alex', 'snack')]: 100 }, slots)).toEqual([{ meal_date: '2026-07-13', member_id: 'alex', calories: 1400, meal_allocations: [{ meal_type: 'snack', percentage: 100 }] }])
    expect(guestDayEntries(dates, { '2026-07-13': 2, '2026-07-14': 0 }, { [guestMealKey('2026-07-13', 'dinner')]: true }, slots)).toEqual([
      { meal_date: '2026-07-13', guest_count: 2, meal_types: ['dinner'] },
    ])
  })
  it('keeps calorie boost sliders balanced to 100 percent', () => {
    const initial = boostSharesFor('2026-07-13', 'alex', ['dinner', 'snack'], {})
    expect(initial).toMatchObject({ dinner: 0, snack: 100 })
    expect(rebalanceBoostShares(initial, 'dinner', 40, ['dinner', 'snack'])).toMatchObject({ dinner: 40, snack: 60 })
    expect(boostSharesFor('2026-07-13', 'alex', ['dinner'], {
      [calorieBoostMealKey('2026-07-13', 'alex', 'dinner')]: 40,
      [calorieBoostMealKey('2026-07-13', 'alex', 'snack')]: 60,
    })).toMatchObject({ dinner: 100, snack: 0 })
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

  it('builds separate recipe slots from defaults and applies a dated regrouping override', () => {
    const dates = plannerDates('2026-07-13', 2)
    const slots = buildPlanSlots({
      dates,
      selectedMemberIds: ['alex', 'sam'],
      attendance: {},
      cookStarts: {},
      foodSafetyAcknowledged: false,
      mealGroupDefaults: {
        breakfast: [{ group_key: 'shared', member_ids: ['alex', 'sam'] }],
        lunch: [{ group_key: 'alex', member_ids: ['alex'] }, { group_key: 'sam', member_ids: ['sam'] }],
        dinner: [{ group_key: 'shared', member_ids: ['alex', 'sam'] }],
        snack: [{ group_key: 'shared', member_ids: ['alex', 'sam'] }],
      },
      mealGroupOverrides: {
        '2026-07-14:lunch': [{ group_key: 'together', member_ids: ['alex', 'sam'] }],
      },
    })
    const lunches = slots.filter(slot => slot.meal_type === 'lunch')

    expect(lunches.map(slot => [slot.meal_date, slot.meal_group_key, slot.participant_member_ids, slot.batch_key])).toEqual([
      ['2026-07-13', 'alex', ['alex'], 'lunch-alex-2026-07-13'],
      ['2026-07-13', 'sam', ['sam'], 'lunch-sam-2026-07-13'],
      ['2026-07-14', 'together', ['alex', 'sam'], 'lunch-together-2026-07-14'],
    ])
  })

  it('records which split meal group guests join', () => {
    const dates = plannerDates('2026-07-13', 1)
    const slots = buildPlanSlots({
      dates,
      selectedMemberIds: ['alex', 'sam'],
      attendance: {},
      cookStarts: {},
      foodSafetyAcknowledged: false,
      mealGroupOverrides: {
        '2026-07-13:dinner': [{ group_key: 'alex', member_ids: ['alex'] }, { group_key: 'sam', member_ids: ['sam'] }],
      },
    })

    expect(guestDayEntries(
      dates,
      { '2026-07-13': 2 },
      { [guestMealKey('2026-07-13', 'dinner')]: true },
      slots,
      { [guestMealKey('2026-07-13', 'dinner')]: 'sam' },
    )).toEqual([{
      meal_date: '2026-07-13',
      guest_count: 2,
      meal_types: ['dinner'],
      meal_groups: [{ meal_type: 'dinner', meal_group_key: 'sam' }],
    }])
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
