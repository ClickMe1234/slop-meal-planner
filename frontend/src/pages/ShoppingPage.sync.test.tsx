import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  activeShoppingList: vi.fn(),
  addPurchasedToPantry: vi.fn(),
  patchShoppingItem: vi.fn(),
  removeShoppingItemMutation: vi.fn(),
  saveShoppingItemMutation: vi.fn(),
}))

vi.mock('../lib/offlineShopping', async importOriginal => ({
  ...await importOriginal<typeof import('../lib/offlineShopping')>(),
  loadOfflineShoppingContext: () => null,
  loadShoppingItemMutations: async () => [],
  loadShoppingItems: async <T,>(seed: T) => seed,
  loadShoppingNameMutations: async () => [],
  queueShoppingItemMutation: async (mutation: Record<string, unknown>) => ({
    ...mutation,
    createdAt: Date.now(),
    attempts: 0,
    status: 'pending',
  }),
  removeShoppingItemMutation: mocks.removeShoppingItemMutation,
  saveOfflineShoppingContext: vi.fn(),
  saveShoppingItemMutation: mocks.saveShoppingItemMutation,
  saveShoppingItems: async () => undefined,
}))

vi.mock('../api/client', async importOriginal => {
  const original = await importOriginal<typeof import('../api/client')>()
  return {
    ...original,
    isDemoMode: false,
    api: {
      ...original.api,
      activeShoppingList: mocks.activeShoppingList,
      addPurchasedToPantry: mocks.addPurchasedToPantry,
      patchShoppingItem: mocks.patchShoppingItem,
    },
  }
})

import { ShoppingPage } from './ShoppingPage'

function shoppingItem(version: number, checked = false, unit = 'g') {
  return {
    id: 'flour',
    display_name: 'Flour',
    exact_quantity: unit === 'kg' ? 1 : 1000,
    purchase_quantity: unit === 'kg' ? 1 : 1000,
    exact_quantity_display: unit === 'kg' ? '1 kg' : '1 kg',
    purchase_quantity_display: unit === 'kg' ? '1 kg' : '1 kg',
    unit,
    available_units: ['g', 'kg'],
    quantity_options: [
      { unit: 'g', exact_quantity: 1000, purchase_quantity: 1000, exact_quantity_display: '1 kg', purchase_quantity_display: '1 kg', approximate: false },
      { unit: 'kg', exact_quantity: 1, purchase_quantity: 1, exact_quantity_display: '1 kg', purchase_quantity_display: '1 kg', approximate: false },
    ],
    category: 'Cupboard',
    checked,
    manual: false,
    source_count: 0,
    recipe_count: 0,
    version,
  }
}

describe('ShoppingPage synchronization', () => {
  let itemVersion: number
  let listVersion: number
  let checked: boolean
  let unit: string

  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
    itemVersion = 1
    listVersion = 3
    checked = false
    unit = 'g'
    mocks.activeShoppingList.mockImplementation(async () => ({
      id: 'list-1',
      meal_plan_id: 'plan-1',
      name: 'Current shopping list',
      active: true,
      rebuild_recommended: false,
      version: listVersion,
      items: [shoppingItem(itemVersion, checked, unit)],
    }))
    mocks.patchShoppingItem.mockImplementation(async (_listId: string, _itemId: string, payload: { checked?: boolean; display_unit?: string }) => {
      if (payload.checked !== undefined) checked = payload.checked
      if (payload.display_unit !== undefined) unit = payload.display_unit
      itemVersion += 1
      listVersion += 1
      return shoppingItem(itemVersion, checked, unit)
    })
    mocks.addPurchasedToPantry.mockResolvedValue([])
  })

  it('refreshes the authoritative list version before purchase intake', async () => {
    const user = userEvent.setup()
    render(<ShoppingPage />)

    await user.click(await screen.findByRole('checkbox', { name: 'Mark Flour collected' }))
    await waitFor(() => expect(mocks.patchShoppingItem).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(mocks.activeShoppingList).toHaveBeenCalledTimes(2))

    await user.click(screen.getByRole('button', { name: 'Add purchased to pantry' }))

    await waitFor(() => expect(mocks.addPurchasedToPantry).toHaveBeenCalledWith('list-1', expect.objectContaining({
      expected_list_version: 4,
    })))
  })

  it('rebases a second offline item edit onto the version returned by the first', async () => {
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false })
    const user = userEvent.setup()
    render(<ShoppingPage />)

    await user.click(await screen.findByRole('checkbox', { name: 'Mark Flour collected' }))
    const unitControls = screen.getByLabelText('Display unit for Flour')
    await user.click(within(unitControls).getByRole('button', { name: 'kg' }))
    expect(mocks.patchShoppingItem).not.toHaveBeenCalled()

    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
    window.dispatchEvent(new Event('online'))

    await waitFor(() => expect(mocks.patchShoppingItem).toHaveBeenCalledTimes(2))
    expect(mocks.patchShoppingItem.mock.calls.map(call => call[2].expected_version)).toEqual([1, 2])
    expect(mocks.patchShoppingItem.mock.calls[0][2]).toEqual(expect.objectContaining({ checked: true }))
    expect(mocks.patchShoppingItem.mock.calls[1][2]).toEqual(expect.objectContaining({ display_unit: 'kg' }))
    expect(mocks.saveShoppingItemMutation).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'unit',
      expectedVersion: 2,
    }))
  })
})
