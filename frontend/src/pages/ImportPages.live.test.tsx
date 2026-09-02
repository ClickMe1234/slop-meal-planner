import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

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

const publisherNutrition = {
  basis: 'per serving',
  energy_kcal: 412,
  protein_g: 18,
  carbohydrate_g: 50,
  fat_g: 10,
}

const importedRecipe: BackendRecipeDetail = {
  ...customRecipe,
  id: 'publisher-stew',
  title: 'Publisher stew',
  source_type: 'url',
  source_url: 'https://www.bbcgoodfood.com/recipes/publisher-stew',
  publisher: 'Good Food',
  version: 3,
  recipe_version_id: 'publisher-version-3',
  version_number: 3,
  publisher_nutrition: publisherNutrition,
  // This represents a legacy imported recipe. The publisher snapshot must
  // remain authoritative even if an old calculated value is still present.
  calculated_nutrition: { energy_kcal: 999, protein_g: 99, carbohydrate_g: 99, fat_g: 99 },
  nutrition_method: 'complete',
}

describe('live import review nutrition', () => {
  it('prefills calculated custom-recipe nutrition and identifies its source', async () => {
    vi.spyOn(api, 'getRecipe').mockResolvedValue(customRecipe)

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/recipes/protein-smoothie/review']}>
          <Routes>
            <Route path="/recipes/:recipeId/review" element={<ImportReviewPage />} />
            <Route path="/recipes" element={<div>Recipes</div>} />
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

  it('keeps publisher nutrition authoritative when saving a legacy URL import', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getRecipe').mockResolvedValue(importedRecipe)
    const save = vi.spyOn(api, 'saveRecipeReview').mockResolvedValue(importedRecipe)

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/recipes/publisher-stew/review']}>
          <Routes>
            <Route path="/recipes/:recipeId/review" element={<ImportReviewPage />} />
            <Route path="/recipes" element={<div>Recipes</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('spinbutton', { name: 'Calories per serving' })).toHaveValue(412)
    expect(screen.getByText('Nutrition from Good Food · per serving')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save recipe' }))

    await waitFor(() => expect(save).toHaveBeenCalledOnce())
    expect(save.mock.calls[0][1]).toMatchObject({ publisher_nutrition: publisherNutrition })
  })
})
