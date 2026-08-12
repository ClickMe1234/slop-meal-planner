import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, Check, ChefHat, Link2, RefreshCw, Scale, ShoppingBasket } from 'lucide-react'
import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  api,
  ApiError,
  type BackendShoppingIngredientChangePreview,
} from '../api/client'
import { Badge, Button, Card, EmptyState, Loading, Notice, PageHeader } from '../components/ui'
import {
  loadShoppingNameMutations,
  saveOfflineShoppingContext,
  saveShoppingItems,
} from '../lib/offlineShopping'
import { mapShoppingItem } from './ShoppingPage'

const recipeUnitOptions = [
  'g', 'kg', 'ml', 'l', 'tsp', 'tbsp', 'cup', 'item', 'can', 'clove', 'slice',
]

export function ShoppingItemDetailPage() {
  const { listId = '', itemId = '' } = useParams()
  const detail = useQuery({
    queryKey: ['shopping-item-sources', listId, itemId],
    queryFn: () => api.shoppingItemSources(listId, itemId),
    enabled: Boolean(listId && itemId),
    retry: false,
  })
  if (detail.isLoading) {
    return <div className="page"><PageHeader title="Ingredient details"/><Loading label="Finding recipe sources…"/></div>
  }
  if (detail.isError || !detail.data) {
    return <div className="page"><PageHeader title="Ingredient unavailable"/><Notice tone="warning" title="Could not open this ingredient">{detail.error instanceof Error ? detail.error.message : 'Reload the shopping list and try again.'}</Notice><Link className="button button--primary" to="/shopping">Back to shopping</Link></div>
  }
  const { item, sources, editable } = detail.data
  return <div className="page page--wide shopping-source-page">
    <div className="review-top"><Link className="icon-link" to="/shopping"><ArrowLeft/>Back to shopping</Link><Badge tone={editable ? 'green' : 'warning'}>{editable ? 'Recipe linked' : 'Read only'}</Badge></div>
    <PageHeader
      eyebrow={item.purchase_quantity_display}
      title={item.display_name}
      description="See exactly which saved recipes created this shopping requirement."
      actions={editable ? <>
        <Link className="button button--secondary" to={`/shopping/${listId}/ingredient-change?mode=unit&items=${item.id}`}><Scale/>Change unit</Link>
        <Link className="button button--primary" to={`/shopping/${listId}/ingredient-change?mode=combine&items=${item.id}`}><Link2/>Combine item<ArrowRight/></Link>
      </> : undefined}
    />
    {!editable && <Notice tone="warning" title={sources.some(source => source.cooked) ? 'A contributing batch is already cooked' : 'Recipe editing unavailable'}>{sources.some(source => source.cooked) ? 'Cooked batches keep the exact recipe version that was used. This shopping line can still be reviewed here.' : 'Rebuild this plan-backed shopping list before changing linked recipes.'}</Notice>}
    <section className="shopping-source-section">
      <div className="section-heading"><div><p className="eyebrow">Recipe provenance</p><h2>Used in {new Set(sources.map(source => source.recipe_id)).size} recipes</h2></div><Badge>{sources.length} ingredient {sources.length === 1 ? 'row' : 'rows'}</Badge></div>
      {sources.length ? <div className="shopping-source-grid">{sources.map(source => <Card className="shopping-source-card" key={source.recipe_ingredient_id}>
        <div className="shopping-source-card-heading"><ChefHat/><div><strong>{source.recipe_title}</strong><span>{source.meal_dates.map(date => new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })).join(' · ')}</span></div>{source.cooked && <Badge tone="warning">Cooked</Badge>}</div>
        <blockquote>{source.original_text}</blockquote>
        <dl><div><dt>In the recipe</dt><dd>{source.recipe_quantity ?? '—'} {source.recipe_unit ?? ''}</dd></div><div><dt>For this plan</dt><dd>{Number(source.plan_quantity).toLocaleString()} {source.plan_unit}</dd></div></dl>
        {source.preparation && <small>Preparation: {source.preparation}</small>}
      </Card>)}</div> : <EmptyState icon={<ShoppingBasket/>} title="No recipe sources recorded" description="Rebuild the active shopping list to add recipe links to existing items."/>}
    </section>
  </div>
}

export function ShoppingIngredientChangePage() {
  const { listId = '' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const mode = searchParams.get('mode') === 'combine' ? 'combine' : 'unit'
  const selectedIds = useMemo(
    () => Array.from(new Set((searchParams.get('items') ?? '').split(',').filter(Boolean))),
    [searchParams],
  )
  const navigate = useNavigate()
  const list = useQuery({
    queryKey: ['shopping-list', listId],
    queryFn: api.activeShoppingList,
    enabled: Boolean(listId),
    retry: false,
  })
  const [targetName, setTargetName] = useState('')
  const [targetUnit, setTargetUnit] = useState('')
  const [preview, setPreview] = useState<BackendShoppingIngredientChangePreview | null>(null)
  const [manualQuantities, setManualQuantities] = useState<Record<string, string>>({})
  const [pendingNameEdits, setPendingNameEdits] = useState(0)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')

  const selected = (list.data?.items ?? []).filter(item => selectedIds.includes(item.id))
  const base = selected[0]
  useEffect(() => {
    if (!base) return
    setTargetName(current => current || base.display_name)
    setTargetUnit(current => current || base.unit)
  }, [base])
  useEffect(() => {
    loadShoppingNameMutations().then(mutations => {
      setPendingNameEdits(mutations.filter(item => item.listId === listId).length)
    }).catch(() => setPendingNameEdits(0))
  }, [listId])

  const toggleItem = (itemId: string) => {
    const next = selectedIds.includes(itemId)
      ? selectedIds.filter(id => id !== itemId)
      : [...selectedIds, itemId]
    const params = new URLSearchParams(searchParams)
    params.set('items', next.join(','))
    setSearchParams(params, { replace: true })
    setPreview(null)
    setManualQuantities({})
  }
  const requestPreview = async (event: FormEvent) => {
    event.preventDefault()
    if (!targetName.trim() || !targetUnit || (mode === 'combine' && selectedIds.length < 2)) return
    setWorking(true)
    setError('')
    try {
      const next = await api.previewShoppingIngredientChange(listId, {
        item_ids: selectedIds,
        target_name: targetName.trim(),
        target_unit: targetUnit,
      })
      setPreview(next)
      setManualQuantities({})
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The conversion preview could not be created.')
    } finally {
      setWorking(false)
    }
  }
  const apply = async () => {
    if (!preview || !list.data) return
    const missing = preview.conversions.filter(value => value.manual_quantity_required && Number(manualQuantities[value.recipe_ingredient_id]) <= 0)
    if (missing.length) {
      setError('Enter a positive equivalent quantity for every highlighted recipe.')
      return
    }
    setWorking(true)
    setError('')
    try {
      const result = await api.applyShoppingIngredientChange(listId, {
        expected_list_version: list.data.version,
        item_ids: selectedIds,
        target_name: preview.target_name,
        target_unit: preview.target_unit,
        manual_conversions: preview.conversions.filter(value => value.manual_quantity_required).map(value => ({
          recipe_ingredient_id: value.recipe_ingredient_id,
          quantity: Number(manualQuantities[value.recipe_ingredient_id]),
        })),
      })
      const mapped = result.shopping_list.items.map(mapShoppingItem)
      await saveShoppingItems(mapped)
      saveOfflineShoppingContext({
        listId: result.shopping_list.id,
        mealPlanId: result.shopping_list.meal_plan_id ?? '',
        rebuildRecommended: result.shopping_list.rebuild_recommended,
      })
      navigate(`/shopping/${result.shopping_list.id}/items/${result.result_item_id}`)
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The recipes and shopping list could not be updated.')
    } finally {
      setWorking(false)
    }
  }

  if (list.isLoading) return <div className="page"><PageHeader title="Change shopping ingredient"/><Loading label="Opening the current list…"/></div>
  if (!list.data || list.data.id !== listId || !base) return <div className="page"><PageHeader title="Shopping item unavailable"/><Notice tone="warning" title="Reload required">This is no longer the active shopping list.</Notice><Link className="button button--primary" to="/shopping">Back to shopping</Link></div>
  const candidates = list.data.items
    .filter(item => !item.manual && (item.source_count ?? 0) > 0)
    .sort((left, right) => Number(selectedIds.includes(right.id)) - Number(selectedIds.includes(left.id)))
  const unitChoices = Array.from(new Set([...(base.available_units ?? []), base.unit, ...recipeUnitOptions]))
  const canPreview = navigator.onLine && !pendingNameEdits && selectedIds.length >= (mode === 'combine' ? 2 : 1) && Boolean(targetName.trim() && targetUnit)

  return <div className="page page--wide shopping-change-page">
    <div className="review-top"><Link className="icon-link" to={mode === 'unit' ? `/shopping/${listId}/items/${base.id}` : '/shopping'}><ArrowLeft/>Cancel</Link><Badge tone="warning">Permanent recipe change</Badge></div>
    <PageHeader eyebrow={mode === 'combine' ? 'Combine shopping items' : 'Recipe-linked unit'} title={mode === 'combine' ? 'Make these one ingredient' : `Change the unit for ${base.display_name}`} description="The app will create new recipe versions, update the current plan, and rebuild the shopping list together."/>
    {!navigator.onLine && <Notice tone="warning" title="Reconnect to continue">Recipe-linked shopping changes cannot be queued offline.</Notice>}
    {pendingNameEdits > 0 && <Notice tone="warning" title="Finish syncing name edits">Return to the shopping list and resolve or sync {pendingNameEdits} pending name {pendingNameEdits === 1 ? 'edit' : 'edits'} first.</Notice>}
    {error && <Notice tone="warning" title="Could not continue">{error}</Notice>}
    <div className="shopping-change-layout">
      <Card className="shopping-change-form">
        <div className="shopping-change-step-heading"><span>1</span><div><p className="eyebrow">Choose the result</p><h2>{mode === 'combine' ? 'Select items to combine' : 'Set the new unit'}</h2></div></div>
        {mode === 'combine' && <section className="shopping-combine-section" aria-labelledby="shopping-combine-heading">
          <div className="shopping-combine-heading"><div><strong id="shopping-combine-heading">Recipe-backed shopping items</strong><small>Select at least two items. Your starting item is pinned at the top.</small></div><Badge tone={selectedIds.length >= 2 ? 'green' : 'neutral'}>{selectedIds.length} selected</Badge></div>
          <fieldset className="shopping-combine-picker"><legend className="sr-only">Recipe-backed shopping items</legend><div className="shopping-combine-options">{candidates.map(item => <label key={item.id} className={selectedIds.includes(item.id) ? 'selected' : ''}><input type="checkbox" checked={selectedIds.includes(item.id)} onChange={() => toggleItem(item.id)}/><span><strong>{item.display_name}</strong><small>{item.purchase_quantity_display} · {item.recipe_count} {item.recipe_count === 1 ? 'recipe' : 'recipes'}</small></span>{selectedIds.includes(item.id) && <Check/>}</label>)}</div></fieldset>
        </section>}
        <form className="shopping-result-form" onSubmit={requestPreview}>
          <div className="shopping-result-heading"><strong>Resulting ingredient</strong><small>This name and unit will be used when the shopping list is rebuilt.</small></div>
          <div className="shopping-result-fields">
            <label>Ingredient name<input value={targetName} disabled={mode === 'unit'} maxLength={240} onChange={event => { setTargetName(event.target.value); setPreview(null) }}/></label>
            <label>Target unit<select value={targetUnit} onChange={event => { setTargetUnit(event.target.value); setPreview(null) }}>{unitChoices.map(unit => <option key={unit} value={unit}>{unit}</option>)}</select></label>
          </div>
          <Button type="submit" disabled={!canPreview || working}>{working && !preview ? 'Checking recipes…' : 'Preview recipe changes'}<ArrowRight/></Button>
        </form>
      </Card>
      <Card className="shopping-change-preview">
        <div className="shopping-change-step-heading"><span>2</span><div><p className="eyebrow">Review every recipe</p><h2>Check the changes</h2></div></div>
        {!preview && <div className="shopping-change-placeholder"><span><RefreshCw/></span><strong>{mode === 'combine' && selectedIds.length < 2 ? 'Choose one more item' : 'Ready for a preview'}</strong><p>{mode === 'combine' && selectedIds.length < 2 ? 'Select another shopping item on the left, then confirm the resulting name and unit.' : 'Preview to see every saved recipe change before anything is updated.'}</p></div>}
        {preview && <>
          <div className="shopping-change-summary"><Scale/><div><strong>{selected.length} shopping {selected.length === 1 ? 'line' : 'lines'} → {preview.target_name}</strong><span>{preview.conversions.length} saved recipe ingredient {preview.conversions.length === 1 ? 'row' : 'rows'} will change to {preview.target_unit}</span></div></div>
          <div className="shopping-conversion-list">{preview.conversions.map(conversion => <div className={`shopping-conversion-row${conversion.manual_quantity_required ? ' needs-input' : ''}`} key={conversion.recipe_ingredient_id}>
            <ChefHat/><div><strong>{conversion.recipe_title}</strong><span>{conversion.original_text}</span><small>{Number(conversion.current_quantity).toLocaleString()} {conversion.current_unit}</small></div>
            {conversion.manual_quantity_required
              ? <label>Equivalent amount<input type="number" min="0.0001" step="any" value={manualQuantities[conversion.recipe_ingredient_id] ?? ''} onChange={event => setManualQuantities(current => ({ ...current, [conversion.recipe_ingredient_id]: event.target.value }))}/><span>{preview.target_unit}</span></label>
              : <div className="shopping-conversion-result"><Check/><strong>{Number(conversion.target_quantity).toLocaleString()} {preview.target_unit}</strong><small>Converted safely</small></div>}
          </div>)}</div>
          <Notice title="Saved recipes are the source of truth">Separate ingredient rows inside the same recipe will stay separate. The rebuilt shopping list will total them.</Notice>
          <Button disabled={working || !canPreview} onClick={apply}>{working ? 'Updating recipes and shopping…' : 'Apply recipe changes'}<ArrowRight/></Button>
        </>}
      </Card>
    </div>
  </div>
}
