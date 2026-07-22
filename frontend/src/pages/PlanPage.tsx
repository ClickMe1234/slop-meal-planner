import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight,
  Bike,
  CalendarRange,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  CircleAlert,
  GripVertical,
  Flame,
  PackageOpen,
  Search,
  Plus,
  Trash2,
  TriangleAlert,
  UserRoundPlus,
  Users,
  WandSparkles,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState, type DragEvent } from 'react'
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
  type BackendPantryItem,
  type BackendPlanDetail,
  type BackendRestriction,
  type BackendTarget,
} from '../api/client'
import {
  MEAL_TYPES,
  attendanceKey,
  batchCount,
  buildPlanSlots,
  calorieBoostEntries,
  calorieBoostKey,
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
  guestDayEntries,
  type CalorieBoosts,
  type AttendanceOverrides,
  type CookStarts,
  type IngredientChoice,
  type IngredientGuidance,
  type GuestCounts,
  type MealType,
  type PlannerDate,
  type PlannerSlot,
} from './planner'

const wizardSteps = ['Dates', 'People', 'Meals', 'Special days', 'Cook days', 'Ingredients', 'Review']
const stepDescriptions = [
  'Choose the planning period',
  'Choose who is eating',
  'Set attendance for every meal',
  'Add exercise and guests',
  'Choose when each recipe changes',
  'Use, prefer or exclude',
  'Check every constraint',
]
const stepTitles = [
  'When are you planning for?',
  'Who is eating?',
  'Who needs each meal?',
  'Anything different this week?',
  'When will you cook something new?',
  'Any ingredients in mind?',
  'Ready to build your plan',
]
const stepHelp = [
  'Choose any period from one day upwards.',
  'Household members and nutrition targets come from your saved profiles.',
  'Untick someone when they are out or do not need that meal. Servings and shopping quantities will follow these choices.',
  'Add extra calories for active days and guests for the dates they are joining you.',
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
const demoIngredientCatalogue: IngredientChoice[] = [
  { id: 'spinach', term: 'spinach', name: 'Spinach', recipes: [{ id: 'green-curry', title: 'Fragrant green vegetable curry' }, { id: 'salmon-greens', title: 'Salmon with summer greens' }] },
  { id: 'chickpeas', term: 'chickpeas', name: 'Chickpeas', recipes: [{ id: 'harissa-chicken', title: 'Harissa chicken with chickpeas' }] },
  { id: 'chicken thighs', term: 'chicken thighs', name: 'Chicken thighs', recipes: [{ id: 'harissa-chicken', title: 'Harissa chicken with chickpeas' }] },
  { id: 'peanuts', term: 'peanuts', name: 'Peanuts', recipes: [{ id: 'apple-peanut-butter', title: 'Apple and peanut butter' }] },
]
const demoPantryItems: BackendPantryItem[] = [
  { id: 'demo-spinach', display_name: 'Spinach', initial_quantity: 200, unit: 'g', always_have: false, use_soon: false, on_hand_quantity: 200, reserved_quantity: 0, usable_quantity: 200, initial_quantity_display: '200 g', on_hand_quantity_display: '200 g', reserved_quantity_display: '0 g', usable_quantity_display: '200 g', version: 1 },
  { id: 'demo-chickpeas', display_name: 'Chickpeas', initial_quantity: 2, unit: 'can', always_have: false, use_soon: false, on_hand_quantity: 2, reserved_quantity: 0, usable_quantity: 2, initial_quantity_display: '2 cans', on_hand_quantity_display: '2 cans', reserved_quantity_display: '0 cans', usable_quantity_display: '2 cans', version: 1 },
  { id: 'demo-miso', display_name: 'White miso', initial_quantity: 1, unit: 'jar', always_have: false, use_soon: false, on_hand_quantity: 1, reserved_quantity: 0, usable_quantity: 1, initial_quantity_display: '1 jar', on_hand_quantity_display: '1 jar', reserved_quantity_display: '0 jars', usable_quantity_display: '1 jar', version: 1 },
]

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
  const [calorieBoosts, setCalorieBoosts] = useState<CalorieBoosts>({})
  const [guestCounts, setGuestCounts] = useState<GuestCounts>({})
  const [cookStarts, setCookStarts] = useState<CookStarts>({})
  const [foodSafetyAcknowledged, setFoodSafetyAcknowledged] = useState(false)
  const [ingredientQuery, setIngredientQuery] = useState('')
  const [ingredientGuidance, setIngredientGuidance] = useState<IngredientGuidance>(emptyIngredientGuidance)
  const [pantryImportOpen, setPantryImportOpen] = useState(false)
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

  const ingredientSearch = useQuery({
    queryKey: ['recipe-ingredients', 'planner', ingredientQuery.trim()],
    queryFn: () => api.searchRecipeIngredients(ingredientQuery.trim()),
    enabled: !isDemoMode && ingredientQuery.trim().length >= 2,
  })
  const pantryQuery = useQuery({
    queryKey: ['pantry'],
    queryFn: api.listPantry,
    enabled: !isDemoMode && pantryImportOpen,
  })
  const recipeIngredientCatalogue = useQuery({
    queryKey: ['recipe-ingredients', 'catalogue'],
    queryFn: () => api.searchRecipeIngredients(''),
    enabled: !isDemoMode && (pantryImportOpen || step === 5),
  })
  const ingredientResults: IngredientChoice[] = isDemoMode
    ? demoIngredientCatalogue.filter(item => item.name.toLowerCase().includes(ingredientQuery.trim().toLowerCase()))
    : (ingredientSearch.data?.items ?? []).slice(0, 8)

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
        : step === 4
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
      if (longBatch && !foodSafetyAcknowledged) setStep(4)
      return
    }
    setGenerating(true)
    setError(null)
    try {
      if (isDemoMode) {
        await new Promise(resolve => window.setTimeout(resolve, 500))
        const plan = buildDemoPlan(dates, slots, calorieBoosts, guestCounts)
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
        must_use_food_record_ids: [],
        prefer_food_record_ids: [],
        exclude_food_record_ids: [],
        must_use_ingredient_terms: ingredientGuidance.must.map(item => item.term),
        prefer_ingredient_terms: ingredientGuidance.prefer.map(item => item.term),
        exclude_ingredient_terms: ingredientGuidance.exclude.map(item => item.term),
        calorie_boosts: calorieBoostEntries(dates, selectedMemberIds, calorieBoosts),
        guest_days: guestDayEntries(dates, guestCounts),
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
      onPlanChange={setLivePlan}
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
    <div className={`planner-layout${step === 5 ? ' planner-layout--ingredients' : ''}`}>
      <aside className="wizard-sidebar"><ol>{wizardSteps.map((name, index) => <li key={name} className={index < step ? 'done' : index === step ? 'active' : ''}><button type="button" disabled={index > maxVisitedStep} onClick={() => openStep(index)}><span>{index < step ? <Check size={15}/> : index + 1}</span><div><strong>{name}</strong><small>{stepDescriptions[index]}</small></div></button></li>)}</ol></aside>
      <Card className={`wizard-panel${step === 5 ? ' wizard-panel--ingredients' : ''}`}>
        <div className="wizard-panel-heading"><p className="eyebrow">Step {step + 1} of {wizardSteps.length}</p><h2>{stepTitles[step]}</h2><p>{stepHelp[step]}</p></div>

        {step === 0 && <DateStep startDate={startDate} days={days} dates={dates} onStartDate={setStartDate} onDays={value => setDays(clampDays(value))}/>}
        {step === 1 && <PeopleStep members={members} selectedMemberIds={selectedMemberIds} targets={targetsByMember} loading={membersQuery.isLoading || selectedTargetLoading} onToggle={toggleMember}/>}
        {step === 2 && <AttendanceStep dates={dates} members={members.filter(member => selectedMemberIds.includes(member.id))} attendance={attendance} onToggle={toggleAttendance}/>}
        {step === 3 && <SpecialDaysStep dates={dates} slots={slots} members={members.filter(member => selectedMemberIds.includes(member.id))} targets={targetsByMember} calorieBoosts={calorieBoosts} guestCounts={guestCounts} onCalorieBoost={(date, memberId, calories) => setCalorieBoosts(current => ({ ...current, [calorieBoostKey(date, memberId)]: calories }))} onGuestCount={(date, count) => setGuestCounts(current => ({ ...current, [date]: count }))}/>}
        {step === 4 && <CookDaysStep dates={dates} selectedMemberIds={selectedMemberIds} attendance={attendance} cookStarts={cookStarts} slots={slots} foodSafetyAcknowledged={foodSafetyAcknowledged} onToggle={toggleCookStart} onAcknowledge={setFoodSafetyAcknowledged}/>}
        {step === 5 && <IngredientsStep query={ingredientQuery} onQuery={setIngredientQuery} loading={ingredientSearch.isFetching} results={ingredientResults} guidance={ingredientGuidance} profileRestrictions={profileRestrictions} catalogue={isDemoMode ? demoIngredientCatalogue : (recipeIngredientCatalogue.data?.items ?? [])} impactLoading={!isDemoMode && recipeIngredientCatalogue.isLoading} impactError={!isDemoMode && recipeIngredientCatalogue.isError} onAdd={addIngredient} onRemove={removeIngredient} onOpenPantry={() => setPantryImportOpen(true)}/>}
        {step === 6 && <ReviewStep dates={dates} slots={slots} members={members.filter(member => selectedMemberIds.includes(member.id))} guidance={ingredientGuidance} profileRestrictionCount={profileRestrictions.length} generating={generating} calorieBoosts={calorieBoosts} guestCounts={guestCounts}/>}

        <div className="wizard-actions">
          <Button variant="ghost" disabled={step === 0 || generating} onClick={() => setStep(current => current - 1)}><ChevronLeft/>Back</Button>
          {step < wizardSteps.length - 1
            ? <Button disabled={stepBlocked} onClick={next}>Continue<ChevronRight/></Button>
            : <Button disabled={generating || generationBlocked} onClick={() => requestGeneration()}><WandSparkles/>{generating ? 'Building your plan…' : 'Generate meal plan'}</Button>}
        </div>
      </Card>
    </div>
    {overwritePrompt && <div className="modal-backdrop" role="presentation"><Card className="recipe-save-modal" role="dialog" aria-modal="true" aria-labelledby="overwrite-plan-title"><p className="eyebrow">Replace current plan</p><h2 id="overwrite-plan-title">Create a new meal plan?</h2><p>Your current plan, <strong>{existingPlan?.name}</strong>, will remain active while you review the new plan. Accepting the new plan will replace it on This week and rebuild the active shopping list.</p><Notice tone="warning" title="Your current plan will be overwritten">Pantry reservations from the current plan will be released when the new plan is accepted.</Notice><div className="button-row"><Button variant="ghost" onClick={() => setOverwritePrompt(null)}>Keep current plan</Button><Button onClick={confirmOverwrite}>Create new plan</Button></div></Card></div>}
    {pantryImportOpen && <PantryIngredientImport
      pantry={isDemoMode ? demoPantryItems : (pantryQuery.data ?? [])}
      catalogue={isDemoMode ? demoIngredientCatalogue : (recipeIngredientCatalogue.data?.items ?? [])}
      guidance={ingredientGuidance}
      loading={!isDemoMode && (pantryQuery.isLoading || recipeIngredientCatalogue.isLoading)}
      error={!isDemoMode && (pantryQuery.isError || recipeIngredientCatalogue.isError)}
      onAdd={addIngredient}
      onClose={() => setPantryImportOpen(false)}
    />}
  </div>
}

function DateStep({ startDate, days, dates, onStartDate, onDays }: { startDate: string; days: number; dates: PlannerDate[]; onStartDate: (value: string) => void; onDays: (value: number) => void }) {
  return <div className="form-grid"><label>Starts<input type="date" value={startDate} onChange={event => onStartDate(event.target.value)}/></label><label>Number of days<div className="stepper"><button type="button" aria-label="Plan one fewer day" onClick={() => onDays(days - 1)}>−</button><input type="number" aria-label="Number of days" min="1" max="31" value={days} onChange={event => onDays(Number(event.target.value))}/><button type="button" aria-label="Plan one more day" onClick={() => onDays(days + 1)}>+</button></div></label><div className="date-preview"><CalendarRange/><span><strong>Planning period</strong><small>{formatDateRange(dates)} · {days} {days === 1 ? 'day' : 'days'}</small></span></div></div>
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
  return <div className="planner-table-wrap" tabIndex={0} aria-label="Meal attendance grid"><table className="planner-grid planner-attendance-grid"><thead><tr><th scope="col">Meal</th>{dates.map(date => <th scope="col" key={date.iso}><strong>{date.weekday}</strong><small>{date.shortDate}</small></th>)}</tr></thead><tbody>{MEAL_TYPES.map(mealType => <tr key={mealType}><th scope="row">{capitalise(mealType)}</th>{dates.map(date => <td key={date.iso} data-date={`${date.weekday} ${date.shortDate}`}><fieldset><legend className="sr-only">{capitalise(mealType)} on {date.shortDate}</legend>{members.map(member => {
    const checked = isAttending(attendance, date.iso, mealType, member.id)
    return <label key={member.id} className={`attendance-person${checked ? ' selected' : ''}`}><input type="checkbox" checked={checked} onChange={() => onToggle(date.iso, mealType, member.id)} aria-label={`${member.name} needs ${mealType} on ${date.shortDate}`}/><span>{member.name}</span></label>
  })}</fieldset></td>)}</tr>)}</tbody></table></div>
}

function SpecialDaysStep({ dates, slots, members, targets, calorieBoosts, guestCounts, onCalorieBoost, onGuestCount }: { dates: PlannerDate[]; slots: PlannerSlot[]; members: BackendMember[]; targets: Map<string, BackendTarget>; calorieBoosts: CalorieBoosts; guestCounts: GuestCounts; onCalorieBoost: (date: string, memberId: string, calories: number) => void; onGuestCount: (date: string, count: number) => void }) {
  const boostCount = calorieBoostEntries(dates, members.map(member => member.id), calorieBoosts).length
  const guestTotal = guestDayEntries(dates, guestCounts).reduce((sum, day) => sum + day.guest_count, 0)
  return <div className="special-days"><div className="special-days-summary"><span><Bike/><strong>{boostCount}</strong><small>active-day {boostCount === 1 ? 'boost' : 'boosts'}</small></span><span><UserRoundPlus/><strong>{guestTotal}</strong><small>guest {guestTotal === 1 ? 'place' : 'places'}</small></span></div><div className="special-day-list">{dates.map(date => {
    const activeMemberIds = new Set(slots.filter(slot => slot.meal_date === date.iso).flatMap(slot => slot.participant_member_ids))
    const hasMeals = activeMemberIds.size > 0
    return <section className="special-day-card" key={date.iso}><header><div><strong>{new Date(`${date.iso}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long' })}</strong><small>{date.shortDate}</small></div>{(guestCounts[date.iso] ?? 0) > 0 && <span className="special-day-status"><UserRoundPlus/>{guestCounts[date.iso]}</span>}</header><div className="special-day-fields"><label><span><UserRoundPlus/>Guests</span><div className="input-suffix"><input type="number" min="0" max="50" step="1" disabled={!hasMeals} value={guestCounts[date.iso] || ''} placeholder="0" onChange={event => onGuestCount(date.iso, Math.max(0, Math.min(50, Math.floor(Number(event.target.value) || 0))))}/><span>people</span></div><small>Each guest gets the largest household portion for each meal.</small></label><div className="calorie-boost-fields"><span className="special-field-label"><Flame/>Extra calories</span>{members.map(member => {
      const target = targets.get(member.id)
      const enabled = target?.mode === 'calorie' && activeMemberIds.has(member.id)
      const key = calorieBoostKey(date.iso, member.id)
      return <label key={member.id}><span>{member.name}</span><div className="input-suffix"><input type="number" min="0" max="10000" step="50" disabled={!enabled} value={calorieBoosts[key] || ''} placeholder="0" aria-label={`${member.name} extra calories on ${date.shortDate}`} onChange={event => onCalorieBoost(date.iso, member.id, Math.max(0, Math.min(10000, Number(event.target.value) || 0)))}/><span>kcal</span></div>{target?.mode === 'macros' && <small>Uses macro targets</small>}{!activeMemberIds.has(member.id) && <small>Not eating this day</small>}</label>
    })}</div></div></section>
  })}</div><Notice tone="info" title="How adjustments work"><span>Calorie boosts raise that person's target for one day. Guest portions increase recipe batches and the shopping list, but do not change household nutrition totals.</span></Notice></div>
}

function CookDaysStep({ dates, selectedMemberIds, attendance, cookStarts, slots, foodSafetyAcknowledged, onToggle, onAcknowledge }: { dates: PlannerDate[]; selectedMemberIds: string[]; attendance: AttendanceOverrides; cookStarts: CookStarts; slots: PlannerSlot[]; foodSafetyAcknowledged: boolean; onToggle: (date: string, mealType: MealType) => void; onAcknowledge: (value: boolean) => void }) {
  const longBatch = hasLongBatch(slots)
  return <><div className="planner-table-wrap" tabIndex={0} aria-label="New recipe cook days grid"><table className="planner-grid planner-cook-grid"><thead><tr><th scope="col">Meal</th>{dates.map(date => <th scope="col" key={date.iso}><strong>{date.weekday}</strong><small>{date.shortDate}</small></th>)}</tr></thead><tbody>{MEAL_TYPES.map(mealType => {
    const firstDate = firstPlannedDate(dates, mealType, selectedMemberIds, attendance)
    return <tr key={mealType}><th scope="row">{capitalise(mealType)}</th>{dates.map(date => {
      const planned = participantsFor(attendance, date.iso, mealType, selectedMemberIds).length > 0
      const forced = planned && date.iso === firstDate
      const checked = forced || Boolean(cookStarts[cookStartKey(date.iso, mealType)])
      return <td key={date.iso} data-date={`${date.weekday} ${date.shortDate}`}><label className={`cook-choice${checked ? ' selected' : ''}${!planned ? ' disabled' : ''}`}><input type="checkbox" disabled={!planned || forced} checked={checked} onChange={() => onToggle(date.iso, mealType)} aria-label={`Cook new ${mealType} on ${date.shortDate}`}/><span>{!planned ? 'Not needed' : forced ? 'First cook' : checked ? 'Cook new' : 'Use batch'}</span></label></td>
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

function IngredientsStep({ query, onQuery, loading, results, guidance, profileRestrictions, catalogue, impactLoading, impactError, onAdd, onRemove, onOpenPantry }: { query: string; onQuery: (value: string) => void; loading: boolean; results: IngredientChoice[]; guidance: IngredientGuidance; profileRestrictions: ProfileRestriction[]; catalogue: IngredientChoice[]; impactLoading: boolean; impactError: boolean; onAdd: (kind: keyof IngredientGuidance, food: IngredientChoice) => void; onRemove: (kind: keyof IngredientGuidance, foodId: string) => void; onOpenPantry: () => void }) {
  return <div className="ingredient-guidance-workspace"><div className="ingredient-guidance"><div className="ingredient-guidance-tools"><label>Find an ingredient<div className="planner-food-search"><Search size={18}/><input value={query} onChange={event => onQuery(event.target.value)} placeholder="Search ingredients in saved recipes…"/></div></label><div className="ingredient-guidance-tool-buttons"><Button variant="secondary" onClick={onOpenPantry}><PackageOpen size={17}/>Import from pantry</Button></div></div>{loading && <Loading label="Searching saved ingredients…"/>}{query.trim().length >= 2 && !loading && <div className="planner-food-results">{results.map(food => <div key={food.id}><strong>{food.name}</strong><span><Button variant="ghost" onClick={() => onAdd('must', food)}>Must use</Button><Button variant="ghost" onClick={() => onAdd('prefer', food)}>Prefer</Button><Button variant="ghost" onClick={() => onAdd('exclude', food)}>Exclude</Button></span></div>)}{!results.length && <p className="muted">No matching saved recipe ingredients found.</p>}</div>}{(['must', 'prefer', 'exclude'] as const).map(kind => <div className="guidance-block" key={kind}><strong>{kind === 'must' ? 'Must use' : capitalise(kind)}</strong><div className="tag-row">{guidance[kind].map(food => <button type="button" className={`tag${kind === 'prefer' ? ' tag--warm' : kind === 'exclude' ? ' tag--danger' : ''}`} key={food.id} onClick={() => onRemove(kind, food.id)} aria-label={`Remove ${food.name} from ${kind}`}>{food.name}<X size={13}/></button>)}{!guidance[kind].length && <span className="muted">None</span>}</div></div>)}<div className="profile-guidance"><div><strong>Household profile rules</strong><Link to="/settings/preferences">Edit profiles</Link></div><p>These saved preferences and restrictions are applied automatically.</p><div className="tag-row">{profileRestrictions.map(item => <span className={`tag${item.hard ? ' tag--danger' : item.kind === 'prefer' ? ' tag--warm' : ''}`} key={`${item.member_id}-${item.id}`} title={`${item.memberName} · ${item.kind}`}>{item.value}</span>)}{!profileRestrictions.length && <span className="muted">No saved rules for the selected people.</span>}</div></div></div><GuidanceImpactDecks catalogue={catalogue} guidance={guidance} loading={impactLoading} error={impactError}/></div>
}

function normaliseIngredientName(value: string): string {
  return value.trim().toLocaleLowerCase().replace(/\s+/g, ' ')
}

function includesIngredientPhrase(value: string, phrase: string): boolean {
  if (!value || !phrase) return false
  const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`(^|[^a-z0-9])${escaped}($|[^a-z0-9])`, 'i').test(value)
}

export function matchPantryIngredient(displayName: string, catalogue: IngredientChoice[]): IngredientChoice | undefined {
  const pantryName = normaliseIngredientName(displayName)
  const exact = catalogue.find(item => [item.id, item.term, item.name].some(value => normaliseIngredientName(value) === pantryName))
  if (exact) return exact
  return catalogue
    .filter(item => {
      const names = [item.term, item.name].map(normaliseIngredientName)
      return names.some(name => includesIngredientPhrase(pantryName, name) || includesIngredientPhrase(name, pantryName))
    })
    .sort((left, right) => Math.abs(left.name.length - displayName.length) - Math.abs(right.name.length - displayName.length))[0]
}

type PantryImportItem = {
  pantry: BackendPantryItem
  choice: IngredientChoice
  available: boolean
}

const pantryGuidanceLabels: Record<keyof IngredientGuidance, string> = {
  must: 'Must use',
  prefer: 'Prefer',
  exclude: "Don't use",
}

function PantryIngredientImport({ pantry, catalogue, guidance, loading, error, onAdd, onClose }: { pantry: BackendPantryItem[]; catalogue: IngredientChoice[]; guidance: IngredientGuidance; loading: boolean; error: boolean; onAdd: (kind: keyof IngredientGuidance, food: IngredientChoice) => void; onClose: () => void }) {
  const [draggedId, setDraggedId] = useState('')
  const [overKind, setOverKind] = useState<keyof IngredientGuidance | ''>('')
  const [message, setMessage] = useState('')
  const items = useMemo<PantryImportItem[]>(() => pantry.map(item => {
    const match = matchPantryIngredient(item.display_name, catalogue)
    const term = normaliseIngredientName(item.display_name)
    return {
      pantry: item,
      choice: match ?? { id: `pantry:${term}`, term, name: item.display_name },
      available: Boolean(match),
    }
  }), [catalogue, pantry])
  const draggedItem = items.find(item => item.pantry.id === draggedId)

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  const assign = (kind: keyof IngredientGuidance, item: PantryImportItem) => {
    if (kind === 'must' && !item.available) {
      setMessage(`${item.pantry.display_name} is not used in any saved recipe, so it cannot be marked Must use.`)
      return
    }
    onAdd(kind, item.choice)
    setMessage(`${item.pantry.display_name} moved to ${pantryGuidanceLabels[kind]}.`)
  }
  const drop = (event: DragEvent<HTMLDivElement>, kind: keyof IngredientGuidance) => {
    event.preventDefault()
    const pantryId = event.dataTransfer.getData('text/pantry-id') || draggedId
    const item = items.find(candidate => candidate.pantry.id === pantryId)
    if (item) assign(kind, item)
    setDraggedId('')
    setOverKind('')
  }

  return <div className="modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}><Card className="pantry-import-modal" role="dialog" aria-modal="true" aria-labelledby="pantry-import-title"><button type="button" className="modal-close" aria-label="Close pantry ingredient importer" onClick={onClose} autoFocus><X/></button><div className="pantry-import-heading"><span><PackageOpen/></span><div><p className="eyebrow">Plan from what you have</p><h2 id="pantry-import-title">Import ingredients from your pantry</h2><p>Drag pantry items into a planning rule, or use the buttons on each item.</p></div></div>{loading && <Loading label="Opening your pantry…"/>}{error && <Notice tone="warning" title="Pantry unavailable">The pantry or saved ingredient catalogue could not be loaded.</Notice>}{!loading && !error && <div className="pantry-import-layout"><section className="pantry-import-shelf" aria-labelledby="pantry-shelf-title"><div className="pantry-import-section-title"><div><p className="eyebrow">Your pantry</p><h3 id="pantry-shelf-title">Pick from the shelf</h3></div><Badge tone="green">{items.length} items</Badge></div><div className="pantry-import-items" role="list">{items.map(item => {
    const selectedKind = (Object.keys(guidance) as Array<keyof IngredientGuidance>).find(kind => guidance[kind].some(choice => choice.id === item.choice.id))
    const warning = 'This pantry ingredient is not used by any saved recipe, so it cannot be marked Must use.'
    return <div key={item.pantry.id} role="listitem" className={`pantry-import-item${item.available ? '' : ' pantry-import-item--warning'}${selectedKind ? ' is-assigned' : ''}`} draggable onDragStart={event => { event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/pantry-id', item.pantry.id); setDraggedId(item.pantry.id); setMessage('') }} onDragEnd={() => { setDraggedId(''); setOverKind('') }}><GripVertical className="pantry-import-grip" aria-hidden="true"/><div className="pantry-import-item-copy"><strong>{item.pantry.display_name}</strong><span>{item.pantry.usable_quantity_display} available{selectedKind ? ` · ${pantryGuidanceLabels[selectedKind]}` : ''}</span></div>{!item.available && <span className="pantry-warning-badge" tabIndex={0} aria-label={warning} data-tooltip={warning} title={warning}><TriangleAlert/></span>}<div className="pantry-import-actions" aria-label={`Assign ${item.pantry.display_name}`}><button type="button" disabled={!item.available} title={!item.available ? warning : 'Must use this ingredient'} onClick={() => assign('must', item)}>Must</button><button type="button" onClick={() => assign('prefer', item)}>Prefer</button><button type="button" onClick={() => assign('exclude', item)}>Don't use</button></div></div>
  })}{!items.length && <div className="pantry-import-empty"><PackageOpen/><strong>Your pantry is empty</strong><span>Add pantry items first, then return here to use them as plan guidance.</span></div>}</div></section><section className="pantry-drop-area" aria-labelledby="pantry-rules-title"><div className="pantry-import-section-title"><div><p className="eyebrow">Plan guidance</p><h3 id="pantry-rules-title">Drop into a rule</h3></div><span className="pantry-drag-hint"><GripVertical/> Drag to move</span></div><div className="pantry-drop-grid">{(['must', 'prefer', 'exclude'] as const).map(kind => {
    const invalidMustDrop = kind === 'must' && Boolean(draggedItem && !draggedItem.available)
    return <div key={kind} className={`pantry-drop-zone pantry-drop-zone--${kind}${overKind === kind ? ' is-over' : ''}${invalidMustDrop ? ' is-locked' : ''}`} onDragEnter={() => setOverKind(kind)} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setOverKind('') }} onDragOver={event => { event.preventDefault(); event.dataTransfer.dropEffect = invalidMustDrop ? 'none' : 'move' }} onDrop={event => drop(event, kind)}><div className="pantry-drop-zone-title"><strong>{pantryGuidanceLabels[kind]}</strong><span>{guidance[kind].length}</span></div><p>{kind === 'must' ? 'The finished plan must include these.' : kind === 'prefer' ? 'Favour recipes containing these where possible.' : 'Keep these out of this plan.'}</p><div className="pantry-drop-zone-items">{guidance[kind].map(choice => <span className="tag" key={choice.id}>{choice.name}</span>)}{!guidance[kind].length && <span className="pantry-drop-placeholder">Drop pantry ingredients here</span>}</div>{invalidMustDrop && <small><TriangleAlert/>Not found in saved recipes</small>}</div>
  })}</div>{message && <p className="pantry-import-status" role="status">{message}</p>}</section></div>}<div className="pantry-import-footer"><p><TriangleAlert/>Amber items are not ingredients in any saved recipe.</p><Button onClick={onClose}>Done</Button></div></Card></div>
}

type RecipeImpactReason = { kind: keyof IngredientGuidance; ingredient: string }
type RecipeImpact = { id: string; title: string; tier: keyof IngredientGuidance; reasons: RecipeImpactReason[] }

export function buildRecipeImpactDecks(catalogue: IngredientChoice[], guidance: IngredientGuidance): { favoured: RecipeImpact[]; excluded: RecipeImpact[]; unmatched: string[] } {
  const matches = Object.fromEntries((['must', 'prefer', 'exclude'] as const).map(kind => [kind, new Map<string, RecipeImpact>()])) as Record<keyof IngredientGuidance, Map<string, RecipeImpact>>
  const unmatched: string[] = []
  for (const kind of ['must', 'prefer', 'exclude'] as const) {
    for (const choice of guidance[kind]) {
      const source = catalogue.find(item => item.id === choice.id || item.term === choice.term)
        ?? matchPantryIngredient(choice.name, catalogue)
        ?? choice
      if (!source.recipes?.length) {
        unmatched.push(choice.name)
        continue
      }
      for (const recipe of source.recipes) {
        const impact = matches[kind].get(recipe.id) ?? { ...recipe, tier: kind, reasons: [] }
        if (!impact.reasons.some(reason => reason.ingredient === choice.name)) impact.reasons.push({ kind, ingredient: choice.name })
        matches[kind].set(recipe.id, impact)
      }
    }
  }
  const excludedIds = new Set(matches.exclude.keys())
  const must = [...matches.must.values()].filter(recipe => !excludedIds.has(recipe.id)).sort((left, right) => left.title.localeCompare(right.title))
  const mustIds = new Set(must.map(recipe => recipe.id))
  const preferred = [...matches.prefer.values()].filter(recipe => !excludedIds.has(recipe.id) && !mustIds.has(recipe.id)).sort((left, right) => left.title.localeCompare(right.title))
  for (const recipe of must) {
    const preferredMatch = matches.prefer.get(recipe.id)
    if (preferredMatch) recipe.reasons.push(...preferredMatch.reasons.filter(reason => !recipe.reasons.some(existing => existing.kind === reason.kind && existing.ingredient === reason.ingredient)))
  }
  return {
    favoured: [...must, ...preferred],
    excluded: [...matches.exclude.values()].sort((left, right) => left.title.localeCompare(right.title)),
    unmatched,
  }
}

function RecipeImpactDeck({ title, description, tone, recipes }: { title: string; description: string; tone: 'favoured' | 'excluded'; recipes: RecipeImpact[] }) {
  const [index, setIndex] = useState(0)
  const [pointerStart, setPointerStart] = useState<number | null>(null)
  const [motion, setMotion] = useState<'next' | 'previous'>('next')
  const [motionKey, setMotionKey] = useState(0)
  useEffect(() => setIndex(current => recipes.length ? Math.min(current, recipes.length - 1) : 0), [recipes.length])
  const move = (amount: number) => {
    if (recipes.length < 2) return
    setMotion(amount > 0 ? 'next' : 'previous')
    setMotionKey(current => current + 1)
    setIndex(current => (current + amount + recipes.length) % recipes.length)
  }
  const current = recipes[index]
  const deckLabel = tone === 'favoured' ? 'favoured' : 'excluded'
  return <section className={`recipe-impact-deck recipe-impact-deck--${tone}`} aria-label={`${title} deck`}><div className="recipe-impact-deck-heading"><div><p className="eyebrow">{tone === 'favoured' ? 'Planner priority' : 'Removed first'}</p><h3>{title}</h3></div><strong>{recipes.length}</strong></div><p className="recipe-impact-deck-description">{description}</p><div className="recipe-impact-stack" tabIndex={current ? 0 : -1} role="group" aria-label={current ? `${current.title}, ${index + 1} of ${recipes.length}` : `No ${deckLabel} recipes`} onKeyDown={event => { if (event.key === 'ArrowLeft') move(-1); if (event.key === 'ArrowRight') move(1) }} onPointerDown={event => setPointerStart(event.clientX)} onPointerUp={event => { if (pointerStart !== null && Math.abs(event.clientX - pointerStart) > 38) move(event.clientX < pointerStart ? 1 : -1); setPointerStart(null) }} onPointerCancel={() => setPointerStart(null)}>{current ? <><span key={`back-${motionKey}`} className={`recipe-impact-card-shadow recipe-impact-card-shadow--back recipe-impact-card-shadow--${motion}`} aria-hidden="true"/><span key={`middle-${motionKey}`} className={`recipe-impact-card-shadow recipe-impact-card-shadow--middle recipe-impact-card-shadow--${motion}`} aria-hidden="true"/><article key={`${current.id}-${motionKey}`} className={`recipe-impact-card recipe-impact-card--${motion}`}><div className="recipe-impact-card-label"><span>{current.tier === 'must' ? 'Must-use match' : current.tier === 'prefer' ? 'Preferred match' : 'Excluded match'}</span><small>{index + 1} / {recipes.length}</small></div><div className="recipe-impact-card-art" aria-hidden="true"><span>{current.title.split(/\s+/).slice(0, 2).map(word => word[0]).join('').toUpperCase()}</span></div><h4>{current.title}</h4><div className="recipe-impact-reasons">{current.reasons.map(reason => <span className={`tag${reason.kind === 'prefer' ? ' tag--warm' : reason.kind === 'exclude' ? ' tag--danger' : ''}`} key={`${reason.kind}-${reason.ingredient}`}>{reason.kind === 'must' ? 'Must' : reason.kind === 'prefer' ? 'Prefer' : "Don't use"}: {reason.ingredient}</span>)}</div></article></> : <div className="recipe-impact-empty"><strong>No recipes in this deck</strong><span>Add ingredient guidance to see which saved recipes are affected.</span></div>}</div><div className="recipe-impact-controls"><button type="button" aria-label={`Previous ${deckLabel} recipe`} disabled={recipes.length < 2} onClick={() => move(-1)}><ChevronLeft/></button><span>{recipes.length ? `${index + 1} of ${recipes.length}` : 'Empty deck'}</span><button type="button" aria-label={`Next ${deckLabel} recipe`} disabled={recipes.length < 2} onClick={() => move(1)}><ChevronRight/></button></div></section>
}

function GuidanceImpactDecks({ catalogue, guidance, loading, error }: { catalogue: IngredientChoice[]; guidance: IngredientGuidance; loading: boolean; error: boolean }) {
  const decks = useMemo(() => buildRecipeImpactDecks(catalogue, guidance), [catalogue, guidance])
  return <aside className="recipe-impact-panel" aria-labelledby="recipe-impact-title"><div className="recipe-impact-panel-heading"><div><p className="eyebrow">Live recipe impact</p><h2 id="recipe-impact-title">What these choices change</h2></div><span>Swipe the cards</span></div>{loading && <Loading label="Checking saved recipes…"/>}{error && <Notice tone="warning" title="Preview unavailable">The saved ingredient catalogue could not be loaded.</Notice>}{!loading && !error && <div className="recipe-impact-decks"><RecipeImpactDeck title="Favoured recipes" description="Must-use matches come first, followed by preferred matches." tone="favoured" recipes={decks.favoured}/><RecipeImpactDeck title="Excluded recipes" description="These recipes are removed before the planner ranks the rest." tone="excluded" recipes={decks.excluded}/></div>}{decks.unmatched.length > 0 && <div className="recipe-impact-unmatched"><TriangleAlert/><span>Not found in a saved recipe: {decks.unmatched.join(', ')}</span></div>}<p className="recipe-impact-note">Ingredient-only preview. Meal tags, household rules and nutrition targets still shape the final plan.</p></aside>
}

function ReviewStep({ dates, slots, members, guidance, profileRestrictionCount, generating, calorieBoosts, guestCounts }: { dates: PlannerDate[]; slots: PlannerSlot[]; members: BackendMember[]; guidance: IngredientGuidance; profileRestrictionCount: number; generating: boolean; calorieBoosts: CalorieBoosts; guestCounts: GuestCounts }) {
  const mealCounts = MEAL_TYPES.map(mealType => `${slots.filter(slot => slot.meal_type === mealType).length} ${mealType}`).join(' · ')
  const boosts = calorieBoostEntries(dates, members.map(member => member.id), calorieBoosts)
  const guestPlaces = guestDayEntries(dates, guestCounts).reduce((sum, day) => sum + day.guest_count, 0)
  return <div className="constraint-review"><dl><div><dt>Dates</dt><dd>{formatDateRange(dates)} · {dates.length} {dates.length === 1 ? 'day' : 'days'}</dd></div><div><dt>Meal slots</dt><dd>{slots.length} total · {mealCounts}</dd></div><div><dt>People</dt><dd>{members.map(member => member.name).join(', ')}</dd></div><div><dt>Special days</dt><dd>{boosts.length} calorie {boosts.length === 1 ? 'boost' : 'boosts'} · {guestPlaces} guest {guestPlaces === 1 ? 'place' : 'places'}</dd></div><div><dt>Cooking</dt><dd>{batchCount(slots)} new recipe {batchCount(slots) === 1 ? 'batch' : 'batches'}</dd></div><div><dt>Plan guidance</dt><dd>{guidance.must.length} must use · {guidance.prefer.length} preferred · {guidance.exclude.length} excluded</dd></div><div><dt>Profile rules</dt><dd>{profileRestrictionCount} applied automatically</dd></div></dl><Notice title="Recipes are meal-tagged">Only planner-ready recipes tagged for the relevant breakfast, lunch, dinner or snack slot will be considered.</Notice>{generating && <ProgressBar value={72} label="Balancing nutrition, portions, batches and preferences…"/>}</div>
}

function GeneratedPlan({ plan, memberNames, onBack, onPlanChange }: { plan: BackendPlanDetail; memberNames: Record<string, string>; onBack: () => void; onPlanChange: (plan: BackendPlanDetail) => void }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const editable = plan.plan.status === 'ready'
  const [accepting, setAccepting] = useState(false)
  const [acceptError, setAcceptError] = useState<{ message: string; code?: string; actions: ApiAction[] } | null>(null)
  const [removingSideId, setRemovingSideId] = useState('')
  const [failedRemovalId, setFailedRemovalId] = useState('')
  const [collapsedDays, setCollapsedDays] = useState<Record<string, boolean>>({})
  const grouped = useMemo(() => plan.occurrences.reduce<Record<string, BackendPlanDetail['occurrences']>>((result, item) => {
    ;(result[item.meal_date] ??= []).push(item)
    return result
  }, {}), [plan.occurrences])
  for (const occurrences of Object.values(grouped)) {
    occurrences.sort((left, right) => compareMealTypes(left.meal_type, right.meal_type) || left.component_slot - right.component_slot)
  }
  const batchDates = plan.occurrences.reduce<Record<string, string[]>>((result, item) => {
    const mainBatchId = item.parent_batch_id ?? item.batch_id
    if (item.component_slot === 0 && !(result[mainBatchId] ?? []).includes(item.meal_date)) (result[mainBatchId] ??= []).push(item.meal_date)
    return result
  }, {})
  const planDayCount = Math.max(1, Math.round((new Date(`${plan.plan.end_date}T12:00:00`).getTime() - new Date(`${plan.plan.start_date}T12:00:00`).getTime()) / (24 * 60 * 60 * 1000)) + 1)
  const dates = plannerDates(plan.plan.start_date, planDayCount).map(date => date.iso)
  const guestCounts = new Map((plan.plan.guest_days ?? []).map(day => [day.meal_date, day.guest_count]))
  const boostsByDate = (plan.plan.calorie_boosts ?? []).reduce<Record<string, Array<{ member_id: string; calories: number }>>>((result, boost) => {
    ;(result[boost.meal_date] ??= []).push({ member_id: boost.member_id, calories: Number(boost.calories) })
    return result
  }, {})

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

  const removeSide = async (sideBatchId: string, ignoreNutritionTolerances = false) => {
    setRemovingSideId(sideBatchId)
    setFailedRemovalId('')
    setAcceptError(null)
    try {
      if (isDemoMode) {
        const updated = { ...plan, occurrences: plan.occurrences.filter(item => item.batch_id !== sideBatchId) }
        storeDemoPlan(updated)
        onPlanChange(updated)
      } else {
        const updated = await api.removePlanSide(plan.plan.id, sideBatchId, plan.plan.version, ignoreNutritionTolerances)
        queryClient.setQueryData(['plan', plan.plan.id], updated)
        onPlanChange(updated)
      }
    } catch (reason) {
      const error = reason instanceof ApiError ? reason : new ApiError(0, 'The added item could not be removed.')
      setAcceptError({ message: error.message, code: error.code, actions: error.actions })
      if (error.code === 'NUTRITION_TARGET_INFEASIBLE') setFailedRemovalId(sideBatchId)
    } finally {
      setRemovingSideId('')
    }
  }

  return <div className="page"><PageHeader eyebrow={`${plan.plan.start_date} – ${plan.plan.end_date}`} title={editable ? 'Your plan is ready' : 'Your accepted plan'} description={editable ? 'Review each day, customise any recipe, then accept the plan to create the shopping list.' : 'This plan is accepted. Review its meals or open the current shopping list.'} actions={<><Button variant="secondary" onClick={onBack}>{editable ? 'Edit setup' : 'Build another plan'}</Button><Button disabled={accepting} onClick={accept}>{accepting ? 'Opening…' : editable ? 'Accept plan' : 'Open shopping list'}<ArrowRight/></Button></>}/>{acceptError && <Card className="planner-action-error" role="alert"><CircleAlert/><div><h3>{acceptError.code === 'SHOPPING_REVIEW_REQUIRED' ? 'Shopping ingredients need attention' : 'Plan needs attention'}</h3><p>{acceptError.message}</p>{acceptError.actions.map((action, index) => <div className="planner-error-action" key={`${action.href}-${index}`}><span>{action.suggestion ?? 'Review the suggested change, then return and accept the plan again.'}</span>{action.href && <Link className="button button--secondary" to={appendReturnTo(action.href, `/plan?plan=${plan.plan.id}`)}>{action.label ?? 'Review issue'}</Link>}</div>)}</div></Card>}<Notice tone="success" title={editable ? 'Plan generated' : 'Plan accepted'}>Each day shows the portion-adjusted calories and macros for every person eating.</Notice><div className="generated-grid">{dates.map(date => {
    const occurrences = grouped[date] ?? []
    const memberNutrition = memberNutritionTotals(occurrences)
    const collapsed = Boolean(collapsedDays[date])
    const dayBoosts = boostsByDate[date] ?? []
    const guestCount = guestCounts.get(date) ?? 0
    return <Card key={date} className={`generated-day${collapsed ? ' is-collapsed' : ''}`}><div className="generated-day-head generated-day-head--rich"><div className="generated-day-date"><strong>{new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long' })}</strong><small>{new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}</small>{(dayBoosts.length > 0 || guestCount > 0) && <span className="generated-day-adjustments">{dayBoosts.map(boost => <em key={boost.member_id}><Flame/>{memberNames[boost.member_id] ?? 'Member'} +{Number(boost.calories).toLocaleString()} kcal</em>)}{guestCount > 0 && <em><UserRoundPlus/>{guestCount} {guestCount === 1 ? 'guest' : 'guests'}</em>}</span>}</div><div className="day-member-nutrition">{memberNutrition.map(item => <div className="day-member-nutrition-row" key={item.memberId}><span>{memberNames[item.memberId] ?? 'Household member'}</span><NutritionStrip compact nutrition={item.nutrition}/></div>)}</div><button type="button" className="day-collapse-button" onClick={() => setCollapsedDays(current => ({ ...current, [date]: !collapsed }))} aria-expanded={!collapsed} aria-controls={`planned-day-${date}`} aria-label={`${collapsed ? 'Expand' : 'Collapse'} ${date}`}>{collapsed ? <ChevronDown/> : <ChevronUp/>}</button></div><div id={`planned-day-${date}`} hidden={collapsed}>{!occurrences.length && <div className="generated-day-empty">No meals needed</div>}{occurrences.map(item => {
      const servings = occurrenceServings(item)
      const kcal = Number(item.nutrition_per_serving?.energy_kcal ?? 0) * servings
      const isSide = item.component_slot > 0
      const sideItems = isSide ? [] : occurrences.filter(side => side.parent_batch_id === item.batch_id)
      const nextSideSlot = [1, 2].find(slot => !sideItems.some(side => side.component_slot === slot))
      const coveredDates = batchDates[item.parent_batch_id ?? item.batch_id] ?? [item.meal_date]
      const shortBatchDate = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
      const coverage = coveredDates.length > 1 ? `${shortBatchDate(coveredDates[0])}–${shortBatchDate(coveredDates.at(-1) as string)}` : shortBatchDate(coveredDates[0])
      return <div className={`generated-meal${isSide ? ' generated-meal--side' : ''}`} key={item.id}>
        <span>{isSide ? item.meal_type === 'snack' ? 'Snack' : 'Side' : capitalise(item.meal_type)}</span>
        <div className="generated-meal-copy"><strong>{item.recipe_title}</strong><small>{item.portions.map(portion => `${memberNames[portion.member_id] ?? 'Household member'} ${Number(portion.servings)} serving${Number(portion.servings) === 1 ? '' : 's'}`).join(' · ')}{Number(item.guest_servings ?? 0) > 0 && ` · Guests ${Number(item.guest_servings)} serving${Number(item.guest_servings) === 1 ? '' : 's'}`}</small>{!isSide && <small>Cooking batch · {coverage}</small>}</div>
        <small>{Math.round(kcal)} kcal</small>
        {editable && <div className="generated-meal-actions">
          {isSide ? <>
            <Link className="generated-meal-customise" to={`/plan/${plan.plan.id}/batches/${item.parent_batch_id}/sides/${item.component_slot}/recipes?mealType=${encodeURIComponent(item.meal_type)}`}><WandSparkles size={15}/>Replace</Link>
            <button type="button" className="generated-meal-remove" disabled={removingSideId === item.batch_id} onClick={() => void removeSide(item.batch_id, failedRemovalId === item.batch_id)}><Trash2 size={15}/>{removingSideId === item.batch_id ? 'Removing…' : failedRemovalId === item.batch_id ? 'Continue anyway' : 'Remove'}</button>
          </> : <>
            <Link className="generated-meal-customise" to={`/plan/${plan.plan.id}/occurrences/${item.id}/recipes?mealType=${encodeURIComponent(item.meal_type)}`}><WandSparkles size={15}/>Customise</Link>
            {nextSideSlot && <Link className="generated-meal-customise generated-meal-add" to={`/plan/${plan.plan.id}/batches/${item.batch_id}/sides/${nextSideSlot}/recipes?mealType=${encodeURIComponent(item.meal_type)}`}><Plus size={15}/>{item.meal_type === 'snack' ? 'Add snacks' : 'Add side'}</Link>}
          </>}
        </div>}
      </div>
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

function buildDemoPlan(dates: PlannerDate[], slots: PlannerSlot[], calorieBoosts: CalorieBoosts, guestCounts: GuestCounts): BackendPlanDetail {
  const batchIndexes = new Map<string, number>()
  const nextIndex: Record<MealType, number> = { breakfast: 0, lunch: 0, dinner: 0, snack: 0 }
  for (const slot of slots) {
    if (!batchIndexes.has(slot.batch_key)) {
      batchIndexes.set(slot.batch_key, nextIndex[slot.meal_type])
      nextIndex[slot.meal_type] += 1
    }
  }
  const batchServings = slots.reduce<Record<string, number>>((result, slot) => {
    result[slot.batch_key] = (result[slot.batch_key] ?? 0) + slot.participant_member_ids.length + (guestCounts[slot.meal_date] ?? 0)
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
      calorie_boosts: calorieBoostEntries(dates, [demoMember.id], calorieBoosts),
      guest_days: guestDayEntries(dates, guestCounts),
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
        component_slot: 0,
        guest_servings: guestCounts[slot.meal_date] ?? 0,
        recipe_id: recipe.id,
        recipe_title: recipe.title,
        batch_servings: batchServings[slot.batch_key],
        nutrition_per_serving: recipe.nutrition,
        portions: slot.participant_member_ids.map(memberId => ({ member_id: memberId, servings: 1 })),
      }
    }),
  }
}
