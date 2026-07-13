import type { ShoppingItem } from '../types'

const dbName = 'savour-offline'
const storeName = 'shopping'
const fallbackKey = 'savour-shopping-fallback'

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(dbName, 1)
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(storeName)) req.result.createObjectStore(storeName, { keyPath: 'id' })
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

export async function loadShoppingItems(seed: ShoppingItem[]): Promise<ShoppingItem[]> {
  if (!('indexedDB' in window)) {
    const stored = localStorage.getItem(fallbackKey)
    return stored ? JSON.parse(stored) as ShoppingItem[] : seed
  }
  const db = await openDatabase()
  const items = await new Promise<ShoppingItem[]>((resolve, reject) => {
    const req = db.transaction(storeName).objectStore(storeName).getAll()
    req.onsuccess = () => resolve(req.result as ShoppingItem[])
    req.onerror = () => reject(req.error)
  })
  db.close()
  if (items.length) return items
  await saveShoppingItems(seed)
  return seed
}

export async function saveShoppingItems(items: ShoppingItem[]): Promise<void> {
  if (!('indexedDB' in window)) {
    localStorage.setItem(fallbackKey, JSON.stringify(items))
    return
  }
  const db = await openDatabase()
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(storeName, 'readwrite')
    const store = tx.objectStore(storeName)
    store.clear()
    items.forEach(item => store.put(item))
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
  db.close()
}

export function shoppingAsText(items: ShoppingItem[]): string {
  const grouped = items.filter(item => !item.checked).reduce<Record<string, ShoppingItem[]>>((result, item) => {
    ;(result[item.category] ??= []).push(item)
    return result
  }, {})
  return ['Savour shopping list', ...Object.entries(grouped).map(([category, group]) => `\n${category}\n${group.map(item => `□ ${item.name} — ${item.buy}`).join('\n')}`)].join('\n')
}
