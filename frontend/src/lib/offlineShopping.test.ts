import { beforeEach, describe, expect, it } from 'vitest'
import {
  loadOfflineShoppingContext,
  loadShoppingNameMutations,
  queueShoppingNameMutation,
  removeShoppingNameMutation,
  saveOfflineShoppingContext,
  saveShoppingNameMutation,
  shoppingAsText,
} from './offlineShopping'
import type { ShoppingItem } from '../types'

const item = (id: string, category: string, checked = false): ShoppingItem => ({
  id,
  name: `Item ${id}`,
  buy: '2 packs',
  exact: '1.5 packs required',
  category,
  checked,
  updatedAt: 1
})

describe('shoppingAsText', () => {
  it('groups outstanding items and omits completed items', () => {
    const text = shoppingAsText([item('a', 'Cupboard'), item('b', 'Produce'), item('c', 'Cupboard', true)])
    expect(text).toContain('Cupboard')
    expect(text).toContain('□ Item a — 2 packs')
    expect(text).toContain('Produce')
    expect(text).not.toContain('Item c')
  })
})

describe('offline shopping name edits', () => {
  beforeEach(() => localStorage.clear())

  it('coalesces repeated edits while preserving the original compare-and-set name', async () => {
    const first = await queueShoppingNameMutation({
      listId: 'list',
      itemId: 'item',
      baseDisplayName: 'courgettes',
      desiredDisplayName: 'courgette',
    })
    const second = await queueShoppingNameMutation({
      listId: 'list',
      itemId: 'item',
      baseDisplayName: 'courgette',
      desiredDisplayName: 'garden courgette',
    })

    expect(second.id).toBe(first.id)
    expect(second.baseDisplayName).toBe('courgettes')
    expect(second.desiredDisplayName).toBe('garden courgette')
    expect(await loadShoppingNameMutations()).toEqual([second])
  })

  it('persists conflicts and removes them after a resolution', async () => {
    const mutation = await queueShoppingNameMutation({
      listId: 'list',
      itemId: 'item',
      baseDisplayName: 'mint',
      desiredDisplayName: 'garden mint',
    })
    const conflict = {
      ...mutation,
      status: 'conflict' as const,
      serverDisplayName: 'fresh mint',
    }
    await saveShoppingNameMutation(conflict)
    expect(await loadShoppingNameMutations()).toEqual([conflict])

    await removeShoppingNameMutation(mutation.id)
    expect(await loadShoppingNameMutations()).toEqual([])
  })

  it('keeps the active list context available when a page starts offline', () => {
    saveOfflineShoppingContext({
      listId: 'list',
      mealPlanId: 'plan',
      rebuildRecommended: true,
    })
    expect(loadOfflineShoppingContext()).toEqual({
      listId: 'list',
      mealPlanId: 'plan',
      rebuildRecommended: true,
    })
  })
})
