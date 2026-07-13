import { Calculator, Check, ChefHat, ExternalLink, Filter, Link2, Search, Sparkles, TriangleAlert } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { NutritionStrip } from '../components/Nutrition'
import { Badge, Button, Card, EmptyState, Loading, Notice, PageHeader, Segmented } from '../components/ui'
import { demoRecipes } from '../data/demo'
import type { Nutrition, Recipe } from '../types'
import { api, ApiError, isDemoMode, type BackendRecipe, type DiscoveryResult, type RecipeSourceKey } from '../api/client'

const SOURCE_OPTIONS: Array<{ value: RecipeSourceKey; label: string }> = [
  { value: 'good_food', label: 'Good Food' },
  { value: 'great_british_chefs', label: 'Great British Chefs' },
  { value: 'allrecipes', label: 'Allrecipes' },
]
const ALL_SOURCES = SOURCE_OPTIONS.map(option => option.value)

export function RecipesPage() {
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState<'all' | 'saved'>('all')
  const [calculating, setCalculating] = useState<string[]>([])
  const [calculated, setCalculated] = useState<Record<string, Nutrition>>({})
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

  const calculate = async (recipe: Recipe) => {
    setCalculating(items => [...items, recipe.id]); setError('')
    try {
      if (isDemoMode) {
        await new Promise(resolve => window.setTimeout(resolve, 900))
        setCalculated(items => ({ ...items, [recipe.id]: { calories: 512, protein: 18, carbs: 76, fat: 16, basis: 'per_serving' } }))
      } else if (recipe.source === 'Saved recipe') {
        const result = await api.calculateRecipe(recipe.id)
        const values = result.per_serving_values
        setCalculated(items => ({ ...items, [recipe.id]: { calories: values.energy_kcal, protein: values.protein_g, carbs: values.carbohydrate_g, fat: values.fat_g, basis: 'per_serving' } }))
      } else {
        const job = await api.startImport(recipe.sourceUrl)
        setImportJobs(items => ({ ...items, [recipe.id]: job.id }))
      }
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The recipe could not be prepared for calculation.')
    } finally {
      setCalculating(items => items.filter(item => item !== recipe.id))
    }
  }

  return <div className="page"><PageHeader eyebrow="Recipe catalogue" title="Find something delicious" description="Search your collection and trusted recipe websites in one place." actions={<><Link className="button button--secondary" to="/recipes/new"><ChefHat size={17}/>Custom recipe</Link><Link className="button button--secondary" to="/recipes/import"><Link2 size={17}/>Import from URL</Link></>} />
    <div className="recipe-search"><Search size={22}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search recipes, ingredients or cuisine…" aria-label="Search recipes"/><button className={filtersOpen?'active':undefined} aria-label="Recipe filters" aria-expanded={filtersOpen} onClick={()=>setFiltersOpen(open=>!open)}><Filter size={19}/><span>Filters{selectedSources.length < ALL_SOURCES.length ? ` (${selectedSources.length})` : ''}</span></button></div>
    {filtersOpen && <Card className="recipe-filter-panel"><div><strong>Recipe websites</strong><span>Choose which supported websites to search.</span></div><div className="filter-options">{SOURCE_OPTIONS.map(option=><label className="check-label" key={option.value}><input type="checkbox" checked={selectedSources.includes(option.value)} onChange={()=>toggleSource(option.value)}/>{option.label}</label>)}</div><Button variant="ghost" onClick={()=>setSelectedSources(ALL_SOURCES)}>Select all</Button></Card>}
    <div className="search-controls"><Segmented value={scope} onChange={setScope} label="Recipe source" options={[{value:'all',label:'Everywhere'},{value:'saved',label:'My recipes'}]}/><div className="source-pills"><span>Searching:</span>{SOURCE_OPTIONS.filter(option=>selectedSources.includes(option.value)).map(option=><Badge key={option.value}>{option.label}</Badge>)}{selectedSources.length===0&&<Badge tone="warning">No websites selected</Badge>}</div></div>
    {remoteSearch.isFetching && <div className="search-status"><Loading label="Searching recipe websites…"/><span>Saved recipes are already shown below</span></div>}
    {error && <Notice tone="warning" title="Recipe needs attention">{error}</Notice>}
    {results.length
      ? <div className="recipe-grid">{results.map(recipe => <RecipeCard key={recipe.id} recipe={recipe} calculating={calculating.includes(recipe.id)} calculated={calculated[recipe.id]} importJob={importJobs[recipe.id]} onCalculate={() => calculate(recipe)}/>)}</div>
      : <EmptyState icon={<ChefHat size={40}/>} title="No recipes found" description="Try a broader search, or import a recipe by URL." action={<Link className="button button--primary" to="/recipes/import">Import recipe</Link>}/>
    }
  </div>
}

function RecipeCard({ recipe, calculating, calculated, importJob, onCalculate }: { recipe: Recipe; calculating: boolean; calculated?: Nutrition; importJob?: string; onCalculate: () => void }) {
  const calculatedNutrition = calculated ?? recipe.nutrition
  return <Card className="recipe-card">
    <div className="recipe-image">{recipe.imageUrl ? <img src={recipe.imageUrl} alt="" loading="lazy"/> : <ChefHat/>}<div className="recipe-source">{recipe.source}</div>{recipe.state === 'ready' && <span className="saved-mark" aria-label="Saved recipe"><Check size={16}/></span>}</div>
    <div className="recipe-content"><div className="recipe-title"><h2>{recipe.title}</h2>{recipe.sourceUrl && <a href={recipe.sourceUrl} target="_blank" rel="noreferrer" aria-label={`Open ${recipe.title} source`}><ExternalLink size={17}/></a>}</div><p className="recipe-meta">{recipe.yield ? `Serves ${recipe.yield}` : 'Yield needs review'}{recipe.mealKinds.length ? ` · ${recipe.mealKinds.join(' · ')}` : ''}</p>
      {calculatedNutrition && <div className="nutrition-panel nutrition-panel--calculated"><div className="panel-label"><span><Sparkles size={14}/>{recipe.nutritionSource==='publisher'?'Website nutrition · per serving':'Calculated per serving'}</span><Badge tone="green">Used for planning</Badge></div><NutritionStrip nutrition={calculatedNutrition} compact/></div>}
      {!calculatedNutrition && recipe.publisherNutrition && <div className="nutrition-panel nutrition-panel--source"><div className="panel-label"><span>Source estimate · per serving</span><Badge tone="warm">Reference only</Badge></div><NutritionStrip nutrition={recipe.publisherNutrition} compact/><small>Website value · not used for planning</small></div>}
      {!calculatedNutrition && !recipe.publisherNutrition && !calculating && <div className="nutrition-missing"><Calculator size={19}/><div><strong>Nutrition not reported</strong><span>Calculate it consistently from the ingredients.</span></div></div>}
      {calculating && <div className="nutrition-loading"><Loading label="Matching ingredients…"/><div className="progress-bar"><span style={{width:'64%'}}/></div></div>}
      {recipe.state === 'needs_review' && !calculated && <div className="review-warning"><TriangleAlert size={17}/><span>{recipe.reviewCount} ingredient matches need review</span></div>}
      <div className="recipe-actions">{calculatedNutrition ? <Button variant="secondary">Open recipe</Button> : importJob ? <Link to={`/imports/${importJob}/review`} className="button button--secondary">Review ingredients</Link> : recipe.state === 'needs_review' ? <Link to={`/recipes/${recipe.id}/review`} className="button button--secondary">Review ingredients</Link> : <Button disabled={calculating} onClick={onCalculate}><Calculator size={17}/>{recipe.publisherNutrition ? 'Import & calculate' : 'Calculate nutrition'}</Button>}{recipe.source !== 'Saved recipe' && !importJob && <Button variant="ghost" disabled={calculating} onClick={onCalculate}>Save</Button>}</div>
    </div>
  </Card>
}

function mapSavedRecipe(recipe: BackendRecipe): Recipe {
  const calculated=recipe.calculated_nutrition
  const publisher=recipe.publisher_nutrition
  return {
    id: recipe.id,
    title: recipe.title,
    source: 'Saved recipe',
    sourceUrl: recipe.source_url ?? '',
    imageUrl: recipe.image_url,
    yield: recipe.yield_servings,
    nutrition: calculated ? {calories:Number(calculated.energy_kcal),protein:Number(calculated.protein_g),carbs:Number(calculated.carbohydrate_g),fat:Number(calculated.fat_g),basis:'per_serving'} : undefined,
    nutritionSource: recipe.nutrition_method==='publisher'?'publisher':calculated?'calculated':undefined,
    publisherNutrition: !calculated&&publisher?.energy_kcal!=null ? {calories:Number(publisher.energy_kcal),protein:Number(publisher.protein_g??0),carbs:Number(publisher.carbohydrate_g??0),fat:Number(publisher.fat_g??0),basis:publisher.basis?.toLowerCase().includes('100g')?'per_100g':'per_serving'} : undefined,
    state: recipe.eligibility === 'planner_ready' ? 'ready' : recipe.eligibility === 'needs_review' ? 'needs_review' : 'no_nutrition',
    reviewCount: recipe.review_count,
    mealKinds: [],
  }
}

function mapDiscoveryResult(recipe: DiscoveryResult): Recipe {
  const preview = recipe.publisher_nutrition
  return {
    id: recipe.url,
    title: recipe.title,
    source: ({ good_food: 'Good Food', great_british_chefs: 'Great British Chefs', allrecipes: 'Allrecipes' } as Record<string, string>)[recipe.source] ?? recipe.source,
    sourceUrl: recipe.url,
    imageUrl: recipe.image_url,
    publisherNutrition: preview && preview.energy_kcal != null ? {
      calories: preview.energy_kcal,
      protein: preview.protein_g ?? 0,
      carbs: preview.carbohydrate_g ?? 0,
      fat: preview.fat_g ?? 0,
      basis: preview.basis?.toLowerCase().includes('100g') ? 'per_100g' : 'per_serving',
    } : undefined,
    state: preview ? 'source_estimate' : 'no_nutrition',
    mealKinds: [],
  }
}
