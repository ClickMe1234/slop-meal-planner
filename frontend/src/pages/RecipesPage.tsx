import { Calculator, Check, ChefHat, ExternalLink, Filter, Link2, Search, Sparkles, TriangleAlert } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { NutritionStrip } from '../components/Nutrition'
import { Badge, Button, Card, EmptyState, Loading, Notice, PageHeader, Segmented } from '../components/ui'
import { demoRecipes } from '../data/demo'
import type { Nutrition, Recipe } from '../types'
import { api, ApiError, isDemoMode, type BackendRecipe, type DiscoveryResult } from '../api/client'

export function RecipesPage() {
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState<'all' | 'saved'>('all')
  const [calculating, setCalculating] = useState<string[]>([])
  const [calculated, setCalculated] = useState<Record<string, Nutrition>>({})
  const [importJobs, setImportJobs] = useState<Record<string, string>>({})
  const [error, setError] = useState('')

  const localSearch = useQuery({
    queryKey: ['recipes', query],
    queryFn: () => api.listRecipes(query),
    enabled: !isDemoMode,
  })
  const remoteSearch = useQuery({
    queryKey: ['recipe-discovery', query.trim()],
    queryFn: () => api.searchRemote(query.trim(), 'recipe-page'),
    enabled: !isDemoMode && scope === 'all' && query.trim().length >= 2,
  })

  const results = useMemo(() => {
    if (isDemoMode) return demoRecipes.filter(recipe => {
      const matches = recipe.title.toLowerCase().includes(query.toLowerCase()) || recipe.source.toLowerCase().includes(query.toLowerCase())
      return matches && (scope === 'all' || recipe.source === 'Saved recipe' || recipe.state === 'ready')
    })
    const local = (localSearch.data?.items ?? []).map(mapSavedRecipe)
    if (scope === 'saved') return local
    const localUrls = new Set(local.map(item => item.sourceUrl).filter(Boolean))
    const remote = (remoteSearch.data?.results ?? [])
      .filter(item => !localUrls.has(item.url))
      .map(mapDiscoveryResult)
    return [...local, ...remote]
  }, [query, scope, localSearch.data, remoteSearch.data])

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
    <div className="recipe-search"><Search size={22}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search recipes, ingredients or cuisine…" aria-label="Search recipes"/><button aria-label="Recipe filters"><Filter size={19}/><span>Filters</span></button></div>
    <div className="search-controls"><Segmented value={scope} onChange={setScope} label="Recipe source" options={[{value:'all',label:'Everywhere'},{value:'saved',label:'My recipes'}]}/><div className="source-pills"><span>Searching:</span><Badge>Good Food</Badge><Badge>Great British Chefs</Badge><Badge>Allrecipes</Badge></div></div>
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
      {calculatedNutrition && <div className="nutrition-panel nutrition-panel--calculated"><div className="panel-label"><span><Sparkles size={14}/>Calculated per serving</span><Badge tone="green">Used for planning</Badge></div><NutritionStrip nutrition={calculatedNutrition} compact/></div>}
      {!calculatedNutrition && recipe.publisherNutrition && <div className="nutrition-panel nutrition-panel--source"><div className="panel-label"><span>Source estimate · per serving</span><Badge tone="warm">Reference only</Badge></div><NutritionStrip nutrition={recipe.publisherNutrition} compact/><small>Website value · not used for planning</small></div>}
      {!calculatedNutrition && !recipe.publisherNutrition && !calculating && <div className="nutrition-missing"><Calculator size={19}/><div><strong>Nutrition not reported</strong><span>Calculate it consistently from the ingredients.</span></div></div>}
      {calculating && <div className="nutrition-loading"><Loading label="Matching ingredients…"/><div className="progress-bar"><span style={{width:'64%'}}/></div></div>}
      {recipe.state === 'needs_review' && !calculated && <div className="review-warning"><TriangleAlert size={17}/><span>{recipe.reviewCount} ingredient matches need review</span></div>}
      <div className="recipe-actions">{calculatedNutrition ? <Button variant="secondary">Open recipe</Button> : importJob ? <Link to={`/imports/${importJob}/review`} className="button button--secondary">Review ingredients</Link> : recipe.state === 'needs_review' ? <Link to={`/imports/${recipe.id}/review`} className="button button--secondary">Review ingredients</Link> : <Button disabled={calculating} onClick={onCalculate}><Calculator size={17}/>{recipe.publisherNutrition ? 'Import & calculate' : 'Calculate nutrition'}</Button>}{recipe.source !== 'Saved recipe' && !importJob && <Button variant="ghost" disabled={calculating} onClick={onCalculate}>Save</Button>}</div>
    </div>
  </Card>
}

function mapSavedRecipe(recipe: BackendRecipe): Recipe {
  return {
    id: recipe.id,
    title: recipe.title,
    source: 'Saved recipe',
    sourceUrl: recipe.source_url ?? '',
    imageUrl: recipe.image_url,
    state: recipe.eligibility === 'planner_ready' ? 'ready' : recipe.eligibility === 'needs_review' ? 'needs_review' : 'no_nutrition',
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
