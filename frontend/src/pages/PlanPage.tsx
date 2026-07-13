import { ArrowRight, CalendarRange, Check, ChevronLeft, ChevronRight, Lock, Sparkles, Users, WandSparkles } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { NutritionStrip } from '../components/Nutrition'
import { Badge, Button, Card, Notice, PageHeader, ProgressBar } from '../components/ui'
import { api, ApiError, isDemoMode, type BackendPlanDetail } from '../api/client'

const wizardSteps = ['Dates', 'Meals', 'People', 'Batches', 'Ingredients', 'Review']

export function PlanPage() {
  const [step, setStep] = useState(0)
  const [generated, setGenerated] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [startDate,setStartDate]=useState('2026-07-20')
  const [days,setDays]=useState(7)
  const [livePlan,setLivePlan]=useState<BackendPlanDetail|null>(null)
  const [error,setError]=useState('')
  const [enabledMeals,setEnabledMeals]=useState(['breakfast','lunch','dinner','snack'])
  const [batchDuration,setBatchDuration]=useState(2)
  const [batchLunches,setBatchLunches]=useState(true)
  const generate = async () => {
    setGenerating(true);setError('')
    if(isDemoMode){window.setTimeout(()=>{setGenerating(false);setGenerated(true)},1200);return}
    try{
      const [members,recipes]=await Promise.all([api.listMembers(),api.listRecipes('')])
      const participants=members.filter(member=>member.active).map(member=>member.id)
      const recipeIds=recipes.items.filter(recipe=>recipe.eligibility==='planner_ready').map(recipe=>recipe.id)
      if(!participants.length)throw new ApiError(422,'Add at least one active household member.')
      if(!recipeIds.length)throw new ApiError(422,'Save at least one recipe with complete website nutrition first.')
      const slots=[]
      for(let day=0;day<days;day+=1){
        const date=new Date(`${startDate}T12:00:00`);date.setDate(date.getDate()+day);const meal_date=date.toISOString().slice(0,10)
        for(const meal_type of enabledMeals)slots.push({meal_date,meal_type,participant_member_ids:participants,batch_key:meal_type==='lunch'&&batchLunches?`lunch-${Math.floor(day/batchDuration)}`:undefined})
      }
      const plan=await api.generatePlan({name:`Plan from ${startDate}`,slots,recipe_ids:recipeIds})
      setLivePlan(await api.getPlan(plan.id));setGenerated(true)
    }catch(reason){setError(reason instanceof ApiError?reason.message:'The plan could not be generated.')}
    finally{setGenerating(false)}
  }
  if (generated) return livePlan?<LiveGeneratedPlan plan={livePlan} onBack={()=>{setGenerated(false);setLivePlan(null)}}/>:<GeneratedPlan onBack={() => setGenerated(false)}/>
  return <div className="page"><PageHeader eyebrow="Automatic planning" title="Build your next meal plan" description="We will use recipes with complete website-reported nutrition and stay within every person's target tolerance." />
    {error&&<Notice tone="warning" title="Plan not feasible">{error}</Notice>}
    <div className="planner-layout"><aside className="wizard-sidebar"><ol>{wizardSteps.map((name,index) => <li key={name} className={index < step ? 'done' : index === step ? 'active' : ''}><button onClick={() => setStep(index)}><span>{index < step ? <Check size={15}/> : index + 1}</span><div><strong>{name}</strong><small>{['Choose the planning period','Pick meals to cover','Choose who is eating','Plan leftovers together','Use, prefer or exclude','Check every constraint'][index]}</small></div></button></li>)}</ol></aside>
      <Card className="wizard-panel"><div className="wizard-panel-heading"><p className="eyebrow">Step {step + 1} of {wizardSteps.length}</p><h2>{['When are you planning for?','Which meals should we plan?','Who is eating?','How should batches last?','Any ingredients in mind?','Ready to build your week'][step]}</h2><p>{['Choose any period from one day upwards.','Leave a meal unplanned when you are eating elsewhere. Its allowance is preserved by default.','Everyone shares the same recipe, with individual portion sizes.','Cooking once for several dates saves time and drives the shopping quantities.','Guide the choices using what you already have or want to avoid.','These are the hard rules the planner will use.'][step]}</p></div>
        {step === 0 && <div className="form-grid"><label>Starts<input type="date" value={startDate} onChange={event=>setStartDate(event.target.value)}/></label><label>Number of days<div className="stepper"><button type="button" onClick={()=>setDays(value=>Math.max(1,value-1))}>−</button><input type="number" min="1" max="31" value={days} onChange={event=>setDays(Math.max(1,Number(event.target.value)))}/><button type="button" onClick={()=>setDays(value=>Math.min(31,value+1))}>+</button></div></label><div className="date-preview"><CalendarRange/><span><strong>Planning period</strong><small>{days} days from {startDate}</small></span></div></div>}
        {step === 1 && <div className="meal-selector">{['Breakfast','Lunch','Dinner','Snack'].map((name,index) => {const key=name.toLowerCase();return <label className="check-card" key={name}><input type="checkbox" checked={enabledMeals.includes(key)} onChange={event=>setEnabledMeals(values=>event.target.checked?[...values,key]:values.filter(value=>value!==key))}/><span><strong>{name}</strong><small>{[25,30,35,10][index]}% of daily target</small></span><Badge tone="green">{days} to plan</Badge></label>})}<Notice title="Eating out?">Leave out a meal type here. Individual dates can be omitted through the planning API.</Notice></div>}
        {step === 2 && <div className="member-selector">{[['Z','Zach','2,000 kcal · ±5%'],['M','Maya','1,700 kcal · ±7%']].map(([avatar,name,target]) => <label className="member-check" key={name}><input type="checkbox" defaultChecked/><span className="member-avatar">{avatar}</span><span><strong>{name}</strong><small>{target}</small></span><Check className="check-icon"/></label>)}</div>}
        {step === 3 && <div className="form-stack"><label>Default batch duration<select value={batchDuration} onChange={event=>setBatchDuration(Number(event.target.value))}><option value="1">Cook each meal once</option><option value="2">2 eating occasions</option><option value="3">3 eating occasions</option></select></label><label className="switch-row"><span><strong>Batch weekday lunches</strong><small>Cook once and allocate portions to following days</small></span><input type="checkbox" checked={batchLunches} onChange={event=>setBatchLunches(event.target.checked)}/></label><Notice tone="warning" title="Leftover reminder">Allocations more than 48 hours after cooking require a food-safety acknowledgement.</Notice></div>}
        {step === 4 && <div className="ingredient-guidance"><label>Find an ingredient<input placeholder="Search your pantry and food catalogue…"/></label><div className="guidance-block"><strong>Must use</strong><div className="tag-row"><span className="tag">Spinach ×</span></div></div><div className="guidance-block"><strong>Prefer</strong><div className="tag-row"><span className="tag tag--warm">Chickpeas ×</span><span className="tag tag--warm">Chicken thighs ×</span></div></div><div className="guidance-block"><strong>Exclude</strong><div className="tag-row"><span className="tag tag--danger">Peanuts ×</span></div></div></div>}
        {step === 5 && <div className="constraint-review"><dl><div><dt>Dates</dt><dd>20–26 July · 7 days</dd></div><div><dt>Meals</dt><dd>28 meal slots</dd></div><div><dt>People</dt><dd>Zach and Maya</dd></div><div><dt>Targets</dt><dd>Individual calorie targets · hard tolerance</dd></div><div><dt>Batches</dt><dd>Weekday lunches last 2 occasions</dd></div><div><dt>Ingredients</dt><dd>Must use spinach · prefer 2 · exclude peanuts</dd></div></dl><Notice tone="success" title="Enough recipes available">42 planner-ready recipes fit these constraints.</Notice>{generating && <ProgressBar value={72} label="Balancing nutrition, variety and pantry use…"/>}</div>}
        <div className="wizard-actions"><Button variant="ghost" disabled={step === 0 || generating} onClick={() => setStep(step-1)}><ChevronLeft/>Back</Button>{step < 5 ? <Button onClick={() => setStep(step+1)}>Continue<ChevronRight/></Button> : <Button disabled={generating} onClick={generate}><WandSparkles/>{generating ? 'Building your plan…':'Generate meal plan'}</Button>}</div>
      </Card>
    </div>
  </div>
}

function GeneratedPlan({ onBack }: { onBack: () => void }) {
  return <div className="page"><PageHeader eyebrow="20–26 July" title="Your plan is ready" description="Every day is within target. Lock anything you love, then regenerate or accept." actions={<><Button variant="secondary" onClick={onBack}>Edit constraints</Button><Button>Accept plan<ArrowRight/></Button></>}/><Notice tone="success" title="All targets satisfied">The plan stays within each person's selected tolerance and respects every hard exclusion.</Notice><div className="generated-grid">{['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].map((day,index) => <Card key={day} className="generated-day"><div className="generated-day-head"><div><strong>{day}</strong><small>{20+index} Jul</small></div><Badge tone="green">{[98,101,99,102,97,100,99][index]}%</Badge></div>{['Breakfast','Lunch','Dinner'].map((kind,mealIndex) => <div className="generated-meal" key={kind}><span>{kind}</span><strong>{[['Berry overnight oats','Harissa chicken','Green vegetable curry'],['Greek yoghurt granola','Harissa chicken · leftover','Salmon & summer greens'],['Mushroom eggs','Rainbow grain bowl','Shakshuka']][index%3][mealIndex]}</strong><small>{[386,524,548][mealIndex]} kcal</small><button aria-label="Lock meal"><Lock size={15}/></button></div>)}<NutritionStrip compact nutrition={{calories:[1961,2024,1983][index%3],protein:132,carbs:218,fat:65,basis:'recipe_total'}}/></Card>)}</div></div>
}

function LiveGeneratedPlan({plan,onBack}:{plan:BackendPlanDetail;onBack:()=>void}){
  const navigate=useNavigate()
  const [accepting,setAccepting]=useState(false)
  const [error,setError]=useState('')
  const grouped=plan.occurrences.reduce<Record<string,BackendPlanDetail['occurrences']>>((result,item)=>{(result[item.meal_date]??=[]).push(item);return result},{})
  const accept=async()=>{setAccepting(true);setError('');try{await api.acceptPlan(plan.plan.id);await api.buildShoppingList(plan.plan.id);navigate('/shopping')}catch(reason){setError(reason instanceof ApiError?reason.message:'The plan could not be accepted.')}finally{setAccepting(false)}}
  return <div className="page"><PageHeader eyebrow={`${plan.plan.start_date} – ${plan.plan.end_date}`} title="Your plan is ready" description="Every selection satisfies the hard target and ingredient rules. Review it before reserving pantry stock." actions={<><Button variant="secondary" onClick={onBack}>Edit constraints</Button><Button disabled={accepting} onClick={accept}>{accepting?'Accepting…':'Accept plan'}<ArrowRight/></Button></>}/>{error&&<Notice tone="warning" title="Could not accept plan">{error}</Notice>}<Notice tone="success" title="All hard targets satisfied">No tolerance was widened. Shared meals use individual quarter-serving portions.</Notice><div className="generated-grid">{Object.entries(grouped).map(([date,occurrences])=><Card key={date} className="generated-day"><div className="generated-day-head"><div><strong>{new Date(`${date}T12:00:00`).toLocaleDateString(undefined,{weekday:'long'})}</strong><small>{date}</small></div><Badge tone="green">Ready</Badge></div>{occurrences.map(item=><div className="generated-meal" key={item.id}><span>{item.meal_type}</span><strong>{item.recipe_title}</strong><small>{item.portions.map(portion=>`${portion.servings} serving`).join(' · ')}</small><span title={`Batch ${item.batch_id}`}><Users size={15}/></span></div>)}</Card>)}</div></div>
}
