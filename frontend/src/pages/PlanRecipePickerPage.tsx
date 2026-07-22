import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Check, ChefHat, ExternalLink, Search, WandSparkles } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { NutritionStrip } from '../components/Nutrition'
import { RecipeRating } from '../components/RecipeRating'
import { Badge, Button, Card, EmptyState, Loading, Notice, PageHeader } from '../components/ui'
import { demoRecipes } from '../data/demo'
import {
  api,
  ApiError,
  isDemoMode,
  type BackendMealType,
  type BackendPlanDetail,
  type BackendRecipe,
  type DiscoveryResult,
} from '../api/client'
import type { Nutrition } from '../types'
import { MEAL_TYPES, capitalise, readDemoPlan, storeDemoPlan, type MealType } from './planner'

interface PickerRecipe {
  id: string
  title: string
  imageUrl?: string
  nutrition?: Nutrition
  eligible: boolean
  warnings: string[]
  mealTypes: BackendMealType[]
}

function isMealType(value: string | null | undefined): value is MealType {
  return Boolean(value && MEAL_TYPES.includes(value as MealType))
}

export function PlanRecipePickerPage() {
  const { planId = '', occurrenceId = '', batchId = '', componentSlot = '' } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [savingId, setSavingId] = useState('')
  const [importingUrl, setImportingUrl] = useState('')
  const [error, setError] = useState<ApiError | null>(null)
  const [failedRecipe, setFailedRecipe] = useState<PickerRecipe | null>(null)

  const planQuery = useQuery({
    queryKey: ['plan', planId],
    queryFn: () => api.getPlan(planId),
    enabled: !isDemoMode && Boolean(planId),
    retry: false,
  })
  const plan = isDemoMode ? readDemoPlan() : planQuery.data
  const sideMode = Boolean(batchId)
  const occurrence = sideMode
    ? plan?.occurrences.find(item => item.batch_id === batchId && item.component_slot === 0)
    : plan?.occurrences.find(item => item.id === occurrenceId)
  const sideSlot = Number(componentSlot)
  const existingSide = sideMode
    ? plan?.occurrences.find(item => item.parent_batch_id === batchId && item.component_slot === sideSlot)
    : undefined
  const requestedMealType = searchParams.get('mealType')
  const mealType = isMealType(occurrence?.meal_type)
    ? occurrence.meal_type
    : isMealType(requestedMealType) ? requestedMealType : undefined
  const candidateTags: BackendMealType[] = sideMode
    ? mealType === 'snack' ? ['snack'] : ['side', 'snack']
    : mealType ? [mealType] : []

  const savedRecipes = useQuery({
    queryKey: ['recipes', 'picker', query, candidateTags.join(',')],
    queryFn: () => api.listRecipes(query, candidateTags, [], 'any', true),
    enabled: !isDemoMode && Boolean(mealType),
  })
  const remoteRecipes = useQuery({
    queryKey: ['recipe-discovery', 'picker', query.trim()],
    queryFn: () => api.searchRemote(query.trim(), `plan-picker-${occurrenceId}`, ['good_food', 'allrecipes']),
    enabled: !isDemoMode && query.trim().length >= 2,
  })

  const recipes = useMemo<PickerRecipe[]>(() => {
    if (!mealType) return []
    if (isDemoMode) {
      return demoRecipes
        .filter(recipe => recipe.mealKinds.some(kind => candidateTags.includes(kind.toLowerCase() as BackendMealType)))
        .filter(recipe => recipe.title.toLowerCase().includes(query.trim().toLowerCase()))
        .map(recipe => ({
          id: recipe.id,
          title: recipe.title,
          imageUrl: recipe.imageUrl,
          nutrition: recipe.nutrition ?? recipe.publisherNutrition,
          eligible: true,
          warnings: [],
          mealTypes: recipe.mealKinds.map(kind => kind.toLowerCase() as BackendMealType),
        }))
    }
    return (savedRecipes.data?.items ?? [])
      .filter(recipe => recipe.meal_types.some(tag => candidateTags.includes(tag)))
      .map(mapBackendRecipe)
  }, [candidateTags, mealType, query, savedRecipes.data])

  const choose = async (recipe: PickerRecipe, ignoreNutritionTolerances = false) => {
    if (!plan || !occurrence || !mealType) return
    setSavingId(recipe.id)
    setError(null)
    setFailedRecipe(null)
    try {
      if (isDemoMode) {
        let updated: BackendPlanDetail
        if (sideMode) {
          const matchingMains = plan.occurrences.filter(item => item.batch_id === batchId && item.component_slot === 0)
          const retained = plan.occurrences.filter(item => !(item.parent_batch_id === batchId && item.component_slot === sideSlot))
          const sideBatchId = existingSide?.batch_id ?? `demo-${batchId}-side-${sideSlot}`
          updated = {
            ...plan,
            occurrences: [...retained, ...matchingMains.map(item => ({
              ...item,
              id: `${item.id}-side-${sideSlot}`,
              batch_id: sideBatchId,
              parent_batch_id: batchId,
              component_slot: sideSlot,
              recipe_id: recipe.id,
              recipe_title: recipe.title,
              batch_servings: item.portions.length * 0.25,
              nutrition_per_serving: recipe.nutrition ? {
                energy_kcal: recipe.nutrition.calories,
                protein_g: recipe.nutrition.protein,
                carbohydrate_g: recipe.nutrition.carbs,
                fat_g: recipe.nutrition.fat,
              } : item.nutrition_per_serving,
              portions: item.portions.map(portion => ({ ...portion, servings: 0.25 })),
            }))],
          }
        } else {
          updated = {
            ...plan,
            occurrences: plan.occurrences.map(item => item.batch_id === occurrence.batch_id ? {
              ...item,
              recipe_id: recipe.id,
              recipe_title: recipe.title,
              nutrition_per_serving: recipe.nutrition ? {
                energy_kcal: recipe.nutrition.calories,
                protein_g: recipe.nutrition.protein,
                carbohydrate_g: recipe.nutrition.carbs,
                fat_g: recipe.nutrition.fat,
              } : item.nutrition_per_serving,
            } : item),
          }
        }
        storeDemoPlan(updated)
      } else {
        const updated = sideMode
          ? await api.addPlanSide(planId, batchId, recipe.id, plan.plan.version, sideSlot, ignoreNutritionTolerances)
          : await api.replacePlanRecipe(planId, occurrenceId, recipe.id, plan.plan.version, ignoreNutritionTolerances)
        queryClient.setQueryData(['plan', planId], updated)
      }
      navigate(`/plan?plan=${encodeURIComponent(planId)}`)
    } catch (reason) {
      const apiError = reason instanceof ApiError ? reason : new ApiError(0, 'The recipe could not be changed.')
      setError(apiError)
      if (apiError.code === 'NUTRITION_TARGET_INFEASIBLE') setFailedRecipe(recipe)
    } finally {
      setSavingId('')
    }
  }

  const startImport = async (result: DiscoveryResult) => {
    if (!mealType) return
    setImportingUrl(result.url)
    setError(null)
    setFailedRecipe(null)
    try {
      const job = await api.startImport(result.url)
      const returnTo = sideMode
        ? `/plan/${planId}/batches/${batchId}/sides/${sideSlot}/recipes?mealType=${encodeURIComponent(mealType)}`
        : `/plan/${planId}/occurrences/${occurrenceId}/recipes?mealType=${encodeURIComponent(mealType)}`
      const suggestedMealType = sideMode && mealType !== 'snack' ? 'side' : mealType
      navigate(`/imports/${job.id}/review?suggestedMealType=${encodeURIComponent(suggestedMealType)}&returnTo=${encodeURIComponent(returnTo)}`)
    } catch (reason) {
      setError(reason instanceof ApiError ? reason : new ApiError(0, 'The recipe could not be imported.'))
    } finally {
      setImportingUrl('')
    }
  }

  const backToPlan = `/plan?plan=${encodeURIComponent(planId)}`
  if ((!isDemoMode && planQuery.isLoading) || (mealType && savedRecipes.isLoading)) {
    return <div className="page"><PageHeader title="Choose a recipe"/><Loading label="Loading saved recipes…"/></div>
  }
  if (!plan || !occurrence || !mealType) {
    return <div className="page"><PageHeader title="Meal unavailable" description="This planned meal could not be found."/><Notice tone="warning" title="Cannot customise this meal">Open the meal plan again and choose a meal from its grid.</Notice><Link className="button button--primary" to={backToPlan}>Back to plan</Link></div>
  }
  if (plan.plan.status !== 'ready') {
    return <div className="page"><PageHeader title="Plan already accepted" description="Accepted meals are locked so their pantry reservations and shopping quantities stay consistent."/><Notice title="Start a new plan to make changes">You can still review this plan and its shopping list.</Notice><Link className="button button--primary" to={backToPlan}>Back to plan</Link></div>
  }

  const remoteResults = remoteRecipes.data?.results ?? []
  const itemLabel = mealType === 'snack' && sideMode ? 'snack' : sideMode ? 'side' : 'recipe'
  const tagLabel = candidateTags.join(' or ')
  const currentRecipeId = existingSide?.recipe_id ?? occurrence.recipe_id
  if (sideMode) {
    return <div className="page">
      <div className="review-top"><Link to={backToPlan} className="icon-link"><ArrowLeft/>Back to plan</Link><Badge tone="green">{capitalise(tagLabel)} recipes</Badge></div>
      <PageHeader
        eyebrow={`${occurrence.meal_date} · ${capitalise(mealType)}`}
        title={`${existingSide ? 'Replace' : 'Add'} ${itemLabel}`}
        description={`This ${itemLabel} applies to the whole ${capitalise(mealType)} cooking batch. Portions across the plan will be recalculated after selection.`}
      />
      <div className="recipe-search planner-picker-search"><Search size={22}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder={`Search saved ${itemLabel} recipes or recipe websites…`} aria-label={`Search ${itemLabel} recipes`}/></div>
      {error && <Card className="planner-generation-error"><Notice tone="warning" title="Could not update meal">{error.message}</Notice>{failedRecipe && <Button variant="secondary" disabled={Boolean(savingId)} onClick={() => choose(failedRecipe, true)}>Continue anyway</Button>}</Card>}
      <section className="planner-picker-section">
        <div className="section-heading"><div><h2>Saved recipes</h2><p>{recipes.length} tagged {tagLabel}</p></div></div>
        {recipes.length
          ? <div className="planner-recipe-grid">{recipes.map(recipe => <PickerRecipeCard key={recipe.id} recipe={recipe} current={recipe.id === currentRecipeId} saving={savingId === recipe.id} onChoose={() => choose(recipe)}/>)}</div>
          : <EmptyState icon={<ChefHat size={38}/>} title={`No saved ${itemLabel} recipes found`} description={`Add a ${tagLabel} tag to a planner-ready recipe, or search recipe websites below.`} action={<Link className="button button--secondary" to="/recipes">Manage recipes</Link>}/>
        }
      </section>
      {query.trim().length >= 2 && <section className="planner-picker-section"><div className="section-heading"><div><h2>Recipe websites</h2><p>Save a new recipe, tag it and return here to select it.</p></div></div>{remoteRecipes.isFetching ? <Loading label="Searching recipe websites…"/> : remoteResults.length ? <div className="planner-remote-results">{remoteResults.map(result => <Card className="planner-remote-card" key={result.url}><div>{result.image_url ? <img src={result.image_url} alt=""/> : <ChefHat/>}</div><span><strong>{result.title}</strong><small>{result.source}</small><RecipeRating rating={result.star_rating} count={result.rating_count}/></span><a href={result.url} target="_blank" rel="noreferrer" aria-label={`Open ${result.title}`}><ExternalLink/></a><Button variant="secondary" disabled={result.already_saved || importingUrl === result.url} onClick={() => startImport(result)}>{result.already_saved ? <><Check/>Already saved</> : importingUrl === result.url ? 'Starting import…' : <><WandSparkles/>Save for {itemLabel}</>}</Button></Card>)}</div> : <p className="muted">No website recipes found. Try a broader search.</p>}</section>}
    </div>
  }
  return <div className="page"><div className="review-top"><Link to={backToPlan} className="icon-link"><ArrowLeft/>Back to plan</Link><Badge tone="green">{capitalise(mealType)} recipes only</Badge></div><PageHeader eyebrow={`${occurrence.meal_date} · ${capitalise(mealType)}`} title="Choose a different recipe" description={`Replace ${occurrence.recipe_title} for this cooked batch and every date it covers. Only saved recipes tagged for ${mealType} can be selected.`}/><div className="recipe-search planner-picker-search"><Search size={22}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder={`Search saved ${mealType} recipes or recipe websites…`} aria-label={`Search ${mealType} recipes`}/></div>{error && <Card className="planner-generation-error"><Notice tone="warning" title="Could not update meal">{error.message}</Notice>{failedRecipe && <Button variant="secondary" disabled={Boolean(savingId)} onClick={() => choose(failedRecipe, true)}>Continue anyway</Button>}</Card>}<section className="planner-picker-section"><div className="section-heading"><div><h2>Saved recipes</h2><p>{recipes.length} tagged for {mealType}</p></div></div>{recipes.length ? <div className="planner-recipe-grid">{recipes.map(recipe => <PickerRecipeCard key={recipe.id} recipe={recipe} current={recipe.id === occurrence.recipe_id} saving={savingId === recipe.id} onChoose={() => choose(recipe)}/>)}</div> : <EmptyState icon={<ChefHat size={38}/>} title={`No saved ${mealType} recipes found`} description={`Add the ${mealType} tag to a planner-ready recipe, or search recipe websites below.`} action={<Link className="button button--secondary" to="/recipes">Manage recipes</Link>}/>}</section>{query.trim().length >= 2 && <section className="planner-picker-section"><div className="section-heading"><div><h2>Recipe websites</h2><p>Save a new recipe, confirm its details and return here to select it.</p></div></div>{remoteRecipes.isFetching ? <Loading label="Searching recipe websites…"/> : remoteResults.length ? <div className="planner-remote-results">{remoteResults.map(result => <Card className="planner-remote-card" key={result.url}><div>{result.image_url ? <img src={result.image_url} alt=""/> : <ChefHat/>}</div><span><strong>{result.title}</strong><small>{result.source}</small><RecipeRating rating={result.star_rating} count={result.rating_count}/></span><a href={result.url} target="_blank" rel="noreferrer" aria-label={`Open ${result.title}`}><ExternalLink/></a><Button variant="secondary" disabled={result.already_saved || importingUrl === result.url} onClick={() => startImport(result)}>{result.already_saved ? <><Check/>Already saved</> : importingUrl === result.url ? 'Starting import…' : <><WandSparkles/>Save for {mealType}</>}</Button></Card>)}</div> : <p className="muted">No website recipes found. Try a broader search.</p>}</section>}</div>
}

function PickerRecipeCard({ recipe, current, saving, onChoose }: { recipe: PickerRecipe; current: boolean; saving: boolean; onChoose: () => void }) {
  return <Card className="planner-recipe-card"><div className="planner-recipe-image">{recipe.imageUrl ? <img src={recipe.imageUrl} alt=""/> : <ChefHat/>}{current && <Badge tone="green">Current</Badge>}</div><div className="planner-recipe-copy"><h3>{recipe.title}</h3><div className="tag-row">{recipe.mealTypes.map(mealType => <Badge key={mealType}>{capitalise(mealType)}</Badge>)}</div>{recipe.nutrition && <NutritionStrip compact nutrition={recipe.nutrition}/>} {recipe.warnings.map(warning => <small className="field-help field-help--warning" key={warning}>{warning}</small>)}<Button disabled={current || saving || !recipe.eligible} onClick={onChoose}>{current ? 'Selected' : saving ? 'Updating plan…' : 'Use this recipe'}</Button></div></Card>
}

function mapBackendRecipe(recipe: BackendRecipe): PickerRecipe {
  const values = recipe.publisher_nutrition ?? recipe.calculated_nutrition
  const nutrition = values && Number(values.energy_kcal) >= 0 ? {
    calories: Number(values.energy_kcal ?? 0),
    protein: Number(values.protein_g ?? 0),
    carbs: Number(values.carbohydrate_g ?? 0),
    fat: Number(values.fat_g ?? 0),
    basis: 'per_serving' as const,
  } : undefined
  return {
    id: recipe.id,
    title: recipe.title,
    imageUrl: recipe.image_url,
    nutrition,
    eligible: recipe.planner_eligible,
    warnings: recipe.planner_warnings,
    mealTypes: recipe.meal_types,
  }
}
