import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, type BackendRecipeDetail } from '../api/client'
import { ImportReviewPage } from './ImportPages'

vi.mock('../api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/client')>()
  return { ...original, isDemoMode: false }
})

afterEach(() => vi.restoreAllMocks())

const customRecipe: BackendRecipeDetail = {
  id: 'protein-smoothie',
  title: 'Protein smoothie V2',
  eligibility: 'planner_ready',
  source_type: 'custom',
  version: 2,
  yield_servings: 1,
  calculated_nutrition: {
    energy_kcal: 273,
    protein_g: 38,
    carbohydrate_g: 15,
    fat_g: 4,
  },
  nutrition_method: 'complete',
  meal_types: ['breakfast', 'snack', 'side'],
  planner_eligible: true,
  planner_warnings: [],
  recipe_version_id: 'version-2',
  version_number: 2,
  ingredients: [{
    id: 'ingredient-1',
    original_text: 'impact protein powder',
    quantity: 30,
    unit: 'g',
    quantity_grams: 30,
    food_phrase: 'impact protein powder',
    included: true,
    optional: false,
    needs_review: false,
    shopping_excluded: false,
  }],
}

describe('live import review nutrition', () => {
  it('prefills calculated custom-recipe nutrition and identifies its source', async () => {
    vi.spyOn(api, 'getRecipe').mockResolvedValue(customRecipe)

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/recipes/protein-smoothie/review']}>
          <Routes>
            <Route path="/recipes/:recipeId/review" element={<ImportReviewPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('spinbutton', { name: 'Calories per serving' })).toHaveValue(273)
    expect(screen.getByRole('spinbutton', { name: 'Protein per serving' })).toHaveValue(38)
    expect(screen.getByRole('spinbutton', { name: 'Carbohydrates per serving' })).toHaveValue(15)
    expect(screen.getByRole('spinbutton', { name: 'Fat per serving' })).toHaveValue(4)
    expect(screen.getByText('Nutrition calculated from ingredients · per serving')).toBeInTheDocument()
    expect(screen.getByText(/update the ingredient matches or quantities to recalculate/i)).toBeInTheDocument()
    expect(screen.getByRole('spinbutton', { name: 'Calories per serving' })).toBeDisabled()
  })
})
