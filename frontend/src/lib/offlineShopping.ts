import type { ShoppingItem } from '../types'

const dbName = 'slop-offline'
const dbVersion = 3
const shoppingStoreName = 'shopping'
const mutationStoreName = 'shoppingMutations'
const scopeStorageKey = 'slop-shopping-scope'
const shoppingFallbackPrefix = 'slop-shopping-fallback:'
const mutationFallbackPrefix = 'slop-shopping-mutations-fallback:'
const contextFallbackPrefix = 'slop-shopping-context:'

export type ShoppingNameMutationStatus = 'pending' | 'conflict' | 'failed' | 'auth_paused'

export interface ShoppingNameMutation {
  kind?: 'name'
  id: string
  listId: string
  itemId: string
  baseDisplayName: string
  desiredDisplayName: string
  createdAt: number
  status: ShoppingNameMutationStatus
  attempts?: number
  nextAttemptAt?: number
  lastError?: string
  serverDisplayName?: string
}

export type ShoppingItemMutationKind = 'checked' | 'unit' | 'manual_add'
export type ShoppingItemMutationStatus = 'pending' | 'conflict' | 'failed' | 'auth_paused'

export interface ShoppingItemMutation {
  id: string
  kind: ShoppingItemMutationKind
  listId: string
  itemId?: string
  operationId: string
  createdAt: number
  attempts: number
  status: ShoppingItemMutationStatus
  nextAttemptAt?: number
  lastError?: string
  expectedVersion?: number
  baseChecked?: boolean
  desiredChecked?: boolean
  baseUnit?: string
  desiredUnit?: string
  localItemId?: string
  displayName?: string
  exactQuantity?: number
  purchaseQuantity?: number
  unit?: string
  category?: string
}

export interface OfflineShoppingContext {
  listId: string
  mealPlanId: string
  rebuildRecommended: boolean
}

interface StoredRecord {
  storageKey: string
  scope: string
  kind?: string
}

let currentScope = 'anonymous'
let indexedDbUnavailable = false
let localStorageUnavailable = false
let memoryShopping: ShoppingItem[] = []
let memoryNameMutations: ShoppingNameMutation[] = []
let memoryItemMutations: ShoppingItemMutation[] = []
let memoryContext: OfflineShoppingContext | null = null

try {
  currentScope = localStorage.getItem(scopeStorageKey) || 'anonymous'
} catch {
  // Private browsing and blocked storage are handled by the in-memory layer.
}

function normaliseScope(scope: string): string {
  const cleaned = scope.trim().replace(/[^a-zA-Z0-9._:-]/g, '_')
  return cleaned || 'anonymous'
}

export function setOfflineShoppingScope(scope?: string): void {
  const nextScope = normaliseScope(scope ?? 'anonymous')
  if (nextScope !== currentScope) {
    memoryShopping = []
    memoryNameMutations = []
    memoryItemMutations = []
    memoryContext = null
  }
  currentScope = nextScope
  safeSet(scopeStorageKey, currentScope)
}

function scopedKey(prefix: string): string {
  return `${prefix}${encodeURIComponent(currentScope)}`
}

function scopedRecordKey(id: string): string {
  return `${currentScope}:${id}`
}

function ensurePersistedScope(): void {
  const persisted = safeGet(scopeStorageKey)
  if (!localStorageUnavailable && !persisted && currentScope !== 'anonymous') {
    currentScope = 'anonymous'
    memoryShopping = []
    memoryNameMutations = []
    memoryItemMutations = []
    memoryContext = null
  }
}

function safeGet(key: string): string | null {
  try {
    const value = localStorage.getItem(key)
    localStorageUnavailable = false
    return value
  } catch {
    localStorageUnavailable = true
    return null
  }
}

function safeSet(key: string, value: string): boolean {
  try {
    localStorage.setItem(key, value)
    localStorageUnavailable = false
    return true
  } catch {
    localStorageUnavailable = true
    return false
  }
}

function safeRemove(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    // The in-memory fallback remains available when storage is blocked.
  }
}

function parseArray<T>(key: string): T[] {
  const stored = safeGet(key)
  if (!stored) return []
  try {
    const parsed = JSON.parse(stored)
    return Array.isArray(parsed) ? parsed as T[] : []
  } catch {
    return []
  }
}

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB is unavailable'))
      return
    }
    const request = indexedDB.open(dbName, dbVersion)
    request.onupgradeneeded = () => {
      const db = request.result
      for (const storeName of [shoppingStoreName, mutationStoreName]) {
        const existing = db.objectStoreNames.contains(storeName)
          ? request.transaction?.objectStore(storeName)
          : null
        if (existing && existing.keyPath !== 'storageKey') db.deleteObjectStore(storeName)
        if (!db.objectStoreNames.contains(storeName)) db.createObjectStore(storeName, { keyPath: 'storageKey' })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('IndexedDB could not be opened'))
    request.onblocked = () => reject(new Error('IndexedDB is blocked'))
  })
}

async function useDatabase<T>(operation: (db: IDBDatabase) => Promise<T>): Promise<T> {
  if (indexedDbUnavailable || typeof indexedDB === 'undefined') throw new Error('IndexedDB is unavailable')
  const db = await openDatabase()
  try {
    return await operation(db)
  } finally {
    db.close()
  }
}

function dbItems(db: IDBDatabase): Promise<ShoppingItem[]> {
  return new Promise((resolve, reject) => {
    const request = db.transaction(shoppingStoreName).objectStore(shoppingStoreName).getAll()
    request.onsuccess = () => resolve((request.result as Array<ShoppingItem & StoredRecord>)
      .filter(item => item.scope === currentScope)
      .map(({ storageKey: _storageKey, scope: _scope, ...item }) => item as ShoppingItem))
    request.onerror = () => reject(request.error)
  })
}

function dbMutations<T extends ShoppingNameMutation | ShoppingItemMutation>(db: IDBDatabase): Promise<T[]> {
  return new Promise((resolve, reject) => {
    const request = db.transaction(mutationStoreName).objectStore(mutationStoreName).getAll()
    request.onsuccess = () => resolve((request.result as Array<T & StoredRecord>)
      .filter(item => item.scope === currentScope)
      .map(({ storageKey: _storageKey, scope: _scope, ...item }) => item as T))
    request.onerror = () => reject(request.error)
  })
}

function putRecord(storeName: string, record: object & { id: string; kind?: string }): Promise<void> {
  return useDatabase(db => new Promise((resolve, reject) => {
    const transaction = db.transaction(storeName, 'readwrite')
    transaction.objectStore(storeName).put({ ...record, storageKey: scopedRecordKey(record.id), scope: currentScope })
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => reject(transaction.error)
  }))
}

function deleteRecord(storeName: string, id: string): Promise<void> {
  return useDatabase(db => new Promise((resolve, reject) => {
    const transaction = db.transaction(storeName, 'readwrite')
    transaction.objectStore(storeName).delete(scopedRecordKey(id))
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => reject(transaction.error)
  }))
}

export async function loadShoppingItems(seed: ShoppingItem[]): Promise<ShoppingItem[]> {
  ensurePersistedScope()
  const fallback = parseArray<ShoppingItem>(scopedKey(shoppingFallbackPrefix))
  if (fallback.length) {
    memoryShopping = fallback
    return fallback
  }
  if (localStorageUnavailable && memoryShopping.length) return memoryShopping
  try {
    const items = await useDatabase(dbItems)
    if (items.length) {
      memoryShopping = items
      return items
    }
  } catch {
    indexedDbUnavailable = true
  }
  memoryShopping = seed
  await saveShoppingItems(seed)
  return seed
}

export async function saveShoppingItems(items: ShoppingItem[]): Promise<void> {
  ensurePersistedScope()
  memoryShopping = items
  const persisted = safeSet(scopedKey(shoppingFallbackPrefix), JSON.stringify(items))
  try {
    await useDatabase(db => new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(shoppingStoreName, 'readwrite')
      const store = transaction.objectStore(shoppingStoreName)
      items.forEach(item => store.put({ ...item, storageKey: scopedRecordKey(item.id), scope: currentScope }))
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => reject(transaction.error)
    }))
  } catch {
    indexedDbUnavailable = true
    if (!persisted) memoryShopping = items
  }
}

export async function loadShoppingNameMutations(): Promise<ShoppingNameMutation[]> {
  ensurePersistedScope()
  const fallback = parseArray<ShoppingNameMutation>(scopedKey(mutationFallbackPrefix))
  if (fallback.length) {
    memoryNameMutations = fallback.filter(item => !('kind' in item) || item.kind === 'name')
    return memoryNameMutations
  }
  if (localStorageUnavailable && memoryNameMutations.length) return memoryNameMutations
  try {
    const mutations = await useDatabase(dbMutations<ShoppingNameMutation>)
    const names = mutations.filter(item => !('kind' in item) || item.kind === 'name')
    if (names.length) {
      memoryNameMutations = names
      return names
    }
  } catch {
    indexedDbUnavailable = true
  }
  memoryNameMutations = fallback.filter(item => !('kind' in item) || item.kind === 'name') as ShoppingNameMutation[]
  return memoryNameMutations
}

export async function loadShoppingItemMutations(): Promise<ShoppingItemMutation[]> {
  ensurePersistedScope()
  const fallback = parseArray<ShoppingNameMutation | ShoppingItemMutation>(scopedKey(mutationFallbackPrefix))
  if (fallback.some(item => 'kind' in item && item.kind !== 'name')) {
    memoryItemMutations = fallback.filter(item => 'kind' in item && item.kind !== 'name') as ShoppingItemMutation[]
    return memoryItemMutations
  }
  if (localStorageUnavailable && memoryItemMutations.length) return memoryItemMutations
  try {
    const mutations = await useDatabase(dbMutations<ShoppingNameMutation | ShoppingItemMutation>)
    const items = mutations.filter(item => 'kind' in item && item.kind !== 'name') as ShoppingItemMutation[]
    if (items.length) {
      memoryItemMutations = items
      return items
    }
  } catch {
    indexedDbUnavailable = true
  }
  memoryItemMutations = fallback.filter(item => 'kind' in item && item.kind !== 'name') as ShoppingItemMutation[]
  return memoryItemMutations
}

function saveMutationFallback(mutation: ShoppingNameMutation | ShoppingItemMutation): void {
  const all = parseArray<ShoppingNameMutation | ShoppingItemMutation>(scopedKey(mutationFallbackPrefix))
  const next = [...all.filter(item => item.id !== mutation.id), mutation]
  safeSet(scopedKey(mutationFallbackPrefix), JSON.stringify(next))
}

export async function saveShoppingNameMutation(mutation: ShoppingNameMutation): Promise<void> {
  memoryNameMutations = [...memoryNameMutations.filter(item => item.id !== mutation.id), mutation]
  saveMutationFallback(mutation)
  try {
    await putRecord(mutationStoreName, { ...mutation, kind: 'name' })
  } catch {
    indexedDbUnavailable = true
  }
}

export async function saveShoppingItemMutation(mutation: ShoppingItemMutation): Promise<void> {
  memoryItemMutations = [...memoryItemMutations.filter(item => item.id !== mutation.id), mutation]
  saveMutationFallback(mutation)
  try {
    await putRecord(mutationStoreName, mutation)
  } catch {
    indexedDbUnavailable = true
  }
}

export async function queueShoppingNameMutation(
  mutation: Omit<ShoppingNameMutation, 'id' | 'createdAt' | 'status'>,
): Promise<ShoppingNameMutation> {
  const existing = (await loadShoppingNameMutations()).find(item => item.id === `${mutation.listId}:${mutation.itemId}`)
  const queued: ShoppingNameMutation = {
    id: `${mutation.listId}:${mutation.itemId}`,
    listId: mutation.listId,
    itemId: mutation.itemId,
    baseDisplayName: existing?.baseDisplayName ?? mutation.baseDisplayName,
    desiredDisplayName: mutation.desiredDisplayName,
    createdAt: existing?.createdAt ?? Date.now(),
    status: existing?.status ?? 'pending',
    attempts: existing?.attempts ?? 0,
    nextAttemptAt: existing?.nextAttemptAt,
    lastError: existing?.lastError,
    serverDisplayName: existing?.serverDisplayName,
  }
  await saveShoppingNameMutation(queued)
  return queued
}

export async function queueShoppingItemMutation(
  mutation: Omit<ShoppingItemMutation, 'createdAt' | 'attempts' | 'status'>,
): Promise<ShoppingItemMutation> {
  const existing = (await loadShoppingItemMutations()).find(item => item.id === mutation.id)
  const queued: ShoppingItemMutation = {
    ...mutation,
    operationId: existing?.operationId ?? mutation.operationId,
    expectedVersion: existing?.expectedVersion ?? mutation.expectedVersion,
    baseChecked: existing?.baseChecked ?? mutation.baseChecked,
    baseUnit: existing?.baseUnit ?? mutation.baseUnit,
    createdAt: existing?.createdAt ?? Date.now(),
    attempts: existing?.attempts ?? 0,
    status: existing?.status ?? 'pending',
    nextAttemptAt: existing?.nextAttemptAt,
    lastError: existing?.lastError,
  }
  await saveShoppingItemMutation(queued)
  return queued
}

function removeMutationFallback(id: string): void {
  const all = parseArray<ShoppingNameMutation | ShoppingItemMutation>(scopedKey(mutationFallbackPrefix))
  safeSet(scopedKey(mutationFallbackPrefix), JSON.stringify(all.filter(item => item.id !== id)))
}

export async function removeShoppingNameMutation(id: string): Promise<void> {
  memoryNameMutations = memoryNameMutations.filter(item => item.id !== id)
  removeMutationFallback(id)
  try {
    await deleteRecord(mutationStoreName, id)
  } catch {
    indexedDbUnavailable = true
  }
}

export async function removeShoppingItemMutation(id: string): Promise<void> {
  memoryItemMutations = memoryItemMutations.filter(item => item.id !== id)
  removeMutationFallback(id)
  try {
    await deleteRecord(mutationStoreName, id)
  } catch {
    indexedDbUnavailable = true
  }
}

export function loadOfflineShoppingContext(): OfflineShoppingContext | null {
  if (memoryContext) return memoryContext
  const stored = safeGet(scopedKey(contextFallbackPrefix))
  if (!stored) return null
  try {
    memoryContext = JSON.parse(stored) as OfflineShoppingContext
    return memoryContext
  } catch {
    return null
  }
}

export function saveOfflineShoppingContext(context: OfflineShoppingContext): void {
  memoryContext = context
  safeSet(scopedKey(contextFallbackPrefix), JSON.stringify(context))
}

export async function clearOfflineShoppingData(): Promise<void> {
  memoryShopping = []
  memoryNameMutations = []
  memoryItemMutations = []
  memoryContext = null
  safeRemove(scopedKey(shoppingFallbackPrefix))
  safeRemove(scopedKey(mutationFallbackPrefix))
  safeRemove(scopedKey(contextFallbackPrefix))
  try {
    await useDatabase(db => new Promise<void>((resolve, reject) => {
      const transaction = db.transaction([shoppingStoreName, mutationStoreName], 'readwrite')
      for (const storeName of [shoppingStoreName, mutationStoreName]) {
        const store = transaction.objectStore(storeName)
        const request = store.getAll()
        request.onsuccess = () => {
          for (const record of request.result as StoredRecord[]) {
            if (record.scope === currentScope) store.delete(record.storageKey)
          }
        }
      }
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => reject(transaction.error)
    }))
  } catch {
    indexedDbUnavailable = true
  }
}

export function shoppingAsText(items: ShoppingItem[]): string {
  const grouped = items
    .filter(item => !item.checked)
    .reduce<Record<string, ShoppingItem[]>>((result, item) => {
      ;(result[item.category] ??= []).push(item)
      return result
    }, {})
  return [
    'Slop shopping list',
    ...Object.entries(grouped).map(([category, group]) =>
      `\n${category}\n${group.map(item => `□ ${item.name} — ${item.buy}`).join('\n')}`,
    ),
  ].join('\n')
}
