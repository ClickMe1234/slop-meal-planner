import { describe, expect, it } from 'vitest'
import { compactNutrition, initialRecipeImportUrl, nutritionFormValues, nutritionReviewPayload } from './ImportPages'

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

describe('nutritionReviewPayload', () => {
  it('clears nutrition when every review field is blank', () => {
    expect(nutritionReviewPayload({
      energy_kcal: '',
      protein_g: '',
      carbohydrate_g: '',
      fat_g: '',
      fibre_g: '',
    })).toBeNull()
  })

  it('normalises editable values as per-serving nutrition', () => {
    expect(nutritionReviewPayload({
      energy_kcal: '475',
      protein_g: '32.5',
      carbohydrate_g: '41',
      fat_g: '17',
      fibre_g: '',
    })).toEqual({
      basis: 'per serving',
      energy_kcal: 475,
      protein_g: 32.5,
      carbohydrate_g: 41,
      fat_g: 17,
      fibre_g: null,
    })
  })
})

describe('nutritionFormValues', () => {
  it('leaves per-100g and per-100ml source values blank for serving review', () => {
    const sourceValues = {
      basis: 'per 100 g',
      energy_kcal: 468,
      protein_g: 16,
      carbohydrate_g: 44,
      fat_g: 24,
      fibre_g: 7,
    }

    expect(nutritionFormValues(sourceValues)).toEqual({
      energy_kcal: '',
      protein_g: '',
      carbohydrate_g: '',
      fat_g: '',
      fibre_g: '',
    })
    expect(nutritionFormValues({ ...sourceValues, basis: 'per 100ml' })).toEqual({
      energy_kcal: '',
      protein_g: '',
      carbohydrate_g: '',
      fat_g: '',
      fibre_g: '',
    })
  })

  it('prefills source values reported per serving', () => {
    expect(nutritionFormValues({
      basis: 'per serving',
      energy_kcal: 468,
      protein_g: 16,
      carbohydrate_g: 44,
      fat_g: 24,
    })).toMatchObject({
      energy_kcal: '468',
      protein_g: '16',
      carbohydrate_g: '44',
      fat_g: '24',
    })
  })
})
