import { Check, ChefHat, ExternalLink, Filter, Link2, Search, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { NutritionStrip } from '../components/Nutrition'
import { Badge, Button, Card, EmptyState, Loading, Notice, PageHeader, Segmented } from '../components/ui'
import { mealKindLabels } from '../components/MealTypePicker'
import { demoRecipes } from '../data/demo'
import type { Nutrition, Recipe } from '../types'
import { api, ApiError, isDemoMode, type BackendRecipe, type DiscoveryResult, type RecipeSourceKey } from '../api/client'

const SOURCE_OPTIONS: Array<{ value: RecipeSourceKey; label: string }> = [
  { value: 'good_food', label: 'Good Food' },
  { value: 'allrecipes', label: 'Allrecipes' },
]
const ALL_SOURCES = SOURCE_OPTIONS.map(option => option.value)

export function savedRecipePlanningBadge(recipe: Pick<Recipe, 'state' | 'mealKinds'>): { tone: 'green' | 'warning'; label: string } {
  if (!recipe.mealKinds.length) return { tone: 'warning', label: 'Needs meal types' }
  if (recipe.state !== 'ready') return { tone: 'warning', label: 'Needs recipe review' }
  return { tone: 'green', label: 'Used for planning' }
}

export function RecipesPage() {
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState<'all' | 'saved'>('all')
  const [saving, setSaving] = useState<string[]>([])
  const [importJobs, setImportJobs] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [selectedSources, setSelectedSources] = useState<RecipeSourceKey[]>(ALL_SOURCES)

  const localSearch = useQuery({
    queryKey: ['recipes', query],
    queryFn: () => api.listRecipes(query),
    enabled: !isDemoMode,
  })
  const remoteSearch = useQuery({
    queryKey: ['recipe-discovery', query.trim(), selectedSources.join(',')],
    queryFn: () => api.searchRemote(query.trim(), 'recipe-page', selectedSources),
    enabled: !isDemoMode && scope === 'all' && query.trim().length >= 2 && selectedSources.length > 0,
  })

  const results = useMemo(() => {
    if (isDemoMode) return demoRecipes.filter(recipe => {
      const matches = recipe.title.toLowerCase().includes(query.toLowerCase()) || recipe.source.toLowerCase().includes(query.toLowerCase())
      const sourceKey = SOURCE_OPTIONS.find(option => option.label === recipe.source)?.value
      return matches && (!sourceKey || selectedSources.includes(sourceKey)) && (scope === 'all' || recipe.source === 'Saved recipe' || recipe.state === 'ready')
    })
    const local = (localSearch.data?.items ?? []).map(mapSavedRecipe)
    if (scope === 'saved') return local
    const localUrls = new Set(local.map(item => item.sourceUrl).filter(Boolean))
    const remote = (remoteSearch.data?.results ?? [])
      .filter(item => !localUrls.has(item.url))
      .map(mapDiscoveryResult)
    return [...local, ...remote]
  }, [query, scope, selectedSources, localSearch.data, remoteSearch.data])

  const toggleSource = (source: RecipeSourceKey) => {
    setSelectedSources(current => current.includes(source) ? current.filter(item => item !== source) : [...current, source])
  }
  const save = async (recipe: Recipe) => {
    setSaving(items => [...items, recipe.id])
    setError('')
    try {
      if (isDemoMode) {
        await new Promise(resolve => window.setTimeout(resolve, 500))
      } else {
        const job = await api.startImport(recipe.sourceUrl)
        setImportJobs(items => ({ ...items, [recipe.id]: job.id }))
      }
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The recipe could not be saved.')
    } finally {
      setSaving(items => items.filter(item => item !== recipe.id))
    }
  }

  return <div className="page">
    <PageHeader eyebrow="Recipe catalogue" title="Find something delicious" description="Search your collection and trusted recipe websites in one place." actions={<><Link className="button button--secondary" to="/recipes/new"><ChefHat size={17}/>Custom recipe</Link><Link className="button button--secondary" to="/recipes/import"><Link2 size={17}/>Import from URL</Link></>}/>
    <div className="recipe-search"><Search size={22}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search recipes, ingredients or cuisine…" aria-label="Search recipes"/><button className={filtersOpen ? 'active' : undefined} aria-label="Recipe filters" aria-expanded={filtersOpen} onClick={() => setFiltersOpen(open => !open)}><Filter size={19}/><span>Filters{selectedSources.length < ALL_SOURCES.length ? ` (${selectedSources.length})` : ''}</span></button></div>
    {filtersOpen && <Card className="recipe-filter-panel"><div><strong>Recipe websites</strong><span>Choose which supported websites to search.</span></div><div className="filter-options">{SOURCE_OPTIONS.map(option => <label className="check-label" key={option.value}><input type="checkbox" checked={selectedSources.includes(option.value)} onChange={() => toggleSource(option.value)}/>{option.label}</label>)}</div><Button variant="ghost" onClick={() => setSelectedSources(ALL_SOURCES)}>Select all</Button></Card>}
    <div className="search-controls"><Segmented value={scope} onChange={setScope} label="Recipe source" options={[{ value: 'all', label: 'Everywhere' }, { value: 'saved', label: 'My recipes' }]}/><div className="source-pills"><span>Searching:</span>{SOURCE_OPTIONS.filter(option => selectedSources.includes(option.value)).map(option => <Badge key={option.value}>{option.label}</Badge>)}{selectedSources.length === 0 && <Badge tone="warning">No websites selected</Badge>}</div></div>
    {remoteSearch.isFetching && <div className="search-status"><Loading label="Searching recipe websites…"/><span>Saved recipes are already shown below</span></div>}
    {error && <Notice tone="warning" title="Recipe could not be saved">{error}</Notice>}
    {results.length
      ? <div className="recipe-grid">{results.map(recipe => <RecipeCard key={recipe.id} recipe={recipe} saving={saving.includes(recipe.id)} importJob={importJobs[recipe.id]} onSave={() => save(recipe)}/>)}</div>
      : <EmptyState icon={<ChefHat size={40}/>} title="No recipes found" description="Try a broader search, or import a recipe by URL." action={<Link className="button button--primary" to="/recipes/import">Import recipe</Link>}/>
    }
  </div>
}

function RecipeThumbnail({ url }: { url?: string }) {
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [url])
  return url && !failed ? <img src={url} alt="" loading="lazy" onError={() => setFailed(true)}/> : <ChefHat/>
}

function RecipeCard({ recipe, saving, importJob, onSave }: { recipe: Recipe; saving: boolean; importJob?: string; onSave: () => void }) {
  const saved = recipe.source === 'Saved recipe' || recipe.state === 'ready'
  const missingMealTypes = saved && recipe.mealKinds.length === 0
  const planningBadge = saved ? savedRecipePlanningBadge(recipe) : null
  const initialNutrition = recipe.nutrition ?? recipe.publisherNutrition
  const cardRef = useRef<HTMLDivElement>(null)
  const [previewEnabled, setPreviewEnabled] = useState(false)
  const shouldLoadPreview = !isDemoMode && !saved && !initialNutrition && Boolean(recipe.sourceUrl)
  useEffect(() => {
    if (!shouldLoadPreview) return
    const node = cardRef.current
    if (!node || !('IntersectionObserver' in window)) {
      setPreviewEnabled(true)
      return
    }
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        setPreviewEnabled(true)
        observer.disconnect()
      }
    }, { rootMargin: '500px' })
    observer.observe(node)
    return () => observer.disconnect()
  }, [shouldLoadPreview, recipe.sourceUrl])
  const preview = useQuery({
    queryKey: ['recipe-nutrition-preview', recipe.sourceUrl],
    queryFn: () => api.nutritionPreview(recipe.sourceUrl),
    enabled: shouldLoadPreview && previewEnabled,
    staleTime: 60 * 60 * 1000,
    retry: false,
  })
  const previewNutrition = completeNutrition(preview.data?.publisher_nutrition) ? mapNutrition(preview.data.publisher_nutrition) : undefined
  const nutrition = initialNutrition ?? previewNutrition
  const nutritionSource = preview.data?.publisher ?? recipe.nutritionSourceName ?? (recipe.source === 'Saved recipe' ? 'the recipe website' : recipe.source)
  const yieldServings = recipe.yield ?? preview.data?.yield_servings
  const loadingNutrition = shouldLoadPreview && (!previewEnabled || preview.isLoading)
  return <div ref={cardRef} className="recipe-card-observer"><Card className="recipe-card">
    <div className="recipe-image"><RecipeThumbnail url={recipe.imageUrl}/><div className="recipe-source">{recipe.source}</div>{saved && <span className="saved-mark" aria-label="Saved recipe"><Check size={16}/></span>}</div>
    <div className="recipe-content">
      <div className="recipe-title"><h2>{recipe.title}</h2>{recipe.sourceUrl && <a href={recipe.sourceUrl} target="_blank" rel="noreferrer" aria-label={`Open ${recipe.title} source`}><ExternalLink size={17}/></a>}</div>
      <p className="recipe-meta">{yieldServings ? `Serves ${yieldServings}` : 'Yield not reported'}{recipe.mealKinds.length ? ` · ${recipe.mealKinds.join(' · ')}` : ''}</p>
      {nutrition ? <div className="nutrition-panel nutrition-panel--calculated"><div className="panel-label"><span><Sparkles size={14}/>Nutrition from {nutritionSource} · per serving</span><Badge tone={planningBadge?.tone ?? 'green'}>{planningBadge?.label ?? 'Used after saving'}</Badge></div><NutritionStrip nutrition={nutrition} compact/></div> : <div className="nutrition-missing"><div><strong>{loadingNutrition ? `Loading nutrition from ${nutritionSource}` : `Nutrition from ${nutritionSource}`}</strong><span>{saved ? 'A complete per-serving set was not reported.' : loadingNutrition ? 'Reading the values reported on the recipe page…' : 'A complete per-serving set was not reported.'}</span></div></div>}
      {missingMealTypes && <div className="recipe-planning-note recipe-planning-note--warning" role="status"><strong>Not used for meal planning</strong><span>Add breakfast, lunch, dinner or snack so the planner knows where this recipe belongs.</span></div>}
      <div className="recipe-actions">{saved ? <Link to={`/recipes/${recipe.id}/review`} className="button button--secondary">{missingMealTypes ? 'Add meal types' : 'Edit meal types'}</Link> : importJob ? <Link to={`/imports/${importJob}/review`} className="button button--secondary">Finish saving</Link> : <Button disabled={saving} onClick={onSave}>{saving ? 'Saving…' : 'Save recipe'}</Button>}</div>
    </div>
  </Card></div>
}

function completeNutrition(nutrition?: BackendRecipe['publisher_nutrition']): nutrition is NonNullable<BackendRecipe['publisher_nutrition']> {
  const basis = nutrition?.basis?.replaceAll(' ', '').toLowerCase() ?? ''
  return Boolean(
    nutrition
    && !basis.includes('100g')
    && !basis.includes('100ml')
    && nutrition.energy_kcal != null
    && nutrition.protein_g != null
    && nutrition.carbohydrate_g != null
    && nutrition.fat_g != null
  )
}

function mapNutrition(nutrition: NonNullable<BackendRecipe['publisher_nutrition']>): Nutrition {
  return {
    calories: Number(nutrition.energy_kcal),
    protein: Number(nutrition.protein_g),
    carbs: Number(nutrition.carbohydrate_g),
    fat: Number(nutrition.fat_g),
    basis: 'per_serving',
  }
}

function sourceName(recipe: BackendRecipe): string {
  if (recipe.publisher) return recipe.publisher
  try {
    return recipe.source_url ? new URL(recipe.source_url).hostname.replace(/^www\./, '') : 'the recipe website'
  } catch {
    return 'the recipe website'
  }
}

function mapSavedRecipe(recipe: BackendRecipe): Recipe {
  const reported = completeNutrition(recipe.publisher_nutrition) ? mapNutrition(recipe.publisher_nutrition) : undefined
  return {
    id: recipe.id,
    title: recipe.title,
    source: 'Saved recipe',
    sourceUrl: recipe.source_url ?? '',
    imageUrl: recipe.image_url,
    yield: recipe.yield_servings,
    nutrition: reported,
    nutritionSource: reported ? 'publisher' : undefined,
    nutritionSourceName: sourceName(recipe),
    state: reported && recipe.yield_servings ? 'ready' : 'no_nutrition',
    reviewCount: recipe.review_count ?? 0,
    mealKinds: mealKindLabels(recipe.meal_types),
  }
}

function mapDiscoveryResult(recipe: DiscoveryResult): Recipe {
  const source = ({ good_food: 'Good Food', allrecipes: 'Allrecipes' } as Record<string, string>)[recipe.source] ?? recipe.source
  const preview = completeNutrition(recipe.publisher_nutrition) ? mapNutrition(recipe.publisher_nutrition) : undefined
  return {
    id: recipe.url,
    title: recipe.title,
    source,
    sourceUrl: recipe.url,
    imageUrl: recipe.image_url,
    publisherNutrition: preview,
    nutritionSourceName: source,
    state: preview ? 'source_estimate' : 'no_nutrition',
    mealKinds: [],
  }
}
