import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  activeShoppingList: vi.fn(),
  addShoppingItem: vi.fn(),
  addPurchasedToPantry: vi.fn(),
  me: vi.fn(),
  patchShoppingItem: vi.fn(),
  itemMutations: [] as Array<Record<string, unknown>>,
  removeShoppingItemMutation: vi.fn(),
  saveShoppingItemMutation: vi.fn(),
}))

vi.mock('../lib/offlineShopping', async importOriginal => ({
  ...await importOriginal<typeof import('../lib/offlineShopping')>(),
  loadOfflineShoppingContext: () => null,
  loadShoppingItemMutations: async () => mocks.itemMutations,
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
      addShoppingItem: mocks.addShoppingItem,
      addPurchasedToPantry: mocks.addPurchasedToPantry,
      me: mocks.me,
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
    mocks.itemMutations = []
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
    mocks.me.mockResolvedValue({ id: 'user-1', username: 'shopper' })
    mocks.addShoppingItem.mockImplementation(async (_listId: string, payload: { display_name: string }) => ({
      ...shoppingItem(1),
      id: 'manual-server-1',
      display_name: payload.display_name,
      exact_quantity: 1,
      purchase_quantity: 1,
      exact_quantity_display: '1',
      purchase_quantity_display: '1',
      unit: 'count',
      category: 'Other',
      manual: true,
    }))
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

  it('keeps an authentication-paused manual addition stopped until explicit retry', async () => {
    mocks.itemMutations = [{
      id: 'list-1:manual:operation-1',
      kind: 'manual_add',
      listId: 'list-1',
      operationId: 'operation-1',
      localItemId: 'manual:operation-1',
      displayName: 'Oat milk',
      exactQuantity: 1,
      purchaseQuantity: 1,
      unit: 'count',
      category: 'Other',
      createdAt: 1,
      attempts: 1,
      status: 'auth_paused',
      lastError: 'Sign in required',
    }]
    const user = userEvent.setup()
    render(<ShoppingPage />)

    const recovery = await screen.findByRole('group', { name: 'Recovery options for Add “Oat milk”' })
    expect(mocks.addShoppingItem).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Add purchased to pantry' })).toBeDisabled()

    await user.click(within(recovery).getByRole('button', { name: 'Retry' }))

    await waitFor(() => expect(mocks.me).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(mocks.addShoppingItem).toHaveBeenCalledWith('list-1', expect.objectContaining({
      display_name: 'Oat milk',
      operation_id: 'operation-1',
    })))
    await waitFor(() => expect(screen.queryByText('Shopping edits need attention')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Add purchased to pantry' })).toBeEnabled()
  })

  it('discards an exhausted checked-state edit and restores its server baseline', async () => {
    mocks.itemMutations = [{
      id: 'list-1:flour:checked',
      kind: 'checked',
      listId: 'list-1',
      itemId: 'flour',
      operationId: 'operation-2',
      expectedVersion: 1,
      baseChecked: false,
      desiredChecked: true,
      createdAt: 1,
      attempts: 5,
      status: 'failed',
      lastError: 'Server unavailable',
    }]
    const user = userEvent.setup()
    render(<ShoppingPage />)

    const checkbox = await screen.findByRole('checkbox', { name: 'Mark Flour not collected' })
    expect(checkbox).toBeChecked()
    const recovery = screen.getByRole('group', { name: 'Recovery options for Mark “Flour” as collected' })
    await user.click(within(recovery).getByRole('button', { name: 'Discard local edit' }))

    await waitFor(() => expect(mocks.removeShoppingItemMutation).toHaveBeenCalledWith('list-1:flour:checked'))
    expect(screen.getByRole('checkbox', { name: 'Mark Flour collected' })).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Add purchased to pantry' })).toBeEnabled()
  })
})
