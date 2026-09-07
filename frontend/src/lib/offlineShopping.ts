import type { ShoppingItem } from '../types'

const dbName = 'slop-offline'
const dbVersion = 3
const shoppingStoreName = 'shopping'
const mutationStoreName = 'shoppingMutations'
// Version-two IndexedDB rows were not scoped. Keep them in a reserved scope
// until the first authenticated load can associate them with the account that
// owns the browser's old offline cache.
const legacyDatabaseScope = '__slop_legacy__'
const scopeStorageKey = 'slop-shopping-scope'
const legacyShoppingFallbackKey = 'slop-shopping-fallback'
const legacyMutationFallbackKey = 'slop-shopping-mutations-fallback'
const legacyContextFallbackKey = 'slop-shopping-context'
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
let memoryShoppingLoaded = false
let memoryNameMutations: ShoppingNameMutation[] = []
let memoryItemMutations: ShoppingItemMutation[] = []
let memoryContext: OfflineShoppingContext | null = null
let adoptedLegacyDatabaseScope = ''

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
    memoryShoppingLoaded = false
    memoryNameMutations = []
    memoryItemMutations = []
    memoryContext = null
    adoptedLegacyDatabaseScope = ''
  }
  currentScope = nextScope
  safeSet(scopeStorageKey, currentScope)
  migrateLegacyFallbacks()
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
    memoryShoppingLoaded = false
    memoryNameMutations = []
    memoryItemMutations = []
    memoryContext = null
    adoptedLegacyDatabaseScope = ''
  }
  migrateLegacyFallbacks()
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

function migrateLegacyFallbacks(): void {
  if (currentScope === 'anonymous') return
  for (const [legacyKey, prefix] of [
    [legacyShoppingFallbackKey, shoppingFallbackPrefix],
    [legacyMutationFallbackKey, mutationFallbackPrefix],
    [legacyContextFallbackKey, contextFallbackPrefix],
  ] as const) {
    const legacyValue = safeGet(legacyKey)
    if (legacyValue === null) continue
    const destinationKey = scopedKey(prefix)
    const destinationValue = safeGet(destinationKey)
    let migratedValue = legacyValue
    if (destinationValue !== null) {
      if (prefix === contextFallbackPrefix) {
        // A scoped context is already authoritative. The two values cannot be
        // merged, but it is safe to discard the old unscoped pointer because
        // it does not contain queued edits or cached list rows.
        safeRemove(legacyKey)
        continue
      }
      const merged = mergeFallbackArrays(legacyValue, destinationValue)
      if (merged === null) continue
      migratedValue = merged
    }
    if (safeSet(destinationKey, migratedValue)) safeRemove(legacyKey)
  }
}

function parseArray<T>(key: string): T[] {
  return parseStoredArray<T>(safeGet(key)) ?? []
}

function parseStoredArray<T>(stored: string | null): T[] | null {
  if (stored === null) return null
  try {
    const parsed = JSON.parse(stored)
    return Array.isArray(parsed) ? parsed as T[] : null
  } catch {
    return null
  }
}

function mergeFallbackArrays(legacyValue: string, currentValue: string): string | null {
  const legacyRecords = parseStoredArray<Record<string, unknown>>(legacyValue)
  const currentRecords = parseStoredArray<Record<string, unknown>>(currentValue)
  if (!legacyRecords || !currentRecords) return null
  const merged = currentRecords.filter(record => record !== null && typeof record === 'object')
  const seen = new Set(
    currentRecords
      .filter(record => record !== null && typeof record === 'object')
      .map(record => record.id)
      .filter((id): id is string | number => typeof id === 'string' || typeof id === 'number')
      .map(id => String(id)),
  )
  for (const record of legacyRecords) {
    if (record === null || typeof record !== 'object') continue
    const id = record.id
    if (typeof id === 'string' || typeof id === 'number') {
      const normalisedId = String(id)
      if (seen.has(normalisedId)) continue
      seen.add(normalisedId)
    }
    merged.push(record)
  }
  return JSON.stringify(merged)
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
      const transaction = request.transaction
      const migrationScope = currentScope === 'anonymous' ? legacyDatabaseScope : currentScope
      for (const storeName of [shoppingStoreName, mutationStoreName]) {
        if (!db.objectStoreNames.contains(storeName)) {
          db.createObjectStore(storeName, { keyPath: 'storageKey' })
          continue
        }
        const existing = transaction?.objectStore(storeName)
        if (!existing || existing.keyPath === 'storageKey') continue
        const recordsRequest = existing.getAll()
        recordsRequest.onsuccess = () => {
          db.deleteObjectStore(storeName)
          const replacement = db.createObjectStore(storeName, { keyPath: 'storageKey' })
          for (const record of recordsRequest.result as Array<{ id?: unknown } & Record<string, unknown>>) {
            if (record.id === undefined || record.id === null) continue
            const id = String(record.id)
            replacement.put({
              ...record,
              id,
              storageKey: `${migrationScope}:${id}`,
              scope: migrationScope,
            })
          }
        }
        recordsRequest.onerror = () => transaction?.abort()
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('IndexedDB could not be opened'))
    request.onblocked = () => reject(new Error('IndexedDB is blocked'))
  })
}

async function adoptLegacyDatabaseRecords(db: IDBDatabase): Promise<void> {
  const targetScope = currentScope
  if (targetScope === 'anonymous' || adoptedLegacyDatabaseScope === targetScope) return
  await new Promise<void>((resolve, reject) => {
    const transaction = db.transaction([shoppingStoreName, mutationStoreName], 'readwrite')
    for (const storeName of [shoppingStoreName, mutationStoreName]) {
      const store = transaction.objectStore(storeName)
      const request = store.getAll()
      request.onsuccess = () => {
        const records = request.result as Array<StoredRecord & Record<string, unknown>>
        const currentKeys = new Set(
          records
            .filter(record => record.scope === targetScope)
            .map(record => record.storageKey),
        )
        for (const record of records) {
          const isLegacy = record.scope === legacyDatabaseScope
            || (!record.scope && String(record.storageKey).startsWith(`${legacyDatabaseScope}:`))
          if (!isLegacy) continue
          const id = record.id === undefined || record.id === null
            ? String(record.storageKey).startsWith(`${legacyDatabaseScope}:`)
              ? String(record.storageKey).slice(legacyDatabaseScope.length + 1)
              : ''
            : String(record.id)
          if (!id) continue
          const targetKey = `${targetScope}:${id}`
          if (!currentKeys.has(targetKey)) {
            store.put({ ...record, id, storageKey: targetKey, scope: targetScope })
            currentKeys.add(targetKey)
          }
          store.delete(record.storageKey)
        }
      }
      request.onerror = () => transaction.abort()
    }
    transaction.oncomplete = () => {
      adoptedLegacyDatabaseScope = targetScope
      resolve()
    }
    transaction.onerror = () => reject(transaction.error)
    transaction.onabort = () => reject(transaction.error ?? new Error('IndexedDB migration was aborted'))
  })
}

async function useDatabase<T>(operation: (db: IDBDatabase) => Promise<T>): Promise<T> {
  if (indexedDbUnavailable || typeof indexedDB === 'undefined') throw new Error('IndexedDB is unavailable')
  const db = await openDatabase()
  try {
    await adoptLegacyDatabaseRecords(db)
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
  const fallbackValue = safeGet(scopedKey(shoppingFallbackPrefix))
  const fallback = parseStoredArray<ShoppingItem>(fallbackValue)
  if (!localStorageUnavailable && fallback !== null) {
    memoryShopping = fallback
    memoryShoppingLoaded = true
    return fallback
  }
  if (localStorageUnavailable && memoryShoppingLoaded) return memoryShopping
  try {
    const items = await useDatabase(dbItems)
    if (items.length) {
      memoryShopping = items
      memoryShoppingLoaded = true
      return items
    }
  } catch {
    indexedDbUnavailable = true
  }
  memoryShopping = seed
  memoryShoppingLoaded = true
  await saveShoppingItems(seed)
  return seed
}

export async function saveShoppingItems(items: ShoppingItem[]): Promise<void> {
  ensurePersistedScope()
  memoryShopping = items
  memoryShoppingLoaded = true
  const persisted = safeSet(scopedKey(shoppingFallbackPrefix), JSON.stringify(items))
  try {
    await useDatabase(db => new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(shoppingStoreName, 'readwrite')
      const store = transaction.objectStore(shoppingStoreName)
      const retainedIds = new Set(items.map(item => item.id))
      const existingRequest = store.getAll()
      existingRequest.onsuccess = () => {
        for (const record of existingRequest.result as Array<ShoppingItem & StoredRecord>) {
          if (record.scope === currentScope && !retainedIds.has(record.id)) store.delete(record.storageKey)
        }
        items.forEach(item => store.put({ ...item, storageKey: scopedRecordKey(item.id), scope: currentScope }))
      }
      existingRequest.onerror = () => transaction.abort()
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
  const fallbackValue = safeGet(scopedKey(mutationFallbackPrefix))
  const fallback = parseStoredArray<ShoppingNameMutation>(fallbackValue)
  if (!localStorageUnavailable && fallback !== null) {
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
  memoryNameMutations = fallback?.filter(item => !('kind' in item) || item.kind === 'name') as ShoppingNameMutation[] ?? []
  return memoryNameMutations
}

export async function loadShoppingItemMutations(): Promise<ShoppingItemMutation[]> {
  ensurePersistedScope()
  const fallbackValue = safeGet(scopedKey(mutationFallbackPrefix))
  const fallback = parseStoredArray<ShoppingNameMutation | ShoppingItemMutation>(fallbackValue)
  if (!localStorageUnavailable && fallback !== null) {
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
  memoryItemMutations = fallback?.filter(item => 'kind' in item && item.kind !== 'name') as ShoppingItemMutation[] ?? []
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
  memoryShoppingLoaded = false
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
