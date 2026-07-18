import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowUpDown, Flag, PackageOpen, Plus, Search, SlidersHorizontal, Trash2 } from 'lucide-react'
import { FormEvent, useMemo, useState } from 'react'
import { api, isDemoMode, type BackendPantryItem, type BackendPantryMatchCandidate, type BackendPantryMatchSuggestion } from '../api/client'
import { Badge, Button, Card, Loading, Notice, PageHeader, Segmented } from '../components/ui'
import { demoPantry } from '../data/demo'
import type { PantryItem } from '../types'

export function PantryPage() {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'all' | 'soon' | 'low'>('all')
  const [sort, setSort] = useState<PantrySort>('alphabetical')
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [unit, setUnit] = useState('count')
  const [demoItems, setDemoItems] = useState(demoPantry)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const [editingQuantity, setEditingQuantity] = useState('')
  const [saving, setSaving] = useState(false)
  const [actionError, setActionError] = useState('')
  const [dismissedMatches, setDismissedMatches] = useState<string[]>([])
  const pantryQuery = useQuery({ queryKey: ['pantry'], queryFn: api.listPantry, enabled: !isDemoMode })
  const matchesQuery = useQuery({ queryKey: ['pantry-match-suggestions'], queryFn: api.pantryMatchSuggestions, enabled: !isDemoMode })
  const pantry: PantryItem[] = isDemoMode ? demoItems : (pantryQuery.data ?? []).map(mapPantryItem)
  const demoMatches: BackendPantryMatchSuggestion[] = [{ pantry_lot_id: 'p1', candidates: [{ food_record_id: 'demo-rice', display_name: 'Rice', confidence: .9 }] }]
  const matchSuggestions = isDemoMode ? demoMatches : (matchesQuery.data ?? [])
  const items = useMemo(() => sortPantryItems(pantry.filter(item =>
    item.name.toLowerCase().includes(query.toLowerCase())
    && (filter === 'all' || (filter === 'soon' && item.useSoon) || (filter === 'low' && isLowStock(item)))
  ), sort), [pantry, query, filter, sort])
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!name.trim()) return
    setActionError('')
    try {
      if (isDemoMode) {
        const numericQuantity = Number(quantity)
        setDemoItems(current => [...current, { id: `demo-${Date.now()}`, version: 1, name: name.trim(), initialQuantity: numericQuantity, quantity: numericQuantity, reserved: 0, unit, category: 'Pantry' }])
      } else {
        await api.addPantry({ display_name: name.trim(), quantity: Number(quantity), unit })
        await queryClient.invalidateQueries({ queryKey: ['pantry'] })
      }
      setName(''); setQuantity('1'); setAdding(false)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'The pantry item could not be added.')
    }
  }
  const startEditing = (item: PantryItem) => {
    setActionError('')
    setEditingId(item.id)
    setEditingName(item.name)
    setEditingQuantity(String(item.quantity))
  }
  const saveEdit = async (item: PantryItem) => {
    const nextQuantity = Number(editingQuantity)
    if (!editingName.trim() || !Number.isFinite(nextQuantity) || nextQuantity < 0) return
    setSaving(true)
    setActionError('')
    try {
      if (isDemoMode) {
        if (nextQuantity < item.reserved) throw new Error('Quantity cannot be lower than stock reserved by an accepted plan.')
        setDemoItems(current => current.map(candidate => candidate.id === item.id ? { ...candidate, name: editingName.trim(), quantity: nextQuantity, version: candidate.version + 1, quantityDisplay: undefined, usableDisplay: undefined } : candidate))
      } else {
        await api.updatePantry(item.id, { expected_version: item.version, display_name: editingName.trim(), quantity: nextQuantity })
        await queryClient.invalidateQueries({ queryKey: ['pantry'] })
      }
      setEditingId(null)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'The pantry item could not be saved.')
    } finally {
      setSaving(false)
    }
  }
  const deleteItem = async (item: PantryItem) => {
    if (!window.confirm(`Delete ${item.name} from the pantry?`)) return
    setSaving(true)
    setActionError('')
    try {
      if (isDemoMode) {
        if (item.reserved > 0) throw new Error('This item is reserved by an accepted plan and cannot be deleted.')
        setDemoItems(current => current.filter(candidate => candidate.id !== item.id))
      } else {
        await api.deletePantry(item.id)
        await queryClient.invalidateQueries({ queryKey: ['pantry'] })
      }
      setEditingId(null)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'The pantry item could not be deleted.')
    } finally {
      setSaving(false)
    }
  }
  const toggleUseSoon = async (item: PantryItem) => {
    setSaving(true)
    setActionError('')
    try {
      if (isDemoMode) {
        setDemoItems(current => current.map(candidate => candidate.id === item.id ? { ...candidate, useSoon: !candidate.useSoon, version: candidate.version + 1 } : candidate))
      } else {
        await api.updatePantry(item.id, { expected_version: item.version, display_name: item.name, quantity: item.quantity, use_soon: !item.useSoon })
        await queryClient.invalidateQueries({ queryKey: ['pantry'] })
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'The use-soon flag could not be changed.')
    } finally {
      setSaving(false)
    }
  }
  const confirmMatch = async (item: PantryItem, candidate: BackendPantryMatchCandidate) => {
    setSaving(true)
    setActionError('')
    try {
      if (isDemoMode) {
        setDemoItems(current => current.map(existing => existing.id === item.id ? { ...existing, foodRecordId: candidate.food_record_id, version: existing.version + 1 } : existing))
      } else {
        await api.confirmPantryMatch(item.id, { expected_version: item.version, food_record_id: candidate.food_record_id })
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ['pantry'] }),
          queryClient.invalidateQueries({ queryKey: ['pantry-match-suggestions'] }),
        ])
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'The pantry match could not be confirmed.')
    } finally {
      setSaving(false)
    }
  }
  const reservedCount = pantry.filter(item => item.reserved > 0).length
  return <div className="page">
    <PageHeader eyebrow="Household stock" title="Pantry" description="Available stock is reserved when you accept a plan and consumed only when you cook." actions={<Button onClick={() => setAdding(value => !value)}><Plus/>Add item</Button>}/>
    {adding && <Card><form className="form-grid" onSubmit={submit}><label>Ingredient<input required value={name} onChange={event => setName(event.target.value)}/></label><label>Quantity<input required min="0.01" step="any" type="number" value={quantity} onChange={event => setQuantity(event.target.value)}/></label><label>Unit<input required value={unit} onChange={event => setUnit(event.target.value)}/></label><Button>Add to pantry</Button></form></Card>}
    {pantryQuery.isLoading && <Loading label="Loading pantry…"/>}
    {pantryQuery.isError && <Notice tone="warning" title="Pantry unavailable">The server pantry could not be loaded.</Notice>}
    {actionError && <Notice tone="warning" title="Pantry not updated">{actionError}</Notice>}
    <div className="summary-cards"><Card><span className="summary-icon"><PackageOpen/></span><div><strong>{pantry.length}</strong><span>ingredients tracked</span></div></Card><Card><span className="summary-icon summary-icon--warm"><AlertTriangle/></span><div><strong>{pantry.filter(item => item.useSoon).length}</strong><span>flagged use soon</span></div></Card><Card><span className="summary-icon summary-icon--blue"><ArrowUpDown/></span><div><strong>{reservedCount}</strong><span>reserved by plan</span></div></Card></div>
    <div className="table-toolbar"><div className="small-search"><Search/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search pantry…"/></div><Segmented value={filter} onChange={setFilter} label="Pantry filter" options={[{value:'all',label:'All'},{value:'soon',label:'Use soon'},{value:'low',label:'Low stock'}]}/><label className="pantry-sort"><SlidersHorizontal aria-hidden="true"/><span>Sort</span><select aria-label="Sort pantry" value={sort} onChange={event => setSort(event.target.value as PantrySort)}><option value="alphabetical">Alphabetical</option><option value="stock-low">Lowest stock</option><option value="stock-high">Highest stock</option></select></label></div>
    {filter === 'low' && <p className="pantry-filter-help"><AlertTriangle/>Low stock is automatic when usable stock is 35% or less of the starting quantity. Accepted-plan reservations reduce the usable amount.</p>}
    <div className="pantry-list">{items.map(item => <PantryRow key={item.id} item={item} match={item.foodRecordId || dismissedMatches.includes(item.id) ? undefined : matchSuggestions.find(suggestion => suggestion.pantry_lot_id === item.id)?.candidates[0]} editing={editingId === item.id} editingName={editingName} editingQuantity={editingQuantity} saving={saving} onEditingName={setEditingName} onEditingQuantity={setEditingQuantity} onStartEditing={startEditing} onCancelEditing={() => setEditingId(null)} onSave={saveEdit} onDelete={deleteItem} onToggleUseSoon={toggleUseSoon} onConfirmMatch={confirmMatch} onDismissMatch={itemId => setDismissedMatches(current => [...current, itemId])}/>)}</div>
  </div>
}

function PantryRow({ item, match, editing, editingName, editingQuantity, saving, onEditingName, onEditingQuantity, onStartEditing, onCancelEditing, onSave, onDelete, onToggleUseSoon, onConfirmMatch, onDismissMatch }: {
  item: PantryItem
  match?: BackendPantryMatchCandidate
  editing: boolean
  editingName: string
  editingQuantity: string
  saving: boolean
  onEditingName: (value: string) => void
  onEditingQuantity: (value: string) => void
  onStartEditing: (item: PantryItem) => void
  onCancelEditing: () => void
  onSave: (item: PantryItem) => void
  onDelete: (item: PantryItem) => void
  onToggleUseSoon: (item: PantryItem) => void
  onConfirmMatch: (item: PantryItem, candidate: BackendPantryMatchCandidate) => void
  onDismissMatch: (itemId: string) => void
}) {
  const usable = item.quantity - item.reserved
  const width = Math.min(100, stockLevel(item) * 100)
  return <Card className={`pantry-item${editing ? ' pantry-item--editing' : ''}`}>
    <div className="pantry-icon">{item.name.slice(0, 1)}</div>
    {editing ? <>
      <div className="pantry-edit-fields">
        <label>Name<input autoFocus required value={editingName} onChange={event => onEditingName(event.target.value)}/></label>
        <label>On-hand quantity<div className="pantry-quantity-input"><input required min={item.reserved} step="any" type="number" value={editingQuantity} onChange={event => onEditingQuantity(event.target.value)}/><span>{item.unit}</span></div></label>
      </div>
      <div className="pantry-edit-note">{item.reserved > 0 ? `${item.reservedDisplay ?? `${item.reserved} ${item.unit}`} is reserved and cannot be removed.` : 'Set the current amount you have on hand.'}</div>
      <div className="pantry-edit-actions"><Button disabled={saving || !editingName.trim()} onClick={() => onSave(item)}>Save</Button><Button variant="ghost" disabled={saving} onClick={onCancelEditing}>Cancel</Button><Button variant="danger" disabled={saving} onClick={() => onDelete(item)}><Trash2/>Delete</Button></div>
    </> : <>
      <div className="pantry-name"><strong>{item.name}</strong><span>{item.foodRecordId ? 'Linked to saved recipes' : item.category}</span>{match && <div className="pantry-match"><span>Recipe match: <strong>{match.display_name}</strong></span><button type="button" disabled={saving} onClick={() => onConfirmMatch(item, match)}>Use as {match.display_name}</button><button type="button" disabled={saving} onClick={() => onDismissMatch(item.id)}>Not now</button></div>}</div>
      <div className="stock-meter"><div><span>Usable</span><strong>{item.usableDisplay ?? `${usable} ${item.unit}`}</strong></div><div className="macro-track"><span className="macro-fill macro-fill--green" style={{ width: `${width}%` }}/></div><small>{item.reservedDisplay ?? `${item.reserved} ${item.unit}`} reserved</small></div>
      <div className="pantry-tags">{item.useSoon && <Badge tone="warning">Use soon</Badge>}{isLowStock(item) && <Badge tone="warm">Low stock</Badge>}{item.expires && <Badge>Use by {item.expires}</Badge>}{item.staple && <Badge>Staple</Badge>}</div>
      <div className="pantry-row-actions"><Button variant="ghost" disabled={saving} onClick={() => onToggleUseSoon(item)}><Flag fill={item.useSoon ? 'currentColor' : 'none'}/>{item.useSoon ? 'Unflag' : 'Use soon'}</Button><Button variant="ghost" onClick={() => onStartEditing(item)}>Edit</Button></div>
    </>}
  </Card>
}

export function mapPantryItem(item: BackendPantryItem): PantryItem {
  return {
    id: item.id,
    foodRecordId: item.food_record_id,
    version: item.version,
    name: item.display_name,
    initialQuantity: Number(item.initial_quantity),
    quantity: Number(item.on_hand_quantity),
    unit: item.unit,
    reserved: Number(item.reserved_quantity),
    quantityDisplay: item.on_hand_quantity_display,
    reservedDisplay: item.reserved_quantity_display,
    usableDisplay: item.usable_quantity_display,
    category: 'Pantry',
    expires: item.expires_on,
    staple: item.always_have,
    useSoon: item.use_soon,
  }
}

export type PantrySort = 'alphabetical' | 'stock-low' | 'stock-high'

export function stockLevel(item: PantryItem): number {
  if (item.initialQuantity <= 0) return 0
  return Math.max(0, item.quantity - item.reserved) / item.initialQuantity
}

export function isLowStock(item: PantryItem): boolean {
  return stockLevel(item) <= .35
}

export function sortPantryItems(items: PantryItem[], sort: PantrySort): PantryItem[] {
  return [...items].sort((left, right) => {
    if (sort === 'alphabetical') return left.name.localeCompare(right.name)
    const difference = stockLevel(left) - stockLevel(right)
    return (sort === 'stock-low' ? difference : -difference) || left.name.localeCompare(right.name)
  })
}
