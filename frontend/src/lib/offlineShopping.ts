import type { ShoppingItem } from '../types'

const dbName = 'savour-offline'
const shoppingStoreName = 'shopping'
const mutationStoreName = 'shoppingMutations'
const shoppingFallbackKey = 'savour-shopping-fallback'
const mutationFallbackKey = 'savour-shopping-mutations-fallback'
const contextFallbackKey = 'savour-shopping-context'

export type ShoppingNameMutationStatus = 'pending' | 'conflict'

export interface ShoppingNameMutation {
  id: string
  listId: string
  itemId: string
  baseDisplayName: string
  desiredDisplayName: string
  createdAt: number
  status: ShoppingNameMutationStatus
  serverDisplayName?: string
}

export interface OfflineShoppingContext {
  listId: string
  mealPlanId: string
  rebuildRecommended: boolean
}

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(dbName, 2)
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(shoppingStoreName)) {
        request.result.createObjectStore(shoppingStoreName, { keyPath: 'id' })
      }
      if (!request.result.objectStoreNames.contains(mutationStoreName)) {
        request.result.createObjectStore(mutationStoreName, { keyPath: 'id' })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function fallbackArray<T>(key: string): T[] {
  const stored = localStorage.getItem(key)
  if (!stored) return []
  try {
    return JSON.parse(stored) as T[]
  } catch {
    return []
  }
}

export async function loadShoppingItems(seed: ShoppingItem[]): Promise<ShoppingItem[]> {
  if (!('indexedDB' in window)) {
    const stored = fallbackArray<ShoppingItem>(shoppingFallbackKey)
    return stored.length ? stored : seed
  }
  const db = await openDatabase()
  const items = await new Promise<ShoppingItem[]>((resolve, reject) => {
    const request = db.transaction(shoppingStoreName).objectStore(shoppingStoreName).getAll()
    request.onsuccess = () => resolve(request.result as ShoppingItem[])
    request.onerror = () => reject(request.error)
  })
  db.close()
  if (items.length) return items
  await saveShoppingItems(seed)
  return seed
}

export async function saveShoppingItems(items: ShoppingItem[]): Promise<void> {
  if (!('indexedDB' in window)) {
    localStorage.setItem(shoppingFallbackKey, JSON.stringify(items))
    return
  }
  const db = await openDatabase()
  await new Promise<void>((resolve, reject) => {
    const transaction = db.transaction(shoppingStoreName, 'readwrite')
    const store = transaction.objectStore(shoppingStoreName)
    store.clear()
    items.forEach(item => store.put(item))
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => reject(transaction.error)
  })
  db.close()
}

export async function loadShoppingNameMutations(): Promise<ShoppingNameMutation[]> {
  if (!('indexedDB' in window)) return fallbackArray<ShoppingNameMutation>(mutationFallbackKey)
  const db = await openDatabase()
  const mutations = await new Promise<ShoppingNameMutation[]>((resolve, reject) => {
    const request = db.transaction(mutationStoreName).objectStore(mutationStoreName).getAll()
    request.onsuccess = () => resolve(request.result as ShoppingNameMutation[])
    request.onerror = () => reject(request.error)
  })
  db.close()
  return mutations
}

export async function saveShoppingNameMutation(mutation: ShoppingNameMutation): Promise<void> {
  if (!('indexedDB' in window)) {
    const mutations = fallbackArray<ShoppingNameMutation>(mutationFallbackKey)
    const next = mutations.filter(item => item.id !== mutation.id)
    next.push(mutation)
    localStorage.setItem(mutationFallbackKey, JSON.stringify(next))
    return
  }
  const db = await openDatabase()
  await new Promise<void>((resolve, reject) => {
    const transaction = db.transaction(mutationStoreName, 'readwrite')
    transaction.objectStore(mutationStoreName).put(mutation)
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => reject(transaction.error)
  })
  db.close()
}

export async function queueShoppingNameMutation(
  mutation: Omit<ShoppingNameMutation, 'id' | 'createdAt' | 'status'>,
): Promise<ShoppingNameMutation> {
  const id = `${mutation.listId}:${mutation.itemId}`
  const existing = (await loadShoppingNameMutations()).find(item => item.id === id)
  const queued: ShoppingNameMutation = {
    id,
    listId: mutation.listId,
    itemId: mutation.itemId,
    baseDisplayName: existing?.baseDisplayName ?? mutation.baseDisplayName,
    desiredDisplayName: mutation.desiredDisplayName,
    createdAt: existing?.createdAt ?? Date.now(),
    status: 'pending',
  }
  await saveShoppingNameMutation(queued)
  return queued
}

export async function removeShoppingNameMutation(id: string): Promise<void> {
  if (!('indexedDB' in window)) {
    const next = fallbackArray<ShoppingNameMutation>(mutationFallbackKey)
      .filter(item => item.id !== id)
    localStorage.setItem(mutationFallbackKey, JSON.stringify(next))
    return
  }
  const db = await openDatabase()
  await new Promise<void>((resolve, reject) => {
    const transaction = db.transaction(mutationStoreName, 'readwrite')
    transaction.objectStore(mutationStoreName).delete(id)
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => reject(transaction.error)
  })
  db.close()
}

export function loadOfflineShoppingContext(): OfflineShoppingContext | null {
  const stored = localStorage.getItem(contextFallbackKey)
  if (!stored) return null
  try {
    return JSON.parse(stored) as OfflineShoppingContext
  } catch {
    return null
  }
}

export function saveOfflineShoppingContext(context: OfflineShoppingContext): void {
  localStorage.setItem(contextFallbackKey, JSON.stringify(context))
}

export function shoppingAsText(items: ShoppingItem[]): string {
  const grouped = items
    .filter(item => !item.checked)
    .reduce<Record<string, ShoppingItem[]>>((result, item) => {
      ;(result[item.category] ??= []).push(item)
      return result
    }, {})
  return [
    'Savour shopping list',
    ...Object.entries(grouped).map(([category, group]) =>
      `\n${category}\n${group.map(item => `□ ${item.name} — ${item.buy}`).join('\n')}`,
    ),
  ].join('\n')
}
