import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Barcode, BookOpenCheck, ExternalLink, PackagePlus, Pencil, Plus, Search, Trash2, Wheat, X } from 'lucide-react'
import { useState } from 'react'
import { api, type ApiDecimal, ApiError, isDemoMode, normaliseFoodQuery, type BackendFood, type BackendFoodLookup, type BackendMealType, type BackendSavedFood, type NutrientCode } from '../api/client'
import { BarcodeScanner } from '../components/BarcodeScanner'
import { FoodSearchSources, type FoodSearchSourceSelection } from '../components/FoodSearchSources'
import { UsdaKeyGuidance } from '../components/UsdaKeyGuidance'
import { Badge, Button, Card, EmptyState, Loading, Notice, PageHeader } from '../components/ui'

const nutrientLabels: Record<NutrientCode, string> = {
  energy_kcal: 'kcal',
  protein_g: 'protein',
  carbohydrate_g: 'carbs',
  fat_g: 'fat',
}
const mealTypes: BackendMealType[] = ['breakfast', 'lunch', 'dinner', 'snack', 'side']

type PantryTarget = {
  foodRecordId: string
  name: string
  basisUnit: 'g' | 'ml'
  packageAmount?: ApiDecimal
  packageUnit?: 'g' | 'ml'
}

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.message : fallback
}

function foodNutrients(food: BackendFood) {
  return Object.fromEntries(food.nutrients.map((item) => [item.code, item.amount ?? null])) as Record<NutrientCode, ApiDecimal | null>
}

function NutritionFacts({ nutrients, basisAmount, basisUnit }: { nutrients: Record<NutrientCode, ApiDecimal | null>; basisAmount: ApiDecimal; basisUnit: string }) {
  return (
    <div className="ingredient-nutrition" aria-label={`Nutrition per ${basisAmount}${basisUnit}`}>
      {(Object.keys(nutrientLabels) as NutrientCode[]).map((code) => (
        <span key={code}>
          <strong>
            {nutrients[code] == null
              ? '—'
              : Number(nutrients[code]).toLocaleString(undefined, {
                  maximumFractionDigits: 1,
                })}
          </strong>
          <small>
            {nutrientLabels[code]}
            {code !== 'energy_kcal' ? ' g' : ''}
          </small>
        </span>
      ))}
    </div>
  )
}

function Dialog({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className={`card dialog-card ${wide ? 'dialog-card--wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <header>
          <h2>{title}</h2>
          <button type="button" aria-label="Close" onClick={onClose}>
            <X />
          </button>
        </header>
        {children}
      </section>
    </div>
  )
}

function PantryDialog({ target, onClose }: { target: PantryTarget; onClose: () => void }) {
  const queryClient = useQueryClient()
  const packageKnown = Boolean(target.packageAmount && target.packageUnit)
  const [packages, setPackages] = useState('1')
  const [quantity, setQuantity] = useState(String(target.packageAmount ?? 1))
  const [unit, setUnit] = useState<'g' | 'ml'>(target.packageUnit ?? target.basisUnit)
  const [expiresOn, setExpiresOn] = useState('')
  const [alwaysHave, setAlwaysHave] = useState(false)
  const [useSoon, setUseSoon] = useState(false)
  const [error, setError] = useState('')
  const mutation = useMutation({
    mutationFn: () =>
      api.addPantry({
        display_name: target.name,
        food_record_id: target.foodRecordId,
        quantity: packageKnown ? Number(packages) * Number(target.packageAmount) : Number(quantity),
        unit: packageKnown ? target.packageUnit! : unit,
        expires_on: expiresOn || undefined,
        always_have: alwaysHave,
        use_soon: useSoon,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['pantry'] })
      onClose()
    },
    onError: (reason) => setError(errorMessage(reason, 'The pantry quantity could not be added.')),
  })
  return (
    <Dialog title={`Add ${target.name} to pantry`} onClose={onClose}>
      <form
        className="form-stack"
        onSubmit={(event) => {
          event.preventDefault()
          mutation.mutate()
        }}
      >
        {packageKnown ? (
          <label>
            Packages
            <input type="number" min="0.01" step="any" required value={packages} onChange={(event) => setPackages(event.target.value)} />
            <small className="field-help">
              {packages || 0} × {target.packageAmount}
              {target.packageUnit} = {(Number(packages || 0) * Number(target.packageAmount)).toLocaleString()}
              {target.packageUnit}
            </small>
          </label>
        ) : (
          <div className="form-grid">
            <label>
              Quantity
              <input type="number" min="0.01" step="any" required value={quantity} onChange={(event) => setQuantity(event.target.value)} />
            </label>
            <label>
              Unit
              <select value={unit} onChange={(event) => setUnit(event.target.value as 'g' | 'ml')}>
                <option value="g">grams</option>
                <option value="ml">millilitres</option>
              </select>
            </label>
          </div>
        )}
        <label>
          Best before / expiry (optional)
          <input type="date" value={expiresOn} onChange={(event) => setExpiresOn(event.target.value)} />
        </label>
        <label className="check-label">
          <input type="checkbox" checked={useSoon} onChange={(event) => setUseSoon(event.target.checked)} />
          Mark as use soon
        </label>
        <label className="check-label">
          <input type="checkbox" checked={alwaysHave} onChange={(event) => setAlwaysHave(event.target.checked)} />
          Always keep this stocked
        </label>
        {error && (
          <Notice tone="warning" title="Could not add to pantry">
            {error}
          </Notice>
        )}
        <div className="button-row">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={mutation.isPending}>
            <PackagePlus size={18} />
            {mutation.isPending ? 'Adding…' : 'Add quantity'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

function ManualFoodDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [basisAmount, setBasisAmount] = useState('100')
  const [basisUnit, setBasisUnit] = useState<'g' | 'ml'>('g')
  const [values, setValues] = useState<Record<NutrientCode, string>>({
    energy_kcal: '',
    protein_g: '',
    carbohydrate_g: '',
    fat_g: '',
  })
  const [error, setError] = useState('')
  const mutation = useMutation({
    mutationFn: () =>
      api.createSavedFood({
        source_type: 'manual',
        display_name: name,
        basis_amount: Number(basisAmount),
        basis_unit: basisUnit,
        nutrients: (Object.keys(values) as NutrientCode[]).map((code) => ({
          code,
          amount: Number(values[code]),
          unit: code === 'energy_kcal' ? 'kcal' : 'g',
        })),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['saved-foods'] })
      onClose()
    },
    onError: (reason) => setError(errorMessage(reason, 'The ingredient could not be saved.')),
  })
  return (
    <Dialog title="Add nutrition manually" onClose={onClose}>
      <form
        className="form-stack"
        onSubmit={(event) => {
          event.preventDefault()
          mutation.mutate()
        }}
      >
        <label>
          Ingredient or product name
          <input required maxLength={300} value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <div className="form-grid">
          <label>
            Label basis
            <input required type="number" min="0.01" step="any" value={basisAmount} onChange={(event) => setBasisAmount(event.target.value)} />
          </label>
          <label>
            Basis unit
            <select value={basisUnit} onChange={(event) => setBasisUnit(event.target.value as 'g' | 'ml')}>
              <option value="g">grams</option>
              <option value="ml">millilitres</option>
            </select>
          </label>
        </div>
        <div className="manual-macro-grid">
          {(Object.keys(nutrientLabels) as NutrientCode[]).map((code) => (
            <label key={code}>
              {nutrientLabels[code]}
              {code !== 'energy_kcal' && ' (g)'}
              <input
                required
                type="number"
                min="0"
                step="any"
                value={values[code]}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [code]: event.target.value,
                  }))
                }
              />
            </label>
          ))}
        </div>
        {error && (
          <Notice tone="warning" title="Could not save">
            {error}
          </Notice>
        )}
        <div className="button-row">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={mutation.isPending}>{mutation.isPending ? 'Saving…' : 'Save ingredient'}</Button>
        </div>
      </form>
    </Dialog>
  )
}

function EditFoodDialog({ food, onClose }: { food: BackendSavedFood; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(food.display_name)
  const [serving, setServing] = useState(String(food.serving_amount ?? ''))
  const [servingUnit, setServingUnit] = useState<'g' | 'ml'>(food.serving_unit ?? food.basis_unit)
  const [planner, setPlanner] = useState(food.planner_enabled)
  const [tags, setTags] = useState<BackendMealType[]>(food.meal_types)
  const [correctNutrition, setCorrectNutrition] = useState(false)
  const [values, setValues] = useState<Record<NutrientCode, string>>(Object.fromEntries((Object.keys(nutrientLabels) as NutrientCode[]).map((code) => [code, String(food.nutrients[code] ?? '')])) as Record<NutrientCode, string>)
  const [error, setError] = useState('')
  const mutation = useMutation({
    mutationFn: () =>
      api.updateSavedFood(food.id, {
        expected_version: food.version,
        display_name: name,
        serving_amount: serving ? Number(serving) : undefined,
        serving_unit: serving ? servingUnit : undefined,
        planner_enabled: planner,
        meal_types: tags,
        ...(correctNutrition
          ? {
              basis_amount: Number(food.basis_amount),
              basis_unit: food.basis_unit,
              nutrients: (Object.keys(values) as NutrientCode[]).map((code) => ({
                code,
                amount: Number(values[code]),
                unit: code === 'energy_kcal' ? 'kcal' : 'g',
              })),
            }
          : {}),
      }),
    onSuccess: async () => {
      await Promise.all([queryClient.invalidateQueries({ queryKey: ['saved-foods'] }), queryClient.invalidateQueries({ queryKey: ['recipes'] })])
      onClose()
    },
    onError: (reason) => setError(errorMessage(reason, 'The ingredient could not be updated.')),
  })
  const toggleTag = (tag: BackendMealType) => setTags((current) => (current.includes(tag) ? current.filter((value) => value !== tag) : [...current, tag]))
  return (
    <Dialog title={`Edit ${food.display_name}`} onClose={onClose} wide>
      <form
        className="form-stack"
        onSubmit={(event) => {
          event.preventDefault()
          mutation.mutate()
        }}
      >
        <label>
          Display name
          <input required value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <div className="form-grid">
          <label>
            Serving amount
            <input type="number" min="0.01" step="any" value={serving} onChange={(event) => setServing(event.target.value)} />
          </label>
          <label>
            Serving unit
            <select value={servingUnit} onChange={(event) => setServingUnit(event.target.value as 'g' | 'ml')}>
              <option value="g">grams</option>
              <option value="ml">millilitres</option>
            </select>
          </label>
        </div>
        <label className="switch-row">
          <span>
            Use as a planned meal
            <small>A confirmed serving becomes a one-serving planner choice.</small>
          </span>
          <input type="checkbox" checked={planner} onChange={(event) => setPlanner(event.target.checked)} />
        </label>
        <fieldset className="meal-tag-fieldset">
          <legend>Available at</legend>
          <div className="tag-row">
            {mealTypes.map((tag) => (
              <button type="button" className={`tag ${tags.includes(tag) ? '' : 'tag--off'}`} aria-pressed={tags.includes(tag)} key={tag} onClick={() => toggleTag(tag)}>
                {tag}
              </button>
            ))}
          </div>
        </fieldset>
        <label className="check-label">
          <input type="checkbox" checked={correctNutrition} onChange={(event) => setCorrectNutrition(event.target.checked)} />
          Correct the saved nutrition values
        </label>
        {correctNutrition && (
          <>
            <p className="muted correction-note">Your correction is saved privately; the Open Food Facts source is not changed.</p>
            <div className="manual-macro-grid">
              {(Object.keys(nutrientLabels) as NutrientCode[]).map((code) => (
                <label key={code}>
                  {nutrientLabels[code]}
                  {code !== 'energy_kcal' && ' (g)'}
                  <input
                    required
                    type="number"
                    min="0"
                    step="any"
                    value={values[code]}
                    onChange={(event) =>
                      setValues((current) => ({
                        ...current,
                        [code]: event.target.value,
                      }))
                    }
                  />
                </label>
              ))}
            </div>
          </>
        )}
        {error && (
          <Notice tone="warning" title="Could not update">
            {error}
          </Notice>
        )}
        <div className="button-row">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={mutation.isPending || (planner && (!serving || !tags.length))}>{mutation.isPending ? 'Saving…' : 'Save changes'}</Button>
        </div>
      </form>
    </Dialog>
  )
}

function LookupCard({ food, onSave, onPantry, saving }: { food: BackendFoodLookup; onSave: () => void; onPantry: () => void; saving: boolean }) {
  return (
    <Card className="ingredient-result-card">
      <div className="ingredient-result-heading">
        <div>
          <Badge tone="blue">Packaged product</Badge>
          <h3>{food.name}</h3>
          <p>{[food.brand, food.barcode].filter(Boolean).join(' · ')}</p>
        </div>
        <Barcode size={24} />
      </div>
      <NutritionFacts nutrients={food.nutrients} basisAmount={food.basis_amount} basisUnit={food.basis_unit} />
      {food.warnings.map((warning) => (
        <small className="ingredient-warning" key={warning}>
          {warning}
        </small>
      ))}
      <div className="ingredient-card-actions">
        <Button variant="secondary" disabled={saving} onClick={onSave}>
          <BookOpenCheck size={17} />
          Save
        </Button>
        <Button disabled={saving} onClick={onPantry}>
          <PackagePlus size={17} />
          Add to pantry
        </Button>
        {food.source_url && (
          <a className="source-link" href={food.source_url} target="_blank" rel="noreferrer">
            Source <ExternalLink size={13} />
          </a>
        )}
      </div>
    </Card>
  )
}

export function IngredientsPage() {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [barcode, setBarcode] = useState('')
  const [lookup, setLookup] = useState<BackendFoodLookup | null>(null)
  const [packagedResults, setPackagedResults] = useState<BackendFoodLookup[]>([])
  const [packagedQuery, setPackagedQuery] = useState('')
  const [remoteError, setRemoteError] = useState('')
  const [message, setMessage] = useState('')
  const [manualOpen, setManualOpen] = useState(false)
  const [pantryTarget, setPantryTarget] = useState<PantryTarget | null>(null)
  const [editing, setEditing] = useState<BackendSavedFood | null>(null)
  const [savingKey, setSavingKey] = useState('')
  const [searchSources, setSearchSources] = useState<FoodSearchSourceSelection>({ general: true, packaged: true })
  const [submittedQuery, setSubmittedQuery] = useState('')
  const normalisedQuery = normaliseFoodQuery(query)
  const resultsAreCurrent = submittedQuery === normalisedQuery && submittedQuery.length >= 2

  const library = useQuery({
    queryKey: ['saved-foods', submittedQuery],
    queryFn: () => api.listSavedFoods(submittedQuery),
    enabled: !isDemoMode,
  })
  const local = useQuery({
    queryKey: ['food-search', submittedQuery],
    queryFn: () => api.searchFoods(submittedQuery),
    enabled: !isDemoMode && searchSources.general && submittedQuery.length >= 2,
  })
  const packagedSearch = useMutation({
    mutationFn: (searchTerm: string) => api.searchPackagedFoods(searchTerm),
    onMutate: (searchTerm) => {
      setPackagedQuery(searchTerm)
      setPackagedResults([])
      setRemoteError('')
    },
    onSuccess: (result) => {
      setPackagedResults(result.items)
      setRemoteError(result.remote_error ?? '')
    },
    onError: (reason) => setRemoteError(errorMessage(reason, 'Packaged product search could not be reached.')),
  })
  const barcodeSearch = useMutation({
    mutationFn: (code: string) => api.lookupBarcode(code),
    onSuccess: (result) => {
      setLookup(result)
      setRemoteError('')
    },
    onError: (reason) => {
      setLookup(null)
      setRemoteError(errorMessage(reason, 'That barcode could not be found.'))
    },
  })

  const runBarcode = (code = barcode) => {
    const cleaned = code.replace(/\D/g, '')
    setBarcode(cleaned)
    if (cleaned) barcodeSearch.mutate(cleaned)
  }
  const runSearch = () => {
    if (normalisedQuery.length < 2 || isDemoMode) return
    setSubmittedQuery(normalisedQuery)
    setRemoteError('')
    if (searchSources.packaged) packagedSearch.mutate(normalisedQuery)
    else { setPackagedQuery(''); setPackagedResults([]) }
  }
  const openPantry = (saved: BackendSavedFood) =>
    setPantryTarget({
      foodRecordId: saved.food_record_id,
      name: saved.display_name,
      basisUnit: saved.basis_unit,
      packageAmount: saved.package_amount,
      packageUnit: saved.package_unit,
    })
  const saveLookup = async (food: BackendFoodLookup, addToPantry: boolean) => {
    setSavingKey(food.provider_record_id)
    setMessage('')
    try {
      let saved = library.data?.items.find((item) => item.barcode === food.barcode)
      if (!saved)
        saved = await api.createSavedFood({
          source_type: 'open_food_facts',
          barcode: food.barcode,
          display_name: food.name,
        })
      await queryClient.invalidateQueries({ queryKey: ['saved-foods'] })
      setMessage(`${saved.display_name} is in your ingredient library.`)
      if (addToPantry) openPantry(saved)
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === 'INGREDIENT_ALREADY_SAVED') {
        const all = await api.listSavedFoods('')
        const saved = all.items.find((item) => item.barcode === food.barcode)
        if (saved) {
          if (addToPantry) openPantry(saved)
          setMessage(`${saved.display_name} is already in your ingredient library.`)
          return
        }
      }
      setRemoteError(errorMessage(reason, 'The product could not be saved.'))
    } finally {
      setSavingKey('')
    }
  }
  const saveLocal = async (food: BackendFood, addToPantry: boolean) => {
    setSavingKey(food.id)
    try {
      let saved = library.data?.items.find((item) => item.food_record_id === food.id)
      if (!saved)
        saved = await api.createSavedFood({
          source_type: 'food_record',
          food_record_id: food.id,
          display_name: food.name,
        })
      await queryClient.invalidateQueries({ queryKey: ['saved-foods'] })
      setMessage(`${saved.display_name} is in your ingredient library.`)
      if (addToPantry) openPantry(saved)
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === 'INGREDIENT_ALREADY_SAVED') {
        const all = await api.listSavedFoods('')
        const saved = all.items.find((item) => item.food_record_id === food.id)
        if (saved) {
          if (addToPantry) openPantry(saved)
          setMessage(`${saved.display_name} is already in your ingredient library.`)
          return
        }
      }
      setRemoteError(errorMessage(reason, 'The ingredient could not be saved.'))
    } finally {
      setSavingKey('')
    }
  }
  const archive = async (food: BackendSavedFood) => {
    if (!window.confirm(`Remove ${food.display_name} from the ingredient library?`)) return
    try {
      await api.archiveSavedFood(food.id)
      await Promise.all([queryClient.invalidateQueries({ queryKey: ['saved-foods'] }), queryClient.invalidateQueries({ queryKey: ['recipes'] })])
    } catch (reason) {
      setRemoteError(errorMessage(reason, 'The ingredient could not be removed.'))
    }
  }

  return (
    <div className="page page--wide ingredients-page">
      <PageHeader
        eyebrow="Household ingredients"
        title="Find it once. Keep it useful."
        description="Scan packaged foods, search trusted nutrition records, or enter a label yourself—then reuse the ingredient in recipes, planning and pantry stock."
        actions={
          <Button onClick={() => setManualOpen(true)}>
            <Plus size={18} />
            Add manually
          </Button>
        }
      />
      {isDemoMode && (
        <Notice tone="info" title="Ingredient tools need a live household">
          Sign in to scan products and save pantry-linked nutrition.
        </Notice>
      )}
      <Card className="ingredient-search-hero">
        <div className="ingredient-search-copy">
          <Badge tone="warm">
            <Wheat size={14} />
            Ingredient search
          </Badge>
          <h2>What are you adding?</h2>
          <p>Choose the nutrition sources you want, then search once across either or both databases.</p>
        </div>
        <FoodSearchSources value={searchSources} onChange={(value) => { setSearchSources(value); setSubmittedQuery('') }}/>
        <div className="ingredient-search-controls">
          <label className="ingredient-search-input">
            <Search />
            <input
              value={query}
              onChange={(event) => { setQuery(event.target.value); setSubmittedQuery('') }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') runSearch()
              }}
              placeholder="e.g. Greek yoghurt, chickpeas, pasta"
            />
          </label>
          <Button type="button" variant="secondary" disabled={normalisedQuery.length < 2 || packagedSearch.isPending || local.isFetching || isDemoMode} onClick={runSearch}>
            {(packagedSearch.isPending || local.isFetching) && resultsAreCurrent ? (
              <Loading label="Searching" />
            ) : (
              <>
                <Search size={18} />
                Search
              </>
            )}
          </Button>
        </div>
        <div className="barcode-panel">
          <div>
            <h3>
              <Barcode />
              Scan a barcode
            </h3>
            <p>Use the camera, a label photo, or enter the digits.</p>
          </div>
          <div className="barcode-number">
            <input inputMode="numeric" pattern="[0-9 ]*" value={barcode} onChange={(event) => setBarcode(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && runBarcode()} placeholder="Barcode number" />
            <Button disabled={!barcode.trim() || barcodeSearch.isPending || isDemoMode} onClick={() => runBarcode()}>
              {barcodeSearch.isPending ? 'Looking…' : 'Look up'}
            </Button>
          </div>
          <BarcodeScanner onCode={runBarcode} />
        </div>
      </Card>
      {message && (
        <Notice tone="success" title="Saved">
          {message}
        </Notice>
      )}
      {remoteError && (
        <Notice tone="warning" title="Search note">
          {remoteError}
        </Notice>
      )}

      {lookup && (
        <section className="ingredient-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Barcode match</p>
              <h2>We found this product</h2>
            </div>
          </div>
          <LookupCard food={lookup} saving={savingKey === lookup.provider_record_id} onSave={() => void saveLookup(lookup, false)} onPantry={() => void saveLookup(lookup, true)} />
        </section>
      )}
      {searchSources.packaged && resultsAreCurrent && packagedQuery === submittedQuery && (packagedSearch.isPending || packagedSearch.isSuccess) && (
        <section className="ingredient-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Open Food Facts</p>
              <h2>Packaged product matches</h2>
            </div>
            <small>Community-contributed label data—check it against the packet.</small>
          </div>
          {packagedSearch.isPending ? (
            <Loading label="Searching packaged foods…" />
          ) : packagedResults.length ? (
            <div className="ingredient-results-grid">
              {packagedResults.map((food) => (
                <LookupCard key={food.provider_record_id} food={food} saving={savingKey === food.provider_record_id} onSave={() => void saveLookup(food, false)} onPantry={() => void saveLookup(food, true)} />
              ))}
            </div>
          ) : (
            <EmptyState title="No packaged products found" description="Check the spelling, try fewer brand words, scan the barcode, or add the nutrition manually." />
          )}
        </section>
      )}

      {searchSources.general && resultsAreCurrent && (local.isLoading || Boolean(local.data?.items.length) || Boolean(local.data?.remote_error)) && (
        <section className="ingredient-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">General ingredients</p>
              <h2>Nutrition database matches</h2>
            </div>
          </div>
          {local.isLoading ? (
            <Loading label="Searching ingredients…" />
          ) : local.data?.items.length ? (
            <div className="ingredient-results-grid">
              {local.data.items.map((food) => (
                <Card className="ingredient-result-card" key={food.id}>
                  <div className="ingredient-result-heading">
                    <div>
                      <Badge>{food.provider.replaceAll('_', ' ')}</Badge>
                      <h3>{food.name}</h3>
                      <p>
                        Per {food.basis_amount}
                        {food.basis_unit}
                      </p>
                    </div>
                    <Wheat size={24} />
                  </div>
                  <NutritionFacts nutrients={foodNutrients(food)} basisAmount={food.basis_amount} basisUnit={food.basis_unit} />
                  <div className="ingredient-card-actions">
                    <Button variant="secondary" disabled={savingKey === food.id} onClick={() => void saveLocal(food, false)}>
                      Save
                    </Button>
                    <Button disabled={savingKey === food.id} onClick={() => void saveLocal(food, true)}>
                      <PackagePlus size={17} />
                      Add to pantry
                    </Button>
                  </div>
                </Card>
              ))}
            </div>
          ) : local.data?.remote_error_code === 'USDA_API_KEY_REQUIRED' ? (
            <UsdaKeyGuidance />
          ) : local.data?.remote_error ? (
            <Notice tone="warning" title="General food search unavailable">
              {local.data.remote_error}
            </Notice>
          ) : null}
        </section>
      )}

      <section className="ingredient-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Your library</p>
            <h2>Saved household ingredients</h2>
          </div>
          <Badge tone="green">{library.data?.total ?? 0} saved</Badge>
        </div>
        {library.isLoading ? (
          <Loading label="Opening the library…" />
        ) : library.data?.items.length ? (
          <div className="saved-food-grid">
            {library.data.items.map((food) => (
              <Card className="saved-food-card" key={food.id}>
                <div className="saved-food-title">
                  <div>
                    <Badge tone={food.planner_enabled ? 'green' : undefined}>{food.planner_enabled ? 'Planner ready' : food.provider.replaceAll('_', ' ')}</Badge>
                    <h3>{food.display_name}</h3>
                    <p>{food.brand || `Per ${food.basis_amount}${food.basis_unit}`}</p>
                  </div>
                  <div className="saved-food-menu">
                    <button aria-label={`Edit ${food.display_name}`} onClick={() => setEditing(food)}>
                      <Pencil size={17} />
                    </button>
                    <button aria-label={`Remove ${food.display_name}`} onClick={() => void archive(food)}>
                      <Trash2 size={17} />
                    </button>
                  </div>
                </div>
                <NutritionFacts nutrients={food.nutrients} basisAmount={food.basis_amount} basisUnit={food.basis_unit} />
                {food.meal_types.length > 0 && (
                  <div className="tag-row">
                    {food.meal_types.map((tag) => (
                      <span className="tag" key={tag}>
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
                <div className="ingredient-card-actions">
                  <Button onClick={() => openPantry(food)}>
                    <PackagePlus size={17} />
                    Add to pantry
                  </Button>
                  {food.source_url && (
                    <a className="source-link" href={food.source_url} target="_blank" rel="noreferrer">
                      Open source <ExternalLink size={13} />
                    </a>
                  )}
                </div>
                {food.attribution && <small className="attribution">{food.attribution}</small>}
              </Card>
            ))}
          </div>
        ) : (
          <EmptyState icon={<Wheat />} title="Your ingredient shelf is empty" description="Scan a barcode, choose a search result, or add the first nutrition label manually." action={<Button onClick={() => setManualOpen(true)}>Add an ingredient</Button>} />
        )}
      </section>

      {manualOpen && <ManualFoodDialog onClose={() => setManualOpen(false)} />}
      {pantryTarget && <PantryDialog target={pantryTarget} onClose={() => setPantryTarget(null)} />}
      {editing && <EditFoodDialog food={editing} onClose={() => setEditing(null)} />}
    </div>
  )
}
