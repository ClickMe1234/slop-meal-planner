import { describe, expect, it } from 'vitest'
import type { BackendSavedFood } from '../api/client'
import { filterSavedFoods } from './IngredientsPage'

const savedFood = (id: string, displayName: string): BackendSavedFood => ({
  id,
  display_name: displayName,
  food_record_id: `record-${id}`,
  provider: 'user',
  provider_record_id: `provider-${id}`,
  dataset_version: 'test',
  basis_amount: 100,
  basis_unit: 'g',
  nutrients: {
    energy_kcal: 100,
    protein_g: 5,
    carbohydrate_g: 12,
    fat_g: 3,
  },
  warnings: [],
  planner_enabled: false,
  meal_types: [],
  version: 1,
})

describe('IngredientsPage household library', () => {
  it('filters the already-loaded household library without waiting for a remote search', () => {
    const foods = [savedFood('greek-yoghurt', 'Greek yoghurt'), savedFood('beans', 'Baked beans')]

    expect(filterSavedFoods(foods, '  GREEK  ')).toEqual([foods[0]])
    expect(filterSavedFoods(foods, '')).toEqual(foods)
  })
})
