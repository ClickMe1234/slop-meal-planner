import 'fake-indexeddb/auto'
import { IDBFactory } from 'fake-indexeddb'
import { beforeEach, describe, expect, it } from 'vitest'
import {
  clearOfflineShoppingData,
  loadOfflineShoppingContext,
  loadShoppingItemMutations,
  loadShoppingItems,
  loadShoppingNameMutations,
  queueShoppingNameMutation,
  removeShoppingNameMutation,
  saveOfflineShoppingContext,
  saveShoppingItems,
  saveShoppingNameMutation,
  setOfflineShoppingScope,
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

const checkedMutation = (id: string, listId = 'list'): object => ({
  id: `${listId}:${id}:checked`,
  kind: 'checked',
  listId,
  itemId: id,
  operationId: `operation-${id}`,
  createdAt: 10,
  attempts: 0,
  status: 'pending',
  expectedVersion: 1,
  baseChecked: false,
  desiredChecked: true,
})

function createVersionTwoDatabase(items: ShoppingItem[], mutations: object[]): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('slop-offline', 2)
    request.onupgradeneeded = () => {
      request.result.createObjectStore('shopping', { keyPath: 'id' })
      request.result.createObjectStore('shoppingMutations', { keyPath: 'id' })
    }
    request.onsuccess = () => {
      const db = request.result
      const transaction = db.transaction(['shopping', 'shoppingMutations'], 'readwrite')
      items.forEach(value => transaction.objectStore('shopping').put(value))
      mutations.forEach(value => transaction.objectStore('shoppingMutations').put(value))
      transaction.oncomplete = () => {
        db.close()
        resolve()
      }
      transaction.onerror = () => reject(transaction.error)
    }
    request.onerror = () => reject(request.error)
  })
}

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
  beforeEach(() => {
    globalThis.indexedDB = new IDBFactory()
    localStorage.clear()
    setOfflineShoppingScope('test-user')
  })

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

  it('migrates version-two IndexedDB rows into the authenticated scope', async () => {
    const cachedItem = item('cached', 'Cupboard')
    const queuedMutation = {
      id: 'list:cached',
      listId: 'list',
      itemId: 'cached',
      baseDisplayName: 'beans',
      desiredDisplayName: 'baked beans',
      createdAt: 10,
      status: 'pending' as const,
    }
    const queuedItemMutation = checkedMutation('cached')
    await createVersionTwoDatabase([cachedItem], [queuedMutation, queuedItemMutation])

    setOfflineShoppingScope('user-upgrading')

    expect(await loadShoppingItems([])).toEqual([cachedItem])
    expect(await loadShoppingNameMutations()).toEqual([queuedMutation])
    expect(await loadShoppingItemMutations()).toEqual([queuedItemMutation])

    setOfflineShoppingScope('different-user')
    expect(await loadShoppingItems([])).toEqual([])
    expect(await loadShoppingNameMutations()).toEqual([])
    expect(await loadShoppingItemMutations()).toEqual([])
  })

  it('adopts version-two rows when the upgrade happens before authentication', async () => {
    setOfflineShoppingScope('anonymous')
    const cachedItem = item('before-auth', 'Cupboard')
    const queuedMutation = {
      id: 'list:before-auth',
      listId: 'list',
      itemId: 'before-auth',
      baseDisplayName: 'beans',
      desiredDisplayName: 'baked beans',
      createdAt: 10,
      status: 'pending' as const,
    }
    await createVersionTwoDatabase([cachedItem], [queuedMutation])

    // Trigger the application upgrade while no account scope is available;
    // the rows must remain recoverable for the account that signs in later.
    await loadShoppingItems([])

    setOfflineShoppingScope('authenticated-user')

    expect(await loadShoppingItems([])).toEqual([cachedItem])
    expect(await loadShoppingNameMutations()).toEqual([queuedMutation])
  })

  it('moves legacy localStorage cache, mutations, and context into the authenticated scope', async () => {
    const cachedItem = item('legacy', 'Produce')
    const queuedMutation = {
      id: 'list:legacy',
      listId: 'list',
      itemId: 'legacy',
      baseDisplayName: 'apple',
      desiredDisplayName: 'cooking apple',
      createdAt: 10,
      status: 'pending' as const,
    }
    const context = { listId: 'list', mealPlanId: 'plan', rebuildRecommended: true }
    localStorage.setItem('slop-shopping-fallback', JSON.stringify([cachedItem]))
    localStorage.setItem('slop-shopping-mutations-fallback', JSON.stringify([queuedMutation]))
    localStorage.setItem('slop-shopping-context', JSON.stringify(context))

    setOfflineShoppingScope('legacy-user')

    expect(await loadShoppingItems([])).toEqual([cachedItem])
    expect(await loadShoppingNameMutations()).toEqual([queuedMutation])
    expect(loadOfflineShoppingContext()).toEqual(context)
    expect(localStorage.getItem('slop-shopping-fallback')).toBeNull()
    expect(localStorage.getItem('slop-shopping-mutations-fallback')).toBeNull()
    expect(localStorage.getItem('slop-shopping-context')).toBeNull()
  })

  it('merges legacy localStorage rows with an existing scoped cache', async () => {
    const scopedItem = item('scoped', 'Cupboard')
    const legacyItem = item('legacy', 'Produce')
    const scopedMutation = {
      id: 'list:scoped',
      listId: 'list',
      itemId: 'scoped',
      baseDisplayName: 'beans',
      desiredDisplayName: 'baked beans',
      createdAt: 20,
      status: 'pending' as const,
    }
    const legacyMutation = {
      id: 'list:legacy',
      listId: 'list',
      itemId: 'legacy',
      baseDisplayName: 'apple',
      desiredDisplayName: 'cooking apple',
      createdAt: 10,
      status: 'pending' as const,
    }
    setOfflineShoppingScope('legacy-merge-user')
    await saveShoppingItems([scopedItem])
    await saveShoppingNameMutation(scopedMutation)
    setOfflineShoppingScope('anonymous')
    localStorage.setItem('slop-shopping-fallback', JSON.stringify([legacyItem]))
    localStorage.setItem('slop-shopping-mutations-fallback', JSON.stringify([legacyMutation]))

    setOfflineShoppingScope('legacy-merge-user')

    expect(await loadShoppingItems([])).toEqual([scopedItem, legacyItem])
    expect(await loadShoppingNameMutations()).toEqual([scopedMutation, legacyMutation])
    expect(localStorage.getItem('slop-shopping-fallback')).toBeNull()
    expect(localStorage.getItem('slop-shopping-mutations-fallback')).toBeNull()
  })

  it('removes stale rows, including an emptied list, without changing another account', async () => {
    setOfflineShoppingScope('user-a')
    await saveShoppingItems([item('keep', 'Cupboard'), item('remove', 'Produce')])
    setOfflineShoppingScope('user-b')
    await saveShoppingItems([item('keep', 'Frozen')])

    setOfflineShoppingScope('user-a')
    await saveShoppingItems([item('keep', 'Cupboard')])
    localStorage.removeItem('slop-shopping-fallback:user-a')
    expect(await loadShoppingItems([])).toEqual([item('keep', 'Cupboard')])

    await saveShoppingItems([])
    expect(await loadShoppingItems([item('resurrected', 'Other')])).toEqual([])
    localStorage.removeItem('slop-shopping-fallback:user-a')
    expect(await loadShoppingItems([])).toEqual([])

    setOfflineShoppingScope('user-b')
    localStorage.removeItem('slop-shopping-fallback:user-b')
    expect(await loadShoppingItems([])).toEqual([item('keep', 'Frozen')])
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

  it('keeps account data isolated while allowing the same account to resume edits', async () => {
    setOfflineShoppingScope('user-a')
    const userAMutation = await queueShoppingNameMutation({
      listId: 'list-a',
      itemId: 'item-a',
      baseDisplayName: 'mint',
      desiredDisplayName: 'garden mint',
    })
    await saveShoppingNameMutation({ ...userAMutation, status: 'auth_paused' })

    setOfflineShoppingScope('user-b')
    expect(await loadShoppingNameMutations()).toEqual([])
    const userBMutation = await queueShoppingNameMutation({
      listId: 'list-b',
      itemId: 'item-b',
      baseDisplayName: 'apples',
      desiredDisplayName: 'cooking apples',
    })

    setOfflineShoppingScope('user-a')
    expect(await loadShoppingNameMutations()).toEqual([{ ...userAMutation, status: 'auth_paused' }])

    await clearOfflineShoppingData()
    expect(await loadShoppingNameMutations()).toEqual([])
    setOfflineShoppingScope('user-b')
    expect(await loadShoppingNameMutations()).toEqual([userBMutation])
  })
})
