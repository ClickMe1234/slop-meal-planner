import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, type BackendFoodLookup, type BackendSavedFood } from '../api/client'
import { filterSavedFoods, LookupCard, PantryDialog } from './IngredientsPage'

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
  afterEach(() => vi.restoreAllMocks())

  it('filters the already-loaded household library without waiting for a remote search', () => {
    const foods = [savedFood('greek-yoghurt', 'Greek yoghurt'), savedFood('beans', 'Baked beans')]

    expect(filterSavedFoods(foods, '  GREEK  ')).toEqual([foods[0]])
    expect(filterSavedFoods(foods, '')).toEqual(foods)
  })

  it('gives Save the same pop-out treatment as Add to pantry and captures its animation origin', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    const food: BackendFoodLookup = {
      provider: 'open_food_facts',
      provider_record_id: 'product-1',
      name: 'Greek yoghurt',
      basis_amount: 100,
      basis_unit: 'g',
      nutrients: { energy_kcal: 100, protein_g: 5, carbohydrate_g: 12, fat_g: 3 },
      complete: true,
      warnings: [],
    }

    render(<LookupCard food={food} saving={false} onSave={onSave} onPantry={vi.fn()} />)
    const save = screen.getByRole('button', { name: 'Save' })
    const pantry = screen.getByRole('button', { name: 'Add to pantry' })
    expect(save).toHaveClass('button--primary')
    expect(pantry).toHaveClass('button--primary')

    await user.click(save)
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ x: expect.any(Number), y: expect.any(Number) }))
  })

  it('starts the pantry animation only after the quantity is added successfully', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'addPantry').mockResolvedValue({} as never)
    const onAdded = vi.fn()
    const onClose = vi.fn()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })

    render(
      <QueryClientProvider client={queryClient}>
        <PantryDialog target={{ foodRecordId: 'food-1', name: 'Greek yoghurt', basisUnit: 'g' }} onAdded={onAdded} onClose={onClose} />
      </QueryClientProvider>,
    )
    await user.click(screen.getByRole('button', { name: 'Add quantity' }))

    await waitFor(() => expect(onAdded).toHaveBeenCalledWith('Greek yoghurt', expect.objectContaining({ x: expect.any(Number), y: expect.any(Number) })))
    expect(onClose).toHaveBeenCalled()
  })
})
