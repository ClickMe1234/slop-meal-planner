import { ArrowLeft, ArrowRight, Barcode, Check, ExternalLink, FileSearch, Link2, Plus, Search, ShieldCheck, Sparkles, Trash2 } from 'lucide-react'
import { FormEvent, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { NutritionStrip } from '../components/Nutrition'
import { BarcodeScanner } from '../components/BarcodeScanner'
import { FoodSearchSources, type FoodSearchSourceSelection } from '../components/FoodSearchSources'
import { UsdaKeyGuidance } from '../components/UsdaKeyGuidance'
import { Badge, Button, Card, Notice, PageHeader, ProgressBar } from '../components/ui'
import { MealTypePicker, normaliseRecipeMealTypes, type RecipeMealType } from '../components/MealTypePicker'
import { api, ApiError, isDemoMode, normaliseFoodQuery, type ApiDecimal, type BackendFood, type BackendFoodLookup, type BackendRecipeDetail, type NutrientCode } from '../api/client'
import { openExternalUrl, safeExternalUrl } from '../lib/safeUrls'

const INGREDIENT_UNITS = ['g', 'kg', 'mg', 'ml', 'l', 'tsp', 'tbsp', 'cup', 'clove', 'small', 'medium', 'large', 'item', 'slice', 'bunch', 'handful', 'can', 'tin', 'jar', 'packet', 'pack', 'bottle', 'sprig', 'stalk', 'head', 'fillet', 'piece', 'pinch', 'dash', 'splash']
const MASS_FACTORS: Record<string, number> = {
  g: 1,
  kg: 1000,
  mg: 0.001,
  oz: 28.3495,
  lb: 453.59237,
}

function gramsFor(amount: string, unit: string): string {
  const value = Number(amount)
  const factor = MASS_FACTORS[unit.trim().toLowerCase()]
  return amount && Number.isFinite(value) && factor ? String(Number((value * factor).toFixed(4))) : ''
}

function completePublisherNutrition(recipe?: BackendRecipeDetail): boolean {
  const nutrition = recipe?.publisher_nutrition
  const basis = nutrition?.basis?.replaceAll(' ', '').toLowerCase() ?? ''
  return Boolean(nutrition && !basis.includes('100g') && !basis.includes('100ml') && ['energy_kcal', 'protein_g', 'carbohydrate_g', 'fat_g'].every((key) => nutrition[key as keyof typeof nutrition] != null))
}

function IngredientUnitOptions() {
  return (
    <datalist id="ingredient-unit-options">
      {INGREDIENT_UNITS.map((unit) => (
        <option value={unit} key={unit} />
      ))}
    </datalist>
  )
}

function MealTypePlanningWarning() {
  return (
    <div className="recipe-planning-note recipe-planning-note--warning" role="status">
      <strong>Not used for meal planning yet</strong>
      <span>You can save this recipe without a meal type, but the planner will ignore it until you add at least one.</span>
    </div>
  )
}

function recipeMealTypes(recipe: BackendRecipeDetail | undefined): RecipeMealType[] {
  return normaliseRecipeMealTypes(recipe?.meal_types)
}

type FoodMatchSelection = { id: string; name: string }
type CompactNutritionValues = Partial<Record<NutrientCode, ApiDecimal | null>>

export function compactNutrition(values: CompactNutritionValues): string {
  const display = (value: ApiDecimal | null | undefined) => {
    const number = Number(value)
    return value == null || !Number.isFinite(number) ? '—' : number.toLocaleString(undefined, { maximumFractionDigits: 1 })
  }
  return `Kc: ${display(values.energy_kcal)}, C: ${display(values.carbohydrate_g)}, F: ${display(values.fat_g)}, P: ${display(values.protein_g)}`
}

function foodNutrition(food: BackendFood): CompactNutritionValues {
  return Object.fromEntries(food.nutrients.map((nutrient) => [nutrient.code, nutrient.amount ?? null]))
}

function IngredientFoodMatch({ term, selectedId, selectedName, onSelect }: { term: string; selectedId?: string; selectedName?: string; onSelect: (food?: FoodMatchSelection) => void }) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState(term)
  const [packagedTerm, setPackagedTerm] = useState('')
  const [packagedResults, setPackagedResults] = useState<BackendFoodLookup[]>([])
  const [barcodeOpen, setBarcodeOpen] = useState(false)
  const [barcode, setBarcode] = useState('')
  const [barcodeResult, setBarcodeResult] = useState<BackendFoodLookup | null>(null)
  const [savingKey, setSavingKey] = useState('')
  const [error, setError] = useState('')
  const [searchSources, setSearchSources] = useState<FoodSearchSourceSelection>({ general: true, packaged: true })
  const [submittedSearch, setSubmittedSearch] = useState('')
  const normalisedSearch = normaliseFoodQuery(search)
  const resultsAreCurrent = submittedSearch === normalisedSearch && submittedSearch.length >= 2
  const results = useQuery({
    queryKey: ['food-search', 'recipe-match', submittedSearch],
    queryFn: () => api.searchFoods(submittedSearch),
    enabled: open && !isDemoMode && searchSources.general && submittedSearch.length >= 2,
  })
  const packagedSearch = useMutation({
    mutationFn: (searchTerm: string) => api.searchPackagedFoods(searchTerm),
    onMutate: (searchTerm) => {
      setPackagedTerm(searchTerm)
      setPackagedResults([])
      setError('')
    },
    onSuccess: (result) => {
      setPackagedResults(result.items)
      setError(result.remote_error ?? '')
    },
    onError: (reason) => setError(reason instanceof ApiError ? reason.message : 'Packaged-food search could not be reached.'),
  })
  const barcodeSearch = useMutation({
    mutationFn: (code: string) => api.lookupBarcode(code),
    onMutate: () => {
      setBarcodeResult(null)
      setError('')
    },
    onSuccess: (result) => setBarcodeResult(result),
    onError: (reason) => setError(reason instanceof ApiError ? reason.message : 'That barcode could not be found.'),
  })
  useEffect(() => {
    if (!open || selectedId) setSearch(term)
  }, [open, selectedId, term])

  const runBarcode = (code = barcode) => {
    const cleaned = code.replace(/\D/g, '')
    setBarcode(cleaned)
    if (cleaned && !isDemoMode) barcodeSearch.mutate(cleaned)
  }
  const runSearch = () => {
    if (normalisedSearch.length < 2 || isDemoMode) return
    setSubmittedSearch(normalisedSearch)
    setError('')
    if (searchSources.packaged) packagedSearch.mutate(normalisedSearch)
    else { setPackagedTerm(''); setPackagedResults([]) }
  }
  const selectLookup = async (food: BackendFoodLookup) => {
    if (!food.barcode) return
    setSavingKey(food.provider_record_id)
    setError('')
    try {
      let saved
      try {
        saved = await api.createSavedFood({
          source_type: 'open_food_facts',
          barcode: food.barcode,
          display_name: food.name,
        })
      } catch (reason) {
        if (!(reason instanceof ApiError && reason.code === 'INGREDIENT_ALREADY_SAVED')) throw reason
        const library = await api.listSavedFoods('')
        saved = library.items.find((item) => item.barcode === food.barcode)
      }
      if (!saved) throw new Error('The saved ingredient could not be found.')
      onSelect({ id: saved.food_record_id, name: saved.display_name })
      setOpen(false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The product could not be added to this recipe.')
    } finally {
      setSavingKey('')
    }
  }
  const renderPackagedResult = (food: BackendFoodLookup, source: 'search' | 'barcode') => (
    <button className="ingredient-match-result ingredient-match-result--packaged" type="button" key={`${source}-${food.provider_record_id}`} disabled={Boolean(savingKey)} onClick={() => void selectLookup(food)}>
      <span className="ingredient-match-result-icon">
        <Barcode size={17} />
      </span>
      <span>
        <strong>{food.name}</strong>
        <small>{[food.brand, food.barcode, `per ${food.basis_amount}${food.basis_unit}`].filter(Boolean).join(' · ')}</small>
        <small className="ingredient-match-result-nutrition">{compactNutrition(food.nutrients)}</small>
      </span>
      <span className="ingredient-match-result-action">{savingKey === food.provider_record_id ? 'Adding…' : 'Use'}</span>
    </button>
  )

  return (
    <div className="ingredient-food-match">
      <div className="ingredient-match-status">
        {selectedId ? (
          <Badge tone="green">
            <Check size={13} />
            Nutrition matched{selectedName ? `: ${selectedName}` : ''}
          </Badge>
        ) : (
          <span>Match a nutrition record to calculate calories and macros.</span>
        )}
        <Button type="button" className="ingredient-match-launch" variant={open ? 'ghost' : 'primary'} onClick={() => setOpen((value) => !value)}>
          <Search size={15} />
          {open ? 'Close finder' : selectedId ? 'Change match' : 'Find nutrition'}
        </Button>
        {selectedId && (
          <Button type="button" variant="ghost" onClick={() => onSelect(undefined)}>
            Clear
          </Button>
        )}
      </div>
      {open && (
        <div className="ingredient-match-workbench">
          <div className="ingredient-match-workbench-heading">
            <div>
              <span className="eyebrow">Nutrition finder</span>
              <strong>Search, scan, then attach</strong>
            </div>
            <small>The selected nutrition record stays linked to this recipe ingredient.</small>
          </div>
          <div className="ingredient-match-toolbar">
            <label>
              <Search size={16} />
              <input aria-label={`Search nutrition for ${term}`} value={search} onChange={(event) => { setSearch(event.target.value); setSubmittedSearch('') }} onKeyDown={(event) => { if (event.key === 'Enter') runSearch() }} placeholder="Ingredient, product or brand" />
            </label>
            <Button type="button" variant="secondary" disabled={normalisedSearch.length < 2 || packagedSearch.isPending || results.isFetching || isDemoMode} onClick={runSearch}>
              <Search size={16} />
              {(packagedSearch.isPending || results.isFetching) && resultsAreCurrent ? 'Searching…' : 'Search'}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setBarcodeOpen((value) => !value)}>
              <Barcode size={16} />
              {barcodeOpen ? 'Hide scanner' : 'Scan barcode'}
            </Button>
          </div>
          <FoodSearchSources compact value={searchSources} onChange={(value) => { setSearchSources(value); setSubmittedSearch('') }}/>
          {barcodeOpen && (
            <div className="ingredient-match-barcode">
              <div className="barcode-number">
                <input aria-label="Barcode number for recipe ingredient" inputMode="numeric" pattern="[0-9 ]*" value={barcode} onChange={(event) => setBarcode(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && runBarcode()} placeholder="Barcode number" />
                <Button type="button" disabled={!barcode.trim() || barcodeSearch.isPending || isDemoMode} onClick={() => runBarcode()}>
                  {barcodeSearch.isPending ? 'Looking…' : 'Look up'}
                </Button>
              </div>
              <BarcodeScanner compact onCode={runBarcode} />
            </div>
          )}
          {((resultsAreCurrent && results.isLoading) || barcodeSearch.isPending) && <small className="ingredient-match-progress">Searching nutrition records…</small>}
          {error && <small className="field-error">{error}</small>}
          {resultsAreCurrent && results.data?.remote_error_code === 'USDA_API_KEY_REQUIRED' ? <UsdaKeyGuidance compact /> : resultsAreCurrent && results.data?.remote_error ? <small className="field-error">{results.data.remote_error}</small> : null}
          <div className="ingredient-match-results">
            {barcodeResult && renderPackagedResult(barcodeResult, 'barcode')}
            {resultsAreCurrent && packagedTerm === submittedSearch && packagedResults.map((food) => renderPackagedResult(food, 'search'))}
            {resultsAreCurrent &&
              results.data?.items.map((food) => (
                <button
                  className="ingredient-match-result"
                  type="button"
                  key={food.id}
                  onClick={() => {
                    onSelect({ id: food.id, name: food.name })
                    setOpen(false)
                  }}
                >
                  <span className="ingredient-match-result-icon">
                    <Search size={17} />
                  </span>
                  <span>
                    <strong>{food.name}</strong>
                    <small>
                      {food.provider.replaceAll('_', ' ')} · per {food.basis_amount}
                      {food.basis_unit}
                    </small>
                    <small className="ingredient-match-result-nutrition">{compactNutrition(foodNutrition(food))}</small>
                  </span>
                  <span className="ingredient-match-result-action">Use</span>
                </button>
              ))}
          </div>
          {resultsAreCurrent && searchSources.packaged && packagedTerm === submittedSearch && packagedSearch.isSuccess && !packagedResults.length && <small>No packaged products found. Try fewer words or scan the barcode.</small>}
          {!resultsAreCurrent && !barcodeResult && <small className="ingredient-match-guidance">Choose one or both sources, then press Enter or Search.</small>}
        </div>
      )}
    </div>
  )
}

export const initialRecipeImportUrl = ''

export function RecipeImportPage() {
  const navigate = useNavigate()
  const [url, setUrl] = useState(initialRecipeImportUrl)
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
        await new Promise((resolve) => window.setTimeout(resolve, 1000))
      }
      throw new ApiError(504, 'The import is still queued. Check the worker and try again.')
    } catch (reason) {
      setStage('idle')
      setError(reason instanceof ApiError ? reason.message : 'The recipe could not be imported.')
    }
  }

  const nutritionSource = recipe?.publisher ?? 'the recipe website'
  return (
    <div className="page page--narrow">
      <PageHeader eyebrow="Recipe import" title="Bring in a recipe" description="Paste a recipe page. We keep its ingredients, units, source link and the nutrition reported by the website." />
      <Card className="import-card">
        <form onSubmit={submit} className="form-stack">
          <label>
            Recipe URL
            <div className="url-input">
              <Link2 size={19} />
              <input type="url" required value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://…" />
            </div>
          </label>
          <Button disabled={stage === 'working'}>
            {stage === 'working' ? 'Reading recipe…' : 'Import recipe'}
            <ArrowRight size={18} />
          </Button>
        </form>
        {error && (
          <Notice tone="warning" title="Import failed">
            {error}
          </Notice>
        )}
        {stage === 'working' && (
          <div className="import-progress">
            <ProgressBar value={62} label="Extracting recipe, nutrition and ingredients" />
            <ol>
              <li className="done">
                <Check />
                URL safety checked
              </li>
              <li className="active">
                <FileSearch />
                Reading structured recipe fields
              </li>
              <li>Detecting ingredient amounts and units</li>
              <li>Preparing your review</li>
            </ol>
          </div>
        )}
        {stage === 'done' && (
          <Notice tone="success" title="Recipe extracted">
            Nutrition source: {nutritionSource}.
          </Notice>
        )}
      </Card>
      {stage === 'done' && (
        <Card className="import-preview">
          <div className="preview-image">
            <div>
              <Badge tone="green">{recipe?.publisher ?? 'Recipe source'}</Badge>
              <h2>{recipe?.title ?? 'Harissa chicken with chickpeas'}</h2>
              <p>
                {recipe?.yield_servings ? `Serves ${recipe.yield_servings}` : 'Yield needs review'} · {recipe?.ingredients.length ?? 5} ingredients
              </p>
            </div>
          </div>
          <div>
            <p>The written method is fetched only when you open it. Slop then keeps the attributed source wording and builds a concise, editable cooking flow.</p>
            <div className="button-row">
              <Button variant="secondary" disabled={!safeExternalUrl(url)} onClick={() => openExternalUrl(url)}>
                <ExternalLink size={17} />
                View source
              </Button>
              <Button onClick={() => navigate(`/imports/${jobId}/review`)}>
                Review recipe
                <ArrowRight size={17} />
              </Button>
            </div>
          </div>
        </Card>
      )}
      <div className="privacy-note">
        <ShieldCheck />
        <div>
          <strong>Designed for your private household</strong>
          <p>Imported recipes retain their source and attribution. Cooking instructions are fetched on demand, never during search.</p>
        </div>
      </div>
    </div>
  )
}

interface EditableIngredientRow {
  original_text: string
  amount: string
  unit: string
  quantity_grams: string
  shopping_excluded: boolean
  food_record_id?: string
  matched_name?: string
}

const emptyIngredient = (): EditableIngredientRow => ({
  original_text: '',
  amount: '',
  unit: 'g',
  quantity_grams: '',
  shopping_excluded: false,
})

export function CustomRecipePage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [title, setTitle] = useState('')
  const [yieldServings, setYieldServings] = useState('4')
  const [instructions, setInstructions] = useState('')
  const [rows, setRows] = useState<EditableIngredientRow[]>([emptyIngredient()])
  const [mealTypes, setMealTypes] = useState<RecipeMealType[]>([])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const update = (index: number, change: Partial<EditableIngredientRow>) => setRows((all) => all.map((row, rowIndex) => (rowIndex === index ? { ...row, ...change } : row)))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    const validRows = rows.filter((row) => row.original_text.trim())
    if (validRows.some((row) => !row.shopping_excluded && (!row.amount || !row.unit))) {
      setError('Add an amount and unit for each ingredient, or leave it off the shopping list.')
      return
    }
    setSaving(true)
    try {
      if (isDemoMode) {
        await new Promise((resolve) => window.setTimeout(resolve, 300))
        navigate('/recipes')
        return
      }
      const saved = await api.createRecipe({
        title,
        yield_servings: Number(yieldServings),
        source_type: 'custom',
        custom_instructions: instructions || null,
        meal_types: mealTypes,
        ingredients: validRows.map((row) => {
          const quantityGrams = row.quantity_grams || gramsFor(row.amount, row.unit)
          return {
            original_text: row.original_text,
            quantity: row.amount ? Number(row.amount) : null,
            unit: row.amount ? row.unit : null,
            quantity_grams: quantityGrams ? Number(quantityGrams) : null,
            food_phrase: row.original_text,
            included: true,
            optional: false,
            needs_review: false,
            shopping_excluded: row.shopping_excluded,
            food_record_id: row.food_record_id,
          }
        }),
      })
      await queryClient.invalidateQueries({ queryKey: ['recipes'] })
      navigate(instructions.trim() ? `/recipes/${saved.id}/method` : '/recipes')
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The custom recipe could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page page--wide">
      <IngredientUnitOptions />
      <PageHeader eyebrow="Custom recipe" title="Add your own recipe" description="Keep each amount and unit as written—tablespoons, cloves, sizes and other count units are supported." />
      <form onSubmit={submit} className="review-layout">
        <section>
          <Card className="form-stack">
            <label>
              Recipe title
              <input required value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label>
              Servings
              <input required type="number" min="0.25" step="0.25" value={yieldServings} onChange={(event) => setYieldServings(event.target.value)} />
            </label>
            <MealTypePicker value={mealTypes} onChange={setMealTypes} />
            {!mealTypes.length && <MealTypePlanningWarning />}
            <label>
              Your instructions
              <textarea value={instructions} onChange={(event) => setInstructions(event.target.value)} rows={8} />
            </label>
          </Card>
          <div className="ingredient-review-list">
            {rows.map((row, index) => {
              const shoppingQuantityMissing = !row.shopping_excluded && (!row.amount || !row.unit)
              return (
                <Card className={`ingredient-row ${shoppingQuantityMissing && row.original_text ? 'ingredient-row--amount' : ''}`} key={index}>
                  <div className="ingredient-copy">
                    <div className="form-grid">
                      <label>
                        Ingredient as written
                        <input
                          required
                          value={row.original_text}
                          onChange={(event) =>
                            update(index, {
                              original_text: event.target.value,
                              food_record_id: undefined,
                              matched_name: undefined,
                            })
                          }
                        />
                      </label>
                      <label>
                        Amount
                        <input
                          type="number"
                          min="0"
                          step="any"
                          value={row.amount}
                          onChange={(event) =>
                            update(index, {
                              amount: event.target.value,
                              quantity_grams: gramsFor(event.target.value, row.unit) || row.quantity_grams,
                            })
                          }
                        />
                      </label>
                      <label>
                        Unit
                        <input
                          required={!row.shopping_excluded}
                          list="ingredient-unit-options"
                          value={row.unit}
                          onChange={(event) =>
                            update(index, {
                              unit: event.target.value,
                              quantity_grams: gramsFor(row.amount, event.target.value),
                            })
                          }
                        />
                      </label>
                    </div>
                    <label className="check-label shopping-exclusion-control">
                      <input
                        type="checkbox"
                        checked={row.shopping_excluded}
                        onChange={(event) =>
                          update(index, {
                            shopping_excluded: event.target.checked,
                          })
                        }
                      />
                      Do not add this to the shopping list <small>(to taste / already stocked)</small>
                    </label>
                    {shoppingQuantityMissing && row.original_text && <span className="ingredient-inline-warning">Enter an amount and unit, or leave this ingredient off the shopping list.</span>}
                    {row.original_text && (
                      <IngredientFoodMatch
                        term={row.original_text}
                        selectedId={row.food_record_id}
                        selectedName={row.matched_name}
                        onSelect={(food) =>
                          update(index, {
                            food_record_id: food?.id,
                            matched_name: food?.name,
                          })
                        }
                      />
                    )}
                  </div>
                  <Button type="button" variant="ghost" onClick={() => setRows((all) => all.filter((_, rowIndex) => rowIndex !== index))}>
                    <Trash2 />
                    Remove
                  </Button>
                </Card>
              )
            })}
          </div>
          <Button type="button" variant="secondary" onClick={() => setRows((all) => [...all, emptyIngredient()])}>
            <Plus />
            Add ingredient
          </Button>
        </section>
        <aside>
          <Card className="review-summary">
            <h2>Custom recipe</h2>
            <p>
              {rows.filter((row) => row.food_record_id).length} of {rows.filter((row) => row.original_text.trim()).length} ingredients matched. When every included ingredient has a compatible nutrition match, Slop calculates calories and macros automatically.
            </p>
            {error && (
              <Notice tone="warning" title="Could not save">
                {error}
              </Notice>
            )}
            <Button disabled={saving}>{saving ? 'Saving…' : 'Save recipe'}</Button>
          </Card>
        </aside>
      </form>
    </div>
  )
}

export function ImportReviewPage() {
  return isDemoMode ? <DemoImportReviewPage /> : <LiveImportReviewPage />
}

type ImportReviewPresentation = 'page' | 'drawer'

interface ImportReviewPresentationProps {
  presentation?: ImportReviewPresentation
  onDismiss?: () => void
  onSaved?: () => void
  demoTitle?: string
}

export function ImportReviewDrawer() {
  const navigate = useNavigate()
  const location = useLocation()
  const drawerState = location.state as { returnFocusRecipeId?: string; demoTitle?: string } | null
  const returnFocusRecipeId = drawerState?.returnFocusRecipeId
  const close = () => navigate(-1)

  useEffect(() => () => {
    window.setTimeout(() => {
      const buttons = Array.from(document.querySelectorAll<HTMLButtonElement>('[data-recipe-save-id]'))
      buttons.find((button) => button.dataset.recipeSaveId === returnFocusRecipeId)?.focus()
    }, 0)
  }, [returnFocusRecipeId])

  const props: ImportReviewPresentationProps = { presentation: 'drawer', onDismiss: close, onSaved: close, demoTitle: drawerState?.demoTitle }
  return isDemoMode ? <DemoImportReviewPage {...props} /> : <LiveImportReviewPage {...props} />
}

function ImportReviewDrawerFrame({ children, saving, onDismiss }: { children: ReactNode; saving: boolean; onDismiss: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (typeof dialog.showModal === 'function') dialog.showModal()
    else dialog.setAttribute('open', '')
    return () => {
      if (dialog.open && typeof dialog.close === 'function') dialog.close()
    }
  }, [])

  return (
    <dialog
      ref={dialogRef}
      className="import-review-drawer"
      aria-label="Review imported recipe"
      onCancel={(event) => {
        event.preventDefault()
        if (!saving) onDismiss()
      }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !saving) onDismiss()
      }}
    >
      {children}
    </dialog>
  )
}

function DemoImportReviewPage({ presentation = 'page', onDismiss, onSaved, demoTitle = 'Harissa chicken with chickpeas' }: ImportReviewPresentationProps = {}) {
  const navigate = useNavigate()
  const [mealTypes, setMealTypes] = useState<RecipeMealType[]>([])
  const [yieldServings, setYieldServings] = useState('4')
  const demoIngredients = ['600g boneless skinless chicken thighs', '2 x 400g cans chickpeas, drained', '2 tbsp rose harissa', 'a splash of olive oil', '1 lemon, zest and juice']
  const deleteRecipe = () => {
    if (!window.confirm(`Delete “${demoTitle}”? This removes it from your recipes. Existing meal plans keep their history.`)) return
    if (onSaved) onSaved()
    else navigate('/recipes')
  }
  const content = (
    <div className="page page--wide">
      <div className="review-top">
        {presentation === 'drawer' ? <button type="button" className="icon-link icon-link--button" onClick={onDismiss}><ArrowLeft />Back to results</button> : <Link to="/recipes" className="icon-link"><ArrowLeft />Back to recipes</Link>}
        <Badge tone="green">Nutrition from Good Food</Badge>
      </div>
      <PageHeader
        eyebrow="Import review"
        title={demoTitle}
        description="Nutrition is reported by Good Food and will be used for planning. The original source link is unavailable in demo mode."
      />
      <div className="review-layout">
        <section>
          <Card className="yield-card recipe-basics-card">
            <label>
              Confirmed servings
              <input aria-label="Confirmed servings" type="number" min="0.25" step="0.25" value={yieldServings} onChange={(event) => setYieldServings(event.target.value)} />
            </label>
            <div className="recipe-meal-type-review">
              <MealTypePicker value={mealTypes} onChange={setMealTypes} />
              {!mealTypes.length && <MealTypePlanningWarning />}
            </div>
          </Card>
          <div className="ingredient-review-list">
            {demoIngredients.map((item) => (
              <Card key={item} className="ingredient-row">
                <div className="ingredient-copy">
                  <small>Ingredient from recipe</small>
                  <strong>{item}</strong>
                </div>
              </Card>
            ))}
          </div>
        </section>
        <aside>
          <Card className="review-summary">
            <Sparkles />
            <h2>Nutrition from Good Food</h2>
            <NutritionStrip
              nutrition={{
                calories: 524,
                protein: 48,
                carbs: 39,
                fat: 18,
                basis: 'per_serving',
              }}
            />
            <p>Per serving · reported by Good Food · used for planning · {yieldServings} servings confirmed</p>
            <Button onClick={() => onSaved ? onSaved() : navigate('/recipes')}>Save recipe</Button>
            <div className="recipe-delete-action">
              <p>Remove this recipe from your collection.</p>
              <Button type="button" variant="danger" onClick={deleteRecipe}><Trash2 />Delete recipe</Button>
            </div>
          </Card>
        </aside>
      </div>
    </div>
  )
  return presentation === 'drawer' && onDismiss ? <ImportReviewDrawerFrame saving={false} onDismiss={onDismiss}>{content}</ImportReviewDrawerFrame> : content
}

interface ImportedIngredientRow {
  id: string
  original_text: string
  amount: string
  unit: string
  quantity_grams: string
  food_phrase: string
  preparation?: string
  food_record_id?: string
  included: boolean
  optional: boolean
  needs_review: boolean
  shopping_excluded: boolean
  shopping_measurement_overridden: boolean
  shopping_group_key?: string
}

function LiveImportReviewPage({ presentation = 'page', onDismiss, onSaved }: ImportReviewPresentationProps = {}) {
  const { jobId = '', recipeId: directRecipeId = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const [rows, setRows] = useState<ImportedIngredientRow[]>([])
  const [yieldServings, setYieldServings] = useState('')
  const [mealTypes, setMealTypes] = useState<RecipeMealType[]>([])
  const [error, setError] = useState('')
  const [deleteError, setDeleteError] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const focusedIngredient = useRef('')
  const requestedReturnTo = searchParams.get('returnTo')
  const returnTo = requestedReturnTo?.startsWith('/') && !requestedReturnTo.startsWith('//') ? requestedReturnTo : '/recipes'
  const focusIngredient = searchParams.get('focusIngredient') ?? ''
  const focusField = searchParams.get('focusField') ?? 'amount'
  const suggestedMealTypes = normaliseRecipeMealTypes((searchParams.get('suggestedMealTypes') ?? searchParams.get('suggestedMealType') ?? '').split(',').filter(Boolean))
  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.job(jobId),
    enabled: Boolean(jobId),
    refetchInterval: (query) => (['queued', 'running'].includes(query.state.data?.status ?? '') ? 1000 : false),
  })
  const recipeId = directRecipeId || job.data?.result?.recipe_id
  const recipe = useQuery({
    queryKey: ['recipe', recipeId],
    queryFn: () => api.getRecipe(recipeId!),
    enabled: Boolean(recipeId),
  })
  const publisherIsPrimary = completePublisherNutrition(recipe.data)
  const busy = saving || deleting
  const present = (content: ReactNode) => presentation === 'drawer' && onDismiss
    ? <ImportReviewDrawerFrame saving={busy} onDismiss={onDismiss}>{content}</ImportReviewDrawerFrame>
    : content

  useEffect(() => {
    if (!recipe.data) return
    setYieldServings(String(recipe.data.yield_servings ?? ''))
    const savedMealTypes = recipeMealTypes(recipe.data)
    setMealTypes(savedMealTypes.length ? savedMealTypes : suggestedMealTypes)
    setRows(
      recipe.data.ingredients.map((item) => ({
        id: item.id,
        original_text: item.original_text,
        amount: String(item.quantity ?? ''),
        unit: item.unit ?? (item.quantity_grams != null ? 'g' : ''),
        quantity_grams: String(item.quantity_grams ?? ''),
        food_phrase: item.food_phrase ?? item.original_text,
        preparation: (item as typeof item & { preparation?: string }).preparation,
        food_record_id: item.food_record_id,
        included: item.included,
        optional: item.optional,
        needs_review: item.needs_review,
        shopping_excluded: item.shopping_excluded ?? false,
        shopping_measurement_overridden: item.shopping_measurement_overridden ?? false,
        shopping_group_key: item.shopping_group_key,
      })),
    )
  }, [recipe.data, suggestedMealTypes.join(',')])

  useEffect(() => {
    if (!focusIngredient || focusedIngredient.current === focusIngredient || !rows.some((row) => row.id === focusIngredient)) return
    const timeout = window.setTimeout(() => {
      const ingredientRow = document.getElementById(`ingredient-${focusIngredient}`)
      ingredientRow?.scrollIntoView?.({ block: 'center' })
      ingredientRow?.querySelector<HTMLInputElement>(focusField === 'name' ? '[data-shopping-name-input]' : '[data-shopping-quantity-input]')?.focus()
      focusedIngredient.current = focusIngredient
    }, 0)
    return () => window.clearTimeout(timeout)
  }, [focusField, focusIngredient, rows])

  const update = (index: number, change: Partial<ImportedIngredientRow>) => setRows((all) => all.map((row, rowIndex) => (rowIndex === index ? { ...row, ...change } : row)))
  const deleteRecipe = async () => {
    if (!recipe.data || !window.confirm(`Delete “${recipe.data.title}”? This removes it from your recipes. Existing meal plans keep their history.`)) return
    setDeleting(true)
    setDeleteError('')
    try {
      await api.deleteRecipe(recipe.data.id)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['recipes'] }),
        queryClient.invalidateQueries({ queryKey: ['recipe', recipe.data.id] }),
        queryClient.invalidateQueries({ queryKey: ['plan'] }),
      ])
      if (presentation === 'drawer' && onSaved) onSaved()
      else navigate(returnTo)
    } catch (reason) {
      setDeleteError(reason instanceof ApiError ? reason.message : 'The recipe could not be deleted.')
    } finally {
      setDeleting(false)
    }
  }
  const save = async () => {
    if (!recipe.data) return
    if (!yieldServings) {
      setError('Confirm how many servings the recipe makes.')
      return
    }
    if (rows.some((row) => row.included && !row.shopping_excluded && (!row.amount || !row.unit))) {
      setError('Add an amount and unit for every included ingredient, or leave it off the shopping list.')
      return
    }
    setSaving(true)
    setError('')
    try {
      const payload: Parameters<typeof api.saveRecipeReview>[1] & {
        meal_types: RecipeMealType[]
      } = {
        expected_version: recipe.data.version,
        title: recipe.data.title,
        yield_servings: Number(yieldServings),
        meal_types: mealTypes,
        ingredients: rows.map((row) => {
          const quantityGrams = row.quantity_grams || gramsFor(row.amount, row.unit)
          return {
            original_text: row.original_text,
            quantity: row.amount ? Number(row.amount) : null,
            unit: row.amount ? row.unit || null : null,
            quantity_grams: quantityGrams ? Number(quantityGrams) : null,
            food_phrase: row.food_phrase,
            preparation: row.preparation,
            included: row.included,
            optional: row.optional,
            needs_review: false,
            food_record_id: row.food_record_id,
            shopping_excluded: row.shopping_excluded,
            shopping_measurement_overridden: row.shopping_measurement_overridden,
            shopping_group_key: row.shopping_group_key,
          }
        }),
      }
      await api.saveRecipeReview(recipe.data.id, payload)
      await Promise.all([queryClient.invalidateQueries({ queryKey: ['recipes'] }), queryClient.invalidateQueries({ queryKey: ['recipe', recipe.data.id] }), queryClient.invalidateQueries({ queryKey: ['plan'] })])
      if (presentation === 'drawer' && onSaved) onSaved()
      else navigate(returnTo)
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The reviewed recipe could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  if (job.data?.status === 'failed')
    return present(
      <div className="page">
        <Notice tone="warning" title="Import failed">
          {job.data.error_detail ?? 'The publisher page could not be read.'}
        </Notice>
      </div>
    )
  if (!recipe.data)
    return present(
      <div className="page">
        <PageHeader eyebrow="Import review" title="Preparing the recipe" description="The worker is safely reading the page and extracting fields already present." />
        <ProgressBar value={job.data?.progress ?? 10} label={job.data?.stage ?? 'Queued'} />
      </div>
    )

  const publisher = recipe.data.publisher_nutrition
  const publisherName = recipe.data.publisher ?? 'the recipe website'
  const publisherPreview =
    publisherIsPrimary && publisher
      ? {
          calories: Number(publisher.energy_kcal),
          protein: Number(publisher.protein_g),
          carbs: Number(publisher.carbohydrate_g),
          fat: Number(publisher.fat_g),
          basis: 'per_serving' as const,
        }
      : null

  return present(
    <div className="page page--wide">
      <IngredientUnitOptions />
      <div className="review-top">
        {presentation === 'drawer' ? <button type="button" className="icon-link icon-link--button" disabled={busy} onClick={onDismiss}><ArrowLeft />Back to results</button> : <Link to={returnTo} className="icon-link"><ArrowLeft />Back</Link>}
        <Badge tone={publisherPreview ? 'green' : undefined}>Nutrition from {publisherName}</Badge>
      </div>
      <PageHeader
        eyebrow="Import review"
        title={recipe.data.title}
        description={publisherPreview ? `Nutrition is reported by ${publisherName} and will be used for planning when meal types are selected.` : `Nutrition from ${publisherName} is unavailable for this recipe.`}
        actions={
          recipe.data.source_url ? (
            <Button variant="secondary" disabled={!safeExternalUrl(recipe.data.source_url)} onClick={() => openExternalUrl(recipe.data.source_url)}>
              <ExternalLink />
              Original recipe
            </Button>
          ) : undefined
        }
      />
      <div className="review-layout">
        <section>
          <Card className="yield-card recipe-basics-card">
            <label>
              Confirmed servings
              <input type="number" min="0.25" step="0.25" value={yieldServings} onChange={(event) => setYieldServings(event.target.value)} />
            </label>
            <div className="recipe-meal-type-review">
              <MealTypePicker value={mealTypes} onChange={setMealTypes} />
              {!mealTypes.length && <MealTypePlanningWarning />}
            </div>
          </Card>
          <div className="ingredient-review-list">
            {rows.map((row, index) => {
              const shoppingQuantityMissing = row.included && !row.shopping_excluded && (!row.amount || !row.unit)
              const warningId = `shopping-warning-${row.id}`
              const nameWarningId = `ingredient-name-warning-${row.id}`
              return (
                <Card id={`ingredient-${row.id}`} key={row.id} className={`ingredient-row ${row.needs_review ? 'ingredient-row--review' : ''} ${shoppingQuantityMissing ? 'ingredient-row--amount' : ''}`}>
                  <div className="ingredient-copy">
                    <small>Ingredient from recipe</small>
                    <strong>{row.original_text}</strong>
                    <div className="form-grid form-grid--ingredient">
                      <label className="ingredient-name-control">
                        Shopping-list name
                        <input
                          data-shopping-name-input
                          required
                          value={row.food_phrase}
                          aria-describedby={row.needs_review ? nameWarningId : undefined}
                          onChange={(event) =>
                            update(index, {
                              food_phrase: event.target.value,
                              needs_review: false,
                              shopping_group_key: undefined,
                            })
                          }
                        />
                        <small className="field-help">Use only the ingredient itself, for example “courgette” rather than “cubed courgette”.</small>
                      </label>
                      <label>
                        Amount
                        <input
                          data-shopping-quantity-input
                          type="number"
                          min="0"
                          step="any"
                          value={row.amount}
                          aria-describedby={shoppingQuantityMissing ? warningId : undefined}
                          onChange={(event) =>
                            update(index, {
                              amount: event.target.value,
                              quantity_grams: gramsFor(event.target.value, row.unit) || row.quantity_grams,
                              shopping_measurement_overridden: true,
                            })
                          }
                        />
                      </label>
                      <label>
                        Unit
                        <input
                          list="ingredient-unit-options"
                          value={row.unit}
                          aria-describedby={shoppingQuantityMissing ? warningId : undefined}
                          onChange={(event) =>
                            update(index, {
                              unit: event.target.value,
                              quantity_grams: gramsFor(row.amount, event.target.value),
                              shopping_measurement_overridden: true,
                            })
                          }
                          placeholder="e.g. tbsp, clove, large"
                        />
                      </label>
                    </div>
                    <div className="form-inline">
                      <label className="check-label">
                        <input type="checkbox" checked={row.included} onChange={(event) => update(index, { included: event.target.checked })} />
                        Include in recipe
                      </label>
                      <label className="check-label">
                        <input
                          type="checkbox"
                          checked={row.optional}
                          onChange={(event) =>
                            update(index, {
                              optional: event.target.checked,
                              included: event.target.checked ? false : row.included,
                            })
                          }
                        />
                        Optional
                      </label>
                    </div>
                    <label className="check-label shopping-exclusion-control">
                      <input
                        type="checkbox"
                        checked={row.shopping_excluded}
                        onChange={(event) =>
                          update(index, {
                            shopping_excluded: event.target.checked,
                          })
                        }
                      />
                      Do not add this to the shopping list <small>(to taste / already stocked)</small>
                    </label>
                    {row.needs_review && (
                      <span className="ingredient-inline-warning" id={nameWarningId}>
                        Please confirm the shopping-list name. We were not sufficiently confident in the automatic result.
                      </span>
                    )}
                    {shoppingQuantityMissing && (
                      <span className="ingredient-inline-warning" id={warningId}>
                        Enter an amount and unit, or leave this ingredient off the shopping list.
                      </span>
                    )}
                  </div>
                </Card>
              )
            })}
          </div>
        </section>
        <aside>
          <Card className="review-summary">
            <Sparkles />
            <h2>Nutrition from {publisherName}</h2>
            {publisherPreview ? (
              <>
                <NutritionStrip nutrition={publisherPreview} />
                <p>Per serving · reported by {publisherName} · used for planning</p>
              </>
            ) : (
              <div className="nutrition-missing">
                <div>
                  <strong>Nutrition unavailable</strong>
                  <span>{publisherName} did not report a complete per-serving nutrition set.</span>
                </div>
              </div>
            )}
            {error && (
              <Notice tone="warning" title="Could not save">
                {error}
              </Notice>
            )}
            <Button disabled={busy} onClick={save}>
              {saving ? 'Saving…' : 'Save recipe'}
            </Button>
            <div className="recipe-delete-action">
              <p>Remove this recipe from your collection.</p>
              {deleteError && <Notice tone="warning" title="Could not delete">{deleteError}</Notice>}
              <Button type="button" variant="danger" disabled={busy} onClick={deleteRecipe}>
                <Trash2 />
                {deleting ? 'Deleting…' : 'Delete recipe'}
              </Button>
            </div>
          </Card>
        </aside>
      </div>
    </div>
  )
}
