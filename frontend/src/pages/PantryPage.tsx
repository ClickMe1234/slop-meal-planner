import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowUpDown, PackageOpen, Plus, Search, SlidersHorizontal, Trash2 } from 'lucide-react'
import { FormEvent, useMemo, useState } from 'react'
import { api, isDemoMode, type BackendPantryItem } from '../api/client'
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
  const pantryQuery = useQuery({ queryKey: ['pantry'], queryFn: api.listPantry, enabled: !isDemoMode })
  const pantry: PantryItem[] = isDemoMode ? demoItems : (pantryQuery.data ?? []).map(mapPantryItem)
  const items = useMemo(() => sortPantryItems(pantry.filter(item =>
    item.name.toLowerCase().includes(query.toLowerCase())
    && (filter === 'all' || (filter === 'soon' && Boolean(item.expires)) || (filter === 'low' && stockLevel(item) <= .35))
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
  const reservedCount = pantry.filter(item => item.reserved > 0).length
  return <div className="page">
    <PageHeader eyebrow="Household stock" title="Pantry" description="Available stock is reserved when you accept a plan and consumed only when you cook." actions={<Button onClick={() => setAdding(value => !value)}><Plus/>Add item</Button>}/>
    {adding && <Card><form className="form-grid" onSubmit={submit}><label>Ingredient<input required value={name} onChange={event => setName(event.target.value)}/></label><label>Quantity<input required min="0.01" step="any" type="number" value={quantity} onChange={event => setQuantity(event.target.value)}/></label><label>Unit<input required value={unit} onChange={event => setUnit(event.target.value)}/></label><Button>Add to pantry</Button></form></Card>}
    {pantryQuery.isLoading && <Loading label="Loading pantry…"/>}
    {pantryQuery.isError && <Notice tone="warning" title="Pantry unavailable">The server pantry could not be loaded.</Notice>}
    {actionError && <Notice tone="warning" title="Pantry not updated">{actionError}</Notice>}
    <div className="summary-cards"><Card><span className="summary-icon"><PackageOpen/></span><div><strong>{pantry.length}</strong><span>ingredients tracked</span></div></Card><Card><span className="summary-icon summary-icon--warm"><AlertTriangle/></span><div><strong>{pantry.filter(item => item.expires).length}</strong><span>use soon</span></div></Card><Card><span className="summary-icon summary-icon--blue"><ArrowUpDown/></span><div><strong>{reservedCount}</strong><span>reserved by plan</span></div></Card></div>
    <div className="table-toolbar"><div className="small-search"><Search/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search pantry…"/></div><Segmented value={filter} onChange={setFilter} label="Pantry filter" options={[{value:'all',label:'All'},{value:'soon',label:'Use soon'},{value:'low',label:'Low stock'}]}/><label className="pantry-sort"><SlidersHorizontal aria-hidden="true"/><span>Sort</span><select aria-label="Sort pantry" value={sort} onChange={event => setSort(event.target.value as PantrySort)}><option value="alphabetical">Alphabetical</option><option value="stock-low">Lowest stock</option><option value="stock-high">Highest stock</option></select></label></div>
    <div className="pantry-list">{items.map(item => { const usable = item.quantity - item.reserved; const width = item.initialQuantity > 0 ? Math.max(0, Math.min(100, usable / item.initialQuantity * 100)) : 0; return <Card key={item.id} className={`pantry-item${editingId === item.id ? ' pantry-item--editing' : ''}`}><div className="pantry-icon">{item.name.slice(0,1)}</div>{editingId === item.id ? <><div className="pantry-edit-fields"><label>Name<input autoFocus required value={editingName} onChange={event => setEditingName(event.target.value)}/></label><label>On-hand quantity<div className="pantry-quantity-input"><input required min={item.reserved} step="any" type="number" value={editingQuantity} onChange={event => setEditingQuantity(event.target.value)}/><span>{item.unit}</span></div></label></div><div className="pantry-edit-note">{item.reserved > 0 ? `${item.reservedDisplay ?? `${item.reserved} ${item.unit}`} is reserved and cannot be removed.` : 'Set the current amount you have on hand.'}</div><div className="pantry-edit-actions"><Button disabled={saving || !editingName.trim()} onClick={() => saveEdit(item)}>Save</Button><Button variant="ghost" disabled={saving} onClick={() => setEditingId(null)}>Cancel</Button><Button variant="danger" disabled={saving} onClick={() => deleteItem(item)}><Trash2/>Delete</Button></div></> : <><div className="pantry-name"><strong>{item.name}</strong><span>{item.category}</span></div><div className="stock-meter"><div><span>Usable</span><strong>{item.usableDisplay ?? `${usable} ${item.unit}`}</strong></div><div className="macro-track"><span className="macro-fill macro-fill--green" style={{width:`${width}%`}}/></div><small>{item.reservedDisplay ?? `${item.reserved} ${item.unit}`} reserved</small></div><div className="pantry-tags">{item.expires && <Badge tone="warning">Use by {item.expires}</Badge>}{item.staple && <Badge>Staple</Badge>}</div><Button variant="ghost" onClick={() => startEditing(item)}>Edit</Button></>}</Card>})}</div>
  </div>
}

export function mapPantryItem(item: BackendPantryItem): PantryItem {
  return {
    id: item.id,
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
  }
}

export type PantrySort = 'alphabetical' | 'stock-low' | 'stock-high'

export function stockLevel(item: PantryItem): number {
  if (item.initialQuantity <= 0) return 0
  return Math.max(0, item.quantity - item.reserved) / item.initialQuantity
}

export function sortPantryItems(items: PantryItem[], sort: PantrySort): PantryItem[] {
  return [...items].sort((left, right) => {
    if (sort === 'alphabetical') return left.name.localeCompare(right.name)
    const difference = stockLevel(left) - stockLevel(right)
    return (sort === 'stock-low' ? difference : -difference) || left.name.localeCompare(right.name)
  })
}
