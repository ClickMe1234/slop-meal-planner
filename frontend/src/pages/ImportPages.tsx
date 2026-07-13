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
  return <div className="page page--narrow"><PageHeader eyebrow="Recipe import" title="Bring in a recipe" description="Paste a recipe page. We will keep the ingredients and source link, then calculate nutrition ourselves." />
    <Card className="import-card"><form onSubmit={submit} className="form-stack"><label>Recipe URL<div className="url-input"><Link2 size={19}/><input type="url" required value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…"/></div></label><Button disabled={stage === 'working'}>{stage === 'working' ? 'Reading recipe…' : 'Import recipe'}<ArrowRight size={18}/></Button></form>{error && <Notice tone="warning" title="Import failed">{error}</Notice>}{stage === 'working' && <div className="import-progress"><ProgressBar value={62} label="Extracting recipe and ingredients"/><ol><li className="done"><Check/>URL safety checked</li><li className="active"><FileSearch/>Reading structured recipe fields</li><li>Preparing ingredient review</li><li>Waiting for your food matches</li></ol></div>}{stage === 'done' && <Notice tone="success" title="Recipe extracted">The recipe is saved as a review draft. Confirm its yield, quantities and food matches before calculation.</Notice>}</Card>
    {stage === 'done' && <Card className="import-preview"><div className="preview-image"><div><Badge tone="green">{recipe?.publisher ?? 'Recipe source'}</Badge><h2>{recipe?.title ?? 'Harissa chicken with chickpeas'}</h2><p>{recipe?.yield_servings ? `Serves ${recipe.yield_servings}` : 'Yield needs review'} · {recipe?.ingredients.length ?? 5} ingredients</p></div></div><div><p>We do not store the publisher's instructions. You will always cook from the original page.</p><div className="button-row"><Button variant="secondary" onClick={() => window.open(url)}><ExternalLink size={17}/>View source</Button><Button onClick={() => navigate(`/imports/${jobId}/review`)}>Review ingredients<ArrowRight size={17}/></Button></div></div></Card>}
    <div className="privacy-note"><ShieldCheck/><div><strong>Designed for your private household</strong><p>Imported recipes retain their source and attribution. Only the details needed for planning are stored.</p></div></div>
  </div>
}

export function CustomRecipePage(){
  const navigate=useNavigate()
  const [title,setTitle]=useState('')
  const [yieldServings,setYieldServings]=useState('4')
  const [instructions,setInstructions]=useState('')
  const [foodQuery,setFoodQuery]=useState('')
  const [rows,setRows]=useState([{original_text:'',amount:'',food_record_id:'',food_phrase:''}])
  const [error,setError]=useState('')
  const [saving,setSaving]=useState(false)
  const foods=useQuery({queryKey:['foods',foodQuery],queryFn:()=>api.searchFoods(foodQuery),enabled:foodQuery.trim().length>=2})
  const update=(index:number,change:Partial<(typeof rows)[number]>)=>setRows(all=>all.map((row,rowIndex)=>rowIndex===index?{...row,...change}:row))
  const submit=async(event:FormEvent)=>{event.preventDefault();setSaving(true);setError('');try{const validRows=rows.filter(row=>row.original_text.trim());const recipe=await api.createRecipe({title,yield_servings:Number(yieldServings),source_type:'custom',custom_instructions:instructions||null,ingredients:validRows.map(row=>({original_text:row.original_text,quantity_grams:row.amount?Number(row.amount):null,unit:'g',food_phrase:row.food_phrase||row.original_text,included:true,optional:false,needs_review:!row.amount||!row.food_record_id,food_record_id:row.food_record_id||null}))});if(validRows.every(row=>row.amount&&row.food_record_id))await api.calculateRecipe(recipe.id);navigate('/recipes')}catch(reason){setError(reason instanceof ApiError?reason.message:'The custom recipe could not be saved.')}finally{setSaving(false)}}
  return <div className="page page--wide"><PageHeader eyebrow="Custom recipe" title="Add your own recipe" description="Custom instructions stay in your household. Nutrition is still calculated from matched ingredient data."/><form onSubmit={submit} className="review-layout"><section><Card className="form-stack"><label>Recipe title<input required value={title} onChange={event=>setTitle(event.target.value)}/></label><label>Servings<input required type="number" min="0.25" step="0.25" value={yieldServings} onChange={event=>setYieldServings(event.target.value)}/></label><label>Your instructions<textarea value={instructions} onChange={event=>setInstructions(event.target.value)} rows={8}/></label></Card><div className="ingredient-review-list">{rows.map((row,index)=><Card className="ingredient-row" key={index}><div className="ingredient-copy"><div className="form-grid"><label>Ingredient as written<input required value={row.original_text} onChange={event=>update(index,{original_text:event.target.value})}/></label><label>Amount in grams<input type="number" min="0" step="any" value={row.amount} onChange={event=>update(index,{amount:event.target.value})}/></label><label>Food-data match<select value={row.food_record_id} onChange={event=>{const food=foods.data?.items.find(item=>item.id===event.target.value);update(index,{food_record_id:event.target.value,food_phrase:food?.name??row.food_phrase})}}><option value="">Choose a food record…</option>{foods.data?.items.filter(food=>food.basis_unit==='g').map(food=><option key={food.id} value={food.id}>{food.name} · {food.provider}</option>)}</select></label></div></div><Button type="button" variant="ghost" onClick={()=>setRows(all=>all.filter((_,rowIndex)=>rowIndex!==index))}><Trash2/>Remove</Button></Card>)}</div><Button type="button" variant="secondary" onClick={()=>setRows(all=>[...all,{original_text:'',amount:'',food_record_id:'',food_phrase:''}])}><Plus/>Add ingredient</Button></section><aside><Card className="review-summary"><h2>Find food matches</h2><label>Search nutrition catalogue<input value={foodQuery} onChange={event=>setFoodQuery(event.target.value)} placeholder="e.g. basmati rice"/></label><p>Choose records with the preparation state that best matches the ingredient as used.</p>{error&&<Notice tone="warning" title="Could not save">{error}</Notice>}<Button disabled={saving}>{saving?'Saving…':'Save recipe'}</Button></Card></aside></form></div>
}

export function ImportReviewPage() {
  return isDemoMode ? <DemoImportReviewPage/> : <LiveImportReviewPage/>
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

interface ReviewRow {
  original_text: string
  amount: string
  basis_unit: 'g' | 'ml'
  food_record_id: string
  food_phrase: string
  included: boolean
  optional: boolean
}

function LiveImportReviewPage() {
  const { jobId = '', recipeId: directRecipeId = '' } = useParams()
  const navigate = useNavigate()
  const [rows, setRows] = useState<ReviewRow[]>([])
  const [yieldServings, setYieldServings] = useState('')
  const [foodQuery, setFoodQuery] = useState('')
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
  const foods = useQuery({ queryKey:['foods',foodQuery],queryFn:()=>api.searchFoods(foodQuery),enabled:foodQuery.trim().length>=2 })
  useEffect(()=>{
    if(!recipe.data)return
    setYieldServings(String(recipe.data.yield_servings ?? ''))
    const ingredientRows: ReviewRow[] = recipe.data.ingredients.map(item=>({
      original_text:item.original_text,
      amount:String(item.quantity_grams ?? item.quantity ?? ''),
      basis_unit:item.quantity_grams != null || item.unit !== 'ml' ? 'g' : 'ml',
      food_record_id:item.food_record_id ?? '',
      food_phrase:item.food_phrase ?? item.original_text,
      included:item.included,
      optional:item.optional,
    }))
    setRows(ingredientRows)
    const firstUnmatched = ingredientRows.find(item=>item.included&&!item.food_record_id)
    setFoodQuery(current=>current || firstUnmatched?.food_phrase || '')
  },[recipe.data])
  const update=(index:number,change:Partial<ReviewRow>)=>setRows(all=>all.map((row,rowIndex)=>rowIndex===index?{...row,...change}:row))
  const save=async()=>{
    if(!recipe.data)return
    if(!yieldServings||rows.some(row=>row.included&&(!row.amount||!row.food_record_id))){setError('Every included ingredient needs an amount and a food-data match.');return}
    setSaving(true);setError('')
    try{
      const reviewed=await api.saveRecipeReview(recipe.data.id,{
        expected_version:recipe.data.version,
        title:recipe.data.title,
        yield_servings:Number(yieldServings),
        ingredients:rows.map(row=>({
          original_text:row.original_text,
          quantity:row.basis_unit==='ml'?Number(row.amount):undefined,
          unit:row.basis_unit,
          quantity_grams:row.basis_unit==='g'?Number(row.amount):undefined,
          food_phrase:row.food_phrase,
          included:row.included,
          optional:row.optional,
          needs_review:false,
          food_record_id:row.food_record_id||undefined,
        })),
      })
      await api.calculateRecipe(reviewed.id)
      navigate('/recipes')
    }catch(reason){setError(reason instanceof ApiError?reason.message:'The reviewed recipe could not be saved.')}
    finally{setSaving(false)}
  }
  if(job.data?.status==='failed')return <div className="page"><Notice tone="warning" title="Import failed">{job.data.error_detail ?? 'The publisher page could not be read.'}</Notice></div>
  if(!recipe.data)return <div className="page"><PageHeader eyebrow="Import review" title="Preparing the recipe" description="The worker is safely reading the page and extracting fields already present."/><ProgressBar value={job.data?.progress ?? 10} label={job.data?.stage ?? 'Queued'}/></div>
  return <div className="page page--wide"><div className="review-top"><Link to="/recipes" className="icon-link"><ArrowLeft/>Back to recipes</Link><Badge tone={rows.some(row=>row.included&&!row.food_record_id)?'warning':'green'}>Human review required</Badge></div><PageHeader eyebrow="Import review" title={recipe.data.title} description="Confirm the serving yield, amounts and food-data matches. Source estimates are never used for planning." actions={recipe.data.source_url?<Button variant="secondary" onClick={()=>window.open(recipe.data.source_url)}><ExternalLink/>Original recipe</Button>:undefined}/><div className="review-layout"><section><Card className="yield-card"><label>Confirmed servings<input type="number" min="0.25" step="0.25" value={yieldServings} onChange={event=>setYieldServings(event.target.value)}/></label></Card><div className="ingredient-review-list">{rows.map((row,index)=><Card key={`${row.original_text}-${index}`} className="ingredient-row"><div className="ingredient-copy"><small>Original ingredient</small><strong>{row.original_text}</strong><div className="form-grid"><label>Amount<input type="number" min="0" step="any" value={row.amount} onChange={event=>update(index,{amount:event.target.value})}/></label><label>Basis<select value={row.basis_unit} onChange={event=>update(index,{basis_unit:event.target.value as 'g'|'ml'})}><option value="g">grams</option><option value="ml">millilitres</option></select></label><label>Food-data match<select value={row.food_record_id} onChange={event=>{const selected=foods.data?.items.find(food=>food.id===event.target.value);update(index,{food_record_id:event.target.value,food_phrase:selected?.name??row.food_phrase,basis_unit:selected?.basis_unit==='ml'?'ml':'g'})}}><option value="">Choose a food record…</option>{foods.data?.items.map(food=><option key={food.id} value={food.id}>{food.name} · {food.provider} {food.dataset_version}</option>)}</select></label></div><div className="form-inline"><label className="check-label"><input type="checkbox" checked={row.included} onChange={event=>update(index,{included:event.target.checked})}/>Include in calculation</label><label className="check-label"><input type="checkbox" checked={row.optional} onChange={event=>update(index,{optional:event.target.checked,included:event.target.checked?false:row.included})}/>Optional</label></div></div></Card>)}</div></section><aside><Card className="review-summary"><Sparkles/><h2>Match foods</h2><p>Search the imported CoFID, USDA or Open Food Facts catalogue, then choose one record for each included ingredient.</p><label>Food search<input value={foodQuery} onChange={event=>setFoodQuery(event.target.value)} placeholder="e.g. chickpeas, drained"/></label>{foods.isFetching&&<ProgressBar value={50} label="Searching foods…"/>}{error&&<Notice tone="warning" title="Not ready">{error}</Notice>}<Button disabled={saving} onClick={save}>{saving?'Calculating…':'Calculate & save recipe'}</Button></Card></aside></div></div>
}
