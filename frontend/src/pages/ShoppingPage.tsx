import {
  Check,
  Clipboard,
  Download,
  ListChecks,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Share2,
  ShoppingBasket,
  Wifi,
  WifiOff,
  X,
} from 'lucide-react'
import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button, Card, EmptyState, Notice, PageHeader } from '../components/ui'
import { initialShopping } from '../data/demo'
import {
  loadOfflineShoppingContext,
  loadShoppingItems,
  loadShoppingNameMutations,
  queueShoppingNameMutation,
  removeShoppingNameMutation,
  saveOfflineShoppingContext,
  saveShoppingItems,
  saveShoppingNameMutation,
  shoppingAsText,
  type ShoppingNameMutation,
} from '../lib/offlineShopping'
import type { ShoppingItem } from '../types'
import {
  api,
  ApiError,
  isDemoMode,
  type ApiAction,
  type BackendShoppingItem,
  type BackendShoppingList,
} from '../api/client'

export function ShoppingPage() {
  const [items, setItems] = useState<ShoppingItem[]>([])
  const [loaded, setLoaded] = useState(false)
  const [online, setOnline] = useState(navigator.onLine)
  const [newItem, setNewItem] = useState('')
  const [notice, setNotice] = useState('')
  const [listId, setListId] = useState('')
  const [mealPlanId, setMealPlanId] = useState('')
  const [rebuildRecommended, setRebuildRecommended] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [rebuildProblem, setRebuildProblem] = useState<{ message: string; actions: ApiAction[] } | null>(null)
  const [versions, setVersions] = useState<Record<string, number>>({})
  const [nameMutations, setNameMutations] = useState<ShoppingNameMutation[]>([])
  const [editingId, setEditingId] = useState('')
  const [editingName, setEditingName] = useState('')
  const syncingNames = useRef(false)

  const applyServerList = (
    server: BackendShoppingList,
    nextItems = server.items.map(mapShoppingItem),
  ) => {
    setListId(server.id)
    setMealPlanId(server.meal_plan_id ?? '')
    setRebuildRecommended(server.rebuild_recommended)
    setVersions(Object.fromEntries(server.items.map(item => [item.id, item.version])))
    setItems(nextItems)
    saveOfflineShoppingContext({
      listId: server.id,
      mealPlanId: server.meal_plan_id ?? '',
      rebuildRecommended: server.rebuild_recommended,
    })
  }

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      const queuedNames = isDemoMode ? [] : await loadShoppingNameMutations()
      if (isDemoMode) {
        const value = await loadShoppingItems(initialShopping)
        if (!cancelled) {
          setItems(value)
          setLoaded(true)
        }
        return
      }
      try {
        const server = await api.activeShoppingList()
        const serverItems = server.items.map(mapShoppingItem)
        const cached = await loadShoppingItems(serverItems)
        const cachedById = new Map(cached.map(item => [item.id, item]))
        const queuedById = new Map(
          queuedNames
            .filter(mutation => mutation.listId === server.id)
            .map(mutation => [mutation.itemId, mutation]),
        )
        const merged = serverItems.map(item => {
          const local = cachedById.get(item.id)
          const queued = queuedById.get(item.id)
          const mergedItem = {
            ...item,
            checked: local?.checked ?? item.checked,
            updatedAt: local?.updatedAt ?? item.updatedAt,
            name: queued?.desiredDisplayName ?? item.name,
          }
          return local?.unit ? selectQuantityUnit(mergedItem, local.unit) : mergedItem
        })
        const nextVersions = Object.fromEntries(server.items.map(item => [item.id, item.version]))
        let checkedChangeConflict = false
        for (const original of server.items) {
          const local = cachedById.get(original.id)
          const displayUnit = local?.unit && original.available_units?.includes(local.unit)
            && local.unit !== original.unit
            ? local.unit
            : undefined
          const checked = local && local.checked !== original.checked ? local.checked : undefined
          if (checked !== undefined || displayUnit) {
            try {
              const updated = await api.patchShoppingItem(server.id, original.id, {
                expected_version: nextVersions[original.id],
                checked,
                display_unit: displayUnit,
              })
              nextVersions[original.id] = updated.version
            } catch {
              if (checked !== undefined) {
                checkedChangeConflict = true
                const mergedItem = merged.find(item => item.id === original.id)
                if (mergedItem) mergedItem.checked = original.checked
              }
            }
          }
        }
        if (!cancelled) {
          setNameMutations(queuedNames)
          applyServerList(server, merged)
          setVersions({ ...nextVersions })
          setLoaded(true)
          if (checkedChangeConflict) {
            setNotice('A checked item changed elsewhere, so the household value was kept.')
          }
          await saveShoppingItems(merged)
        }
      } catch {
        const cached = await loadShoppingItems([])
        const context = loadOfflineShoppingContext()
        const queuedById = new Map(queuedNames.map(mutation => [mutation.itemId, mutation]))
        if (!cancelled) {
          if (context) {
            setListId(context.listId)
            setMealPlanId(context.mealPlanId)
            setRebuildRecommended(context.rebuildRecommended)
          }
          setNameMutations(queuedNames)
          setItems(cached.map(item => ({
            ...item,
            name: queuedById.get(item.id)?.desiredDisplayName ?? item.name,
          })))
          setLoaded(true)
          setNotice('Working from the offline copy until the server is available.')
        }
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const up = () => setOnline(true)
    const down = () => setOnline(false)
    addEventListener('online', up)
    addEventListener('offline', down)
    return () => {
      removeEventListener('online', up)
      removeEventListener('offline', down)
    }
  }, [])

  useEffect(() => {
    if (loaded) {
      saveShoppingItems(items).catch(() => setNotice('Changes are saved in this browser only.'))
    }
  }, [items, loaded])

  useEffect(() => {
    if (
      isDemoMode
      || !online
      || !loaded
      || syncingNames.current
      || !nameMutations.some(mutation => mutation.status === 'pending')
    ) return

    let cancelled = false
    syncingNames.current = true
    const flush = async () => {
      let next = [...nameMutations]
      for (const mutation of nameMutations.filter(item => item.status === 'pending')) {
        try {
          const updated = await api.renameShoppingItem(mutation.listId, mutation.itemId, {
            display_name: mutation.desiredDisplayName,
            expected_display_name: mutation.baseDisplayName,
          })
          await removeShoppingNameMutation(mutation.id)
          next = next.filter(item => item.id !== mutation.id)
          if (!cancelled) {
            setItems(all => all.map(item => item.id === mutation.itemId
              ? { ...item, name: updated.display_name, updatedAt: Date.now() }
              : item))
            setVersions(all => ({ ...all, [mutation.itemId]: updated.version }))
          }
        } catch (reason) {
          if (reason instanceof ApiError && reason.code === 'SHOPPING_NAME_CONFLICT') {
            const conflict: ShoppingNameMutation = {
              ...mutation,
              status: 'conflict',
              serverDisplayName: reason.actions[0]?.current_display_name ?? mutation.baseDisplayName,
            }
            await saveShoppingNameMutation(conflict)
            next = next.map(item => item.id === conflict.id ? conflict : item)
            continue
          }
          break
        }
      }
      if (!cancelled) setNameMutations(next)
      syncingNames.current = false
    }
    void flush()
    return () => {
      cancelled = true
    }
  }, [loaded, nameMutations, online])

  const grouped = useMemo(
    () => items.reduce<Record<string, ShoppingItem[]>>((out, item) => {
      ;(out[item.category] ??= []).push(item)
      return out
    }, {}),
    [items],
  )
  const mutationsByItem = useMemo(
    () => new Map(nameMutations.map(mutation => [mutation.itemId, mutation])),
    [nameMutations],
  )
  const currentListMutations = nameMutations.filter(mutation => mutation.listId === listId)
  const conflicts = currentListMutations.filter(mutation => mutation.status === 'conflict')
  const completed = items.filter(item => item.checked).length

  const toggle = async (id: string) => {
    const current = items.find(item => item.id === id)
    if (!current) return
    const checked = !current.checked
    setItems(all => all.map(item => item.id === id
      ? { ...item, checked, updatedAt: Date.now() }
      : item))
    if (!isDemoMode && online && listId && versions[id]) {
      try {
        const updated = await api.patchShoppingItem(listId, id, {
          expected_version: versions[id],
          checked,
        })
        setVersions(all => ({ ...all, [id]: updated.version }))
      } catch {
        setNotice('Saved offline. This change will be reconciled when the list reloads.')
      }
    }
  }

  const startNameEdit = (item: ShoppingItem) => {
    setEditingId(item.id)
    setEditingName(item.name)
  }

  const selectUnit = async (id: string, unit: string) => {
    const current = items.find(item => item.id === id)
    if (!current || current.unit === unit) return
    setItems(all => all.map(item => item.id === id
      ? { ...selectQuantityUnit(item, unit), updatedAt: Date.now() }
      : item))
    if (!isDemoMode && online && listId && versions[id]) {
      try {
        const updated = await api.patchShoppingItem(listId, id, {
          expected_version: versions[id],
          display_unit: unit,
        })
        setItems(all => all.map(item => item.id === id ? mapShoppingItem(updated) : item))
        setVersions(all => ({ ...all, [id]: updated.version }))
      } catch {
        setNotice('Unit choice saved on this device. It will be reconciled when the list reloads.')
      }
    }
  }

  const finishNameEdit = async (event: FormEvent, item: ShoppingItem) => {
    event.preventDefault()
    const desiredName = editingName.trim()
    if (!desiredName || desiredName === item.name) {
      setEditingId('')
      return
    }
    if (!isDemoMode && !listId) {
      setEditingId('')
      setNotice('The active list details are unavailable. Reconnect before editing this name.')
      return
    }
    setItems(all => all.map(value => value.id === item.id
      ? { ...value, name: desiredName, updatedAt: Date.now() }
      : value))
    setEditingId('')
    if (isDemoMode || (item.manual && !versions[item.id])) return

    const existing = mutationsByItem.get(item.id)
    const baseDisplayName = existing?.baseDisplayName ?? item.name
    if (online) {
      try {
        const updated = await api.renameShoppingItem(listId, item.id, {
          display_name: desiredName,
          expected_display_name: baseDisplayName,
        })
        if (existing) await removeShoppingNameMutation(existing.id)
        setNameMutations(all => all.filter(mutation => mutation.itemId !== item.id))
        setItems(all => all.map(value => value.id === item.id
          ? { ...value, name: updated.display_name, updatedAt: Date.now() }
          : value))
        setVersions(all => ({ ...all, [item.id]: updated.version }))
        setNotice('Ingredient name updated and remembered for this household.')
        return
      } catch (reason) {
        if (reason instanceof ApiError && reason.code === 'SHOPPING_NAME_CONFLICT') {
          const conflict: ShoppingNameMutation = {
            id: `${listId}:${item.id}`,
            listId,
            itemId: item.id,
            baseDisplayName,
            desiredDisplayName: desiredName,
            createdAt: existing?.createdAt ?? Date.now(),
            status: 'conflict',
            serverDisplayName: reason.actions[0]?.current_display_name ?? baseDisplayName,
          }
          await saveShoppingNameMutation(conflict)
          setNameMutations(all => [...all.filter(mutation => mutation.id !== conflict.id), conflict])
          return
        }
      }
    }

    const queued = await queueShoppingNameMutation({
      listId,
      itemId: item.id,
      baseDisplayName,
      desiredDisplayName: desiredName,
    })
    setNameMutations(all => [...all.filter(mutation => mutation.id !== queued.id), queued])
    setNotice('Name edit saved offline. It will sync when this device reconnects.')
  }

  const useMyName = async (mutation: ShoppingNameMutation) => {
    const pending: ShoppingNameMutation = {
      ...mutation,
      baseDisplayName: mutation.serverDisplayName ?? mutation.baseDisplayName,
      status: 'pending',
      serverDisplayName: undefined,
    }
    await saveShoppingNameMutation(pending)
    setNameMutations(all => all.map(item => item.id === pending.id ? pending : item))
  }

  const keepHouseholdName = async (mutation: ShoppingNameMutation) => {
    const serverName = mutation.serverDisplayName ?? mutation.baseDisplayName
    await removeShoppingNameMutation(mutation.id)
    setNameMutations(all => all.filter(item => item.id !== mutation.id))
    setItems(all => all.map(item => item.id === mutation.itemId
      ? { ...item, name: serverName, updatedAt: Date.now() }
      : item))
  }

  const add = async (event: FormEvent) => {
    event.preventDefault()
    if (!newItem.trim()) return
    const name = newItem.trim()
    if (!isDemoMode && online && listId) {
      try {
        const item = await api.addShoppingItem(listId, {
          display_name: name,
          exact_quantity: 1,
          purchase_quantity: 1,
          unit: 'count',
          category: 'Other',
        })
        setItems(all => [...all, mapShoppingItem(item)])
        setVersions(all => ({ ...all, [item.id]: item.version }))
      } catch {
        setItems(all => [...all, manualShoppingItem(name)])
      }
    } else {
      setItems(all => [...all, manualShoppingItem(name)])
    }
    setNewItem('')
  }

  const rebuild = async () => {
    if (!mealPlanId) {
      setNotice('This list is no longer linked to a meal plan, so it cannot be rebuilt automatically.')
      return
    }
    if (currentListMutations.length) {
      setNotice('Resolve or sync the pending ingredient name edits before rebuilding the list.')
      return
    }
    setRebuilding(true)
    setRebuildProblem(null)
    try {
      const updated = await api.buildShoppingList(mealPlanId)
      applyServerList(updated)
      await saveShoppingItems(updated.items.map(mapShoppingItem))
      setNotice('The shopping list was rebuilt with the latest ingredient and measurement improvements.')
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === 'SHOPPING_REVIEW_REQUIRED') {
        setRebuildProblem({ message: reason.message, actions: reason.actions })
      }
      setNotice('The list could not be rebuilt. Review any highlighted recipe ingredients and try again.')
    } finally {
      setRebuilding(false)
    }
  }

  const addPurchased = async () => {
    if (!listId) return
    try {
      await api.addPurchasedToPantry(listId)
      setItems(all => all.map(item => ({ ...item, checked: false })))
      setNotice('Purchased items were added to the pantry.')
    } catch {
      setNotice('Tick at least one purchased item before adding it to the pantry.')
    }
  }

  const text = () => shoppingAsText(items)
  const share = async () => {
    try {
      if (navigator.share) await navigator.share({ title: 'Savour shopping list', text: text() })
      else {
        await navigator.clipboard.writeText(text())
        setNotice('Shopping list copied to clipboard.')
      }
    } catch {
      // The native share sheet can be dismissed without changing the list.
    }
  }
  const copy = async () => {
    await navigator.clipboard.writeText(text())
    setNotice('Shopping list copied to clipboard.')
  }
  const download = () => {
    const anchor = document.createElement('a')
    anchor.href = URL.createObjectURL(new Blob([text()], { type: 'text/plain' }))
    anchor.download = 'savour-shopping-list.txt'
    anchor.click()
    URL.revokeObjectURL(anchor.href)
  }

  const syncLabel = !online
    ? 'Working offline'
    : conflicts.length
      ? 'Name conflict'
      : currentListMutations.length
        ? 'Syncing edits'
        : 'Synced'

  return <div className="page">
    <PageHeader
      eyebrow="20–26 July"
      title="Shopping list"
      description="Rounded to practical amounts after using what is already in your pantry."
      actions={<>
        <Button variant="secondary" onClick={share}><Share2/>Share</Button>
        <Button variant="ghost" onClick={copy}><Clipboard/>Copy</Button>
        <Button variant="ghost" onClick={download}><Download/>.txt</Button>
        {!isDemoMode && <Button onClick={addPurchased}>Add purchased to pantry</Button>}
      </>}
    />
    {rebuildRecommended && <Notice tone="warning" title="Shopping list improvements are available">
      <div className="shopping-rebuild-copy">
        <p>Your current list is unchanged so checked and manual items remain safe. Rebuild when you are ready to apply improved ingredient names and measurement conversions.</p>
        {currentListMutations.length > 0 && <p className="field-help field-help--warning">Sync or resolve {currentListMutations.length} name edit{currentListMutations.length === 1 ? '' : 's'} first.</p>}
        <Button
          variant="secondary"
          disabled={rebuilding || !online || currentListMutations.length > 0}
          onClick={rebuild}
        >{rebuilding ? 'Rebuilding…' : 'Rebuild shopping list'}</Button>
        {rebuildProblem && <div className="shopping-rebuild-problem" role="alert">
          <strong>Recipe review needed</strong>
          <p>{rebuildProblem.message}</p>
          <div className="button-row">{rebuildProblem.actions.map((action, index) => action.href
            ? <Link className="button button--secondary" key={`${action.href}-${index}`} to={shoppingReviewHref(action.href)}>{action.label ?? 'Review ingredient'}</Link>
            : null)}</div>
        </div>}
      </div>
    </Notice>}
    <div className="shopping-status">
      <div className="shopping-progress">
        <div><ShoppingBasket/><span><strong>{completed} of {items.length}</strong><small>items collected</small></span></div>
        <div className="progress-bar"><span style={{ width: `${items.length ? completed / items.length * 100 : 0}%` }}/></div>
      </div>
      <Badge tone={online && !currentListMutations.length ? 'green' : 'warning'}>
        {online ? <Wifi size={14}/> : <WifiOff size={14}/>} {syncLabel}
      </Badge>
    </div>
    {notice && <button className="toast" onClick={() => setNotice('')}><Check/>{notice}</button>}
    <form className="quick-add" onSubmit={add}><Plus/><input value={newItem} onChange={event => setNewItem(event.target.value)} placeholder="Add something to the list…"/><Button type="submit">Add</Button></form>
    {items.length
      ? <div className="shopping-groups">{Object.entries(grouped).map(([category, group]) => <section key={category}>
          <div className="shopping-group-title"><h2>{category}</h2><span>{group.filter(item => !item.checked).length} left</span></div>
          <Card className="shopping-list">{group.map(item => {
            const mutation = mutationsByItem.get(item.id)
            return <div className={`shopping-item-block ${item.checked ? 'checked' : ''}`} key={item.id}>
              <div className={`shopping-row ${item.checked ? 'checked' : ''}`}>
                <label className="shopping-check-control" aria-label={`Mark ${item.name} ${item.checked ? 'not collected' : 'collected'}`}>
                  <input type="checkbox" checked={item.checked} onChange={() => toggle(item.id)}/>
                  <span className="custom-check"><Check/></span>
                </label>
                <span className="shopping-copy"><strong>{item.name}</strong>{(item.exact || item.pantryUsed) && <span>{item.exact}{item.exact && item.pantryUsed && <> · </>}{item.pantryUsed}</span>}</span>
                <span className="shopping-quantity">
                  <strong className="buy-amount">{item.buy}</strong>
                  {(item.quantityOptions?.length ?? 0) > 1 && <span className="shopping-unit-options" aria-label={`Display unit for ${item.name}`}>
                    {item.quantityOptions?.map(option => <button
                      type="button"
                      key={option.unit}
                      className={item.unit === option.unit ? 'active' : ''}
                      aria-pressed={item.unit === option.unit}
                      title={option.approximate ? `Approximate conversion to ${unitLabel(option.unit)}` : `Show in ${unitLabel(option.unit)}`}
                      onClick={() => selectUnit(item.id, option.unit)}
                    >{unitLabel(option.unit)}</button>)}
                  </span>}
                </span>
                {item.manual && <Badge>Manual</Badge>}
                {mutation?.status === 'pending' && <Badge tone="warning">Name pending</Badge>}
                <Button
                  type="button"
                  variant="ghost"
                  className="shopping-name-edit"
                  disabled={mutation?.status === 'conflict'}
                  aria-label={`Edit ${item.name}`}
                  onClick={() => startNameEdit(item)}
                ><Pencil size={16}/></Button>
              </div>
              {editingId === item.id && <form className="shopping-name-editor" onSubmit={event => finishNameEdit(event, item)}>
                <label>Ingredient name<input autoFocus maxLength={240} value={editingName} onChange={event => setEditingName(event.target.value)}/></label>
                <Button type="submit"><Save size={16}/>Save</Button>
                <Button type="button" variant="ghost" onClick={() => setEditingId('')}><X size={16}/>Cancel</Button>
              </form>}
              {mutation?.status === 'conflict' && <div className="shopping-name-conflict" role="alert">
                <div><strong>Name changed elsewhere</strong><p>The household list now says “{mutation.serverDisplayName}”; this device saved “{mutation.desiredDisplayName}”.</p></div>
                <div className="button-row">
                  <Button type="button" onClick={() => useMyName(mutation)}>Use mine</Button>
                  <Button type="button" variant="secondary" onClick={() => keepHouseholdName(mutation)}>Keep household name</Button>
                </div>
              </div>}
            </div>
          })}</Card>
        </section>)}</div>
      : <EmptyState icon={<ListChecks/>} title="Everything is done" description="Your active shopping list is empty."/>}
    <div className="shopping-footer"><RefreshCw/><p>Ingredient name edits are remembered for the household. Offline edits sync safely when this device reconnects.</p></div>
  </div>
}

function manualShoppingItem(name: string): ShoppingItem {
  return {
    id: crypto.randomUUID(),
    name,
    buy: '1',
    exact: 'Manual item',
    category: 'Other',
    checked: false,
    manual: true,
    updatedAt: Date.now(),
  }
}

export function mapShoppingItem(item: BackendShoppingItem): ShoppingItem {
  const exact = item.exact_quantity_display === item.purchase_quantity_display
    ? ''
    : `${item.exact_quantity_display} required`
  return {
    id: item.id,
    name: item.display_name,
    buy: item.purchase_quantity_display,
    exact,
    category: item.category,
    checked: item.checked,
    manual: item.manual,
    updatedAt: Date.now(),
    unit: item.unit,
    quantityOptions: (item.quantity_options ?? []).map(option => ({
      unit: option.unit,
      buy: option.purchase_quantity_display,
      exact: option.exact_quantity_display === option.purchase_quantity_display
        ? ''
        : `${option.exact_quantity_display} required`,
      approximate: option.approximate,
    })),
  }
}

function selectQuantityUnit(item: ShoppingItem, unit: string): ShoppingItem {
  const option = item.quantityOptions?.find(value => value.unit === unit)
  return option ? { ...item, unit, buy: option.buy, exact: option.exact } : item
}

function unitLabel(unit: string): string {
  return unit === 'cup' ? 'cups' : unit
}

function shoppingReviewHref(href: string): string {
  const separator = href.includes('?') ? '&' : '?'
  return `${href}${separator}returnTo=${encodeURIComponent('/shopping')}`
}
