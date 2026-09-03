import { ArrowLeft, Barcode, Check, Package, Plus, Search, Sparkles, Trash2, X } from 'lucide-react'
import { type FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BarcodeScanner } from '../components/BarcodeScanner'
import { FoodSearchSources, type FoodSearchSourceSelection } from '../components/FoodSearchSources'
import { MealTypePicker, normaliseRecipeMealTypes, type RecipeMealType } from '../components/MealTypePicker'
import { NutritionStrip } from '../components/Nutrition'
import { UsdaKeyGuidance } from '../components/UsdaKeyGuidance'
import { Badge, Button, Card, Loading, Notice, PageHeader } from '../components/ui'
import {
  api,
  ApiError,
  isDemoMode,
  normaliseFoodQuery,
  type ApiDecimal,
  type BackendCustomRecipeUpdate,
  type BackendFood,
  type BackendFoodLookup,
  type BackendRecipeDetail,
  type BackendRecipeNutritionConversionOption,
  type BackendRecipeNutritionPreview,
  type BackendRecipeNutritionPreviewIngredientResult,
  type NutritionBasisUnit,
  type NutritionConversionSource,
  type NutrientCode,
} from '../api/client'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import type { Nutrition } from '../types'

const INGREDIENT_UNITS = ['g', 'kg', 'mg', 'ml', 'l', 'tsp', 'tbsp', 'cup', 'clove', 'small', 'medium', 'large', 'item', 'slice', 'bunch', 'handful', 'can', 'tin', 'jar', 'packet', 'pack', 'bottle', 'sprig', 'stalk', 'head', 'fillet', 'piece', 'pinch', 'dash', 'splash']

const MASS_FACTORS: Record<string, number> = {
  g: 1,
  kg: 1000,
  mg: 0.001,
  oz: 28.3495,
  lb: 453.59237,
}

const INPUT_UNIT_ALIASES: Record<string, string> = {
  gram: 'g', grams: 'g',
  kilogram: 'kg', kilograms: 'kg',
  milligram: 'mg', milligrams: 'mg',
  millilitre: 'ml', millilitres: 'ml', milliliter: 'ml', milliliters: 'ml',
  litre: 'l', litres: 'l', liter: 'l', liters: 'l',
  teaspoon: 'tsp', teaspoons: 'tsp', tsps: 'tsp',
  tablespoon: 'tbsp', tablespoons: 'tbsp', tbsps: 'tbsp',
  cups: 'cup',
  cans: 'can', tins: 'tin', jars: 'jar', packets: 'packet', packs: 'pack', bottles: 'bottle',
  cloves: 'clove', slices: 'slice', pieces: 'piece',
}

let ingredientIdSequence = 0

function createIngredientId() {
  ingredientIdSequence += 1
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `draft-ingredient-${ingredientIdSequence}`
}

function canonicalInputUnit(unit: string | null | undefined) {
  const value = unit?.trim().toLowerCase().replace(/\s+/g, ' ') ?? ''
  return INPUT_UNIT_ALIASES[value] ?? value
}

function gramsFor(amount: string, unit: string) {
  const value = Number(amount)
  const factor = MASS_FACTORS[canonicalInputUnit(unit)]
  return amount && Number.isFinite(value) && factor ? String(Number((value * factor).toFixed(4))) : ''
}

function isDirectNutritionUnit(unit: string, basisUnit: NutritionBasisUnit) {
  const canonical = canonicalInputUnit(unit)
  if (basisUnit === 'g') return Boolean(MASS_FACTORS[canonical])
  return ['ml', 'l', 'tsp', 'tbsp', 'cup'].includes(canonical)
}

function displayNumber(value: ApiDecimal | null | undefined, maximumFractionDigits = 1) {
  const number = Number(value)
  return value == null || !Number.isFinite(number)
    ? '—'
    : number.toLocaleString(undefined, { maximumFractionDigits })
}

function compactNutrition(values: Partial<Record<NutrientCode, ApiDecimal | null>>) {
  return `Kc: ${displayNumber(values.energy_kcal)}, C: ${displayNumber(values.carbohydrate_g)}, F: ${displayNumber(values.fat_g)}, P: ${displayNumber(values.protein_g)}`
}

function servingConstraintError(minimumServings: string, servingIncrement: string) {
  if (Boolean(minimumServings) !== Boolean(servingIncrement)) {
    return 'Set both the minimum planned servings and serving increment, or leave both blank.'
  }
  if (minimumServings && servingIncrement) {
    const values = [Number(minimumServings), Number(servingIncrement)]
    if (values.some((value) => !Number.isFinite(value) || value < 0.25 || value > 2 || !Number.isInteger(value * 4))) {
      return 'Use quarter-serving values from 0.25 to 2 for both planner limits.'
    }
  }
  return ''
}

function IngredientUnitOptions() {
  return <datalist id="custom-ingredient-unit-options">{INGREDIENT_UNITS.map((unit) => <option value={unit} key={unit} />)}</datalist>
}

function ServingConstraintFields({
  minimumServings,
  servingIncrement,
  onMinimumServingsChange,
  onServingIncrementChange,
}: {
  minimumServings: string
  servingIncrement: string
  onMinimumServingsChange: (value: string) => void
  onServingIncrementChange: (value: string) => void
}) {
  const error = servingConstraintError(minimumServings, servingIncrement)
  return <fieldset className="serving-constraints" aria-describedby="custom-serving-constraints-help">
    <legend>Planner serving limits <span>Optional</span></legend>
    <div className="form-grid">
      <label>Minimum planned servings<input type="number" min="0.25" max="2" step="0.25" value={minimumServings} onChange={(event) => onMinimumServingsChange(event.target.value)} /></label>
      <label>Serving increment<input type="number" min="0.25" max="2" step="0.25" value={servingIncrement} onChange={(event) => onServingIncrementChange(event.target.value)} /></label>
    </div>
    <small id="custom-serving-constraints-help">Set both to limit planner portions. Use quarter-serving values from 0.25 to 2.</small>
    {error && <small className="field-error" role="alert">{error}</small>}
  </fieldset>
}

interface EditableCustomIngredient {
  client_id: string
  lineage_id?: string
  original_text: string
  amount: string
  unit: string
  quantity_grams: string
  food_record_id?: string
  matched_name?: string
  included: boolean
  optional: boolean
  shopping_excluded: boolean
  nutrition_input_unit?: string
  nutrition_basis_amount_per_unit?: string
  nutrition_basis_unit?: NutritionBasisUnit
  nutrition_conversion_source?: NutritionConversionSource
}

function emptyIngredient(): EditableCustomIngredient {
  return {
    client_id: createIngredientId(),
    original_text: '',
    amount: '',
    unit: 'g',
    quantity_grams: '',
    included: true,
    optional: false,
    shopping_excluded: false,
  }
}

function editableIngredient(ingredient: BackendRecipeDetail['ingredients'][number]): EditableCustomIngredient {
  return {
    client_id: createIngredientId(),
    lineage_id: ingredient.lineage_id,
    original_text: ingredient.original_text,
    amount: ingredient.quantity == null ? '' : String(ingredient.quantity),
    unit: ingredient.unit ?? (ingredient.quantity_grams != null ? 'g' : ''),
    quantity_grams: ingredient.quantity_grams == null ? '' : String(ingredient.quantity_grams),
    food_record_id: ingredient.food_record_id,
    matched_name: ingredient.food_phrase,
    included: ingredient.included,
    optional: ingredient.optional,
    shopping_excluded: ingredient.shopping_excluded ?? false,
    nutrition_input_unit: ingredient.nutrition_input_unit ?? undefined,
    nutrition_basis_amount_per_unit: ingredient.nutrition_basis_amount_per_unit == null ? undefined : String(ingredient.nutrition_basis_amount_per_unit),
    nutrition_basis_unit: ingredient.nutrition_basis_unit ?? undefined,
    nutrition_conversion_source: ingredient.nutrition_conversion_source ?? undefined,
  }
}

function previewForIngredient(preview: BackendRecipeNutritionPreview | undefined, clientId: string) {
  return preview?.ingredients.find((item) => item.client_id === clientId)
}

function issueForIngredient(preview: BackendRecipeNutritionPreview | undefined, clientId: string) {
  const resultIssues = previewForIngredient(preview, clientId)?.issues ?? []
  const topLevelIssues = preview?.issues.filter((issue) => issue.client_id === clientId) ?? []
  return [
    ...topLevelIssues,
    ...resultIssues.filter((issue) => !topLevelIssues.some((topLevel) => topLevel.code === issue.code && topLevel.message === issue.message)),
  ]
}

function statusLabel(result: BackendRecipeNutritionPreviewIngredientResult | undefined, row: EditableCustomIngredient) {
  if (!row.original_text.trim()) return 'Add an ingredient name'
  if (!result) return row.food_record_id ? 'Checking nutrition…' : 'Nutrition not matched'
  switch (result.status) {
    case 'resolved': return 'Nutrition resolved'
    case 'missing_match': return 'Find a nutrition record'
    case 'missing_conversion': return 'Confirm what this unit represents'
    case 'incompatible_units': return 'Confirm a compatible equivalent'
    case 'incomplete_food_nutrients':
    case 'incomplete_nutrients': return 'Food label is incomplete'
    default: return result.status.replaceAll('_', ' ')
  }
}

function issueTone(result: BackendRecipeNutritionPreviewIngredientResult | undefined, row: EditableCustomIngredient) {
  return result?.status === 'resolved' ? 'green' : row.food_record_id ? 'warning' : 'neutral'
}

function conversionSourceFor(option: BackendRecipeNutritionConversionOption | undefined): NutritionConversionSource {
  if (option?.kind === 'remembered') {
    return option.source === 'package' || option.source === 'serving' ? option.source : 'manual'
  }
  return option?.kind === 'package' || option?.kind === 'serving' ? option.kind : 'manual'
}

interface LookupFoodPresentation {
  foodRecordId?: string
  name: string
  brand?: string
  barcode?: string
  basisAmount: ApiDecimal
  basisUnit: NutritionBasisUnit
  nutrients: Partial<Record<NutrientCode, ApiDecimal | null>>
  packageAmount?: ApiDecimal
  packageUnit?: NutritionBasisUnit
  packageDescription?: string
  servingAmount?: ApiDecimal
  servingUnit?: NutritionBasisUnit
  servingDescription?: string
  warnings: string[]
  provider: string
}

function presentationFromFood(food: BackendFood): LookupFoodPresentation {
  return {
    foodRecordId: food.id,
    name: food.name,
    brand: food.brand,
    barcode: food.barcode,
    basisAmount: food.basis_amount,
    basisUnit: food.basis_unit === 'ml' ? 'ml' : 'g',
    nutrients: Object.fromEntries(food.nutrients.map((nutrient) => [nutrient.code, nutrient.amount ?? null])),
    packageAmount: food.package_amount,
    packageUnit: food.package_unit,
    packageDescription: food.package_description,
    servingAmount: food.serving_amount,
    servingUnit: food.serving_unit,
    servingDescription: food.serving_description,
    warnings: [],
    provider: food.provider,
  }
}

function presentationFromLookup(food: BackendFoodLookup, foodRecordId?: string): LookupFoodPresentation {
  return {
    foodRecordId,
    name: food.name,
    brand: food.brand,
    barcode: food.barcode,
    basisAmount: food.basis_amount,
    basisUnit: food.basis_unit,
    nutrients: food.nutrients,
    packageAmount: food.package_amount,
    packageUnit: food.package_unit,
    packageDescription: food.package_description,
    servingAmount: food.serving_amount,
    servingUnit: food.serving_unit,
    servingDescription: food.serving_description,
    warnings: food.warnings,
    provider: food.provider,
  }
}

function resolvedFoodName(food: Pick<LookupFoodPresentation, 'name' | 'brand'>): string {
  const name = food.name.trim()
  const brand = food.brand?.split(',')[0]?.trim()
  if (!brand || name.toLocaleLowerCase().includes(brand.toLocaleLowerCase())) return name
  return `${brand} ${name}`
}

function fallbackConversionOptions(food: LookupFoodPresentation, row: EditableCustomIngredient): BackendRecipeNutritionConversionOption[] {
  const inputUnit = canonicalInputUnit(row.unit) || row.unit
  const options: BackendRecipeNutritionConversionOption[] = []
  if (food.packageAmount != null && food.packageUnit) {
    options.push({
      kind: 'package', input_unit: inputUnit, basis_amount_per_unit: food.packageAmount, basis_unit: food.packageUnit,
      description: food.packageDescription || `Package size: ${displayNumber(food.packageAmount)} ${food.packageUnit}`,
      requires_confirmation: true,
    })
  }
  if (food.servingAmount != null && food.servingUnit) {
    options.push({
      kind: 'serving', input_unit: inputUnit, basis_amount_per_unit: food.servingAmount, basis_unit: food.servingUnit,
      description: food.servingDescription || `Label serving: ${displayNumber(food.servingAmount)} ${food.servingUnit}`,
      requires_confirmation: true,
    })
  }
  return options
}

function FoodResult({ food, onSelect, busy }: { food: LookupFoodPresentation; onSelect: () => void; busy: boolean }) {
  return <button className="ingredient-match-result ingredient-match-result--packaged" type="button" disabled={busy} onClick={onSelect}>
    <span className="ingredient-match-result-icon"><Package size={17} aria-hidden="true" /></span>
    <span>
      <strong>{food.name}</strong>
      <small>{[food.brand, food.barcode, `label: per ${displayNumber(food.basisAmount)} ${food.basisUnit}`].filter(Boolean).join(' · ')}</small>
      <small className="ingredient-match-result-nutrition">{compactNutrition(food.nutrients)}</small>
      {(food.packageDescription || food.servingDescription) && <small>{[food.packageDescription, food.servingDescription].filter(Boolean).join(' · ')}</small>}
      {food.warnings.map((warning) => <small className="field-help--warning" key={warning}>{warning}</small>)}
    </span>
    <span className="ingredient-match-result-action">Use</span>
  </button>
}

function NutritionLookupDialog({
  row,
  previewIngredient,
  onClose,
  onSelectFood,
  onConfirmConversion,
}: {
  row: EditableCustomIngredient
  previewIngredient?: BackendRecipeNutritionPreviewIngredientResult
  onClose: () => void
  onSelectFood: (selection: { foodRecordId: string; name: string }) => void
  onConfirmConversion: (conversion: Pick<EditableCustomIngredient, 'nutrition_input_unit' | 'nutrition_basis_amount_per_unit' | 'nutrition_basis_unit' | 'nutrition_conversion_source'>) => void
}) {
  const searchInput = useRef<HTMLInputElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const [search, setSearch] = useState(row.original_text)
  const [submittedSearch, setSubmittedSearch] = useState('')
  const [searchSources, setSearchSources] = useState<FoodSearchSourceSelection>({ general: true, packaged: true })
  const [packagedResults, setPackagedResults] = useState<BackendFoodLookup[]>([])
  const [packagedTerm, setPackagedTerm] = useState('')
  const [barcodeOpen, setBarcodeOpen] = useState(false)
  const [barcode, setBarcode] = useState('')
  const [barcodeResult, setBarcodeResult] = useState<BackendFoodLookup | null>(null)
  const [selection, setSelection] = useState<LookupFoodPresentation | null>(null)
  const [selectingKey, setSelectingKey] = useState('')
  const [error, setError] = useState('')
  const [selectedOption, setSelectedOption] = useState<BackendRecipeNutritionConversionOption | undefined>()
  const [conversionAmount, setConversionAmount] = useState('')
  const [conversionUnit, setConversionUnit] = useState<NutritionBasisUnit>('g')
  const normalisedSearch = normaliseFoodQuery(search)
  const resultsAreCurrent = submittedSearch === normalisedSearch && submittedSearch.length >= 2
  const generalSearch = useQuery({
    queryKey: ['food-search', 'custom-recipe-editor', submittedSearch],
    queryFn: () => api.searchFoods(submittedSearch),
    enabled: !isDemoMode && searchSources.general && resultsAreCurrent,
    retry: false,
  })
  const packagedSearch = useMutation({
    mutationFn: (term: string) => api.searchPackagedFoods(term),
    onMutate: (term) => {
      setPackagedTerm(term)
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
    onSuccess: setBarcodeResult,
    onError: (reason) => setError(reason instanceof ApiError ? reason.message : 'That barcode could not be found.'),
  })

  useEffect(() => {
    const timer = window.setTimeout(() => searchInput.current?.focus(), 0)
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      if (event.key !== 'Tab') return
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )
      if (!focusable?.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement
      if (event.shiftKey && (active === first || !dialogRef.current?.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !dialogRef.current?.contains(active))) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [onClose])

  const runSearch = () => {
    if (isDemoMode || normalisedSearch.length < 2) return
    setSubmittedSearch(normalisedSearch)
    setError('')
    if (searchSources.packaged) packagedSearch.mutate(normalisedSearch)
    else {
      setPackagedTerm('')
      setPackagedResults([])
    }
  }

  const runBarcode = (code = barcode) => {
    const cleaned = code.replace(/\D/g, '')
    setBarcode(cleaned)
    if (cleaned && !isDemoMode) barcodeSearch.mutate(cleaned)
  }

  const choosePresentation = (food: LookupFoodPresentation) => {
    if (!food.foodRecordId) return
    onSelectFood({ foodRecordId: food.foodRecordId, name: resolvedFoodName(food) })
    if (isDirectNutritionUnit(row.unit, food.basisUnit)) {
      onClose()
      return
    }
    setSelection(food)
    // A preview can still describe the previous food while its refetch is in
    // flight. Never carry that product's remembered/package mapping forward.
    const existing = previewIngredient?.food_record_id === food.foodRecordId
      ? previewIngredient.conversion_options
      : []
    const first = existing[0] ?? fallbackConversionOptions(food, row)[0]
    if (first) {
      setSelectedOption(first)
      setConversionAmount(first.basis_amount_per_unit == null ? '' : String(first.basis_amount_per_unit))
      setConversionUnit(first.basis_unit ?? food.basisUnit)
    } else {
      setConversionAmount('')
      setConversionUnit(food.basisUnit)
    }
  }

  const chooseLookup = async (lookup: BackendFoodLookup) => {
    if (!lookup.barcode) {
      setError('This product is missing a barcode, so it cannot yet be saved to your household food library.')
      return
    }
    setSelectingKey(lookup.provider_record_id)
    setError('')
    try {
      const presentation = presentationFromLookup(lookup)
      let saved
      try {
        saved = await api.createSavedFood({
          source_type: 'open_food_facts',
          barcode: lookup.barcode,
          display_name: resolvedFoodName(presentation),
        })
      } catch (reason) {
        if (!(reason instanceof ApiError && reason.code === 'INGREDIENT_ALREADY_SAVED')) throw reason
        const library = await api.listSavedFoods('')
        saved = library.items.find((item) => item.barcode === lookup.barcode)
      }
      if (!saved) throw new Error('The saved ingredient could not be found.')
      choosePresentation({ ...presentation, foodRecordId: saved.food_record_id })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The product could not be attached to this ingredient.')
    } finally {
      setSelectingKey('')
    }
  }

  const options = useMemo(() => {
    const fromPreview = selection && previewIngredient?.food_record_id === selection.foodRecordId
      ? (previewIngredient?.conversion_options ?? [])
      : []
    const fallback = selection ? fallbackConversionOptions(selection, row) : []
    const optionsByKey = new Map<string, BackendRecipeNutritionConversionOption>()
    for (const option of [...fromPreview, ...fallback]) {
      const key = `${option.kind}:${option.input_unit}:${option.basis_amount_per_unit ?? ''}:${option.basis_unit ?? ''}`
      if (!optionsByKey.has(key)) optionsByKey.set(key, option)
    }
    return [...optionsByKey.values()]
  }, [previewIngredient, row, selection])

  const applyOption = (option: BackendRecipeNutritionConversionOption) => {
    setSelectedOption(option)
    setConversionAmount(option.basis_amount_per_unit == null ? '' : String(option.basis_amount_per_unit))
    setConversionUnit(option.basis_unit ?? selection?.basisUnit ?? 'g')
  }

  const confirmConversion = () => {
    const amount = Number(conversionAmount)
    if (!Number.isFinite(amount) || amount <= 0) {
      setError('Enter the mass or volume represented by one recipe unit.')
      return
    }
    onConfirmConversion({
      nutrition_input_unit: canonicalInputUnit(row.unit),
      nutrition_basis_amount_per_unit: String(amount),
      nutrition_basis_unit: conversionUnit,
      nutrition_conversion_source: conversionSourceFor(selectedOption),
    })
    onClose()
  }

  const busy = Boolean(selectingKey) || packagedSearch.isPending || generalSearch.isFetching || barcodeSearch.isPending
  const title = selection ? `Confirm ${row.unit || 'recipe unit'} equivalent` : `Find nutrition for ${row.original_text || 'ingredient'}`

  return <div className="nutrition-lookup-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <div className="nutrition-lookup-dialog-wrap" ref={dialogRef}>
    <Card className="nutrition-lookup-dialog" role="dialog" aria-modal="true" aria-labelledby="nutrition-lookup-title">
      <header>
        <div>
          <p className="eyebrow">Nutrition finder</p>
          <h2 id="nutrition-lookup-title">{title}</h2>
        </div>
        <button type="button" className="modal-close" aria-label="Close nutrition finder" onClick={onClose}><X aria-hidden="true" /></button>
      </header>
      {selection ? <>
        <div className="nutrition-selected-food">
          <Package aria-hidden="true" />
          <div><strong>{selection.name}</strong><span>{[selection.brand, `label per ${displayNumber(selection.basisAmount)} ${selection.basisUnit}`].filter(Boolean).join(' · ')}</span></div>
        </div>
        <p className="nutrition-conversion-help">The recipe still says <strong>{row.amount || '…'} {row.unit || 'unit'}</strong>. Confirm its nutrition equivalent; the shopping and pantry unit will stay unchanged.</p>
        {options.length > 0 && <div className="nutrition-conversion-options" aria-label="Suggested equivalents">
          {options.map((option) => {
            const selected = selectedOption === option
            return <button className={selected ? 'active' : ''} type="button" key={`${option.kind}-${option.description}-${option.basis_amount_per_unit ?? ''}`} aria-pressed={selected} onClick={() => applyOption(option)}>
              <span><strong>{option.kind === 'remembered' ? 'Remembered mapping' : option.kind === 'package' ? 'Package size' : option.kind === 'serving' ? 'Label serving' : 'Manual equivalent'}</strong><small>{option.description}</small></span>
              {selected && <Check aria-hidden="true" />}
            </button>
          })}
        </div>}
        <div className="nutrition-equivalence-fields">
          <label>One {row.unit || 'recipe unit'} equals<input aria-label={`Equivalent amount for one ${row.unit || 'recipe unit'}`} type="number" min="0" step="any" value={conversionAmount} onChange={(event) => { setConversionAmount(event.target.value); setSelectedOption(undefined) }} /></label>
          <label>Nutrition basis<select aria-label="Nutrition basis unit" value={conversionUnit} onChange={(event) => { setConversionUnit(event.target.value as NutritionBasisUnit); setSelectedOption(undefined) }}><option value="g">g</option><option value="ml">ml</option></select></label>
        </div>
        <p className="nutrition-equivalence-preview" aria-live="polite">{conversionAmount && Number(conversionAmount) > 0 ? `1 ${row.unit || 'unit'} = ${conversionAmount} ${conversionUnit}` : 'Choose a package or serving size, or enter a custom equivalent.'}</p>
        {error && <small className="field-error" role="alert">{error}</small>}
        <div className="button-row nutrition-lookup-actions"><Button type="button" variant="ghost" onClick={() => setSelection(null)}>Back to results</Button><Button type="button" onClick={confirmConversion}>Confirm equivalent</Button></div>
      </> : <>
        {isDemoMode && <Notice tone="info" title="Nutrition matching is unavailable in demo mode">Explore the editor here, then connect a live household to search labels, scan products, and save the recipe.</Notice>}
        <div className="ingredient-match-toolbar nutrition-lookup-search">
          <label><Search size={16} aria-hidden="true" /><input ref={searchInput} aria-label={`Search nutrition for ${row.original_text || 'ingredient'}`} value={search} onChange={(event) => { setSearch(event.target.value); setSubmittedSearch('') }} onKeyDown={(event) => event.key === 'Enter' && runSearch()} placeholder="Ingredient, product or brand" /></label>
          <Button type="button" variant="secondary" disabled={normalisedSearch.length < 2 || busy || isDemoMode} onClick={runSearch}><Search size={16} />{busy && resultsAreCurrent ? 'Searching…' : 'Search'}</Button>
          <Button type="button" variant="ghost" disabled={isDemoMode} onClick={() => setBarcodeOpen((open) => !open)}><Barcode size={16} />{barcodeOpen ? 'Hide scanner' : 'Scan barcode'}</Button>
        </div>
        <FoodSearchSources compact disabled={isDemoMode} value={searchSources} onChange={(value) => { setSearchSources(value); setSubmittedSearch('') }} />
        {barcodeOpen && <div className="ingredient-match-barcode">
          <div className="barcode-number"><input aria-label="Barcode number for recipe ingredient" inputMode="numeric" pattern="[0-9 ]*" value={barcode} onChange={(event) => setBarcode(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && runBarcode()} placeholder="Barcode number" /><Button type="button" disabled={!barcode.trim() || barcodeSearch.isPending || isDemoMode} onClick={() => runBarcode()}>{barcodeSearch.isPending ? 'Looking…' : 'Look up'}</Button></div>
          {!isDemoMode && <BarcodeScanner compact onCode={runBarcode} />}
        </div>}
        {error && <small className="field-error" role="alert">{error}</small>}
        {resultsAreCurrent && generalSearch.isError ? <small className="field-error" role="alert">{generalSearch.error instanceof ApiError ? generalSearch.error.message : 'General food search could not be reached.'}</small> : resultsAreCurrent && generalSearch.data?.remote_error_code === 'USDA_API_KEY_REQUIRED' ? <UsdaKeyGuidance compact /> : resultsAreCurrent && generalSearch.data?.remote_error ? <small className="field-error">{generalSearch.data.remote_error}</small> : null}
        {busy && <Loading label="Searching nutrition records…" />}
        <div className="ingredient-match-results nutrition-lookup-results">
          {barcodeResult && <FoodResult food={presentationFromLookup(barcodeResult)} busy={Boolean(selectingKey)} onSelect={() => void chooseLookup(barcodeResult)} />}
          {resultsAreCurrent && packagedTerm === submittedSearch && packagedResults.map((food) => <FoodResult key={food.provider_record_id} food={presentationFromLookup(food)} busy={Boolean(selectingKey)} onSelect={() => void chooseLookup(food)} />)}
          {resultsAreCurrent && generalSearch.data?.items.map((food) => <FoodResult key={food.id} food={presentationFromFood(food)} busy={Boolean(selectingKey)} onSelect={() => choosePresentation(presentationFromFood(food))} />)}
        </div>
        {resultsAreCurrent && searchSources.packaged && packagedTerm === submittedSearch && packagedSearch.isSuccess && !packagedResults.length && <small>No packaged products found. Try fewer words or scan the barcode.</small>}
        {!resultsAreCurrent && !barcodeResult && !isDemoMode && <small className="ingredient-match-guidance">Choose one or both sources, then press Enter or Search.</small>}
      </>}
    </Card>
    </div>
  </div>
}

function NutritionSummary({
  preview,
  isLoading,
  isFetching,
}: {
  preview?: BackendRecipeNutritionPreview
  isLoading: boolean
  isFetching: boolean
}) {
  const complete = Boolean(preview?.complete)
  const perServing = preview?.per_serving_values
  const nutrition: Nutrition | undefined = complete && perServing
    ? {
        calories: Number(perServing.energy_kcal),
        protein: Number(perServing.protein_g),
        carbs: Number(perServing.carbohydrate_g),
        fat: Number(perServing.fat_g),
        basis: 'per_serving',
      }
    : undefined
  const firstIssue = preview?.issues[0]?.message
  return <section className="custom-nutrition-summary" aria-live="polite">
    {isLoading ? <Loading label="Calculating ingredient nutrition…" /> : nutrition ? <div className="nutrition-panel nutrition-panel--calculated">
      <div className="panel-label"><span><Sparkles size={14} aria-hidden="true" />Nutrition calculated from ingredients · per serving</span><Badge tone="green">Ready for planning</Badge></div>
      <NutritionStrip nutrition={nutrition} compact />
    </div> : <div className="nutrition-missing"><div><strong>Nutrition needs ingredient matches</strong><span>{firstIssue ?? 'Add ingredients, match their food records, and set servings to calculate nutrition.'}</span></div></div>}
    {isFetching && !isLoading && <small className="custom-preview-stale">Updating nutrition…</small>}
  </section>
}

function ingredientPayload(row: EditableCustomIngredient): BackendCustomRecipeUpdate['ingredients'][number] {
  const quantityGrams = gramsFor(row.amount, row.unit)
  return {
    lineage_id: row.lineage_id,
    original_text: row.original_text.trim(),
    quantity: row.amount ? Number(row.amount) : null,
    unit: row.amount ? row.unit || null : null,
    quantity_grams: quantityGrams ? Number(quantityGrams) : null,
    food_phrase: row.food_record_id ? row.matched_name?.trim() || row.original_text.trim() : row.original_text.trim(),
    food_record_id: row.food_record_id,
    nutrition_input_unit: row.nutrition_input_unit,
    nutrition_basis_amount_per_unit: row.nutrition_basis_amount_per_unit ? Number(row.nutrition_basis_amount_per_unit) : null,
    nutrition_basis_unit: row.nutrition_basis_unit,
    nutrition_conversion_source: row.nutrition_conversion_source,
    included: row.included,
    optional: row.optional,
    needs_review: false,
    shopping_excluded: row.shopping_excluded,
  }
}

export function CustomRecipePage({ recipe: suppliedRecipe }: { recipe?: BackendRecipeDetail } = {}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [title, setTitle] = useState('')
  const [yieldServings, setYieldServings] = useState('4')
  const [minimumServings, setMinimumServings] = useState('')
  const [servingIncrement, setServingIncrement] = useState('')
  const [instructions, setInstructions] = useState('')
  const [mealTypes, setMealTypes] = useState<RecipeMealType[]>([])
  const [rows, setRows] = useState<EditableCustomIngredient[]>([emptyIngredient()])
  const [activeLookupId, setActiveLookupId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [savedMessage, setSavedMessage] = useState('')
  const [savedRecipe, setSavedRecipe] = useState<BackendRecipeDetail | undefined>()
  const returnFocus = useRef<HTMLElement | null>(null)
  const hydratedVersion = useRef<string | null>(null)
  const recipe = savedRecipe ?? suppliedRecipe
  const isEditing = Boolean(recipe)

  useEffect(() => {
    if (!suppliedRecipe) return
    const versionKey = `${suppliedRecipe.id}:${suppliedRecipe.version}`
    if (hydratedVersion.current === versionKey) return
    hydratedVersion.current = versionKey
    setTitle(suppliedRecipe.title)
    setYieldServings(String(suppliedRecipe.yield_servings ?? ''))
    setMinimumServings(suppliedRecipe.minimum_servings == null ? '' : String(suppliedRecipe.minimum_servings))
    setServingIncrement(suppliedRecipe.serving_increment == null ? '' : String(suppliedRecipe.serving_increment))
    setInstructions(suppliedRecipe.custom_instructions ?? '')
    setMealTypes(normaliseRecipeMealTypes(suppliedRecipe.meal_types))
    setRows(suppliedRecipe.ingredients.length ? suppliedRecipe.ingredients.map(editableIngredient) : [emptyIngredient()])
  }, [suppliedRecipe])

  const previewPayload = useMemo(() => ({
    yield_servings: yieldServings.trim() ? Number(yieldServings) : null,
    ingredients: rows.filter((row) => row.original_text.trim()).map((row) => ({
      client_id: row.client_id,
      original_text: row.original_text.trim(),
      quantity: row.amount.trim() ? Number(row.amount) : null,
      unit: row.unit.trim() || null,
      included: row.included,
      food_record_id: row.food_record_id ?? null,
      nutrition_input_unit: row.nutrition_input_unit ?? null,
      nutrition_basis_amount_per_unit: row.nutrition_basis_amount_per_unit ? Number(row.nutrition_basis_amount_per_unit) : null,
      nutrition_basis_unit: row.nutrition_basis_unit ?? null,
      nutrition_conversion_source: row.nutrition_conversion_source ?? null,
    })),
  }), [rows, yieldServings])
  const debouncedPreviewPayload = useDebouncedValue(previewPayload, 350)
  const nutritionPreview = useQuery({
    queryKey: ['custom-recipe-nutrition-preview', recipe?.id ?? 'new', debouncedPreviewPayload],
    queryFn: () => api.previewRecipeNutrition(debouncedPreviewPayload),
    enabled: !isDemoMode && debouncedPreviewPayload.ingredients.length > 0,
    retry: false,
  })
  const previewError = nutritionPreview.isError
    ? nutritionPreview.error instanceof ApiError ? nutritionPreview.error.message : 'Nutrition could not be calculated. Your draft is still safe to save.'
    : ''
  const activeRow = activeLookupId ? rows.find((row) => row.client_id === activeLookupId) : undefined
  const activePreview = activeRow ? previewForIngredient(nutritionPreview.data, activeRow.client_id) : undefined
  const resolvedRows = nutritionPreview.data?.ingredients.filter((item) => item.status === 'resolved').length ?? rows.filter((row) => row.food_record_id).length
  const validRows = rows.filter((row) => row.original_text.trim())
  // Preview requests are debounced. A previously complete result must not
  // make a just-edited row look ready to save before its new result arrives.
  const previewIsCurrent = JSON.stringify(previewPayload) === JSON.stringify(debouncedPreviewPayload)
  const complete = Boolean(previewIsCurrent && nutritionPreview.data?.complete)
  const saveLabel = saving
    ? 'Saving…'
    : isDemoMode
      ? 'Saving unavailable in demo'
      : complete
        ? 'Save recipe'
        : 'Save as draft'

  const updateRow = (clientId: string, change: Partial<EditableCustomIngredient>) => {
    setSavedMessage('')
    setRows((current) => current.map((row) => row.client_id === clientId ? { ...row, ...change } : row))
  }

  const changeUnit = (row: EditableCustomIngredient, unit: string) => {
    const from = canonicalInputUnit(row.nutrition_input_unit ?? row.unit)
    const to = canonicalInputUnit(unit)
    const conversionChanged = Boolean(row.nutrition_input_unit && from !== to)
    updateRow(row.client_id, {
      unit,
      quantity_grams: gramsFor(row.amount, unit),
      ...(conversionChanged ? {
        nutrition_input_unit: undefined,
        nutrition_basis_amount_per_unit: undefined,
        nutrition_basis_unit: undefined,
        nutrition_conversion_source: undefined,
      } : {}),
    })
  }

  const closeLookup = () => {
    setActiveLookupId(null)
    window.setTimeout(() => returnFocus.current?.focus(), 0)
  }

  const openLookup = (row: EditableCustomIngredient, element: HTMLElement) => {
    returnFocus.current = element
    setError('')
    setActiveLookupId(row.client_id)
  }

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (saving) return
    setError('')
    setSavedMessage('')
    if (isDemoMode) {
      setError('Saving custom recipes is unavailable in demo mode. Connect a live household to persist your work.')
      return
    }
    if (!title.trim()) {
      setError('Give this recipe a title before saving.')
      return
    }
    const yieldNumber = yieldServings.trim() ? Number(yieldServings) : null
    if (yieldNumber != null && (!Number.isFinite(yieldNumber) || yieldNumber <= 0)) {
      setError('Enter a recipe yield greater than zero, or leave it blank while this is a draft.')
      return
    }
    const constraintsError = servingConstraintError(minimumServings, servingIncrement)
    if (constraintsError) {
      setError(constraintsError)
      return
    }
    if (validRows.some((row) => row.included && !row.shopping_excluded && (!row.amount.trim() || !row.unit.trim()))) {
      setError('Add an amount and unit for every included shopping ingredient, or leave it off the shopping list.')
      return
    }
    setSaving(true)
    try {
      const payload: BackendCustomRecipeUpdate = {
        expected_version: recipe?.version ?? 0,
        title: title.trim(),
        yield_servings: yieldNumber,
        minimum_servings: minimumServings ? Number(minimumServings) : null,
        serving_increment: servingIncrement ? Number(servingIncrement) : null,
        custom_instructions: instructions.trim() || null,
        meal_types: mealTypes,
        ingredients: validRows.map(ingredientPayload),
      }
      const { expected_version: _expectedVersion, ...createPayload } = payload
      const saved = recipe
        ? await api.updateCustomRecipe(recipe.id, payload)
        : await api.createRecipe({ ...createPayload, source_type: 'custom' })
      setSavedRecipe(saved)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['recipes'] }),
        queryClient.invalidateQueries({ queryKey: ['recipe', saved.id] }),
        queryClient.invalidateQueries({ queryKey: ['plan'] }),
      ])
      const savedComplete = saved.nutrition_method === 'complete'
      setSavedMessage(savedComplete ? 'Recipe saved with complete nutrition. It can be used for planning when it has meal types.' : 'Draft saved. Your current plans still use their last complete recipe version.')
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The custom recipe could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  const reloadEditor = () => {
    if (!recipe) return
    hydratedVersion.current = null
    setError('')
    setSavedRecipe(undefined)
    void queryClient.invalidateQueries({ queryKey: ['recipe', recipe.id] })
  }

  return <div className="page page--wide custom-recipe-page">
    <IngredientUnitOptions />
    <Link to="/recipes" className="icon-link"><ArrowLeft aria-hidden="true" />Back to recipes</Link>
    <PageHeader
      eyebrow={isEditing ? 'Custom recipe editor' : 'Custom recipe'}
      title={isEditing ? `Edit ${recipe?.title ?? 'recipe'}` : 'Add your own recipe'}
      description="Keep the amount and unit that belong in the recipe and shopping list. Confirm a separate nutrition equivalent only when a count or package unit needs one."
      actions={recipe ? <Link to={`/recipes/${recipe.id}/method`} className="button button--secondary">Edit cooking method</Link> : undefined}
    />
    {isDemoMode && <Notice tone="info" title="Saving needs a live household">Demo mode lets you explore the custom recipe editor, but it cannot persist recipes. Connect a household before saving.</Notice>}
    <form onSubmit={save} className="review-layout custom-recipe-editor">
      <fieldset className="custom-editor-fields" disabled={saving}>
      <section className="custom-recipe-editor-main">
        <Card className="form-stack recipe-basics-card custom-recipe-basics">
          <label>Recipe title<input required value={title} onChange={(event) => { setTitle(event.target.value); setSavedMessage('') }} /></label>
          <label>Servings <span className="optional-label">Required for complete nutrition</span><input aria-label="Recipe servings" type="number" min="0.25" step="0.25" value={yieldServings} onChange={(event) => { setYieldServings(event.target.value); setSavedMessage('') }} /></label>
          <ServingConstraintFields minimumServings={minimumServings} servingIncrement={servingIncrement} onMinimumServingsChange={setMinimumServings} onServingIncrementChange={setServingIncrement} />
          <MealTypePicker value={mealTypes} onChange={(value) => { setMealTypes(value); setSavedMessage('') }} />
          {!mealTypes.length && <div className="recipe-planning-note recipe-planning-note--warning" role="status"><strong>Not used for meal planning yet</strong><span>Save the recipe now, then choose at least one meal type when you want it considered by the planner.</span></div>}
          {isEditing
            ? <Notice tone="info" title="Cooking method stays with its version"><Link to={`/recipes/${recipe?.id}/method`}>Edit the cooking method on its dedicated page.</Link></Notice>
            : <label>Your instructions <span className="optional-label">Optional</span><textarea value={instructions} onChange={(event) => { setInstructions(event.target.value); setSavedMessage('') }} rows={7} /></label>}
        </Card>
        <NutritionSummary preview={nutritionPreview.data} isLoading={nutritionPreview.isLoading} isFetching={nutritionPreview.isFetching} />
        {previewError && <Notice tone="warning" title="Could not update nutrition">{previewError}</Notice>}
        {error && <Notice tone="warning" title="Could not save recipe">{error}</Notice>}
        {savedMessage && <Notice tone="success" title="Recipe saved">{savedMessage}</Notice>}
        {error && recipe && <Button type="button" variant="secondary" onClick={reloadEditor}>Reload editor</Button>}
        <div className="custom-ingredient-list-header"><div><p className="eyebrow">Ingredients</p><h2>Recipe quantities and nutrition</h2><span>{resolvedRows} of {validRows.length} ingredients matched</span></div><Button type="button" variant="secondary" onClick={() => setRows((current) => [...current, emptyIngredient()])}><Plus aria-hidden="true" />Add ingredient</Button></div>
        <div className="ingredient-review-list custom-ingredient-review-list">
          {rows.map((row, index) => {
            const rowPreview = previewForIngredient(nutritionPreview.data, row.client_id)
            const rowIssues = issueForIngredient(nutritionPreview.data, row.client_id)
            const shoppingQuantityMissing = row.included && !row.shopping_excluded && row.original_text.trim() && (!row.amount.trim() || !row.unit.trim())
            return <Card key={row.client_id} className={`ingredient-row custom-ingredient-row ${shoppingQuantityMissing ? 'ingredient-row--amount' : ''} ${rowPreview?.status === 'resolved' ? 'custom-ingredient-row--resolved' : ''}`}>
              <div className="ingredient-copy">
                <div className="form-grid form-grid--ingredient">
                  <label className="ingredient-name-control">Ingredient as written<input aria-label={`Ingredient as written ${index + 1}`} value={row.original_text} onChange={(event) => updateRow(row.client_id, { original_text: event.target.value })} placeholder="e.g. chickpeas" /></label>
                  <label>Amount<input aria-label={`Amount for ${row.original_text || `ingredient ${index + 1}`}`} type="number" min="0" step="any" value={row.amount} onChange={(event) => updateRow(row.client_id, { amount: event.target.value, quantity_grams: gramsFor(event.target.value, row.unit) })} /></label>
                  <label>Unit<input aria-label={`Unit for ${row.original_text || `ingredient ${index + 1}`}`} list="custom-ingredient-unit-options" value={row.unit} onChange={(event) => changeUnit(row, event.target.value)} placeholder="e.g. can, tbsp, g" /></label>
                </div>
                <div className="form-inline custom-ingredient-controls">
                  <label className="check-label"><input type="checkbox" checked={row.included} onChange={(event) => updateRow(row.client_id, { included: event.target.checked })} />Include in recipe</label>
                  <label className="check-label"><input type="checkbox" checked={row.optional} onChange={(event) => updateRow(row.client_id, { optional: event.target.checked, included: event.target.checked ? false : row.included })} />Optional</label>
                  <label className="check-label"><input type="checkbox" checked={row.shopping_excluded} onChange={(event) => updateRow(row.client_id, { shopping_excluded: event.target.checked })} />Do not add to shopping list</label>
                </div>
                {shoppingQuantityMissing && <span className="ingredient-inline-warning">Enter an amount and unit, or leave this ingredient off the shopping list.</span>}
                {row.original_text.trim() && <div className="custom-ingredient-nutrition">
                  <Badge tone={issueTone(rowPreview, row)}>{rowPreview?.status === 'resolved' && <Check aria-hidden="true" />}{statusLabel(rowPreview, row)}</Badge>
                  {row.matched_name && <span className="custom-matched-name">{row.matched_name}</span>}
                  {rowPreview?.status === 'resolved' && rowPreview.contribution?.energy_kcal != null && <strong>{displayNumber(rowPreview.contribution.energy_kcal)} kcal</strong>}
                  {rowIssues.map((issue, issueIndex) => <small className="field-help field-help--warning" key={`${issue.code}-${issueIndex}`}>{issue.message}</small>)}
                </div>}
              </div>
              <div className="custom-ingredient-actions">
                <Button type="button" variant="secondary" disabled={!row.original_text.trim() || saving} onClick={(event) => openLookup(row, event.currentTarget)}><Search aria-hidden="true" />{row.food_record_id ? 'Change nutrition' : 'Find nutrition'}</Button>
                <Button type="button" variant="ghost" aria-label={`Remove ${row.original_text || `ingredient ${index + 1}`}`} disabled={rows.length === 1 || saving} onClick={() => setRows((current) => current.filter((item) => item.client_id !== row.client_id))}><Trash2 aria-hidden="true" />Remove</Button>
              </div>
            </Card>
          })}
        </div>
        <Button type="button" variant="secondary" className="custom-add-ingredient-bottom" onClick={() => setRows((current) => [...current, emptyIngredient()])}><Plus aria-hidden="true" />Add ingredient</Button>
      </section>
      </fieldset>
      <aside className="custom-recipe-aside"><Button type="submit" disabled={saving || isDemoMode}>{saveLabel}</Button>{savedRecipe && <Link to={`/recipes/${savedRecipe.id}/method`} className="button button--secondary custom-method-after-save">Edit cooking method</Link>}{savedMessage && <Button type="button" variant="ghost" onClick={() => navigate('/recipes')}>Back to recipes</Button>}</aside>
      <div className="custom-mobile-save"><Button type="submit" disabled={saving || isDemoMode}>{saveLabel}</Button></div>
    </form>
    {activeRow && <NutritionLookupDialog
      key={activeRow.client_id}
      row={activeRow}
      previewIngredient={activePreview}
      onClose={closeLookup}
      onSelectFood={({ foodRecordId, name }) => updateRow(activeRow.client_id, {
        food_record_id: foodRecordId,
        matched_name: name,
        nutrition_input_unit: undefined,
        nutrition_basis_amount_per_unit: undefined,
        nutrition_basis_unit: undefined,
        nutrition_conversion_source: undefined,
      })}
      onConfirmConversion={(conversion) => updateRow(activeRow.client_id, conversion)}
    />}
  </div>
}

/** Loads a saved recipe once to keep custom-edit routing distinct from publisher import review. */
export function CustomRecipeEditPage() {
  const { recipeId = '' } = useParams()
  const recipe = useQuery({ queryKey: ['recipe', recipeId], queryFn: () => api.getRecipe(recipeId), enabled: !isDemoMode && Boolean(recipeId), retry: false })
  if (isDemoMode) return <CustomRecipePage />
  if (recipe.isLoading) return <div className="page"><Loading label="Opening custom recipe…" /></div>
  if (recipe.isError) return <div className="page"><Notice tone="warning" title="Could not open recipe">{recipe.error instanceof ApiError ? recipe.error.message : 'The recipe could not be loaded.'}</Notice></div>
  if (!recipe.data) return null
  if (recipe.data.source_type !== 'custom') return <div className="page"><Notice tone="warning" title="This recipe is imported">Use the import review to edit publisher recipes.</Notice><Link to={`/recipes/${recipe.data.id}/review`} className="button button--secondary">Open import review</Link></div>
  return <CustomRecipePage recipe={recipe.data} />
}
