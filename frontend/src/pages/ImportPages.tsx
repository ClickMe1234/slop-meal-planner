import { ArrowLeft, ArrowRight, Check, CheckCircle2, CircleAlert, ExternalLink, FileSearch, Link2, Plus, ShieldCheck, Sparkles, Trash2 } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { NutritionStrip } from '../components/Nutrition'
import { Badge, Button, Card, Notice, PageHeader, ProgressBar } from '../components/ui'
import { api, ApiError, isDemoMode, type BackendRecipeDetail } from '../api/client'

const ingredients = [
  { original: '600g boneless skinless chicken thighs', parsed: '600 g · chicken thighs, skinless, raw', match: 'CoFID · Chicken, thigh, meat only, raw', status: 'matched' },
  { original: '2 x 400g cans chickpeas, drained', parsed: '800 g package · chickpeas · drained', match: 'CoFID · Chick peas, canned, drained', status: 'matched' },
  { original: '2 tbsp rose harissa', parsed: '2 tbsp · rose harissa', match: 'Choose a food record', status: 'review' },
  { original: 'a splash of olive oil', parsed: 'Amount not known · olive oil', match: 'CoFID · Olive oil', status: 'amount' },
  { original: '1 lemon, zest and juice', parsed: '1 medium · lemon', match: 'CoFID · Lemon, flesh and juice', status: 'matched' }
]

const INGREDIENT_UNITS = ['g','kg','mg','ml','l','tsp','tbsp','cup','clove','small','medium','large','item','slice','bunch','handful','can','tin','jar','packet','pack','bottle','sprig','stalk','head','fillet','piece','pinch','dash','splash']
const MASS_FACTORS: Record<string, number> = { g: 1, kg: 1000, mg: .001, oz: 28.3495, lb: 453.59237 }

function gramsFor(amount: string, unit: string): string {
  const value = Number(amount)
  const factor = MASS_FACTORS[unit.trim().toLowerCase()]
  return amount && Number.isFinite(value) && factor ? String(Number((value * factor).toFixed(4))) : ''
}

function completePublisherNutrition(recipe?: BackendRecipeDetail): boolean {
  const nutrition = recipe?.publisher_nutrition
  const basis = nutrition?.basis?.replaceAll(' ', '').toLowerCase() ?? ''
  return Boolean(nutrition && !basis.includes('100g') && !basis.includes('100ml') && ['energy_kcal','protein_g','carbohydrate_g','fat_g'].every(key => nutrition[key as keyof typeof nutrition] != null))
}

function IngredientUnitOptions() {
  return <datalist id="ingredient-unit-options">{INGREDIENT_UNITS.map(unit=><option value={unit} key={unit}/>)}</datalist>
}

export function RecipeImportPage() {
  const navigate = useNavigate()
  const [url, setUrl] = useState('https://www.bbcgoodfood.com/recipes/')
  const [stage, setStage] = useState<'idle'|'working'|'done'>('idle')
  const [jobId, setJobId] = useState('demo')
  const [recipe, setRecipe] = useState<BackendRecipeDetail | null>(null)
  const [error, setError] = useState('')
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setStage('working'); setError('')
    if (isDemoMode) { window.setTimeout(() => setStage('done'), 1200); return }
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
  return <div className="page page--narrow"><PageHeader eyebrow="Recipe import" title="Bring in a recipe" description="Paste a recipe page. We keep its ingredients, units, source link and published nutrition, with ingredient calculation as a fallback." />
    <Card className="import-card"><form onSubmit={submit} className="form-stack"><label>Recipe URL<div className="url-input"><Link2 size={19}/><input type="url" required value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…"/></div></label><Button disabled={stage === 'working'}>{stage === 'working' ? 'Reading recipe…' : 'Import recipe'}<ArrowRight size={18}/></Button></form>{error && <Notice tone="warning" title="Import failed">{error}</Notice>}{stage === 'working' && <div className="import-progress"><ProgressBar value={62} label="Extracting recipe, nutrition and ingredients"/><ol><li className="done"><Check/>URL safety checked</li><li className="active"><FileSearch/>Reading structured recipe fields</li><li>Detecting ingredient amounts and units</li><li>Preparing your review</li></ol></div>}{stage === 'done' && <Notice tone="success" title="Recipe extracted">Confirm the yield and detected units. Food matching is required only when the website has no complete nutrition.</Notice>}</Card>
    {stage === 'done' && <Card className="import-preview"><div className="preview-image"><div><Badge tone="green">{recipe?.publisher ?? 'Recipe source'}</Badge><h2>{recipe?.title ?? 'Harissa chicken with chickpeas'}</h2><p>{recipe?.yield_servings ? `Serves ${recipe.yield_servings}` : 'Yield needs review'} · {recipe?.ingredients.length ?? 5} ingredients</p></div></div><div><p>We do not store the publisher's instructions. You will always cook from the original page.</p><div className="button-row"><Button variant="secondary" onClick={() => window.open(url)}><ExternalLink size={17}/>View source</Button><Button onClick={() => navigate(`/imports/${jobId}/review`)}>Review ingredients<ArrowRight size={17}/></Button></div></div></Card>}
    <div className="privacy-note"><ShieldCheck/><div><strong>Designed for your private household</strong><p>Imported recipes retain their source and attribution. Only the details needed for planning are stored.</p></div></div>
  </div>
}

interface EditableIngredientRow {
  original_text: string
  amount: string
  unit: string
  quantity_grams: string
  food_record_id: string
  food_phrase: string
  food_basis_unit: string
  search: string
}

const emptyIngredient = (): EditableIngredientRow => ({ original_text:'', amount:'', unit:'g', quantity_grams:'', food_record_id:'', food_phrase:'', food_basis_unit:'g', search:'' })

export function CustomRecipePage(){
  const navigate=useNavigate()
  const [title,setTitle]=useState('')
  const [yieldServings,setYieldServings]=useState('4')
  const [instructions,setInstructions]=useState('')
  const [activeRow,setActiveRow]=useState(0)
  const [rows,setRows]=useState<EditableIngredientRow[]>([emptyIngredient()])
  const [error,setError]=useState('')
  const [saving,setSaving]=useState(false)
  const search=rows[activeRow]?.search ?? ''
  const foods=useQuery({queryKey:['foods',search],queryFn:()=>api.searchFoods(search),enabled:search.trim().length>=2})
  const update=(index:number,change:Partial<EditableIngredientRow>)=>setRows(all=>all.map((row,rowIndex)=>rowIndex===index?{...row,...change}:row))
  const submit=async(event:FormEvent)=>{
    event.preventDefault();setError('')
    const validRows=rows.filter(row=>row.original_text.trim())
    const unresolved=validRows.some(row=>!row.amount||!row.unit||!row.food_record_id||(row.food_basis_unit!=='ml'&&!(row.quantity_grams||gramsFor(row.amount,row.unit))))
    if(unresolved){setError('Every ingredient needs its recipe amount, unit, food match, and a gram weight when the selected food is weight-based.');return}
    setSaving(true)
    try{
      const recipe=await api.createRecipe({title,yield_servings:Number(yieldServings),source_type:'custom',custom_instructions:instructions||null,ingredients:validRows.map(row=>{const quantityGrams=row.quantity_grams||gramsFor(row.amount,row.unit);return {original_text:row.original_text,quantity:Number(row.amount),unit:row.unit,quantity_grams:quantityGrams?Number(quantityGrams):null,food_phrase:row.food_phrase||row.original_text,included:true,optional:false,needs_review:false,food_record_id:row.food_record_id}})})
      await api.calculateRecipe(recipe.id)
      navigate('/recipes')
    }catch(reason){setError(reason instanceof ApiError?reason.message:'The custom recipe could not be saved.')}finally{setSaving(false)}
  }
  return <div className="page page--wide"><IngredientUnitOptions/><PageHeader eyebrow="Custom recipe" title="Add your own recipe" description="Keep the amount and unit as written—tablespoons, cloves, sizes and other count units are supported."/><form onSubmit={submit} className="review-layout"><section><Card className="form-stack"><label>Recipe title<input required value={title} onChange={event=>setTitle(event.target.value)}/></label><label>Servings<input required type="number" min="0.25" step="0.25" value={yieldServings} onChange={event=>setYieldServings(event.target.value)}/></label><label>Your instructions<textarea value={instructions} onChange={event=>setInstructions(event.target.value)} rows={8}/></label></Card><div className="ingredient-review-list">{rows.map((row,index)=>{const options=index===activeRow?(foods.data?.items??[]):[];const needsWeight=Boolean(row.food_record_id&&row.food_basis_unit!=='ml'&&!MASS_FACTORS[row.unit.trim().toLowerCase()]);return <Card className="ingredient-row" key={index}><div className="ingredient-copy"><div className="form-grid"><label>Ingredient as written<input required value={row.original_text} onChange={event=>update(index,{original_text:event.target.value,search:row.search||event.target.value})}/></label><label>Amount<input type="number" min="0" step="any" value={row.amount} onChange={event=>update(index,{amount:event.target.value,quantity_grams:gramsFor(event.target.value,row.unit)||row.quantity_grams})}/></label><label>Unit<input required list="ingredient-unit-options" value={row.unit} onChange={event=>update(index,{unit:event.target.value,quantity_grams:gramsFor(row.amount,event.target.value)})}/></label>{needsWeight&&<label>Weight for nutrition (g)<input type="number" min="0" step="any" value={row.quantity_grams} onChange={event=>update(index,{quantity_grams:event.target.value})}/></label>}<label>Find food record<input type="search" value={row.search} onFocus={()=>setActiveRow(index)} onChange={event=>{setActiveRow(index);update(index,{search:event.target.value})}} placeholder="e.g. basmati rice"/></label><label>Food-data match<select value={row.food_record_id} onFocus={()=>setActiveRow(index)} onChange={event=>{const food=options.find(item=>item.id===event.target.value);update(index,{food_record_id:event.target.value,food_phrase:food?.name??row.food_phrase,food_basis_unit:food?.basis_unit??row.food_basis_unit})}}><option value="">Choose a food record…</option>{row.food_record_id&&!options.some(food=>food.id===row.food_record_id)&&<option value={row.food_record_id}>{row.food_phrase} · selected</option>}{options.map(food=><option key={food.id} value={food.id}>{food.name} · {food.provider}</option>)}</select></label></div>{index===activeRow&&foods.isFetching&&<ProgressBar value={50} label="Searching food records…"/>}{index===activeRow&&search.length>=2&&!foods.isFetching&&foods.data?.total===0&&<small className="field-help">No matches found. Try the plain ingredient name without quantities or preparation words.</small>}</div><Button type="button" variant="ghost" onClick={()=>setRows(all=>all.filter((_,rowIndex)=>rowIndex!==index))}><Trash2/>Remove</Button></Card>})}</div><Button type="button" variant="secondary" onClick={()=>setRows(all=>[...all,emptyIngredient()])}><Plus/>Add ingredient</Button></section><aside><Card className="review-summary"><h2>Nutrition matching</h2><p>Search each row using the plain food name. Remote FoodData Central matches are cached for future recipes.</p>{foods.data?.remote_error&&<Notice tone="warning" title="Remote search unavailable">{foods.data.remote_error}</Notice>}{error&&<Notice tone="warning" title="Could not save">{error}</Notice>}<Button disabled={saving}>{saving?'Saving…':'Save recipe'}</Button></Card></aside></form></div>
}

export function ImportReviewPage() {
  return isDemoMode ? <DemoImportReviewPage/> : <LiveImportReviewPageNew/>
}

function DemoImportReviewPage() {
  const navigate = useNavigate()
  const [oilAmount, setOilAmount] = useState('1')
  const [harissaResolved, setHarissaResolved] = useState(false)
  const [step, setStep] = useState(2)
  const issues = (harissaResolved ? 0 : 1) + (oilAmount ? 0 : 1)
  return <div className="page page--wide"><div className="review-top"><Link to="/recipes" className="icon-link"><ArrowLeft/>Back to recipes</Link><div><Badge tone={issues ? 'warning':'green'}>{issues ? `${issues} issue needs review` : 'Ready to calculate'}</Badge></div></div>
    <PageHeader eyebrow="Import review" title="Harissa chicken with chickpeas" description="Check the uncertain details. Confident matches stay out of your way." actions={<Button variant="secondary"><ExternalLink size={17}/>Original recipe</Button>} />
    <div className="review-steps">{['Recipe','Ingredients','Food matches','Calculation','Save'].map((name,index) => <button key={name} className={index < step ? 'done' : index === step ? 'active' : ''} onClick={() => setStep(index)}><span>{index < step ? <Check/> : index + 1}</span>{name}</button>)}</div>
    <div className="review-layout"><section><Card className="yield-card"><div><CheckCircle2/><div><strong>Yield confirmed</strong><p>4 servings from the source page</p></div></div><Button variant="ghost">Change</Button></Card><div className="ingredient-review-list">{ingredients.map((item,index) => <Card key={item.original} className={`ingredient-row ingredient-row--${item.status}`}><div className="ingredient-status">{item.status === 'matched' ? <CheckCircle2/> : <CircleAlert/>}</div><div className="ingredient-copy"><small>Original ingredient</small><strong>{item.original}</strong><span>{item.parsed}</span><div className="food-match"><span>{item.status === 'matched' ? 'Matched to' : item.status === 'review' ? 'Match required' : 'Amount required'}</span>{item.status === 'review' ? <select value={harissaResolved ? 'rose' : ''} onChange={e => setHarissaResolved(Boolean(e.target.value))}><option value="">Choose a food record…</option><option value="rose">Rose harissa paste, prepared</option><option value="harissa">Harissa paste</option></select> : item.status === 'amount' ? <div className="amount-control"><input type="number" value={oilAmount} onChange={e => setOilAmount(e.target.value)}/><select defaultValue="tbsp"><option>tbsp</option><option>tsp</option><option>ml</option></select></div> : <strong>{item.match}</strong>}</div></div>{item.status === 'matched' && <Badge tone="green">High confidence</Badge>}</Card>)}</div></section>
      <aside><Card className="review-summary"><Sparkles/><h2>Calculation preview</h2><NutritionStrip nutrition={{calories:524,protein:48,carbs:39,fat:18,basis:'per_serving'}}/><p>Per serving · based on 4 servings</p><dl><div><dt>Ingredient matches</dt><dd>4 of 5</dd></div><div><dt>Quantity conversions</dt><dd>5 of 5</dd></div><div><dt>Primary dataset</dt><dd>CoFID</dd></div></dl>{issues > 0 ? <Notice tone="warning" title="Not ready yet">Resolve {issues} highlighted field before saving.</Notice> : <Notice tone="success" title="Ready to save">All required fields have been resolved.</Notice>}<Button disabled={issues > 0} onClick={() => navigate('/recipes')}>Calculate & save recipe</Button></Card></aside>
    </div>
  </div>
}

interface ImportedIngredientRow {
  original_text: string
  amount: string
  unit: string
  quantity_grams: string
  food_record_id: string
  food_phrase: string
  food_basis_unit: string
  search: string
  included: boolean
  optional: boolean
}

function LiveImportReviewPageNew() {
  const { jobId = '', recipeId: directRecipeId = '' } = useParams()
  const navigate = useNavigate()
  const [rows, setRows] = useState<ImportedIngredientRow[]>([])
  const [yieldServings, setYieldServings] = useState('')
  const [activeRow, setActiveRow] = useState(0)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const job = useQuery({
    queryKey:['job',jobId],
    queryFn:()=>api.job(jobId),
    enabled:Boolean(jobId),
    refetchInterval: query => ['queued','running'].includes(query.state.data?.status ?? '') ? 1000 : false,
  })
  const recipeId = directRecipeId || job.data?.result?.recipe_id
  const recipe = useQuery({ queryKey:['recipe',recipeId],queryFn:()=>api.getRecipe(recipeId!),enabled:Boolean(recipeId) })
  const search = rows[activeRow]?.search ?? ''
  const foods = useQuery({ queryKey:['foods',search],queryFn:()=>api.searchFoods(search),enabled:search.trim().length>=2 })
  const publisherIsPrimary = completePublisherNutrition(recipe.data)

  useEffect(()=>{
    if(!recipe.data)return
    setYieldServings(String(recipe.data.yield_servings ?? ''))
    const ingredientRows: ImportedIngredientRow[] = recipe.data.ingredients.map(item=>({
      original_text:item.original_text,
      amount:String(item.quantity ?? ''),
      unit:item.unit ?? (item.quantity_grams != null ? 'g' : ''),
      quantity_grams:String(item.quantity_grams ?? ''),
      food_record_id:item.food_record_id ?? '',
      food_phrase:item.food_phrase ?? item.original_text,
      food_basis_unit:'g',
      search:item.food_phrase ?? item.original_text,
      included:item.included,
      optional:item.optional,
    }))
    setRows(ingredientRows)
    const firstUnmatched = ingredientRows.findIndex(item=>item.included&&!item.food_record_id)
    setActiveRow(firstUnmatched >= 0 ? firstUnmatched : 0)
  },[recipe.data])

  const update=(index:number,change:Partial<ImportedIngredientRow>)=>setRows(all=>all.map((row,rowIndex)=>rowIndex===index?{...row,...change}:row))
  const rowNeedsFallbackWork=(row:ImportedIngredientRow)=>row.included&&(
    !row.amount || !row.unit || !row.food_record_id || (row.food_basis_unit!=='ml'&&!(row.quantity_grams||gramsFor(row.amount,row.unit)))
  )
  const unresolvedRows=publisherIsPrimary ? [] : rows.filter(rowNeedsFallbackWork)

  const save=async()=>{
    if(!recipe.data)return
    if(!yieldServings){setError('Confirm how many servings the recipe makes.');return}
    if(unresolvedRows.length){setError(`${unresolvedRows.length} included ingredient${unresolvedRows.length===1?' still needs':'s still need'} an amount, unit, compatible weight, or food match.`);return}
    setSaving(true);setError('')
    try{
      const reviewed=await api.saveRecipeReview(recipe.data.id,{
        expected_version:recipe.data.version,
        title:recipe.data.title,
        yield_servings:Number(yieldServings),
        ingredients:rows.map(row=>{
          const quantityGrams=row.quantity_grams||gramsFor(row.amount,row.unit)
          return {
            original_text:row.original_text,
            quantity:row.amount?Number(row.amount):undefined,
            unit:row.unit||undefined,
            quantity_grams:quantityGrams?Number(quantityGrams):undefined,
            food_phrase:row.food_phrase,
            included:row.included,
            optional:row.optional,
            needs_review:!publisherIsPrimary&&rowNeedsFallbackWork(row),
            food_record_id:row.food_record_id||undefined,
          }
        }),
      })
      await api.calculateRecipe(reviewed.id)
      navigate('/recipes')
    }catch(reason){setError(reason instanceof ApiError?reason.message:'The reviewed recipe could not be saved.')}
    finally{setSaving(false)}
  }

  if(job.data?.status==='failed')return <div className="page"><Notice tone="warning" title="Import failed">{job.data.error_detail ?? 'The publisher page could not be read.'}</Notice></div>
  if(!recipe.data)return <div className="page"><PageHeader eyebrow="Import review" title="Preparing the recipe" description="The worker is safely reading the page and extracting fields already present."/><ProgressBar value={job.data?.progress ?? 10} label={job.data?.stage ?? 'Queued'}/></div>
  const publisher=recipe.data.publisher_nutrition
  const publisherPreview=publisherIsPrimary&&publisher ? {calories:Number(publisher.energy_kcal),protein:Number(publisher.protein_g),carbs:Number(publisher.carbohydrate_g),fat:Number(publisher.fat_g),basis:'per_serving' as const} : null

  return <div className="page page--wide"><IngredientUnitOptions/><div className="review-top"><Link to="/recipes" className="icon-link"><ArrowLeft/>Back to recipes</Link><Badge tone={unresolvedRows.length?'warning':'green'}>{publisherIsPrimary?'Publisher nutrition ready':unresolvedRows.length?`${unresolvedRows.length} fallback issue${unresolvedRows.length===1?'':'s'}`:'Ready to calculate'}</Badge></div><PageHeader eyebrow="Import review" title={recipe.data.title} description={publisherIsPrimary?'Confirm the serving yield and parsed ingredient units. The website nutrition will be used; food matching is optional.':'The website did not provide a complete per-serving nutrition set, so match each included ingredient for the fallback calculation.'} actions={recipe.data.source_url?<Button variant="secondary" onClick={()=>window.open(recipe.data.source_url)}><ExternalLink/>Original recipe</Button>:undefined}/><div className="review-layout"><section><Card className="yield-card"><label>Confirmed servings<input type="number" min="0.25" step="0.25" value={yieldServings} onChange={event=>setYieldServings(event.target.value)}/></label></Card><div className="ingredient-review-list">{rows.map((row,index)=>{const options=index===activeRow?(foods.data?.items??[]):[];const needsWeight=Boolean(!publisherIsPrimary&&row.food_record_id&&row.food_basis_unit!=='ml'&&!MASS_FACTORS[row.unit.trim().toLowerCase()]);return <Card key={`${row.original_text}-${index}`} className={`ingredient-row ${!publisherIsPrimary&&rowNeedsFallbackWork(row)?'ingredient-row--review':''}`}><div className="ingredient-copy"><small>Original ingredient</small><strong>{row.original_text}</strong><div className="form-grid form-grid--ingredient"><label>Amount<input type="number" min="0" step="any" value={row.amount} onChange={event=>update(index,{amount:event.target.value,quantity_grams:gramsFor(event.target.value,row.unit)||row.quantity_grams})}/></label><label>Unit<input list="ingredient-unit-options" value={row.unit} onChange={event=>update(index,{unit:event.target.value,quantity_grams:gramsFor(row.amount,event.target.value)})} placeholder="e.g. tbsp, clove, large"/></label>{needsWeight&&<label>Weight for fallback (g)<input type="number" min="0" step="any" value={row.quantity_grams} onChange={event=>update(index,{quantity_grams:event.target.value})}/></label>}</div><div className="food-match"><span>Food-data match {publisherIsPrimary?'(optional)':'(required for fallback)'}</span><label>Search food records<input type="search" value={row.search} onFocus={()=>setActiveRow(index)} onChange={event=>{setActiveRow(index);update(index,{search:event.target.value})}} placeholder="Use the plain ingredient name"/></label><select aria-label={`Food-data match for ${row.original_text}`} value={row.food_record_id} onFocus={()=>setActiveRow(index)} onChange={event=>{const selected=options.find(food=>food.id===event.target.value);update(index,{food_record_id:event.target.value,food_phrase:selected?.name??row.food_phrase,food_basis_unit:selected?.basis_unit??row.food_basis_unit})}}><option value="">Choose a food record…</option>{row.food_record_id&&!options.some(food=>food.id===row.food_record_id)&&<option value={row.food_record_id}>{row.food_phrase} · selected</option>}{options.map(food=><option key={food.id} value={food.id}>{food.name} · {food.provider} {food.dataset_version}</option>)}</select>{index===activeRow&&foods.isFetching&&<ProgressBar value={50} label="Searching local and FoodData Central records…"/>}{index===activeRow&&search.trim().length>=2&&!foods.isFetching&&foods.data?.total===0&&<small className="field-help">No records matched. Try a shorter food name, such as “chickpeas” instead of the full ingredient line.</small>}{index===activeRow&&foods.data?.remote_error&&<small className="field-help field-help--warning">{foods.data.remote_error}</small>}</div><div className="form-inline"><label className="check-label"><input type="checkbox" checked={row.included} onChange={event=>update(index,{included:event.target.checked})}/>Include in recipe</label><label className="check-label"><input type="checkbox" checked={row.optional} onChange={event=>update(index,{optional:event.target.checked,included:event.target.checked?false:row.included})}/>Optional</label></div></div></Card>})}</div></section><aside><Card className="review-summary"><Sparkles/><h2>{publisherIsPrimary?'Website nutrition':'Fallback calculation'}</h2>{publisherPreview&&<><NutritionStrip nutrition={publisherPreview}/><p>Per serving · supplied by {recipe.data.publisher??'the recipe website'}</p><Notice tone="success" title="Ready without food matching">These values will be used for planning. Ingredient matching remains available for your records and as a future fallback.</Notice></>}{!publisherIsPrimary&&<p>Search each ingredient by its plain food name. Volume units such as tbsp and tsp are converted automatically for volume-based records; count units need a gram weight for a weight-based record.</p>}{error&&<Notice tone="warning" title="Not ready">{error}</Notice>}<Button disabled={saving} onClick={save}>{saving?'Saving…':publisherIsPrimary?'Save recipe':'Calculate & save recipe'}</Button></Card></aside></div></div>
}
