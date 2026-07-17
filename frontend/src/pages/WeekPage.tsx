import { Check, ChefHat, ChevronLeft, ChevronRight, Clock3, ExternalLink, RefreshCw, Scale } from 'lucide-react'
import { useMemo, useState, type CSSProperties } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { NutritionRings } from '../components/Nutrition'
import { Badge, Button, Card, EmptyState, Loading, Notice, PageHeader } from '../components/ui'
import { demoRecipes, demoWeek } from '../data/demo'
import { api, isDemoMode, type BackendPlanDetail } from '../api/client'
import { compareMealTypes } from './planner'

type NutritionTotals = { calories: number; protein: number; carbs: number; fat: number }
const emptyNutrition = (): NutritionTotals => ({ calories: 0, protein: 0, carbs: 0, fat: 0 })

export function WeekPage() {
  return isDemoMode ? <DemoWeekPage/> : <LiveWeekPage/>
}

function RecipePreview({ imageUrl }: { imageUrl?: string }) {
  return <div className="meal-preview" aria-hidden="true">
    {imageUrl ? <img src={imageUrl} alt=""/> : <ChefHat/>}
  </div>
}

function MealBatchInfo({ label, servings }: { label: string; servings: string }) {
  return <div className="meal-batch"><Clock3/><div><span>{label}</span><strong>{servings}</strong></div></div>
}

function mealTypeLabel(value: string) {
  return value.charAt(0).toLocaleUpperCase() + value.slice(1)
}

function groupByMealType<T>(items: T[], key: (item: T) => string) {
  const groups = new Map<string, T[]>()
  items.forEach(item => {
    const mealType = key(item)
    groups.set(mealType, [...(groups.get(mealType) ?? []), item])
  })
  return Array.from(groups.entries())
}

function RecipeTitle({ title, sourceUrl }: { title: string; sourceUrl?: string }) {
  return sourceUrl && sourceUrl !== '#'
    ? <h3><a href={sourceUrl} target="_blank" rel="noreferrer">{title}<ExternalLink size={14}/></a></h3>
    : <h3>{title}</h3>
}

function CookControl({ cooked, pending = false, onClick }: { cooked: boolean; pending?: boolean; onClick: () => void }) {
  return <button
    type="button"
    className={`cook-control${cooked ? ' is-cooked' : ''}`}
    onClick={onClick}
    disabled={pending}
    aria-label={cooked ? 'Unmark recipe cooked' : 'Mark recipe cooked'}
  >
    <span className="cook-control__icon">{cooked ? <Check/> : <ChefHat/>}</span>
    <strong>{pending ? 'Saving…' : cooked ? 'Cooked' : 'Mark cooked'}</strong>
  </button>
}

export function BatchWeightControl({ servings, portions, savedWeight, draft, pending = false, onDraftChange, onSave, onClear }: {
  servings: number
  portions: Array<{ memberId: string; name: string; servings: number }>
  savedWeight?: number
  draft: string
  pending?: boolean
  onDraftChange: (value: string) => void
  onSave: () => void
  onClear: () => void
}) {
  const numericWeight = Number(draft)
  const validWeight = draft.trim() !== '' && Number.isFinite(numericWeight) && numericWeight > 0
  const gramsPerServing = validWeight && servings > 0 ? numericWeight / servings : undefined

  return <form className="batch-weight" aria-label="Cooked batch weight" onSubmit={event => { event.preventDefault(); onSave() }}>
    <div className="batch-weight__heading"><span><Scale/></span><div><strong>Portion by weight</strong><small>Optional · weigh the finished batch</small></div></div>
    <label className="batch-weight__input"><span className="sr-only">Total cooked batch weight</span><span className="input-suffix"><input type="number" min="1" step="1" inputMode="numeric" placeholder="Total weight" aria-label="Total cooked batch weight" value={draft} onChange={event => onDraftChange(event.target.value)}/><span>g</span></span></label>
    <output className="batch-weight__result" aria-live="polite">
      <span>Portion guide</span>
      <div className="batch-weight__portions">{portions.map(portion => <div className="batch-weight__portion" key={portion.memberId}>
        <div><b>{portion.name}</b><small>{portion.servings} {portion.servings === 1 ? 'serving' : 'servings'}</small></div>
        <strong>{gramsPerServing === undefined ? '—' : `${Math.round(gramsPerServing * portion.servings)} g`}</strong>
      </div>)}</div>
      <small>{servings} {servings === 1 ? 'serving' : 'servings'} in the batch</small>
    </output>
    <div className="batch-weight__actions"><Button type="submit" disabled={!validWeight || pending}>{pending ? 'Saving…' : savedWeight === undefined ? 'Save weight' : 'Update'}</Button>{savedWeight !== undefined && <Button type="button" variant="ghost" disabled={pending} onClick={onClear}>Clear</Button>}</div>
  </form>
}

function NutritionCard({ totals, calorieTarget, macroTargets }: {
  totals: NutritionTotals
  calorieTarget: number
  macroTargets?: { protein: number; carbs: number; fat: number }
}) {
  const percentage = calorieTarget > 0 ? Math.round(totals.calories / calorieTarget * 100) : 0
  return <Card className="nutrition-card">
    <div className="nutrition-card__heading">
      <div><span>Today’s progress</span><h2>Daily nutrition</h2></div>
      <strong className="nutrition-percent">{percentage}% <small>of target</small></strong>
    </div>
    <NutritionRings
      calories={Math.round(totals.calories)}
      target={Math.round(calorieTarget || 1)}
      protein={Math.round(totals.protein)}
      carbs={Math.round(totals.carbs)}
      fat={Math.round(totals.fat)}
      macroTargets={macroTargets}
    />
  </Card>
}

function DemoWeekPage() {
  const [selected, setSelected] = useState(0)
  const [cooked, setCooked] = useState<string[]>([])
  const [batchWeights, setBatchWeights] = useState<Record<string, number>>({})
  const [weightDrafts, setWeightDrafts] = useState<Record<string, string>>({})
  const day = demoWeek[selected]
  const mealGroups = groupByMealType(day.meals, meal => meal.kind)
  const totals = useMemo(() => day.meals.filter(item => cooked.includes(item.id)).reduce((sum, item) => ({
    calories: sum.calories + item.nutrition.calories,
    protein: sum.protein + item.nutrition.protein,
    carbs: sum.carbs + item.nutrition.carbs,
    fat: sum.fat + item.nutrition.fat,
  }), emptyNutrition()), [cooked, day])

  return <div className="page">
    <PageHeader eyebrow="13–19 July" title="This week" description="Everything is planned. Make changes without losing the meals you want to keep." actions={<><Button variant="secondary"><RefreshCw size={17}/>Regenerate unlocked</Button><Button>Plan next week</Button></>}/>
    <div className="week-toolbar"><button aria-label="Previous week"><ChevronLeft/></button><strong>13 – 19 July 2026</strong><button aria-label="Next week"><ChevronRight/></button><Badge tone="green">Within targets</Badge></div>
    <div className="day-tabs" style={{ '--day-count': demoWeek.length } as CSSProperties}>{demoWeek.map((item, index) => <button key={item.date} className={selected === index ? 'active' : ''} onClick={() => setSelected(index)}><span>{item.day.slice(0, 3)}</span><strong>{item.shortDate.split(' ')[0]}</strong></button>)}</div>
    <div className="week-layout">
      <section>
        <div className="section-heading"><div><h2>{day.day}</h2><p>{day.shortDate} · {day.meals.length} planned meals</p></div></div>
        <div className="meal-groups">{mealGroups.map(([mealType, group]) => <section className="meal-group" key={mealType}>
          <div className="meal-group__heading"><h3>{mealType}</h3><span>{group.length} {group.length === 1 ? 'recipe' : 'recipes'}</span></div>
          <div className="meal-list">{group.map(meal => {
            const recipe = demoRecipes.find(item => meal.title.toLocaleLowerCase().includes(item.title.split(' ')[0].toLocaleLowerCase()))
            const isCooked = cooked.includes(meal.id)
            return <Card className={`meal-card${isCooked ? ' is-cooked' : ''}`} key={meal.id}>
              <RecipePreview imageUrl={recipe?.imageUrl}/>
              <MealBatchInfo label={meal.batchLabel ? 'Batch plan' : 'Portion'} servings={meal.batchLabel ?? `${meal.portions} serving`}/>
              <div className="meal-body"><div><RecipeTitle title={meal.title} sourceUrl={recipe?.sourceUrl}/><p>{meal.portions} serving · {meal.nutrition.calories} kcal</p></div><div className="meal-macros"><span>P <strong>{meal.nutrition.protein}g</strong></span><span>C <strong>{meal.nutrition.carbs}g</strong></span><span>F <strong>{meal.nutrition.fat}g</strong></span></div></div>
              <div className="meal-actions"><CookControl cooked={isCooked} onClick={() => {
                setCooked(items => isCooked ? items.filter(id => id !== meal.id) : [...items, meal.id])
                if (isCooked) {
                  setBatchWeights(items => { const next = { ...items }; delete next[meal.id]; return next })
                  setWeightDrafts(items => { const next = { ...items }; delete next[meal.id]; return next })
                }
              }}/></div>
              {isCooked && <BatchWeightControl
                servings={meal.portions}
                portions={[{ memberId: 'demo', name: 'You', servings: meal.portions }]}
                savedWeight={batchWeights[meal.id]}
                draft={weightDrafts[meal.id] ?? String(batchWeights[meal.id] ?? '')}
                onDraftChange={value => setWeightDrafts(items => ({ ...items, [meal.id]: value }))}
                onSave={() => {
                setBatchWeights(items => ({ ...items, [meal.id]: Number(weightDrafts[meal.id] ?? batchWeights[meal.id]) }))
                setWeightDrafts(items => { const next = { ...items }; delete next[meal.id]; return next })
                }}
                onClear={() => {
                setBatchWeights(items => { const next = { ...items }; delete next[meal.id]; return next })
                setWeightDrafts(items => ({ ...items, [meal.id]: '' }))
                }}
              />}
            </Card>
          })}</div>
        </section>)}</div>
      </section>
      <aside className="day-summary"><NutritionCard totals={totals} calorieTarget={day.targetCalories}/><Card className="prep-card"><div><Clock3/><h3>Prep ahead</h3></div><p>Make 3 portions of harissa chicken at lunch. Two are reserved for Tuesday and Wednesday.</p><Button variant="ghost">View batch</Button></Card></aside>
    </div>
  </div>
}

function occurrenceNutrition(item: BackendPlanDetail['occurrences'][number], memberId?: string): NutritionTotals {
  const servings = Number(item.portions.find(portion => portion.member_id === memberId)?.servings ?? 0)
  const nutrition = item.nutrition_per_serving ?? {}
  return {
    calories: Number(nutrition.energy_kcal ?? 0) * servings,
    protein: Number(nutrition.protein_g ?? 0) * servings,
    carbs: Number(nutrition.carbohydrate_g ?? 0) * servings,
    fat: Number(nutrition.fat_g ?? 0) * servings,
  }
}

function LiveWeekPage() {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState(0)
  const [cookedOverrides, setCookedOverrides] = useState<Record<string, boolean>>({})
  const [pendingBatches, setPendingBatches] = useState<string[]>([])
  const [pendingWeights, setPendingWeights] = useState<string[]>([])
  const [weightDrafts, setWeightDrafts] = useState<Record<string, string>>({})
  const [cookError, setCookError] = useState<string>()
  const session = useQuery({ queryKey: ['session'], queryFn: api.me, retry: false })
  const members = useQuery({ queryKey: ['members'], queryFn: api.listMembers })
  const plans = useQuery({ queryKey: ['plans'], queryFn: api.listPlans, refetchOnMount: 'always' })
  const current = plans.data?.find(plan => plan.status === 'accepted') ?? plans.data?.find(plan => plan.status === 'ready')
  const detail = useQuery({ queryKey: ['plan', current?.id], queryFn: () => api.getPlan(current!.id), enabled: Boolean(current) })
  const target = useQuery({ queryKey: ['target', session.data?.member_id], queryFn: () => api.getTarget(session.data!.member_id!), enabled: Boolean(session.data?.member_id) })

  if (plans.isLoading || detail.isLoading) return <div className="page"><Loading label="Loading your meal plan…"/></div>
  if (!current || !detail.data) return <div className="page"><PageHeader eyebrow="Meal planning" title="This week" description="Your accepted plan will appear here."/><EmptyState icon={<Clock3/>} title="No active plan" description="Generate a plan after adding planner-ready recipes."/></div>

  const dates = Array.from(new Set(detail.data.occurrences.map(item => item.meal_date))).sort()
  const date = dates[Math.min(selected, Math.max(0, dates.length - 1))]
  const meals = detail.data.occurrences.filter(item => item.meal_date === date).sort((left, right) => compareMealTypes(left.meal_type, right.meal_type))
  const mealGroups = groupByMealType(meals, meal => meal.meal_type)
  const memberId = session.data?.member_id
  const isCooked = (meal: BackendPlanDetail['occurrences'][number]) => Object.hasOwn(cookedOverrides, meal.batch_id) ? cookedOverrides[meal.batch_id] : Boolean(meal.cooked_at)
  const totals = meals.filter(isCooked).reduce((sum, item) => {
    const nutrition = occurrenceNutrition(item, memberId)
    return { calories: sum.calories + nutrition.calories, protein: sum.protein + nutrition.protein, carbs: sum.carbs + nutrition.carbs, fat: sum.fat + nutrition.fat }
  }, emptyNutrition())
  const targetCalories = target.data?.mode === 'calorie'
    ? Number(target.data.calorie_target ?? 0)
    : Number(target.data?.protein_target_g ?? 0) * 4 + Number(target.data?.carbohydrate_target_g ?? 0) * 4 + Number(target.data?.fat_target_g ?? 0) * 9
  const macroTargets = {
    protein: Number(target.data?.protein_target_g ?? target.data?.protein_min_g ?? 130),
    carbs: Number(target.data?.carbohydrate_target_g ?? target.data?.carbohydrate_min_g ?? 225),
    fat: Number(target.data?.fat_target_g ?? target.data?.fat_min_g ?? 67),
  }

  const toggleCooked = async (batchId: string, currentlyCooked: boolean) => {
    const nextCooked = !currentlyCooked
    const selectedBatch = detail.data.occurrences.find(item => item.batch_id === batchId)
    const rootBatchId = selectedBatch?.parent_batch_id ?? batchId
    const batchGroupIds = Array.from(new Set(detail.data.occurrences
      .filter(item => item.batch_id === rootBatchId || item.parent_batch_id === rootBatchId)
      .map(item => item.batch_id)))
    setCookError(undefined)
    setCookedOverrides(items => batchGroupIds.reduce((next, id) => ({ ...next, [id]: nextCooked }), items))
    setPendingBatches(items => Array.from(new Set([...items, ...batchGroupIds])))
    try {
      await (nextCooked ? api.markBatchCooked(current.id, batchId) : api.unmarkBatchCooked(current.id, batchId))
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['plan', current.id] }),
        queryClient.invalidateQueries({ queryKey: ['pantry'] }),
      ])
      setCookedOverrides(items => {
        const next = { ...items }
        batchGroupIds.forEach(id => delete next[id])
        return next
      })
    } catch (error) {
      setCookedOverrides(items => {
        const next = { ...items }
        batchGroupIds.forEach(id => delete next[id])
        return next
      })
      setCookError(error instanceof Error ? error.message : 'Could not update this recipe’s cooked state.')
    } finally {
      setPendingBatches(items => items.filter(id => !batchGroupIds.includes(id)))
    }
  }

  const saveCookedWeight = async (batchId: string, cookedWeightGrams: number | null) => {
    setCookError(undefined)
    setPendingWeights(items => [...items, batchId])
    try {
      await api.updateBatchCookedWeight(current.id, batchId, cookedWeightGrams)
      await queryClient.invalidateQueries({ queryKey: ['plan', current.id] })
      setWeightDrafts(items => {
        const next = { ...items }
        delete next[batchId]
        return next
      })
    } catch (error) {
      setCookError(error instanceof Error ? error.message : 'Could not save this batch weight.')
    } finally {
      setPendingWeights(items => items.filter(id => id !== batchId))
    }
  }

  return <div className="page">
    <PageHeader eyebrow={`${current.start_date} – ${current.end_date}`} title="This week" description="Accepted batches reserve pantry stock and consume it only when you mark them cooked." actions={<Button>Plan next week</Button>}/>
    {current.status === 'ready' && <Notice tone="warning" title="Draft plan">Accept this plan from the Plan page before pantry stock is reserved.</Notice>}
    {cookError && <Notice tone="warning" title="Cooking update failed">{cookError}</Notice>}
    <div className="day-tabs" style={{ '--day-count': dates.length } as CSSProperties}>{dates.map((item, index) => <button key={item} className={selected === index ? 'active' : ''} onClick={() => setSelected(index)}><span>{new Date(`${item}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short' })}</span><strong>{new Date(`${item}T12:00:00`).getDate()}</strong></button>)}</div>
    <div className="week-layout">
      <section>
        <div className="section-heading"><div><h2>{new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long' })}</h2><p>{date} · {meals.length} planned meals</p></div></div>
        <div className="meal-groups">{mealGroups.map(([mealType, group]) => <section className="meal-group" key={mealType}>
          <div className="meal-group__heading"><h3>{mealTypeLabel(mealType)}</h3><span>{group.length} {group.length === 1 ? 'recipe' : 'recipes'}</span></div>
          <div className="meal-list">{group.map(meal => {
            const nutrition = occurrenceNutrition(meal, memberId)
            const cooked = isCooked(meal)
            return <Card className={`meal-card${cooked ? ' is-cooked' : ''}`} key={meal.id}>
              <RecipePreview imageUrl={meal.image_url}/>
              <MealBatchInfo label={meal.component_slot > 0 ? `Side ${meal.component_slot}` : 'Batch'} servings={`${meal.batch_servings} servings`}/>
              <div className="meal-body"><div><RecipeTitle title={meal.recipe_title} sourceUrl={meal.source_url}/><p>{Number(meal.portions.find(portion => portion.member_id === memberId)?.servings ?? 0)} serving · {Math.round(nutrition.calories)} kcal</p></div><div className="meal-macros"><span>P <strong>{Math.round(nutrition.protein)}g</strong></span><span>C <strong>{Math.round(nutrition.carbs)}g</strong></span><span>F <strong>{Math.round(nutrition.fat)}g</strong></span></div></div>
              <div className="meal-actions"><CookControl cooked={cooked} pending={pendingBatches.includes(meal.batch_id)} onClick={() => toggleCooked(meal.batch_id, cooked)}/></div>
              {cooked && <BatchWeightControl
                servings={Number(meal.batch_servings)}
                portions={meal.portions.map((portion, index) => ({
                  memberId: portion.member_id,
                  name: members.data?.find(member => member.id === portion.member_id)?.name ?? (portion.member_id === memberId ? 'You' : `Person ${index + 1}`),
                  servings: Number(portion.servings),
                }))}
                savedWeight={meal.cooked_weight_grams == null ? undefined : Number(meal.cooked_weight_grams)}
                draft={weightDrafts[meal.batch_id] ?? String(meal.cooked_weight_grams ?? '')}
                pending={pendingWeights.includes(meal.batch_id)}
                onDraftChange={value => setWeightDrafts(items => ({ ...items, [meal.batch_id]: value }))}
                onSave={() => saveCookedWeight(meal.batch_id, Number(weightDrafts[meal.batch_id] ?? meal.cooked_weight_grams))}
                onClear={() => saveCookedWeight(meal.batch_id, null)}
              />}
            </Card>
          })}</div>
        </section>)}</div>
      </section>
      <aside className="day-summary"><NutritionCard totals={totals} calorieTarget={targetCalories} macroTargets={macroTargets}/></aside>
    </div>
  </div>
}
