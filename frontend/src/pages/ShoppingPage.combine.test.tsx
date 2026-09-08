import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

vi.mock('../lib/offlineShopping', async importOriginal => ({
  ...await importOriginal<typeof import('../lib/offlineShopping')>(),
  loadOfflineShoppingContext: () => null,
  loadShoppingItems: async <T,>(seed: T) => seed,
  loadShoppingNameMutations: async () => [],
  saveOfflineShoppingContext: vi.fn(),
  saveShoppingItems: async () => undefined,
}))

vi.mock('../api/client', async importOriginal => {
  const original = await importOriginal<typeof import('../api/client')>()
  return {
    ...original,
    isDemoMode: false,
    api: {
      ...original.api,
      activeShoppingList: vi.fn(async () => ({
        id: 'list-1',
        meal_plan_id: 'plan-1',
        name: 'Current shopping list',
        active: true,
        rebuild_recommended: false,
        version: 3,
        items: [
          { id: 'chicken', display_name: 'Chicken thighs', exact_quantity: 1000, purchase_quantity: 1000, exact_quantity_display: '1 kg', purchase_quantity_display: '1 kg', unit: 'g', category: 'Meat & fish', checked: false, manual: false, source_count: 2, recipe_count: 2, version: 1 },
          { id: 'rice', display_name: 'Rice', exact_quantity: 500, purchase_quantity: 500, exact_quantity_display: '500 g', purchase_quantity_display: '500 g', unit: 'g', category: 'Cupboard', checked: false, manual: false, source_count: 1, recipe_count: 1, version: 1 },
          { id: 'milk', display_name: 'Milk', exact_quantity: 1, purchase_quantity: 1, exact_quantity_display: '1 item', purchase_quantity_display: '1 item', unit: 'item', category: 'Other', checked: false, manual: true, source_count: 0, recipe_count: 0, version: 1 },
        ],
      })),
    },
  }
})

import { ShoppingPage } from './ShoppingPage'

function CombineDestination() {
  const location = useLocation()
  return <div>{location.pathname}{location.search}</div>
}

describe('ShoppingPage combine shortcuts', () => {
  beforeEach(() => localStorage.clear())

  it('opens the combine page with the selected recipe-backed item', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/shopping']}><Routes>
      <Route path="/shopping" element={<ShoppingPage/>}/>
      <Route path="/shopping/:listId/ingredient-change" element={<CombineDestination/>}/>
    </Routes></MemoryRouter>)

    const chicken = await screen.findByRole('link', { name: 'Combine Chicken thighs with another item' })
    expect(screen.getByRole('link', { name: 'Combine Rice with another item' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Combine Milk with another item' })).not.toBeInTheDocument()

    await user.click(chicken)
    expect(screen.getByText('/shopping/list-1/ingredient-change?mode=combine&items=chicken')).toBeInTheDocument()
  })
})
