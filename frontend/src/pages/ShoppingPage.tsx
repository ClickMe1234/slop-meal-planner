import { Check, Clipboard, Download, ListChecks, Plus, RefreshCw, Share2, ShoppingBasket, Wifi, WifiOff } from 'lucide-react'
import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Badge, Button, Card, EmptyState, PageHeader } from '../components/ui'
import { initialShopping } from '../data/demo'
import { loadShoppingItems, saveShoppingItems, shoppingAsText } from '../lib/offlineShopping'
import type { ShoppingItem } from '../types'
import { api, isDemoMode, type BackendShoppingItem } from '../api/client'

export function ShoppingPage() {
  const [items,setItems] = useState<ShoppingItem[]>([])
  const [loaded,setLoaded] = useState(false)
  const [online,setOnline] = useState(navigator.onLine)
  const [newItem,setNewItem] = useState('')
  const [notice,setNotice] = useState('')
  const [listId,setListId] = useState('')
  const [versions,setVersions] = useState<Record<string,number>>({})
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      if (isDemoMode) {
        const value = await loadShoppingItems(initialShopping)
        if (!cancelled) { setItems(value); setLoaded(true) }
        return
      }
      try {
        const server = await api.activeShoppingList()
        const serverItems = server.items.map(mapShoppingItem)
        const cached = await loadShoppingItems(serverItems)
        const cachedById = new Map(cached.map(item => [item.id,item]))
        const merged = serverItems.map(item => cachedById.has(item.id) ? { ...item, checked: cachedById.get(item.id)!.checked, updatedAt: cachedById.get(item.id)!.updatedAt } : item)
        const nextVersions = Object.fromEntries(server.items.map(item => [item.id,item.version]))
        if (!cancelled) { setListId(server.id); setVersions(nextVersions); setItems(merged); setLoaded(true) }
        for (const original of server.items) {
          const local = cachedById.get(original.id)
          if (local && local.checked !== original.checked) {
            const updated = await api.patchShoppingItem(server.id, original.id, { expected_version: nextVersions[original.id], checked: local.checked })
            nextVersions[original.id] = updated.version
          }
        }
        if (!cancelled) { setVersions({...nextVersions}); await saveShoppingItems(merged) }
      } catch {
        const cached = await loadShoppingItems([])
        if (!cancelled) { setItems(cached); setLoaded(true); setNotice('Working from the offline copy until the server is available.') }
      }
    }
    load()
    return () => { cancelled = true }
  },[])
  useEffect(() => { const up=()=>setOnline(true),down=()=>setOnline(false); addEventListener('online',up);addEventListener('offline',down);return()=>{removeEventListener('online',up);removeEventListener('offline',down)} },[])
  useEffect(() => { if(loaded) saveShoppingItems(items).catch(()=>setNotice('Changes are saved in this browser only.')) },[items,loaded])
  const grouped = useMemo(() => items.reduce<Record<string,ShoppingItem[]>>((out,item)=>{(out[item.category]??=[]).push(item);return out},{}),[items])
  const completed=items.filter(item=>item.checked).length
  const toggle=async(id:string)=>{
    const current=items.find(item=>item.id===id); if(!current)return
    const checked=!current.checked
    setItems(all=>all.map(item=>item.id===id?{...item,checked,updatedAt:Date.now()}:item))
    if(!isDemoMode&&online&&listId&&versions[id])try{const updated=await api.patchShoppingItem(listId,id,{expected_version:versions[id],checked});setVersions(all=>({...all,[id]:updated.version}))}catch{setNotice('Saved offline. This change will be reconciled when the list reloads.')}
  }
  const add=async(event:FormEvent)=>{event.preventDefault();if(!newItem.trim())return;const name=newItem.trim();if(!isDemoMode&&online&&listId)try{const item=await api.addShoppingItem(listId,{display_name:name,exact_quantity:1,purchase_quantity:1,unit:'count',category:'Other'});setItems(all=>[...all,mapShoppingItem(item)]);setVersions(all=>({...all,[item.id]:item.version}))}catch{setItems(all=>[...all,{id:crypto.randomUUID(),name,buy:'1',exact:'Manual item',category:'Other',checked:false,manual:true,updatedAt:Date.now()}])}else setItems(all=>[...all,{id:crypto.randomUUID(),name,buy:'1',exact:'Manual item',category:'Other',checked:false,manual:true,updatedAt:Date.now()}]);setNewItem('')}
  const addPurchased=async()=>{if(!listId)return;try{await api.addPurchasedToPantry(listId);setItems(all=>all.map(item=>({...item,checked:false})));setNotice('Purchased items were added to the pantry.')}catch{setNotice('Tick at least one purchased item before adding it to the pantry.')}}
  const text=()=>shoppingAsText(items)
  const share=async()=>{try{if(navigator.share)await navigator.share({title:'Savour shopping list',text:text()});else{await navigator.clipboard.writeText(text());setNotice('Shopping list copied to clipboard.')}}catch{/* user cancelled */}}
  const copy=async()=>{await navigator.clipboard.writeText(text());setNotice('Shopping list copied to clipboard.')}
  const download=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text()],{type:'text/plain'}));a.download='savour-shopping-list.txt';a.click();URL.revokeObjectURL(a.href)}
  return <div className="page"><PageHeader eyebrow="20–26 July" title="Shopping list" description="Rounded to practical amounts after using what is already in your pantry." actions={<><Button variant="secondary" onClick={share}><Share2/>Share</Button><Button variant="ghost" onClick={copy}><Clipboard/>Copy</Button><Button variant="ghost" onClick={download}><Download/>.txt</Button>{!isDemoMode&&<Button onClick={addPurchased}>Add purchased to pantry</Button>}</>}/><div className="shopping-status"><div className="shopping-progress"><div><ShoppingBasket/><span><strong>{completed} of {items.length}</strong><small>items collected</small></span></div><div className="progress-bar"><span style={{width:`${items.length ? completed/items.length*100:0}%`}}/></div></div><Badge tone={online?'green':'warning'}>{online?<Wifi size={14}/>:<WifiOff size={14}/>} {online?'Synced':'Working offline'}</Badge></div>{notice&&<button className="toast" onClick={()=>setNotice('')}><Check/>{notice}</button>}<form className="quick-add" onSubmit={add}><Plus/><input value={newItem} onChange={e=>setNewItem(e.target.value)} placeholder="Add something to the list…"/><Button type="submit">Add</Button></form>{items.length?<div className="shopping-groups">{Object.entries(grouped).map(([category,group])=><section key={category}><div className="shopping-group-title"><h2>{category}</h2><span>{group.filter(item=>!item.checked).length} left</span></div><Card className="shopping-list">{group.map(item=><label key={item.id} className={`shopping-row ${item.checked?'checked':''}`}><input type="checkbox" checked={item.checked} onChange={()=>toggle(item.id)}/><span className="custom-check"><Check/></span><span className="shopping-copy"><strong>{item.name}</strong><span>{item.exact}{item.pantryUsed&&<> · {item.pantryUsed}</>}</span></span><strong className="buy-amount">{item.buy}</strong>{item.manual&&<Badge>Manual</Badge>}</label>)}</Card></section>)}</div>:<EmptyState icon={<ListChecks/>} title="Everything is done" description="Your active shopping list is empty."/>}<div className="shopping-footer"><RefreshCw/><p>Plan changes are shown as a diff before this list updates. Manual items and checked state are preserved.</p></div></div>
}

function mapShoppingItem(item: BackendShoppingItem): ShoppingItem {
  return { id:item.id,name:item.display_name,buy:`${item.purchase_quantity} ${item.unit}`,exact:`Exact: ${item.exact_quantity} ${item.unit}`,category:item.category,checked:item.checked,manual:item.manual,updatedAt:Date.now() }
}
