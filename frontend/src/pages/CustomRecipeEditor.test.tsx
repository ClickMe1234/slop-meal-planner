import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, type BackendFoodLookup, type BackendRecipeDetail, type BackendRecipeNutritionPreviewRequest, type BackendSavedFood } from '../api/client'
import { CustomRecipePage } from './CustomRecipeEditor'

vi.mock('../api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/client')>()
  return { ...original, isDemoMode: false }
})

afterEach(() => vi.restoreAllMocks())

const chickpeas: BackendFoodLookup = {
  provider: 'open_food_facts',
  provider_record_id: 'off-123',
  name: 'Chickpeas in water',
  brand: 'Tinned Co',
  barcode: '5012345678900',
  basis_amount: 100,
  basis_unit: 'g',
  nutrients: { energy_kcal: 84, protein_g: 4.9, carbohydrate_g: 11.8, fat_g: 1.5 },
  complete: true,
  package_amount: 400,
  package_unit: 'g',
  package_description: '400 g can',
  serving_amount: 120,
  serving_unit: 'g',
  serving_description: '120 g drained serving',
  warnings: [],
}

const butterBeans: BackendFoodLookup = {
  ...chickpeas,
  provider_record_id: 'off-456',
  name: 'Butter beans in water',
  barcode: '5012345678999',
  package_amount: 240,
  package_description: '240 g can',
}

function previewFor(request: BackendRecipeNutritionPreviewRequest) {
  const row = request.ingredients[0]
  const resolved = Boolean(row?.food_record_id && row.nutrition_basis_amount_per_unit && row.nutrition_basis_unit)
  return {
    complete: resolved,
    yield_servings: request.yield_servings,
    batch_values: resolved ? { energy_kcal: 672, protein_g: 39.2, carbohydrate_g: 94.4, fat_g: 12 } : {},
    per_serving_values: resolved ? { energy_kcal: 168, protein_g: 9.8, carbohydrate_g: 23.6, fat_g: 3 } : {},
    issues: resolved ? [] : [{ code: 'missing_match', message: 'Choose a nutrition record.', client_id: row?.client_id }],
    ingredients: row ? [{
      client_id: row.client_id,
      status: resolved ? 'resolved' : 'missing_match',
      food_record_id: row.food_record_id ?? undefined,
      formula: resolved ? '2 cans × 400 g/can × 84 kcal/100 g = 672 kcal batch ÷ 4 servings = 168 kcal/serving' : undefined,
      contribution: resolved ? { energy_kcal: 672, protein_g: 39.2, carbohydrate_g: 94.4, fat_g: 12 } : {},
      conversion_options: [],
    }] : [],
  }
}

function renderEditor() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><CustomRecipePage /></MemoryRouter></QueryClientProvider>)
}

describe('CustomRecipePage', () => {
  it('confirms a package conversion, shows the formula, and preserves cans in the save payload', async () => {
    const user = userEvent.setup()
    const preview = vi.spyOn(api, 'previewRecipeNutrition').mockImplementation(async (request) => previewFor(request))
    vi.spyOn(api, 'searchFoods').mockResolvedValue({ items: [], total: 0 })
    vi.spyOn(api, 'searchPackagedFoods').mockResolvedValue({ items: [chickpeas], page: 1, has_more: false })
    vi.spyOn(api, 'createSavedFood').mockResolvedValue({ food_record_id: 'saved-chickpeas', display_name: chickpeas.name } as BackendSavedFood)
    const create = vi.spyOn(api, 'createRecipe').mockResolvedValue({ id: 'custom-1', version: 1 } as BackendRecipeDetail)
    renderEditor()

    await user.type(screen.getByRole('textbox', { name: 'Recipe title' }), 'Chickpea stew')
    await user.type(screen.getByRole('textbox', { name: 'Ingredient as written 1' }), 'Chickpeas')
    await user.type(screen.getByRole('spinbutton', { name: 'Amount for Chickpeas' }), '2')
    const unit = screen.getByRole('combobox', { name: 'Unit for Chickpeas' })
    await user.clear(unit)
    await user.type(unit, 'can')

    await user.click(screen.getByRole('button', { name: 'Find nutrition' }))
    await user.clear(screen.getByRole('textbox', { name: /search nutrition for chickpeas/i }))
    await user.type(screen.getByRole('textbox', { name: /search nutrition for chickpeas/i }), 'chickpeas')
    await user.click(screen.getByRole('button', { name: /^search$/i }))
    await user.click(await screen.findByRole('button', { name: /chickpeas in water/i }))

    expect(await screen.findByRole('heading', { name: /confirm can equivalent/i })).toBeInTheDocument()
    expect(screen.getByRole('spinbutton', { name: 'Equivalent amount for one can' })).toHaveValue(400)
    await user.click(screen.getByRole('button', { name: 'Confirm equivalent' }))

    expect(await screen.findByText(/2 cans × 400 g\/can/i)).toBeInTheDocument()
    expect(screen.getAllByText('Complete nutrition').length).toBeGreaterThan(0)
    await user.click(screen.getAllByRole('button', { name: 'Save recipe' })[0])

    await waitFor(() => expect(create).toHaveBeenCalledOnce())
    expect(create.mock.calls[0][0]).toMatchObject({
      source_type: 'custom',
      yield_servings: 4,
      ingredients: [expect.objectContaining({
        quantity: 2,
        unit: 'can',
        food_record_id: 'saved-chickpeas',
        nutrition_input_unit: 'can',
        nutrition_basis_amount_per_unit: 400,
        nutrition_basis_unit: 'g',
        nutrition_conversion_source: 'package',
      })],
    })
    expect(preview).toHaveBeenCalled()
  })

  it('saves an incomplete new recipe as a draft without pretending it is complete', async () => {
    const user = userEvent.setup()
    const create = vi.spyOn(api, 'createRecipe').mockResolvedValue({ id: 'draft-1', version: 1 } as BackendRecipeDetail)
    renderEditor()

    await user.type(screen.getByRole('textbox', { name: 'Recipe title' }), 'Unfinished soup')
    expect(screen.getAllByText('Known so far').length).toBeGreaterThan(0)
    await user.click(screen.getAllByRole('button', { name: 'Save as draft' })[0])

    await waitFor(() => expect(create).toHaveBeenCalledOnce())
    expect(create.mock.calls[0][0]).toMatchObject({
      source_type: 'custom',
      title: 'Unfinished soup',
      ingredients: [],
    })
    expect((await screen.findAllByText(/draft saved/i)).length).toBeGreaterThan(0)
  })

  it('does not reuse a previous product mapping after choosing another product', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'previewRecipeNutrition').mockImplementation(async (request) => previewFor(request))
    vi.spyOn(api, 'searchFoods').mockResolvedValue({ items: [], total: 0 })
    vi.spyOn(api, 'searchPackagedFoods').mockResolvedValue({ items: [chickpeas, butterBeans], page: 1, has_more: false })
    vi.spyOn(api, 'createSavedFood')
      .mockResolvedValueOnce({ food_record_id: 'saved-chickpeas', display_name: chickpeas.name } as BackendSavedFood)
      .mockResolvedValueOnce({ food_record_id: 'saved-butter-beans', display_name: butterBeans.name } as BackendSavedFood)
    renderEditor()

    await user.type(screen.getByRole('textbox', { name: 'Ingredient as written 1' }), 'Beans')
    await user.type(screen.getByRole('spinbutton', { name: 'Amount for Beans' }), '2')
    const unit = screen.getByRole('combobox', { name: 'Unit for Beans' })
    await user.clear(unit)
    await user.type(unit, 'can')

    await user.click(screen.getByRole('button', { name: 'Find nutrition' }))
    await user.clear(screen.getByRole('textbox', { name: /search nutrition for beans/i }))
    await user.type(screen.getByRole('textbox', { name: /search nutrition for beans/i }), 'beans')
    await user.click(screen.getByRole('button', { name: /^search$/i }))
    await user.click(await screen.findByRole('button', { name: /chickpeas in water/i }))
    await user.click(screen.getByRole('button', { name: 'Confirm equivalent' }))

    await user.click(screen.getByRole('button', { name: 'Change nutrition' }))
    await user.clear(screen.getByRole('textbox', { name: /search nutrition for beans/i }))
    await user.type(screen.getByRole('textbox', { name: /search nutrition for beans/i }), 'beans')
    await user.click(screen.getByRole('button', { name: /^search$/i }))
    await user.click(await screen.findByRole('button', { name: /butter beans in water/i }))

    expect(await screen.findByRole('heading', { name: /confirm can equivalent/i })).toBeInTheDocument()
    expect(screen.getByRole('spinbutton', { name: 'Equivalent amount for one can' })).toHaveValue(240)
  })
})
