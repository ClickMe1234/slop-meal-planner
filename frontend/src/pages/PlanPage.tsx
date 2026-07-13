import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight,
  CalendarRange,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  CircleAlert,
  Search,
  Users,
  WandSparkles,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { NutritionStrip } from '../components/Nutrition'
import { Badge, Button, Card, Loading, Notice, PageHeader, ProgressBar } from '../components/ui'
import {
  api,
  ApiError,
  isDemoMode,
  type ApiAction,
  type ApiNutritionIssue,
  type BackendMember,
  type BackendPlanDetail,
  type BackendRestriction,
  type BackendTarget,
} from '../api/client'
import {
  MEAL_TYPES,
  attendanceKey,
  batchCount,
  buildPlanSlots,
  capitalise,
  compareMealTypes,
  cookStartKey,
  emptyIngredientGuidance,
  firstPlannedDate,
  formatDateRange,
  hasLongBatch,
  isAttending,
  memberNutritionTotals,
  occurrenceServings,
  participantsFor,
  plannerDates,
  readDemoPlan,
  storeDemoPlan,
  type AttendanceOverrides,
  type CookStarts,
  type IngredientChoice,
  type IngredientGuidance,
  type MealType,
  type PlannerDate,
  type PlannerSlot,
} from './planner'

const wizardSteps = ['Dates', 'People', 'Meals', 'Cook days', 'Ingredients', 'Review']
const stepDescriptions = [
  'Choose the planning period',
  'Choose who is eating',
  'Set attendance for every meal',
  'Choose when each recipe changes',
  'Use, prefer or exclude',
  'Check every constraint',
]
const stepTitles = [
  'When are you planning for?',
  'Who is eating?',
  'Who needs each meal?',
  'When will you cook something new?',
  'Any ingredients in mind?',
  'Ready to build your plan',
]
const stepHelp = [
  'Choose any period from one day upwards.',
  'Household members and nutrition targets come from your saved profiles.',
  'Untick someone when they are out or do not need that meal. Servings and shopping quantities will follow these choices.',
  'A tick starts a new recipe batch. Unticked dates use the most recent recipe for that meal.',
  'Add plan-specific ingredient guidance. Saved household restrictions are applied automatically too.',
  'These dates, portions, batches and ingredient rules will be sent to the planner.',
]

const demoMember: BackendMember = { id: 'demo-you', name: 'You', active: true, version: 1 }
const demoTarget: BackendTarget = {
  id: 'demo-target',
  member_id: demoMember.id,
  mode: 'calorie',
  calorie_target: 2000,
  tolerance_percent: 5,
  allocations: [
    { meal_type: 'breakfast', percentage: 25 },
    { meal_type: 'lunch', percentage: 30 },
    { meal_type: 'dinner', percentage: 35 },
    { meal_type: 'snack', percentage: 10 },
  ],
  version: 1,
}

function localToday(): string {
  const value = new Date()
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function clampDays(value: number): number {
  return Number.isFinite(value) ? Math.min(31, Math.max(1, value)) : 1
}

export function PlanPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const restoredPlanId = searchParams.get('plan')
  const [step, setStep] = useState(0)
  const [maxVisitedStep, setMaxVisitedStep] = useState(0)
  const [generating, setGenerating] = useState(false)
  const [startDate, setStartDate] = useState(localToday)
  const [days, setDays] = useState(7)
  const [livePlan, setLivePlan] = useState<BackendPlanDetail | null>(() => restoredPlanId === 'demo' ? readDemoPlan() : null)
  const [error, setError] = useState<ApiError | null>(null)
  const [selectedMemberIds, setSelectedMemberIds] = useState<string[]>([])
  const [membersInitialised, setMembersInitialised] = useState(false)
  const [attendance, setAttendance] = useState<AttendanceOverrides>({})
  const [cookStarts, setCookStarts] = useState<CookStarts>({})
  const [foodSafetyAcknowledged, setFoodSafetyAcknowledged] = useState(false)
  const [ingredientQuery, setIngredientQuery] = useState('')
  const [ingredientGuidance, setIngredientGuidance] = useState<IngredientGuidance>(emptyIngredientGuidance)
  const [overwritePrompt, setOverwritePrompt] = useState<{ ignoreNutritionTolerances: boolean } | null>(null)
  const [overwriteConfirmed, setOverwriteConfirmed] = useState(false)

  const membersQuery = useQuery({
    queryKey: ['members'],
    queryFn: api.listMembers,
    enabled: !isDemoMode,
  })
  const members = useMemo(
    () => isDemoMode ? [demoMember] : (membersQuery.data ?? []).filter(member => member.active),
    [membersQuery.data],
  )

  useEffect(() => {
    if (membersInitialised || !members.length) return
    setSelectedMemberIds(members.map(member => member.id))
    setMembersInitialised(true)
  }, [members, membersInitialised])

  const targetsQuery = useQuery({
    queryKey: ['targets'],
    queryFn: api.listTargets,
    enabled: !isDemoMode,
    retry: false,
  })
  const plansQuery = useQuery({
    queryKey: ['plans'],
    queryFn: api.listPlans,
    enabled: !isDemoMode,
  })
  const existingPlan = isDemoMode
    ? readDemoPlan()?.plan
    : plansQuery.data?.find(plan => plan.status === 'accepted' || plan.status === 'ready')
  const targetsByMember = useMemo(() => new Map<string, BackendTarget>(
    isDemoMode
      ? [[demoMember.id, demoTarget]]
      : (targetsQuery.data ?? []).map(target => [target.member_id, target] as const),
  ), [targetsQuery.data])
  const selectedTargetLoading = !isDemoMode && targetsQuery.isLoading
  const selectedWithoutTarget = selectedMemberIds.filter(memberId => !targetsByMember.has(memberId))

  const restrictionQueries = useQueries({
    queries: selectedMemberIds.map(memberId => ({
      queryKey: ['restrictions', memberId],
      queryFn: () => api.listRestrictions(memberId),
      enabled: !isDemoMode,
    })),
  })
  const profileRestrictions = useMemo(() => selectedMemberIds.flatMap((memberId, index) => {
    const member = members.find(item => item.id === memberId)
    return (restrictionQueries[index]?.data ?? []).map(item => ({ ...item, memberName: member?.name ?? 'Household member' }))
  }), [members, restrictionQueries, selectedMemberIds])

  const foodSearch = useQuery({
    queryKey: ['foods', 'planner', ingredientQuery.trim()],
    queryFn: () => api.searchFoods(ingredientQuery.trim()),
    enabled: !isDemoMode && ingredientQuery.trim().length >= 2,
  })
  const foodResults: IngredientChoice[] = isDemoMode
    ? ['Spinach', 'Chickpeas', 'Chicken thighs', 'Peanuts']
      .filter(name => name.toLowerCase().includes(ingredientQuery.trim().toLowerCase()))
      .map(name => ({ id: `demo-${name.toLowerCase().replaceAll(' ', '-')}`, name }))
    : (foodSearch.data?.items ?? []).slice(0, 8).map(food => ({ id: food.id, name: food.name }))

  const dates = useMemo(() => plannerDates(startDate, days), [startDate, days])
  const slots = useMemo(() => buildPlanSlots({
    dates,
    selectedMemberIds,
    attendance,
    cookStarts,
    foodSafetyAcknowledged,
  }), [attendance, cookStarts, dates, foodSafetyAcknowledged, selectedMemberIds])
  const longBatch = hasLongBatch(slots)

  const restoredPlan = useQuery({
    queryKey: ['plan', restoredPlanId],
    queryFn: () => api.getPlan(restoredPlanId as string),
    enabled: !isDemoMode && Boolean(restoredPlanId),
    retry: false,
  })
  const displayedPlan = livePlan ?? restoredPlan.data ?? (restoredPlanId === 'demo' ? readDemoPlan() : null)

  const toggleMember = (memberId: string) => {
    setSelectedMemberIds(current => current.includes(memberId)
      ? current.filter(id => id !== memberId)
      : [...current, memberId])
  }
  const toggleAttendance = (date: string, mealType: MealType, memberId: string) => {
    const key = attendanceKey(date, mealType, memberId)
    setAttendance(current => ({ ...current, [key]: !isAttending(current, date, mealType, memberId) }))
  }
  const toggleCookStart = (date: string, mealType: MealType) => {
    const key = cookStartKey(date, mealType)
    setCookStarts(current => ({ ...current, [key]: !current[key] }))
  }
  const addIngredient = (kind: keyof IngredientGuidance, food: IngredientChoice) => {
    setIngredientGuidance(current => ({
      must: kind === 'must' ? [...current.must.filter(item => item.id !== food.id), food] : current.must.filter(item => item.id !== food.id),
      prefer: kind === 'prefer' ? [...current.prefer.filter(item => item.id !== food.id), food] : current.prefer.filter(item => item.id !== food.id),
      exclude: kind === 'exclude' ? [...current.exclude.filter(item => item.id !== food.id), food] : current.exclude.filter(item => item.id !== food.id),
    }))
  }
  const removeIngredient = (kind: keyof IngredientGuidance, foodId: string) => {
    setIngredientGuidance(current => ({ ...current, [kind]: current[kind].filter(item => item.id !== foodId) }))
  }

  const stepBlocked = step === 0
    ? !startDate || days < 1
    : step === 1
      ? !selectedMemberIds.length || selectedTargetLoading || selectedWithoutTarget.length > 0
      : step === 2
        ? slots.length === 0
        : step === 3
          ? longBatch && !foodSafetyAcknowledged
          : false
  const generationBlocked = !slots.length
    || !selectedMemberIds.length
    || selectedTargetLoading
    || selectedWithoutTarget.length > 0
    || (longBatch && !foodSafetyAcknowledged)

  const next = () => {
    const nextStep = Math.min(wizardSteps.length - 1, step + 1)
    setStep(nextStep)
    setMaxVisitedStep(current => Math.max(current, nextStep))
  }
  const openStep = (index: number) => {
    if (index <= maxVisitedStep) setStep(index)
  }
  const closePlan = () => {
    setLivePlan(null)
    setSearchParams({}, { replace: true })
  }

  const generate = async (ignoreNutritionTolerances = false) => {
    if (generationBlocked) {
      if (longBatch && !foodSafetyAcknowledged) setStep(3)
      return
    }
    setGenerating(true)
    setError(null)
    try {
      if (isDemoMode) {
        await new Promise(resolve => window.setTimeout(resolve, 500))
        const plan = buildDemoPlan(dates, slots)
        storeDemoPlan(plan)
        setLivePlan(plan)
        setSearchParams({ plan: 'demo' }, { replace: true })
        return
      }

      const plan = await api.generatePlan({
        name: `Plan from ${startDate}`,
        start_date: dates[0]?.iso,
        end_date: dates.at(-1)?.iso,
        slots,
        // An empty selection means all planner-ready household recipes. The
        // backend applies meal tags and nutrition rules without a page-size cap.
        recipe_ids: [],
        must_use_food_record_ids: ingredientGuidance.must.map(item => item.id),
        prefer_food_record_ids: ingredientGuidance.prefer.map(item => item.id),
        exclude_food_record_ids: ingredientGuidance.exclude.map(item => item.id),
        ignore_nutrition_tolerances: ignoreNutritionTolerances,
      })
      const detail = await api.getPlan(plan.id)
      await queryClient.invalidateQueries({ queryKey: ['plans'] })
      setLivePlan(detail)
      setSearchParams({ plan: plan.id }, { replace: true })
    } catch (reason) {
      setError(reason instanceof ApiError ? reason : new ApiError(0, 'The plan could not be generated.'))
    } finally {
      setGenerating(false)
    }
  }

  const requestGeneration = (ignoreNutritionTolerances = false) => {
    if (existingPlan && !overwriteConfirmed) {
      setOverwritePrompt({ ignoreNutritionTolerances })
      return
    }
    void generate(ignoreNutritionTolerances)
  }

  const confirmOverwrite = () => {
    const request = overwritePrompt
    setOverwritePrompt(null)
    setOverwriteConfirmed(true)
    if (request) void generate(request.ignoreNutritionTolerances)
  }

  if (displayedPlan) {
    return <GeneratedPlan
      plan={displayedPlan}
      memberNames={Object.fromEntries(members.map(member => [member.id, member.name]))}
      onBack={closePlan}
    />
  }
  if (restoredPlanId && !isDemoMode && restoredPlan.isLoading) {
    return <div className="page"><PageHeader title="Opening your meal plan"/><Loading label="Loading planned meals…"/></div>
  }
  if (restoredPlanId && !isDemoMode && restoredPlan.isError) {
    return <div className="page"><PageHeader title="Meal plan unavailable" description="This plan could not be restored."/><Notice tone="warning" title="Could not open plan">{restoredPlan.error instanceof Error ? restoredPlan.error.message : 'Try opening the plan again.'}</Notice><Button onClick={closePlan}>Build a new plan</Button></div>
  }

  return <div className="page">
    <PageHeader eyebrow="Automatic planning" title="Build your next meal plan" description="Set exactly who needs each meal and when you want to cook. Portions, ingredients and shopping quantities follow those choices."/>
    {error && <Card className="planner-generation-error"><PlanGenerationError error={error}/>{error.code === 'NUTRITION_TARGET_INFEASIBLE' && <Button variant="secondary" disabled={generating} onClick={() => requestGeneration(true)}>Continue anyway</Button>}</Card>}
    <div className="planner-layout">
      <aside className="wizard-sidebar"><ol>{wizardSteps.map((name, index) => <li key={name} className={index < step ? 'done' : index === step ? 'active' : ''}><button type="button" disabled={index > maxVisitedStep} onClick={() => openStep(index)}><span>{index < step ? <Check size={15}/> : index + 1}</span><div><strong>{name}</strong><small>{stepDescriptions[index]}</small></div></button></li>)}</ol></aside>
      <Card className="wizard-panel">
        <div className="wizard-panel-heading"><p className="eyebrow">Step {step + 1} of {wizardSteps.length}</p><h2>{stepTitles[step]}</h2><p>{stepHelp[step]}</p></div>

        {step === 0 && <DateStep startDate={startDate} days={days} dates={dates} onStartDate={setStartDate} onDays={value => setDays(clampDays(value))}/>}
        {step === 1 && <PeopleStep members={members} selectedMemberIds={selectedMemberIds} targets={targetsByMember} loading={membersQuery.isLoading || selectedTargetLoading} onToggle={toggleMember}/>}
        {step === 2 && <AttendanceStep dates={dates} members={members.filter(member => selectedMemberIds.includes(member.id))} attendance={attendance} onToggle={toggleAttendance}/>}
        {step === 3 && <CookDaysStep dates={dates} selectedMemberIds={selectedMemberIds} attendance={attendance} cookStarts={cookStarts} slots={slots} foodSafetyAcknowledged={foodSafetyAcknowledged} onToggle={toggleCookStart} onAcknowledge={setFoodSafetyAcknowledged}/>}
        {step === 4 && <IngredientsStep query={ingredientQuery} onQuery={setIngredientQuery} loading={foodSearch.isFetching} results={foodResults} guidance={ingredientGuidance} profileRestrictions={profileRestrictions} onAdd={addIngredient} onRemove={removeIngredient}/>}
        {step === 5 && <ReviewStep dates={dates} slots={slots} members={members.filter(member => selectedMemberIds.includes(member.id))} guidance={ingredientGuidance} profileRestrictionCount={profileRestrictions.length} generating={generating}/>}

        <div className="wizard-actions">
          <Button variant="ghost" disabled={step === 0 || generating} onClick={() => setStep(current => current - 1)}><ChevronLeft/>Back</Button>
          {step < wizardSteps.length - 1
            ? <Button disabled={stepBlocked} onClick={next}>Continue<ChevronRight/></Button>
            : <Button disabled={generating || generationBlocked} onClick={() => requestGeneration()}><WandSparkles/>{generating ? 'Building your plan…' : 'Generate meal plan'}</Button>}
        </div>
      </Card>
    </div>
    {overwritePrompt && <div className="modal-backdrop" role="presentation"><Card className="recipe-save-modal" role="dialog" aria-modal="true" aria-labelledby="overwrite-plan-title"><p className="eyebrow">Replace current plan</p><h2 id="overwrite-plan-title">Create a new meal plan?</h2><p>Your current plan, <strong>{existingPlan?.name}</strong>, will remain active while you review the new plan. Accepting the new plan will replace it on This week and rebuild the active shopping list.</p><Notice tone="warning" title="Your current plan will be overwritten">Pantry reservations from the current plan will be released when the new plan is accepted.</Notice><div className="button-row"><Button variant="ghost" onClick={() => setOverwritePrompt(null)}>Keep current plan</Button><Button onClick={confirmOverwrite}>Create new plan</Button></div></Card></div>}
  </div>
}

function DateStep({ startDate, days, dates, onStartDate, onDays }: { startDate: string; days: number; dates: PlannerDate[]; onStartDate: (value: string) => void; onDays: (value: number) => void }) {
  return <div className="form-grid"><label>Starts<input type="date" value={startDate} onChange={event => onStartDate(event.target.value)}/></label><label>Number of days<div className="stepper"><button type="button" aria-label="Plan one fewer day" onClick={() => onDays(days - 1)}>−</button><input type="number" min="1" max="31" value={days} onChange={event => onDays(Number(event.target.value))}/><button type="button" aria-label="Plan one more day" onClick={() => onDays(days + 1)}>+</button></div></label><div className="date-preview"><CalendarRange/><span><strong>Planning period</strong><small>{formatDateRange(dates)} · {days} {days === 1 ? 'day' : 'days'}</small></span></div></div>
}

function PeopleStep({ members, selectedMemberIds, targets, loading, onToggle }: { members: BackendMember[]; selectedMemberIds: string[]; targets: Map<string, BackendTarget>; loading: boolean; onToggle: (memberId: string) => void }) {
  if (loading && !members.length) return <Loading label="Loading your household…"/>
  if (!members.length) return <Notice tone="warning" title="No active household members">Add or reactivate someone in Household settings before building a plan.</Notice>
  return <><div className="member-selector">{members.map(member => {
    const checked = selectedMemberIds.includes(member.id)
    const target = targets.get(member.id)
    return <label className={`member-check${checked ? ' selected' : ''}`} key={member.id}><input type="checkbox" checked={checked} onChange={() => onToggle(member.id)}/><span className="member-avatar">{member.name.slice(0, 1).toUpperCase()}</span><span><strong>{member.name}</strong><small>{target ? formatTarget(target) : 'Nutrition target required'}</small></span><span className="member-check-indicator" aria-hidden>{checked && <Check size={14}/>}</span></label>
  })}</div>{selectedMemberIds.some(id => !targets.has(id)) && <Notice tone="warning" title="Nutrition target needed"><span>Add a target for every selected person in <Link to="/settings/targets">Targets & meals</Link>.</span></Notice>}</>
}

function formatTarget(target: BackendTarget): string {
  if (target.mode === 'calorie') return `${Math.round(Number(target.calorie_target ?? 0)).toLocaleString()} kcal · ±${target.tolerance_percent}%`
  return `P ${Number(target.protein_target_g ?? 0)}g · C ${Number(target.carbohydrate_target_g ?? 0)}g · F ${Number(target.fat_target_g ?? 0)}g · ±${target.tolerance_percent}%`
}

function AttendanceStep({ dates, members, attendance, onToggle }: { dates: PlannerDate[]; members: BackendMember[]; attendance: AttendanceOverrides; onToggle: (date: string, mealType: MealType, memberId: string) => void }) {
  return <div className="planner-table-wrap" tabIndex={0} aria-label="Meal attendance grid"><table className="planner-grid planner-attendance-grid"><thead><tr><th scope="col">Meal</th>{dates.map(date => <th scope="col" key={date.iso}><strong>{date.weekday}</strong><small>{date.shortDate}</small></th>)}</tr></thead><tbody>{MEAL_TYPES.map(mealType => <tr key={mealType}><th scope="row">{capitalise(mealType)}</th>{dates.map(date => <td key={date.iso}><fieldset><legend className="sr-only">{capitalise(mealType)} on {date.shortDate}</legend>{members.map(member => {
    const checked = isAttending(attendance, date.iso, mealType, member.id)
    return <label key={member.id} className={`attendance-person${checked ? ' selected' : ''}`}><input type="checkbox" checked={checked} onChange={() => onToggle(date.iso, mealType, member.id)} aria-label={`${member.name} needs ${mealType} on ${date.shortDate}`}/><span>{member.name}</span></label>
  })}</fieldset></td>)}</tr>)}</tbody></table></div>
}

function CookDaysStep({ dates, selectedMemberIds, attendance, cookStarts, slots, foodSafetyAcknowledged, onToggle, onAcknowledge }: { dates: PlannerDate[]; selectedMemberIds: string[]; attendance: AttendanceOverrides; cookStarts: CookStarts; slots: PlannerSlot[]; foodSafetyAcknowledged: boolean; onToggle: (date: string, mealType: MealType) => void; onAcknowledge: (value: boolean) => void }) {
  const longBatch = hasLongBatch(slots)
  return <><div className="planner-table-wrap" tabIndex={0} aria-label="New recipe cook days grid"><table className="planner-grid planner-cook-grid"><thead><tr><th scope="col">Meal</th>{dates.map(date => <th scope="col" key={date.iso}><strong>{date.weekday}</strong><small>{date.shortDate}</small></th>)}</tr></thead><tbody>{MEAL_TYPES.map(mealType => {
    const firstDate = firstPlannedDate(dates, mealType, selectedMemberIds, attendance)
    return <tr key={mealType}><th scope="row">{capitalise(mealType)}</th>{dates.map(date => {
      const planned = participantsFor(attendance, date.iso, mealType, selectedMemberIds).length > 0
      const forced = planned && date.iso === firstDate
      const checked = forced || Boolean(cookStarts[cookStartKey(date.iso, mealType)])
      return <td key={date.iso}><label className={`cook-choice${checked ? ' selected' : ''}${!planned ? ' disabled' : ''}`}><input type="checkbox" disabled={!planned || forced} checked={checked} onChange={() => onToggle(date.iso, mealType)} aria-label={`Cook new ${mealType} on ${date.shortDate}`}/><span>{!planned ? 'Not needed' : checked ? 'Cook new' : 'Use batch'}</span></label></td>
    })}</tr>
  })}</tbody></table></div><p className="planner-grid-note">The first required meal always starts a batch. Add more ticks wherever you want a different recipe.</p>{longBatch && <Notice tone="warning" title="Long leftover window"><span>At least one batch lasts more than 48 hours. Confirm that you will store it safely. <label className="check-label"><input type="checkbox" checked={foodSafetyAcknowledged} onChange={event => onAcknowledge(event.target.checked)}/>I understand and want to continue</label></span></Notice>}</>
}

export function PlanGenerationError({ error }: { error: ApiError }) {
  if (error.code !== 'NUTRITION_TARGET_INFEASIBLE' || !error.issues.length) {
    return <Notice tone="warning" title="Plan not feasible">{error.message}</Notice>
  }

  const byDate = error.issues.reduce<Record<string, ApiNutritionIssue[]>>((result, issue) => {
    ;(result[issue.date] ??= []).push(issue)
    return result
  }, {})

  return <Notice tone="warning" title="Some daily targets could not be met">
    <p>{error.message} You can adjust your targets or continue with the closest available plan.</p>
    <div className="nutrition-plan-issues">
      {Object.entries(byDate).map(([date, issues]) => {
        const matching = new Map<string, { members: string[]; messages: string[] }>()
        for (const issue of issues) {
          const messages = issue.violations.map(violation => violation.message)
          const key = messages.join('|')
          const group = matching.get(key) ?? { members: [], messages }
          group.members.push(issue.member)
          matching.set(key, group)
        }
        return <div key={date} className="nutrition-plan-issue-day">
          <strong>{new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })}</strong>
          <ul>{[...matching.values()].map(group => <li key={`${group.members.join('-')}-${group.messages.join('-')}`}><b>{group.members.join(' & ')}</b><span>{group.messages.join('; ')}</span></li>)}</ul>
        </div>
      })}
    </div>
  </Notice>
}

type ProfileRestriction = BackendRestriction & { memberName: string }

function IngredientsStep({ query, onQuery, loading, results, guidance, profileRestrictions, onAdd, onRemove }: { query: string; onQuery: (value: string) => void; loading: boolean; results: IngredientChoice[]; guidance: IngredientGuidance; profileRestrictions: ProfileRestriction[]; onAdd: (kind: keyof IngredientGuidance, food: IngredientChoice) => void; onRemove: (kind: keyof IngredientGuidance, foodId: string) => void }) {
  return <div className="ingredient-guidance"><label>Find an ingredient<div className="planner-food-search"><Search size={18}/><input value={query} onChange={event => onQuery(event.target.value)} placeholder="Search your food catalogue…"/></div></label>{loading && <Loading label="Searching foods…"/>}{query.trim().length >= 2 && !loading && <div className="planner-food-results">{results.map(food => <div key={food.id}><strong>{food.name}</strong><span><Button variant="ghost" onClick={() => onAdd('must', food)}>Must use</Button><Button variant="ghost" onClick={() => onAdd('prefer', food)}>Prefer</Button><Button variant="ghost" onClick={() => onAdd('exclude', food)}>Exclude</Button></span></div>)}{!results.length && <p className="muted">No matching foods found.</p>}</div>}{(['must', 'prefer', 'exclude'] as const).map(kind => <div className="guidance-block" key={kind}><strong>{kind === 'must' ? 'Must use' : capitalise(kind)}</strong><div className="tag-row">{guidance[kind].map(food => <button type="button" className={`tag${kind === 'prefer' ? ' tag--warm' : kind === 'exclude' ? ' tag--danger' : ''}`} key={food.id} onClick={() => onRemove(kind, food.id)} aria-label={`Remove ${food.name} from ${kind}`}>{food.name}<X size={13}/></button>)}{!guidance[kind].length && <span className="muted">None</span>}</div></div>)}<div className="profile-guidance"><div><strong>Household profile rules</strong><Link to="/settings/preferences">Edit profiles</Link></div><p>These saved preferences and restrictions are applied automatically.</p><div className="tag-row">{profileRestrictions.map(item => <span className={`tag${item.hard ? ' tag--danger' : item.kind === 'prefer' ? ' tag--warm' : ''}`} key={`${item.member_id}-${item.id}`} title={`${item.memberName} · ${item.kind}`}>{item.value}</span>)}{!profileRestrictions.length && <span className="muted">No saved rules for the selected people.</span>}</div></div></div>
}

function ReviewStep({ dates, slots, members, guidance, profileRestrictionCount, generating }: { dates: PlannerDate[]; slots: PlannerSlot[]; members: BackendMember[]; guidance: IngredientGuidance; profileRestrictionCount: number; generating: boolean }) {
  const mealCounts = MEAL_TYPES.map(mealType => `${slots.filter(slot => slot.meal_type === mealType).length} ${mealType}`).join(' · ')
  return <div className="constraint-review"><dl><div><dt>Dates</dt><dd>{formatDateRange(dates)} · {dates.length} {dates.length === 1 ? 'day' : 'days'}</dd></div><div><dt>Meal slots</dt><dd>{slots.length} total · {mealCounts}</dd></div><div><dt>People</dt><dd>{members.map(member => member.name).join(', ')}</dd></div><div><dt>Cooking</dt><dd>{batchCount(slots)} new recipe {batchCount(slots) === 1 ? 'batch' : 'batches'}</dd></div><div><dt>Plan guidance</dt><dd>{guidance.must.length} must use · {guidance.prefer.length} preferred · {guidance.exclude.length} excluded</dd></div><div><dt>Profile rules</dt><dd>{profileRestrictionCount} applied automatically</dd></div></dl><Notice title="Recipes are meal-tagged">Only planner-ready recipes tagged for the relevant breakfast, lunch, dinner or snack slot will be considered.</Notice>{generating && <ProgressBar value={72} label="Balancing nutrition, portions, batches and preferences…"/>}</div>
}

function GeneratedPlan({ plan, memberNames, onBack }: { plan: BackendPlanDetail; memberNames: Record<string, string>; onBack: () => void }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const editable = plan.plan.status === 'ready'
  const [accepting, setAccepting] = useState(false)
  const [acceptError, setAcceptError] = useState<{ message: string; code?: string; actions: ApiAction[] } | null>(null)
  const [collapsedDays, setCollapsedDays] = useState<Record<string, boolean>>({})
  const grouped = useMemo(() => plan.occurrences.reduce<Record<string, BackendPlanDetail['occurrences']>>((result, item) => {
    ;(result[item.meal_date] ??= []).push(item)
    return result
  }, {}), [plan.occurrences])
  for (const occurrences of Object.values(grouped)) {
    occurrences.sort((left, right) => compareMealTypes(left.meal_type, right.meal_type))
  }
  const planDayCount = Math.max(1, Math.round((new Date(`${plan.plan.end_date}T12:00:00`).getTime() - new Date(`${plan.plan.start_date}T12:00:00`).getTime()) / (24 * 60 * 60 * 1000)) + 1)
  const dates = plannerDates(plan.plan.start_date, planDayCount).map(date => date.iso)

  const accept = async () => {
    if (isDemoMode) {
      navigate('/shopping')
      return
    }
    setAccepting(true)
    setAcceptError(null)
    try {
      await api.acceptPlan(plan.plan.id)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['plans'] }),
        queryClient.invalidateQueries({ queryKey: ['plan'] }),
      ])
      navigate('/shopping')
    } catch (reason) {
      if (reason instanceof ApiError) setAcceptError({ message: reason.message, code: reason.code, actions: reason.actions })
      else setAcceptError({ message: 'The plan could not be accepted.', actions: [] })
    } finally {
      setAccepting(false)
    }
  }

  return <div className="page"><PageHeader eyebrow={`${plan.plan.start_date} – ${plan.plan.end_date}`} title={editable ? 'Your plan is ready' : 'Your accepted plan'} description={editable ? 'Review each day, customise any recipe, then accept the plan to create the shopping list.' : 'This plan is accepted. Review its meals or open the current shopping list.'} actions={<><Button variant="secondary" onClick={onBack}>{editable ? 'Edit setup' : 'Build another plan'}</Button><Button disabled={accepting} onClick={accept}>{accepting ? 'Opening…' : editable ? 'Accept plan' : 'Open shopping list'}<ArrowRight/></Button></>}/>{acceptError && <Card className="planner-action-error" role="alert"><CircleAlert/><div><h3>{acceptError.code === 'SHOPPING_REVIEW_REQUIRED' ? 'Shopping quantities need attention' : 'Plan needs attention'}</h3><p>{acceptError.message}</p>{acceptError.actions.map((action, index) => <div className="planner-error-action" key={`${action.href}-${index}`}><span>{action.suggestion ?? 'Review the suggested change, then return and accept the plan again.'}</span>{action.href && <Link className="button button--secondary" to={appendReturnTo(action.href, `/plan?plan=${plan.plan.id}`)}>{action.label ?? 'Review issue'}</Link>}</div>)}</div></Card>}<Notice tone="success" title={editable ? 'Plan generated' : 'Plan accepted'}>Each day shows the portion-adjusted calories and macros for every person eating.</Notice><div className="generated-grid">{dates.map(date => {
    const occurrences = grouped[date] ?? []
    const memberNutrition = memberNutritionTotals(occurrences)
    const collapsed = Boolean(collapsedDays[date])
    return <Card key={date} className={`generated-day${collapsed ? ' is-collapsed' : ''}`}><div className="generated-day-head generated-day-head--rich"><div className="generated-day-date"><strong>{new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long' })}</strong><small>{new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}</small></div><div className="day-member-nutrition">{memberNutrition.map(item => <div className="day-member-nutrition-row" key={item.memberId}><span>{memberNames[item.memberId] ?? 'Household member'}</span><NutritionStrip compact nutrition={item.nutrition}/></div>)}</div><button type="button" className="day-collapse-button" onClick={() => setCollapsedDays(current => ({ ...current, [date]: !collapsed }))} aria-expanded={!collapsed} aria-controls={`planned-day-${date}`} aria-label={`${collapsed ? 'Expand' : 'Collapse'} ${date}`}>{collapsed ? <ChevronDown/> : <ChevronUp/>}</button></div><div id={`planned-day-${date}`} hidden={collapsed}>{!occurrences.length && <div className="generated-day-empty">No meals needed</div>}{occurrences.map(item => {
      const servings = occurrenceServings(item)
      const kcal = Number(item.nutrition_per_serving?.energy_kcal ?? 0) * servings
      return <div className="generated-meal" key={item.id}><span>{capitalise(item.meal_type)}</span><div className="generated-meal-copy"><strong>{item.recipe_title}</strong><small>{item.portions.map(portion => `${memberNames[portion.member_id] ?? 'Household member'} ${Number(portion.servings)} serving${Number(portion.servings) === 1 ? '' : 's'}`).join(' · ')}</small></div><small>{Math.round(kcal)} kcal</small>{editable && <Link className="generated-meal-customise" to={`/plan/${plan.plan.id}/occurrences/${item.id}/recipes?mealType=${encodeURIComponent(item.meal_type)}`}><WandSparkles size={15}/>Customise</Link>}</div>
    })}</div></Card>
  })}</div></div>
}

function appendReturnTo(href: string, returnTo: string): string {
  const [path, query = ''] = href.split('?', 2)
  const params = new URLSearchParams(query)
  if (params.has('ingredient') && !params.has('focusIngredient')) {
    params.set('focusIngredient', params.get('ingredient') as string)
  }
  params.set('returnTo', returnTo)
  return `${path}?${params.toString()}`
}

const demoMeals: Record<MealType, Array<{ id: string; title: string; nutrition: Record<string, number> }>> = {
  breakfast: [
    { id: 'overnight-oats', title: 'Berry overnight oats', nutrition: { energy_kcal: 386, protein_g: 17, carbohydrate_g: 56, fat_g: 10 } },
    { id: 'mushroom-eggs', title: 'Mushroom scrambled eggs', nutrition: { energy_kcal: 394, protein_g: 29, carbohydrate_g: 18, fat_g: 22 } },
  ],
  lunch: [
    { id: 'harissa-chicken', title: 'Harissa chicken with chickpeas', nutrition: { energy_kcal: 524, protein_g: 48, carbohydrate_g: 39, fat_g: 18 } },
    { id: 'grain-bowl', title: 'Rainbow grain bowl', nutrition: { energy_kcal: 512, protein_g: 21, carbohydrate_g: 71, fat_g: 17 } },
  ],
  dinner: [
    { id: 'green-curry', title: 'Fragrant green vegetable curry', nutrition: { energy_kcal: 441, protein_g: 13, carbohydrate_g: 51, fat_g: 21 } },
    { id: 'salmon-greens', title: 'Salmon with summer greens', nutrition: { energy_kcal: 601, protein_g: 45, carbohydrate_g: 36, fat_g: 28 } },
  ],
  snack: [
    { id: 'apple-peanut-butter', title: 'Apple and peanut butter', nutrition: { energy_kcal: 248, protein_g: 8, carbohydrate_g: 29, fat_g: 12 } },
    { id: 'yoghurt-berries', title: 'Yoghurt and berries', nutrition: { energy_kcal: 206, protein_g: 14, carbohydrate_g: 24, fat_g: 6 } },
  ],
}

function buildDemoPlan(dates: PlannerDate[], slots: PlannerSlot[]): BackendPlanDetail {
  const batchIndexes = new Map<string, number>()
  const nextIndex: Record<MealType, number> = { breakfast: 0, lunch: 0, dinner: 0, snack: 0 }
  for (const slot of slots) {
    if (!batchIndexes.has(slot.batch_key)) {
      batchIndexes.set(slot.batch_key, nextIndex[slot.meal_type])
      nextIndex[slot.meal_type] += 1
    }
  }
  const batchServings = slots.reduce<Record<string, number>>((result, slot) => {
    result[slot.batch_key] = (result[slot.batch_key] ?? 0) + slot.participant_member_ids.length
    return result
  }, {})
  return {
    plan: {
      id: 'demo',
      name: 'Demo meal plan',
      start_date: dates[0]?.iso ?? localToday(),
      end_date: dates.at(-1)?.iso ?? localToday(),
      status: 'ready',
      diagnostics: [],
      version: 1,
    },
    occurrences: slots.map((slot, index) => {
      const recipes = demoMeals[slot.meal_type]
      const recipe = recipes[(batchIndexes.get(slot.batch_key) ?? 0) % recipes.length]
      return {
        id: `demo-occurrence-${index}`,
        meal_date: slot.meal_date,
        meal_type: slot.meal_type,
        batch_id: slot.batch_key,
        recipe_id: recipe.id,
        recipe_title: recipe.title,
        batch_servings: batchServings[slot.batch_key],
        nutrition_per_serving: recipe.nutrition,
        portions: slot.participant_member_ids.map(memberId => ({ member_id: memberId, servings: 1 })),
      }
    }),
  }
}
