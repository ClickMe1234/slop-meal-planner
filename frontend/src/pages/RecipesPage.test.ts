import { describe, expect, it } from 'vitest'
import { savedRecipePlanningBadge } from './RecipesPage'

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
