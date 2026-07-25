import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  CalendarX2,
  ChefHat,
  CircleMinus,
  Flame,
  LockKeyhole,
  RefreshCcw,
  RotateCcw,
  Save,
  Sparkles,
  Trash2,
  UserRoundPlus,
  Utensils,
} from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  api,
  ApiError,
  type BackendPlanDetail,
  type BackendPlanPreservingEditRequest,
} from '../api/client'
import { Badge, Button, Card, Loading, Notice, PageHeader } from '../components/ui'
import { compareMealTypes } from './planner'
import {
  clearPlanEditDraft,
  readPlanEditDraft,
  writePlanEditDraft,
  type PlanEditBoostDraft,
  type PlanEditCookDaySelection,
  type PlanEditGuestDraft,
  type PlanEditRecipeSelection,
} from './planEditDraft'

type GuestDraft = PlanEditGuestDraft
type BoostDraft = PlanEditBoostDraft

const editKey = (mealDate: string, value: string) => `${mealDate}::${value}`
const splitEditKey = (value: string) => {
  const [mealDate, suffix] = value.split('::')
  return { mealDate, suffix }
}
const mealLabel = (mealType: string) => mealType.charAt(0).toUpperCase() + mealType.slice(1)
const dateLabel = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
})

export function buildPreservingEditPayload(
  detail: BackendPlanDetail,
  removedDates: Set<string>,
  guests: Record<string, GuestDraft>,
  boosts: Record<string, BoostDraft>,
  addedCookDays: Record<string, PlanEditCookDaySelection>,
  removedCookDays: Set<string>,
  recipeSwaps: Record<string, PlanEditRecipeSelection>,
  ignoreNutritionTolerances = false,
): BackendPlanPreservingEditRequest {
  const mealTypesByDate = detail.occurrences.reduce<Record<string, string[]>>((result, occurrence) => {
    if (occurrence.component_slot !== 0) return result
    result[occurrence.meal_date] = Array.from(new Set([...(result[occurrence.meal_date] ?? []), occurrence.meal_type]))
      .sort(compareMealTypes)
    return result
  }, {})
  const removedBatchIds = new Set(
    detail.occurrences
      .filter(occurrence => occurrence.component_slot === 0
        && removedCookDays.has(editKey(occurrence.meal_date, occurrence.meal_type)))
      .map(occurrence => occurrence.batch_id),
  )
  const retainedBatchIds = new Set(
    detail.occurrences
      .filter(occurrence => occurrence.component_slot === 0
        && !removedDates.has(occurrence.meal_date)
        && !removedBatchIds.has(occurrence.batch_id))
      .map(occurrence => occurrence.batch_id),
  )
  return {
    expected_plan_version: detail.plan.version,
    removed_dates: Array.from(removedDates).sort(),
    calorie_boosts: Object.entries(boosts)
      .map(([key, value]) => ({ ...splitEditKey(key), value }))
      .filter(({ mealDate, value }) => !removedDates.has(mealDate) && Number(value.calories) > 0)
      .map(({ mealDate, suffix: memberId, value }) => ({
        meal_date: mealDate,
        member_id: memberId,
        calories: Number(value.calories),
        meal_allocations: value.mealAllocations,
      })),
    guest_days: Object.entries(guests)
      .filter(([mealDate, value]) => !removedDates.has(mealDate) && value.count > 0)
      .map(([mealDate, value]) => {
        const everyMeal = mealTypesByDate[mealDate] ?? []
        const selected = [...value.mealTypes].sort(compareMealTypes)
        return {
          meal_date: mealDate,
          guest_count: value.count,
          meal_types: selected.length === everyMeal.length ? [] : selected,
        }
      }),
    added_cook_days: Object.values(addedCookDays)
      .filter(item => !removedDates.has(item.mealDate))
      .map(item => ({
        meal_date: item.mealDate,
        meal_type: item.mealType,
        recipe_id: item.recipeId,
      }))
      .sort((left, right) => left.meal_date.localeCompare(right.meal_date) || compareMealTypes(left.meal_type, right.meal_type)),
    removed_cook_days: Array.from(removedCookDays)
      .map(key => splitEditKey(key))
      .filter(({ mealDate }) => !removedDates.has(mealDate))
      .map(({ mealDate, suffix: mealType }) => ({ meal_date: mealDate, meal_type: mealType }))
      .sort((left, right) => left.meal_date.localeCompare(right.meal_date) || compareMealTypes(left.meal_type, right.meal_type)),
    recipe_swaps: Object.entries(recipeSwaps)
      .filter(([batchId]) => retainedBatchIds.has(batchId))
      .map(([batchId, selection]) => ({ batch_id: batchId, recipe_id: selection.recipeId }))
      .sort((left, right) => left.batch_id.localeCompare(right.batch_id)),
    ignore_nutrition_tolerances: ignoreNutritionTolerances,
  }
}

export function PlanEditPage() {
  const { planId = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const initialisedVersion = useRef<number | undefined>(undefined)
  const planQuery = useQuery({
    queryKey: ['plan', planId],
    queryFn: () => api.getPlan(planId),
    enabled: Boolean(planId),
  })
  const membersQuery = useQuery({ queryKey: ['members'], queryFn: api.listMembers })
  const [removedDates, setRemovedDates] = useState<Set<string>>(new Set())
  const [guests, setGuests] = useState<Record<string, GuestDraft>>({})
  const [boosts, setBoosts] = useState<Record<string, BoostDraft>>({})
  const [addedCookDays, setAddedCookDays] = useState<Record<string, PlanEditCookDaySelection>>({})
  const [removedCookDays, setRemovedCookDays] = useState<Set<string>>(new Set())
  const [recipeSwaps, setRecipeSwaps] = useState<Record<string, PlanEditRecipeSelection>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<ApiError | null>(null)

  const detail = planQuery.data
  const dates = useMemo(
    () => detail ? Array.from(new Set(detail.occurrences.map(item => item.meal_date))).sort() : [],
    [detail],
  )
  const mealsByDate = useMemo(() => detail?.occurrences.reduce<Record<string, BackendPlanDetail['occurrences']>>((result, meal) => {
    ;(result[meal.meal_date] ??= []).push(meal)
    return result
  }, {}) ?? {}, [detail])
  const memberNames = useMemo(
    () => Object.fromEntries((membersQuery.data ?? []).map(member => [member.id, member.name])),
    [membersQuery.data],
  )

  useEffect(() => {
    if (!detail || initialisedVersion.current === detail.plan.version) return
    const savedDraft = readPlanEditDraft(detail.plan.id)
    if (savedDraft?.planVersion === detail.plan.version) {
      setRemovedDates(new Set(savedDraft.removedDates))
      setGuests(savedDraft.guests)
      setBoosts(savedDraft.boosts)
      setAddedCookDays(savedDraft.addedCookDays)
      setRemovedCookDays(new Set(savedDraft.removedCookDays))
      setRecipeSwaps(savedDraft.recipeSwaps)
      initialisedVersion.current = detail.plan.version
      return
    }
    clearPlanEditDraft(detail.plan.id)
    const initialGuests: Record<string, GuestDraft> = {}
    for (const day of detail.plan.guest_days ?? []) {
      const plannedMealTypes = (mealsByDate[day.meal_date] ?? [])
        .filter(item => item.component_slot === 0)
        .map(item => item.meal_type)
      initialGuests[day.meal_date] = {
        count: day.guest_count,
        mealTypes: day.meal_types?.length ? [...day.meal_types] : Array.from(new Set(plannedMealTypes)),
      }
    }
    const initialBoosts: Record<string, BoostDraft> = {}
    for (const boost of detail.plan.calorie_boosts ?? []) {
      initialBoosts[editKey(boost.meal_date, boost.member_id)] = {
        calories: String(boost.calories),
        mealAllocations: boost.meal_allocations ?? [],
      }
    }
    setRemovedDates(new Set())
    setGuests(initialGuests)
    setBoosts(initialBoosts)
    setAddedCookDays({})
    setRemovedCookDays(new Set())
    setRecipeSwaps({})
    initialisedVersion.current = detail.plan.version
  }, [detail, mealsByDate])

  useEffect(() => {
    if (!detail || initialisedVersion.current !== detail.plan.version) return
    writePlanEditDraft(detail.plan.id, {
      planVersion: detail.plan.version,
      removedDates: Array.from(removedDates),
      guests,
      boosts,
      addedCookDays,
      removedCookDays: Array.from(removedCookDays),
      recipeSwaps,
    })
  }, [addedCookDays, boosts, detail, guests, recipeSwaps, removedCookDays, removedDates])

  if (planQuery.isLoading || membersQuery.isLoading) {
    return <div className="page"><PageHeader title="Opening the plan editor"/><Loading label="Pinning your existing recipes…"/></div>
  }
  if (planQuery.isError || !detail) {
    return <div className="page"><PageHeader title="Plan editor unavailable"/><Notice tone="warning" title="The plan could not be opened">{planQuery.error instanceof Error ? planQuery.error.message : 'Return to This week and try again.'}</Notice><Link className="button button--secondary" to="/week"><ArrowLeft/>Back to This week</Link></div>
  }

  const updateGuestCount = (mealDate: string, count: number) => {
    const plannedMealTypes = (mealsByDate[mealDate] ?? [])
      .filter(item => item.component_slot === 0)
      .map(item => item.meal_type)
    setGuests(current => ({
      ...current,
      [mealDate]: {
        count: Math.max(0, Math.min(50, count || 0)),
        mealTypes: current[mealDate]?.mealTypes ?? Array.from(new Set(plannedMealTypes)),
      },
    }))
  }
  const toggleGuestMeal = (mealDate: string, mealType: string) => {
    setGuests(current => {
      const day = current[mealDate] ?? { count: 1, mealTypes: [] }
      if (day.mealTypes.length === 1 && day.mealTypes[0] === mealType) return current
      return {
        ...current,
        [mealDate]: {
          ...day,
          mealTypes: day.mealTypes.includes(mealType)
            ? day.mealTypes.filter(item => item !== mealType)
            : [...day.mealTypes, mealType],
        },
      }
    })
  }
  const updateBoost = (mealDate: string, memberId: string, calories: string) => {
    const key = editKey(mealDate, memberId)
    setBoosts(current => ({
      ...current,
      [key]: {
        calories,
        mealAllocations: current[key]?.mealAllocations ?? [],
      },
    }))
  }
  const toggleRemovedDate = (mealDate: string) => {
    setRemovedDates(current => {
      const next = new Set(current)
      if (next.has(mealDate)) next.delete(mealDate)
      else next.add(mealDate)
      return next
    })
  }
  const persistDraft = () => {
    writePlanEditDraft(detail.plan.id, {
      planVersion: detail.plan.version,
      removedDates: Array.from(removedDates),
      guests,
      boosts,
      addedCookDays,
      removedCookDays: Array.from(removedCookDays),
      recipeSwaps,
    })
  }
  const openRecipePicker = (
    meal: BackendPlanDetail['occurrences'][number],
    editMode: 'swap' | 'addCook',
  ) => {
    persistDraft()
    const params = new URLSearchParams({
      mealType: meal.meal_type,
      editMode,
      returnTo: `/plan/${detail.plan.id}/edit`,
    })
    navigate(`/plan/${encodeURIComponent(detail.plan.id)}/occurrences/${encodeURIComponent(meal.id)}/recipes?${params.toString()}`)
  }
  const toggleRemovedCookDay = (mealDate: string, mealType: string, batchId: string) => {
    const key = editKey(mealDate, mealType)
    setRemovedCookDays(current => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
    setRecipeSwaps(current => {
      if (!(batchId in current)) return current
      const next = { ...current }
      delete next[batchId]
      return next
    })
  }
  const cancelAddedCookDay = (mealDate: string, mealType: string) => {
    const key = editKey(mealDate, mealType)
    setAddedCookDays(current => {
      const next = { ...current }
      delete next[key]
      return next
    })
  }
  const save = async (ignoreNutritionTolerances = false) => {
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await api.editPlanPreservingRecipes(
        detail.plan.id,
        buildPreservingEditPayload(
          detail,
          removedDates,
          guests,
          boosts,
          addedCookDays,
          removedCookDays,
          recipeSwaps,
          ignoreNutritionTolerances,
        ),
      )
      queryClient.setQueryData(['plan', detail.plan.id], updated)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['plans'] }),
        queryClient.invalidateQueries({ queryKey: ['shopping-list'] }),
        queryClient.invalidateQueries({ queryKey: ['pantry'] }),
      ])
      clearPlanEditDraft(detail.plan.id)
      navigate('/week')
    } catch (reason) {
      setSaveError(reason instanceof ApiError ? reason : new ApiError(0, 'The plan changes could not be saved.'))
    } finally {
      setSaving(false)
    }
  }

  const keptRecipeCount = new Set(
    detail.occurrences
      .filter(item => !removedDates.has(item.meal_date))
      .map(item => item.recipe_id),
  ).size
  return <div className="page plan-edit-page">
    <PageHeader
      eyebrow="Recipe-preserving editor"
      title="Adjust the week, keep the meals"
      description="The recipes already in your plan stay put unless you deliberately swap a batch, add a cooking day or merge one back."
      actions={<Link className="button button--ghost" to="/week" onClick={() => clearPlanEditDraft(detail.plan.id)}><ArrowLeft/>Discard and return</Link>}
    />

    <div className="plan-edit-principle">
      <span><LockKeyhole/><strong>{keptRecipeCount} recipes in place</strong></span>
      <p>Guest, calorie and day changes still preserve recipes. Batch controls are now explicit and visibly staged before you save.</p>
    </div>

    {saveError && <Notice tone="warning" title={saveError.code === 'NUTRITION_TARGET_INFEASIBLE' ? 'Portions need permission to bend' : 'The plan could not be updated'}>
      {saveError.message}
      {saveError.code === 'NUTRITION_TARGET_INFEASIBLE' && <div className="button-row"><Button variant="secondary" disabled={saving} onClick={() => void save(true)}>Keep recipes with closest portions</Button></div>}
    </Notice>}

    <div className="plan-edit-layout">
      <main className="plan-edit-days">
        {dates.map((mealDate, dayIndex) => {
          const meals = [...(mealsByDate[mealDate] ?? [])].sort((left, right) => compareMealTypes(left.meal_type, right.meal_type) || left.component_slot - right.component_slot)
          const mainMeals = meals.filter(item => item.component_slot === 0)
          const participantIds = Array.from(new Set(mainMeals.flatMap(item => item.portions.map(portion => portion.member_id))))
          const cooked = meals.some(item => Boolean(item.cooked_at))
          const removed = removedDates.has(mealDate)
          const guest = guests[mealDate] ?? { count: 0, mealTypes: mainMeals.map(item => item.meal_type) }
          return <Card className={`plan-edit-day${removed ? ' is-removed' : ''}${cooked ? ' is-locked' : ''}`} key={mealDate}>
            <div className="plan-edit-day-index">{String(dayIndex + 1).padStart(2, '0')}</div>
            <header className="plan-edit-day-header">
              <div>
                <p className="eyebrow">{mealDate}</p>
                <h2>{dateLabel(mealDate)}</h2>
              </div>
              {cooked
                ? <Badge tone="green"><LockKeyhole/>Cooked · locked</Badge>
                : <Button variant={removed ? 'secondary' : 'ghost'} onClick={() => toggleRemovedDate(mealDate)}>{removed ? <RotateCcw/> : <Trash2/>}{removed ? 'Restore day' : 'Remove day'}</Button>}
            </header>

            {removed ? <div className="plan-edit-removed">
              <CalendarX2/>
              <div><strong>This day will be removed</strong><span>Every other day and its recipes remain in place.</span></div>
            </div> : <>
              <section className="plan-edit-recipes" aria-label={`Pinned recipes for ${mealDate}`}>
                {mainMeals.map(meal => {
                  const newCookKey = editKey(mealDate, meal.meal_type)
                  const existingCookStart = meal.planned_cook_date === mealDate
                  const sideMeals = meals.filter(item => item.parent_batch_id === meal.batch_id)
                  const batchCooked = Boolean(meal.cooked_at) || sideMeals.some(item => Boolean(item.cooked_at))
                  const addedSelection = Object.values(addedCookDays)
                    .filter(item => item.mealType === meal.meal_type
                      && item.mealDate >= (meal.planned_cook_date ?? mealDate)
                      && item.mealDate <= mealDate)
                    .sort((left, right) => right.mealDate.localeCompare(left.mealDate))[0]
                  const addingCookStart = addedSelection?.mealDate === mealDate
                  const removalKey = editKey(meal.planned_cook_date ?? mealDate, meal.meal_type)
                  const removingBatch = removedCookDays.has(removalKey)
                  const previousMeal = detail.occurrences
                    .filter(item => item.component_slot === 0
                      && item.meal_type === meal.meal_type
                      && item.meal_date < (meal.planned_cook_date ?? mealDate)
                      && !removedDates.has(item.meal_date))
                    .sort((left, right) => right.meal_date.localeCompare(left.meal_date))[0]
                  const swappedRecipe = recipeSwaps[meal.batch_id]
                  const inheritedRecipe = previousMeal ? recipeSwaps[previousMeal.batch_id] : undefined
                  const previousBatchCooked = Boolean(previousMeal?.cooked_at) || detail.occurrences.some(
                    item => item.parent_batch_id === previousMeal?.batch_id && Boolean(item.cooked_at),
                  )
                  const displayedRecipe = removingBatch
                    ? inheritedRecipe?.recipeTitle ?? previousMeal?.recipe_title ?? meal.recipe_title
                    : addedSelection?.recipeTitle ?? swappedRecipe?.recipeTitle ?? meal.recipe_title
                  const canRemoveCookDay = existingCookStart
                    && Boolean(previousMeal)
                    && !batchCooked
                    && !previousBatchCooked
                  return <article className={`plan-edit-recipe${addingCookStart ? ' starts-new-batch' : ''}${removingBatch ? ' removes-batch' : ''}`} key={meal.id}>
                    <div className="plan-edit-recipe-rail"><ChefHat/><span/></div>
                    <div className="plan-edit-recipe-copy">
                      <span>{mealLabel(meal.meal_type)}{sideMeals.length ? ` + ${sideMeals.length} side` : ''}</span>
                      <div className="plan-edit-recipe-title">
                        <strong>{displayedRecipe}</strong>
                        {!batchCooked && !removingBatch && !addedSelection && <button type="button" onClick={() => openRecipePicker(meal, 'swap')} aria-label={`Swap ${meal.recipe_title} batch`}><RefreshCcw/>Swap</button>}
                        {addingCookStart && <button type="button" onClick={() => openRecipePicker(meal, 'addCook')} aria-label={`Change new recipe for ${mealDate}`}><RefreshCcw/>Change</button>}
                      </div>
                      <small>{removingBatch
                        ? `Will continue the previous batch${previousMeal ? ` from ${previousMeal.meal_date}` : ''}`
                        : addedSelection
                          ? addingCookStart ? 'New cook batch selected' : `Continues new batch from ${addedSelection.mealDate}`
                          : swappedRecipe
                            ? 'Recipe swap applies to every date in this batch'
                            : existingCookStart ? 'Cooked fresh from here' : `Continues from ${new Date(`${meal.planned_cook_date}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' })}`}</small>
                    </div>
                    {existingCookStart
                      ? <div className="plan-edit-cook-actions">
                          <span className="plan-edit-cook-stamp"><Utensils/>{removingBatch ? 'Merging back' : 'Cook day'}</span>
                          {canRemoveCookDay && <button type="button" className={`plan-edit-cook-remove${removingBatch ? ' active' : ''}`} onClick={() => toggleRemovedCookDay(mealDate, meal.meal_type, meal.batch_id)}>{removingBatch ? <RotateCcw/> : <CircleMinus/>}{removingBatch ? 'Keep cook day' : 'Remove cook day'}</button>}
                        </div>
                      : !cooked && <div className="plan-edit-cook-actions">
                          <button type="button" className={`plan-edit-cook-toggle${addingCookStart ? ' active' : ''}`} onClick={() => openRecipePicker(meal, 'addCook')}><Sparkles/>{addingCookStart ? 'Recipe selected' : 'Add cooking day'}</button>
                          {addingCookStart && <button type="button" className="plan-edit-boundary-cancel" onClick={() => cancelAddedCookDay(mealDate, meal.meal_type)}>Cancel</button>}
                        </div>}
                  </article>
                })}
              </section>

              <div className="plan-edit-adjustments">
                <section>
                  <div className="plan-edit-section-title"><UserRoundPlus/><div><strong>Guests</strong><span>Scale these recipes; do not replace them.</span></div></div>
                  <div className="plan-edit-guest-control">
                    <label>Guest places<input type="number" min="0" max="50" value={guest.count || ''} placeholder="0" disabled={cooked} onChange={event => updateGuestCount(mealDate, Number(event.target.value))}/></label>
                    {guest.count > 0 && <div className="plan-edit-meal-chips">{mainMeals.map(meal => <button type="button" disabled={cooked} className={guest.mealTypes.includes(meal.meal_type) ? 'active' : ''} onClick={() => toggleGuestMeal(mealDate, meal.meal_type)} key={meal.meal_type}>{mealLabel(meal.meal_type)}</button>)}</div>}
                    {guest.count > 0 && !cooked && <button type="button" className="plan-edit-inline-remove" onClick={() => updateGuestCount(mealDate, 0)}>Remove guests</button>}
                  </div>
                </section>

                <section>
                  <div className="plan-edit-section-title"><Flame/><div><strong>Calorie boost</strong><span>Portions move; recipe cards stay pinned.</span></div></div>
                  <div className="plan-edit-boost-list">
                    {participantIds.map(memberId => {
                      const value = boosts[editKey(mealDate, memberId)]?.calories ?? ''
                      return <label key={memberId}><span>{memberNames[memberId] ?? 'Household member'}</span><span className="plan-edit-number"><input type="number" min="0" max="10000" step="50" value={value} placeholder="0" disabled={cooked} onChange={event => updateBoost(mealDate, memberId, event.target.value)}/><small>kcal</small></span></label>
                    })}
                  </div>
                </section>
              </div>
            </>}
          </Card>
        })}
      </main>

      <aside className="plan-edit-summary">
        <Card>
          <p className="eyebrow">Change ledger</p>
          <h2>Your week, with seams visible</h2>
          <dl>
            <div><dt>Recipes retained</dt><dd>{keptRecipeCount}</dd></div>
            <div><dt>Days removed</dt><dd>{removedDates.size}</dd></div>
            <div><dt>New cook points</dt><dd>{Object.keys(addedCookDays).length}</dd></div>
            <div><dt>Cook points removed</dt><dd>{removedCookDays.size}</dd></div>
            <div><dt>Recipe swaps</dt><dd>{Object.keys(recipeSwaps).length}</dd></div>
            <div><dt>Plan days kept</dt><dd>{dates.length - removedDates.size}</dd></div>
          </dl>
          <div className="plan-edit-summary-rule"><ChefHat/><p><strong>Batch edits stay contained</strong><span>Swaps affect one batch. New cook points start a selected recipe; removed cook points fall back to the previous batch.</span></p></div>
          <Button disabled={saving || removedDates.size === dates.length} onClick={() => void save()}><Save/>{saving ? 'Re-stitching the week…' : 'Save plan changes'}</Button>
          <small>The active shopping list and uncooked pantry reservations are rebuilt after this succeeds.</small>
        </Card>
      </aside>
    </div>
  </div>
}
