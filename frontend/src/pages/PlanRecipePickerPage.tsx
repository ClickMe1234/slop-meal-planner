import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Check, ChefHat, ExternalLink, Search, WandSparkles } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { NutritionStrip } from '../components/Nutrition'
import { Badge, Button, Card, EmptyState, Loading, Notice, PageHeader } from '../components/ui'
import { demoRecipes } from '../data/demo'
import {
  api,
  ApiError,
  isDemoMode,
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
  mealTypes: MealType[]
}

function isMealType(value: string | null | undefined): value is MealType {
  return Boolean(value && MEAL_TYPES.includes(value as MealType))
}

export function PlanRecipePickerPage() {
  const { planId = '', occurrenceId = '' } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [savingId, setSavingId] = useState('')
  const [importingUrl, setImportingUrl] = useState('')
  const [error, setError] = useState('')

  const planQuery = useQuery({
    queryKey: ['plan', planId],
    queryFn: () => api.getPlan(planId),
    enabled: !isDemoMode && Boolean(planId),
    retry: false,
  })
  const plan = isDemoMode ? readDemoPlan() : planQuery.data
  const occurrence = plan?.occurrences.find(item => item.id === occurrenceId)
  const requestedMealType = searchParams.get('mealType')
  const mealType = isMealType(occurrence?.meal_type)
    ? occurrence.meal_type
    : isMealType(requestedMealType) ? requestedMealType : undefined

  const savedRecipes = useQuery({
    queryKey: ['recipes', 'picker', query, mealType],
    queryFn: () => api.listRecipes(query, mealType),
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
        .filter(recipe => recipe.mealKinds.some(kind => kind.toLowerCase() === mealType))
        .filter(recipe => recipe.title.toLowerCase().includes(query.trim().toLowerCase()))
        .map(recipe => ({
          id: recipe.id,
          title: recipe.title,
          imageUrl: recipe.imageUrl,
          nutrition: recipe.nutrition ?? recipe.publisherNutrition,
          eligible: true,
          warnings: [],
          mealTypes: recipe.mealKinds.map(kind => kind.toLowerCase()).filter(isMealType),
        }))
    }
    return (savedRecipes.data?.items ?? [])
      .filter(recipe => recipe.meal_types.includes(mealType))
      .map(mapBackendRecipe)
  }, [mealType, query, savedRecipes.data])

  const choose = async (recipe: PickerRecipe) => {
    if (!plan || !occurrence || !mealType) return
    setSavingId(recipe.id)
    setError('')
    try {
      if (isDemoMode) {
        const updated: BackendPlanDetail = {
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
        storeDemoPlan(updated)
      } else {
        const updated = await api.replacePlanRecipe(planId, occurrenceId, recipe.id, plan.plan.version)
        queryClient.setQueryData(['plan', planId], updated)
      }
      navigate(`/plan?plan=${encodeURIComponent(planId)}`)
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The recipe could not be changed.')
    } finally {
      setSavingId('')
    }
  }

  const startImport = async (result: DiscoveryResult) => {
    if (!mealType) return
    setImportingUrl(result.url)
    setError('')
    try {
      const job = await api.startImport(result.url)
      const returnTo = `/plan/${planId}/occurrences/${occurrenceId}/recipes?mealType=${encodeURIComponent(mealType)}`
      navigate(`/imports/${job.id}/review?suggestedMealType=${encodeURIComponent(mealType)}&returnTo=${encodeURIComponent(returnTo)}`)
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The recipe could not be imported.')
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
  return <div className="page"><div className="review-top"><Link to={backToPlan} className="icon-link"><ArrowLeft/>Back to plan</Link><Badge tone="green">{capitalise(mealType)} recipes only</Badge></div><PageHeader eyebrow={`${occurrence.meal_date} · ${capitalise(mealType)}`} title="Choose a different recipe" description={`Replace ${occurrence.recipe_title} for this cooked batch and every date it covers. Only saved recipes tagged for ${mealType} can be selected.`}/><div className="recipe-search planner-picker-search"><Search size={22}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder={`Search saved ${mealType} recipes or recipe websites…`} aria-label={`Search ${mealType} recipes`}/></div>{error && <Notice tone="warning" title="Could not update meal">{error}</Notice>}<section className="planner-picker-section"><div className="section-heading"><div><h2>Saved recipes</h2><p>{recipes.length} tagged for {mealType}</p></div></div>{recipes.length ? <div className="planner-recipe-grid">{recipes.map(recipe => <PickerRecipeCard key={recipe.id} recipe={recipe} current={recipe.id === occurrence.recipe_id} saving={savingId === recipe.id} onChoose={() => choose(recipe)}/>)}</div> : <EmptyState icon={<ChefHat size={38}/>} title={`No saved ${mealType} recipes found`} description={`Add the ${mealType} tag to a planner-ready recipe, or search recipe websites below.`} action={<Link className="button button--secondary" to="/recipes">Manage recipes</Link>}/>}</section>{query.trim().length >= 2 && <section className="planner-picker-section"><div className="section-heading"><div><h2>Recipe websites</h2><p>Save a new recipe, confirm its details and return here to select it.</p></div></div>{remoteRecipes.isFetching ? <Loading label="Searching recipe websites…"/> : remoteResults.length ? <div className="planner-remote-results">{remoteResults.map(result => <Card className="planner-remote-card" key={result.url}><div>{result.image_url ? <img src={result.image_url} alt=""/> : <ChefHat/>}</div><span><strong>{result.title}</strong><small>{result.source}</small></span><a href={result.url} target="_blank" rel="noreferrer" aria-label={`Open ${result.title}`}><ExternalLink/></a><Button variant="secondary" disabled={result.already_saved || importingUrl === result.url} onClick={() => startImport(result)}>{result.already_saved ? <><Check/>Already saved</> : importingUrl === result.url ? 'Starting import…' : <><WandSparkles/>Save for {mealType}</>}</Button></Card>)}</div> : <p className="muted">No website recipes found. Try a broader search.</p>}</section>}</div>
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
