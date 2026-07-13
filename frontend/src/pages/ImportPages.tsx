import { ArrowLeft, ArrowRight, Check, ExternalLink, FileSearch, Link2, Plus, ShieldCheck, Sparkles, Trash2 } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { NutritionStrip } from '../components/Nutrition'
import { Badge, Button, Card, Notice, PageHeader, ProgressBar } from '../components/ui'
import { api, ApiError, isDemoMode, type BackendRecipeDetail } from '../api/client'

const INGREDIENT_UNITS = ['g', 'kg', 'mg', 'ml', 'l', 'tsp', 'tbsp', 'cup', 'clove', 'small', 'medium', 'large', 'item', 'slice', 'bunch', 'handful', 'can', 'tin', 'jar', 'packet', 'pack', 'bottle', 'sprig', 'stalk', 'head', 'fillet', 'piece', 'pinch', 'dash', 'splash']
const MASS_FACTORS: Record<string, number> = { g: 1, kg: 1000, mg: 0.001, oz: 28.3495, lb: 453.59237 }

function gramsFor(amount: string, unit: string): string {
  const value = Number(amount)
  const factor = MASS_FACTORS[unit.trim().toLowerCase()]
  return amount && Number.isFinite(value) && factor ? String(Number((value * factor).toFixed(4))) : ''
}

function completePublisherNutrition(recipe?: BackendRecipeDetail): boolean {
  const nutrition = recipe?.publisher_nutrition
  const basis = nutrition?.basis?.replaceAll(' ', '').toLowerCase() ?? ''
  return Boolean(
    nutrition
    && !basis.includes('100g')
    && !basis.includes('100ml')
    && ['energy_kcal', 'protein_g', 'carbohydrate_g', 'fat_g'].every(
      key => nutrition[key as keyof typeof nutrition] != null,
    )
  )
}

function IngredientUnitOptions() {
  return <datalist id="ingredient-unit-options">{INGREDIENT_UNITS.map(unit => <option value={unit} key={unit}/>)}</datalist>
}

export function RecipeImportPage() {
  const navigate = useNavigate()
  const [url, setUrl] = useState('https://www.bbcgoodfood.com/recipes/')
  const [stage, setStage] = useState<'idle' | 'working' | 'done'>('idle')
  const [jobId, setJobId] = useState('demo')
  const [recipe, setRecipe] = useState<BackendRecipeDetail | null>(null)
  const [error, setError] = useState('')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setStage('working')
    setError('')
    if (isDemoMode) {
      window.setTimeout(() => setStage('done'), 1200)
      return
    }
    try {
      const started = await api.startImport(url)
      setJobId(started.id)
      for (let attempt = 0; attempt < 90; attempt += 1) {
        const job = await api.job(started.id)
        if (job.status === 'failed') throw new ApiError(422, job.error_detail ?? 'The page could not be imported.')
        if (job.status === 'awaiting_review' || job.status === 'succeeded') {
          if (job.result?.recipe_id) setRecipe(await api.getRecipe(job.result.recipe_id))
          setStage('done')
          return
        }
        await new Promise(resolve => window.setTimeout(resolve, 1000))
      }
      throw new ApiError(504, 'The import is still queued. Check the worker and try again.')
    } catch (reason) {
      setStage('idle')
      setError(reason instanceof ApiError ? reason.message : 'The recipe could not be imported.')
    }
  }

  const nutritionSource = recipe?.publisher ?? 'the recipe website'
  return <div className="page page--narrow">
    <PageHeader eyebrow="Recipe import" title="Bring in a recipe" description="Paste a recipe page. We keep its ingredients, units, source link and the nutrition reported by the website."/>
    <Card className="import-card">
      <form onSubmit={submit} className="form-stack">
        <label>Recipe URL<div className="url-input"><Link2 size={19}/><input type="url" required value={url} onChange={event => setUrl(event.target.value)} placeholder="https://…"/></div></label>
        <Button disabled={stage === 'working'}>{stage === 'working' ? 'Reading recipe…' : 'Import recipe'}<ArrowRight size={18}/></Button>
      </form>
      {error && <Notice tone="warning" title="Import failed">{error}</Notice>}
      {stage === 'working' && <div className="import-progress"><ProgressBar value={62} label="Extracting recipe, nutrition and ingredients"/><ol><li className="done"><Check/>URL safety checked</li><li className="active"><FileSearch/>Reading structured recipe fields</li><li>Detecting ingredient amounts and units</li><li>Preparing your review</li></ol></div>}
      {stage === 'done' && <Notice tone="success" title="Recipe extracted">Nutrition source: {nutritionSource}.</Notice>}
    </Card>
    {stage === 'done' && <Card className="import-preview"><div className="preview-image"><div><Badge tone="green">{recipe?.publisher ?? 'Recipe source'}</Badge><h2>{recipe?.title ?? 'Harissa chicken with chickpeas'}</h2><p>{recipe?.yield_servings ? `Serves ${recipe.yield_servings}` : 'Yield needs review'} · {recipe?.ingredients.length ?? 5} ingredients</p></div></div><div><p>We do not store the publisher's instructions. You will always cook from the original page.</p><div className="button-row"><Button variant="secondary" onClick={() => window.open(url)}><ExternalLink size={17}/>View source</Button><Button onClick={() => navigate(`/imports/${jobId}/review`)}>Review recipe<ArrowRight size={17}/></Button></div></div></Card>}
    <div className="privacy-note"><ShieldCheck/><div><strong>Designed for your private household</strong><p>Imported recipes retain their source and attribution. Only the details needed for planning are stored.</p></div></div>
  </div>
}

interface EditableIngredientRow {
  original_text: string
  amount: string
  unit: string
  quantity_grams: string
}

const emptyIngredient = (): EditableIngredientRow => ({ original_text: '', amount: '', unit: 'g', quantity_grams: '' })

export function CustomRecipePage() {
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [yieldServings, setYieldServings] = useState('4')
  const [instructions, setInstructions] = useState('')
  const [rows, setRows] = useState<EditableIngredientRow[]>([emptyIngredient()])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const update = (index: number, change: Partial<EditableIngredientRow>) => setRows(all => all.map((row, rowIndex) => rowIndex === index ? { ...row, ...change } : row))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    const validRows = rows.filter(row => row.original_text.trim())
    if (validRows.some(row => !row.amount || !row.unit)) {
      setError('Add an amount and unit for each ingredient.')
      return
    }
    setSaving(true)
    try {
      await api.createRecipe({
        title,
        yield_servings: Number(yieldServings),
        source_type: 'custom',
        custom_instructions: instructions || null,
        ingredients: validRows.map(row => {
          const quantityGrams = row.quantity_grams || gramsFor(row.amount, row.unit)
          return {
            original_text: row.original_text,
            quantity: Number(row.amount),
            unit: row.unit,
            quantity_grams: quantityGrams ? Number(quantityGrams) : null,
            food_phrase: row.original_text,
            included: true,
            optional: false,
            needs_review: false,
          }
        }),
      })
      navigate('/recipes')
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The custom recipe could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  return <div className="page page--wide"><IngredientUnitOptions/><PageHeader eyebrow="Custom recipe" title="Add your own recipe" description="Keep each amount and unit as written—tablespoons, cloves, sizes and other count units are supported."/><form onSubmit={submit} className="review-layout"><section><Card className="form-stack"><label>Recipe title<input required value={title} onChange={event => setTitle(event.target.value)}/></label><label>Servings<input required type="number" min="0.25" step="0.25" value={yieldServings} onChange={event => setYieldServings(event.target.value)}/></label><label>Your instructions<textarea value={instructions} onChange={event => setInstructions(event.target.value)} rows={8}/></label></Card><div className="ingredient-review-list">{rows.map((row, index) => <Card className="ingredient-row" key={index}><div className="ingredient-copy"><div className="form-grid"><label>Ingredient as written<input required value={row.original_text} onChange={event => update(index, { original_text: event.target.value })}/></label><label>Amount<input type="number" min="0" step="any" value={row.amount} onChange={event => update(index, { amount: event.target.value, quantity_grams: gramsFor(event.target.value, row.unit) || row.quantity_grams })}/></label><label>Unit<input required list="ingredient-unit-options" value={row.unit} onChange={event => update(index, { unit: event.target.value, quantity_grams: gramsFor(row.amount, event.target.value) })}/></label></div></div><Button type="button" variant="ghost" onClick={() => setRows(all => all.filter((_, rowIndex) => rowIndex !== index))}><Trash2/>Remove</Button></Card>)}</div><Button type="button" variant="secondary" onClick={() => setRows(all => [...all, emptyIngredient()])}><Plus/>Add ingredient</Button></section><aside><Card className="review-summary"><h2>Custom recipe</h2><p>Ingredient matching is paused. Custom recipes are saved without estimated nutrition and are not used for automatic nutrition planning.</p>{error && <Notice tone="warning" title="Could not save">{error}</Notice>}<Button disabled={saving}>{saving ? 'Saving…' : 'Save recipe'}</Button></Card></aside></form></div>
}

export function ImportReviewPage() {
  return isDemoMode ? <DemoImportReviewPage/> : <LiveImportReviewPage/>
}

function DemoImportReviewPage() {
  const navigate = useNavigate()
  const demoIngredients = ['600g boneless skinless chicken thighs', '2 x 400g cans chickpeas, drained', '2 tbsp rose harissa', 'a splash of olive oil', '1 lemon, zest and juice']
  return <div className="page page--wide"><div className="review-top"><Link to="/recipes" className="icon-link"><ArrowLeft/>Back to recipes</Link><Badge tone="green">Nutrition from Good Food</Badge></div><PageHeader eyebrow="Import review" title="Harissa chicken with chickpeas" description="Nutrition is reported by Good Food and will be used for planning." actions={<Button variant="secondary"><ExternalLink size={17}/>Original recipe</Button>}/><div className="review-layout"><section><Card className="yield-card"><label>Confirmed servings<input type="number" min="0.25" step="0.25" defaultValue="4"/></label></Card><div className="ingredient-review-list">{demoIngredients.map(item => <Card key={item} className="ingredient-row"><div className="ingredient-copy"><small>Ingredient from recipe</small><strong>{item}</strong></div></Card>)}</div></section><aside><Card className="review-summary"><Sparkles/><h2>Nutrition from Good Food</h2><NutritionStrip nutrition={{ calories: 524, protein: 48, carbs: 39, fat: 18, basis: 'per_serving' }}/><p>Per serving · reported by Good Food · used for planning</p><Button onClick={() => navigate('/recipes')}>Save recipe</Button></Card></aside></div></div>
}

interface ImportedIngredientRow {
  original_text: string
  amount: string
  unit: string
  quantity_grams: string
  food_phrase: string
  included: boolean
  optional: boolean
}

function LiveImportReviewPage() {
  const { jobId = '', recipeId: directRecipeId = '' } = useParams()
  const navigate = useNavigate()
  const [rows, setRows] = useState<ImportedIngredientRow[]>([])
  const [yieldServings, setYieldServings] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.job(jobId),
    enabled: Boolean(jobId),
    refetchInterval: query => ['queued', 'running'].includes(query.state.data?.status ?? '') ? 1000 : false,
  })
  const recipeId = directRecipeId || job.data?.result?.recipe_id
  const recipe = useQuery({ queryKey: ['recipe', recipeId], queryFn: () => api.getRecipe(recipeId!), enabled: Boolean(recipeId) })
  const publisherIsPrimary = completePublisherNutrition(recipe.data)

  useEffect(() => {
    if (!recipe.data) return
    setYieldServings(String(recipe.data.yield_servings ?? ''))
    setRows(recipe.data.ingredients.map(item => ({
      original_text: item.original_text,
      amount: String(item.quantity ?? ''),
      unit: item.unit ?? (item.quantity_grams != null ? 'g' : ''),
      quantity_grams: String(item.quantity_grams ?? ''),
      food_phrase: item.food_phrase ?? item.original_text,
      included: item.included,
      optional: item.optional,
    })))
  }, [recipe.data])

  const update = (index: number, change: Partial<ImportedIngredientRow>) => setRows(all => all.map((row, rowIndex) => rowIndex === index ? { ...row, ...change } : row))
  const save = async () => {
    if (!recipe.data) return
    if (!yieldServings) {
      setError('Confirm how many servings the recipe makes.')
      return
    }
    setSaving(true)
    setError('')
    try {
      await api.saveRecipeReview(recipe.data.id, {
        expected_version: recipe.data.version,
        title: recipe.data.title,
        yield_servings: Number(yieldServings),
        ingredients: rows.map(row => {
          const quantityGrams = row.quantity_grams || gramsFor(row.amount, row.unit)
          return {
            original_text: row.original_text,
            quantity: row.amount ? Number(row.amount) : undefined,
            unit: row.unit || undefined,
            quantity_grams: quantityGrams ? Number(quantityGrams) : undefined,
            food_phrase: row.food_phrase,
            included: row.included,
            optional: row.optional,
            needs_review: false,
          }
        }),
      })
      navigate('/recipes')
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The reviewed recipe could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  if (job.data?.status === 'failed') return <div className="page"><Notice tone="warning" title="Import failed">{job.data.error_detail ?? 'The publisher page could not be read.'}</Notice></div>
  if (!recipe.data) return <div className="page"><PageHeader eyebrow="Import review" title="Preparing the recipe" description="The worker is safely reading the page and extracting fields already present."/><ProgressBar value={job.data?.progress ?? 10} label={job.data?.stage ?? 'Queued'}/></div>

  const publisher = recipe.data.publisher_nutrition
  const publisherName = recipe.data.publisher ?? 'the recipe website'
  const publisherPreview = publisherIsPrimary && publisher ? {
    calories: Number(publisher.energy_kcal),
    protein: Number(publisher.protein_g),
    carbs: Number(publisher.carbohydrate_g),
    fat: Number(publisher.fat_g),
    basis: 'per_serving' as const,
  } : null

  return <div className="page page--wide"><IngredientUnitOptions/><div className="review-top"><Link to="/recipes" className="icon-link"><ArrowLeft/>Back to recipes</Link><Badge tone={publisherPreview ? 'green' : undefined}>Nutrition from {publisherName}</Badge></div><PageHeader eyebrow="Import review" title={recipe.data.title} description={publisherPreview ? `Nutrition is reported by ${publisherName} and will be used for planning.` : `Nutrition from ${publisherName} is unavailable for this recipe.`} actions={recipe.data.source_url ? <Button variant="secondary" onClick={() => window.open(recipe.data.source_url)}><ExternalLink/>Original recipe</Button> : undefined}/><div className="review-layout"><section><Card className="yield-card"><label>Confirmed servings<input type="number" min="0.25" step="0.25" value={yieldServings} onChange={event => setYieldServings(event.target.value)}/></label></Card><div className="ingredient-review-list">{rows.map((row, index) => <Card key={`${row.original_text}-${index}`} className="ingredient-row"><div className="ingredient-copy"><small>Ingredient from recipe</small><strong>{row.original_text}</strong><div className="form-grid form-grid--ingredient"><label>Amount<input type="number" min="0" step="any" value={row.amount} onChange={event => update(index, { amount: event.target.value, quantity_grams: gramsFor(event.target.value, row.unit) || row.quantity_grams })}/></label><label>Unit<input list="ingredient-unit-options" value={row.unit} onChange={event => update(index, { unit: event.target.value, quantity_grams: gramsFor(row.amount, event.target.value) })} placeholder="e.g. tbsp, clove, large"/></label></div><div className="form-inline"><label className="check-label"><input type="checkbox" checked={row.included} onChange={event => update(index, { included: event.target.checked })}/>Include in recipe</label><label className="check-label"><input type="checkbox" checked={row.optional} onChange={event => update(index, { optional: event.target.checked, included: event.target.checked ? false : row.included })}/>Optional</label></div></div></Card>)}</div></section><aside><Card className="review-summary"><Sparkles/><h2>Nutrition from {publisherName}</h2>{publisherPreview ? <><NutritionStrip nutrition={publisherPreview}/><p>Per serving · reported by {publisherName} · used for planning</p></> : <div className="nutrition-missing"><div><strong>Nutrition unavailable</strong><span>{publisherName} did not report a complete per-serving nutrition set.</span></div></div>}{error && <Notice tone="warning" title="Could not save">{error}</Notice>}<Button disabled={saving} onClick={save}>{saving ? 'Saving…' : 'Save recipe'}</Button></Card></aside></div></div>
}
