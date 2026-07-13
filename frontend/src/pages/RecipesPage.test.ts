import { describe, expect, it } from 'vitest'
import type { BackendRecipeDetail } from '../api/client'
import { importedRecipeNeedsReview, savedRecipePlanningBadge } from './RecipesPage'

describe('saved recipe planning status', () => {
  it('does not claim a tagged recipe is usable until its recipe data is ready', () => {
    expect(savedRecipePlanningBadge({ state: 'no_nutrition', mealKinds: ['Dinner'] })).toEqual({
      tone: 'warning',
      label: 'Needs recipe review',
    })
  })

  it('requires both ready recipe data and at least one meal type', () => {
    expect(savedRecipePlanningBadge({ state: 'ready', mealKinds: [] }).tone).toBe('warning')
    expect(savedRecipePlanningBadge({ state: 'ready', mealKinds: ['Breakfast'] })).toEqual({
      tone: 'green',
      label: 'Used for planning',
    })
  })
})

describe('import review routing', () => {
  const recipe = (ingredient: Partial<BackendRecipeDetail['ingredients'][number]>): BackendRecipeDetail => ({
    id: 'recipe',
    title: 'Soup',
    eligibility: 'planner_ready',
    source_type: 'url',
    version: 1,
    yield_servings: 4,
    meal_types: [],
    planner_eligible: false,
    planner_warnings: [],
    recipe_version_id: 'version',
    version_number: 1,
    ingredients: [{
      id: 'ingredient',
      original_text: '2 onions',
      quantity: 2,
      unit: 'item',
      included: true,
      optional: false,
      needs_review: false,
      shopping_excluded: false,
      ...ingredient,
    }],
  })

  it('skips review when all included ingredients have shopping quantities', () => {
    expect(importedRecipeNeedsReview(recipe({}))).toBe(false)
  })

  it('opens review for missing quantities unless the ingredient is excluded from shopping', () => {
    expect(importedRecipeNeedsReview(recipe({ quantity: undefined, unit: undefined }))).toBe(true)
    expect(importedRecipeNeedsReview(recipe({ quantity: undefined, unit: undefined, shopping_excluded: true }))).toBe(false)
  })
})
