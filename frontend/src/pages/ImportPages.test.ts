import { describe, expect, it } from 'vitest'
import { compactNutrition, initialRecipeImportUrl } from './ImportPages'

describe('compactNutrition', () => {
  it('starts recipe link imports with an empty URL', () => {
    expect(initialRecipeImportUrl).toBe('')
  })

  it('shows calories, carbs, fat and protein in the recipe search format', () => {
    expect(compactNutrition({
      energy_kcal: 100,
      carbohydrate_g: 8,
      fat_g: 10,
      protein_g: 13,
    })).toBe('Kc: 100, C: 8, F: 10, P: 13')
  })

  it('keeps incomplete nutrition records explicit and compact', () => {
    expect(compactNutrition({ energy_kcal: '95.25', protein_g: 4 })).toBe('Kc: 95.3, C: —, F: —, P: 4')
  })
})
