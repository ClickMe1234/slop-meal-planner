import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowUpDown, PackageOpen, Plus, Search, SlidersHorizontal } from 'lucide-react'
import { FormEvent, useMemo, useState } from 'react'
import { api, isDemoMode, type BackendPantryItem } from '../api/client'
import { Badge, Button, Card, Loading, Notice, PageHeader, Segmented } from '../components/ui'
import { demoPantry } from '../data/demo'
import type { PantryItem } from '../types'

export function PantryPage() {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'all' | 'soon' | 'low'>('all')
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [unit, setUnit] = useState('count')
  const pantryQuery = useQuery({ queryKey: ['pantry'], queryFn: api.listPantry, enabled: !isDemoMode })
  const pantry: PantryItem[] = isDemoMode ? demoPantry : (pantryQuery.data ?? []).map(mapPantryItem)
  const items = useMemo(() => pantry.filter(item =>
    item.name.toLowerCase().includes(query.toLowerCase())
    && (filter === 'all' || (filter === 'soon' && Boolean(item.expires)) || (filter === 'low' && item.quantity - item.reserved <= item.quantity * .35))
  ), [pantry, query, filter])
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (isDemoMode || !name.trim()) { setAdding(false); return }
    await api.addPantry({ display_name: name.trim(), quantity: Number(quantity), unit })
    setName(''); setQuantity('1'); setAdding(false)
    await queryClient.invalidateQueries({ queryKey: ['pantry'] })
  }
  const reservedCount = pantry.filter(item => item.reserved > 0).length
  return <div className="page">
    <PageHeader eyebrow="Household stock" title="Pantry" description="Available stock is reserved when you accept a plan and consumed only when you cook." actions={<Button onClick={() => setAdding(value => !value)}><Plus/>Add item</Button>}/>
    {adding && <Card><form className="form-grid" onSubmit={submit}><label>Ingredient<input required value={name} onChange={event => setName(event.target.value)}/></label><label>Quantity<input required min="0.01" step="any" type="number" value={quantity} onChange={event => setQuantity(event.target.value)}/></label><label>Unit<input required value={unit} onChange={event => setUnit(event.target.value)}/></label><Button>Add to pantry</Button></form></Card>}
    {pantryQuery.isLoading && <Loading label="Loading pantry…"/>}
    {pantryQuery.isError && <Notice tone="warning" title="Pantry unavailable">The server pantry could not be loaded.</Notice>}
    <div className="summary-cards"><Card><span className="summary-icon"><PackageOpen/></span><div><strong>{pantry.length}</strong><span>ingredients tracked</span></div></Card><Card><span className="summary-icon summary-icon--warm"><AlertTriangle/></span><div><strong>{pantry.filter(item => item.expires).length}</strong><span>use soon</span></div></Card><Card><span className="summary-icon summary-icon--blue"><ArrowUpDown/></span><div><strong>{reservedCount}</strong><span>reserved by plan</span></div></Card></div>
    <div className="table-toolbar"><div className="small-search"><Search/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search pantry…"/></div><Segmented value={filter} onChange={setFilter} label="Pantry filter" options={[{value:'all',label:'All'},{value:'soon',label:'Use soon'},{value:'low',label:'Low stock'}]}/><Button variant="ghost"><SlidersHorizontal/>Sort</Button></div>
    <div className="pantry-list">{items.map(item => { const usable = item.quantity - item.reserved; const width = item.quantity > 0 ? Math.max(0, usable / item.quantity * 100) : 0; return <Card key={item.id} className="pantry-item"><div className="pantry-icon">{item.name.slice(0,1)}</div><div className="pantry-name"><strong>{item.name}</strong><span>{item.category}</span></div><div className="stock-meter"><div><span>Usable</span><strong>{item.usableDisplay ?? `${usable} ${item.unit}`}</strong></div><div className="macro-track"><span className="macro-fill macro-fill--green" style={{width:`${width}%`}}/></div><small>{item.reservedDisplay ?? `${item.reserved} ${item.unit}`} reserved</small></div><div className="pantry-tags">{item.expires && <Badge tone="warning">Use by {item.expires}</Badge>}{item.staple && <Badge>Staple</Badge>}</div><Button variant="ghost">Edit</Button></Card>})}</div>
  </div>
}

export function mapPantryItem(item: BackendPantryItem): PantryItem {
  return {
    id: item.id,
    name: item.display_name,
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
