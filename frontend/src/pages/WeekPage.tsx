import { ChevronLeft, ChevronRight, Clock3, Lock, MoreHorizontal, RefreshCw } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { NutritionRings } from '../components/Nutrition'
import { Badge, Button, Card, EmptyState, Loading, Notice, PageHeader } from '../components/ui'
import { demoWeek } from '../data/demo'
import { api, isDemoMode } from '../api/client'
import { compareMealTypes } from './planner'

export function WeekPage() {
  return isDemoMode ? <DemoWeekPage/> : <LiveWeekPage/>
}

function DemoWeekPage() {
  const [selected, setSelected] = useState(0)
  const [locked, setLocked] = useState<string[]>([])
  const day = demoWeek[selected]
  const totals = useMemo(() => day.meals.reduce((sum, item) => ({ calories: sum.calories + item.nutrition.calories, protein: sum.protein + item.nutrition.protein, carbs: sum.carbs + item.nutrition.carbs, fat: sum.fat + item.nutrition.fat }), { calories: 0, protein: 0, carbs: 0, fat: 0 }), [day])
  return <div className="page"><PageHeader eyebrow="13–19 July" title="This week" description="Everything is planned. Make changes without losing the meals you want to keep." actions={<><Button variant="secondary"><RefreshCw size={17}/>Regenerate unlocked</Button><Button>Plan next week</Button></>} />
    <div className="week-toolbar"><button aria-label="Previous week"><ChevronLeft/></button><strong>13 – 19 July 2026</strong><button aria-label="Next week"><ChevronRight/></button><Badge tone="green">Within targets</Badge></div>
    <div className="day-tabs">{demoWeek.map((item,index) => <button key={item.date} className={selected === index ? 'active' : ''} onClick={() => setSelected(index)}><span>{item.day.slice(0,3)}</span><strong>{item.shortDate.split(' ')[0]}</strong></button>)}</div>
    <div className="week-layout">
      <section><div className="section-heading"><div><h2>{day.day}</h2><p>{day.shortDate} · {day.meals.length} planned meals</p></div><Badge tone="green">{Math.round(totals.calories/day.targetCalories*100)}% of target</Badge></div><div className="meal-list">{day.meals.map(meal => <Card className="meal-card" key={meal.id}><div className="meal-kind"><span>{meal.kind}</span>{meal.batchLabel && <small><Clock3 size={13}/>{meal.batchLabel}</small>}</div><div className="meal-body"><div><h3>{meal.title}</h3><p>{meal.portions} serving · {meal.nutrition.calories} kcal</p></div><div className="meal-macros"><span>P <strong>{meal.nutrition.protein}g</strong></span><span>C <strong>{meal.nutrition.carbs}g</strong></span><span>F <strong>{meal.nutrition.fat}g</strong></span></div></div><div className="meal-actions"><button className={locked.includes(meal.id) ? 'is-locked' : ''} onClick={() => setLocked(items => items.includes(meal.id) ? items.filter(id => id !== meal.id) : [...items,meal.id])} aria-label={locked.includes(meal.id) ? `Unlock ${meal.title}` : `Lock ${meal.title}`}><Lock size={17}/></button><button aria-label={`More options for ${meal.title}`}><MoreHorizontal size={19}/></button></div></Card>)}</div></section>
      <aside className="day-summary"><Card><h2>Daily nutrition</h2><NutritionRings calories={totals.calories} target={day.targetCalories} protein={totals.protein} carbs={totals.carbs} fat={totals.fat}/><div className="target-note"><span/>Within your 5% tolerance</div></Card><Card className="prep-card"><div><Clock3/><h3>Prep ahead</h3></div><p>Make 3 portions of harissa chicken at lunch. Two are reserved for Tuesday and Wednesday.</p><Button variant="ghost">View batch</Button></Card></aside>
    </div>
  </div>
}

function LiveWeekPage(){
  const queryClient=useQueryClient()
  const [selected,setSelected]=useState(0)
  const session=useQuery({queryKey:['session'],queryFn:api.me,retry:false})
  const plans=useQuery({queryKey:['plans'],queryFn:api.listPlans,refetchOnMount:'always'})
  const current=plans.data?.find(plan=>plan.status==='accepted')??plans.data?.find(plan=>plan.status==='ready')
  const detail=useQuery({queryKey:['plan',current?.id],queryFn:()=>api.getPlan(current!.id),enabled:Boolean(current)})
  const target=useQuery({queryKey:['target',session.data?.member_id],queryFn:()=>api.getTarget(session.data!.member_id!),enabled:Boolean(session.data?.member_id)})
  if(plans.isLoading||detail.isLoading)return <div className="page"><Loading label="Loading your meal plan…"/></div>
  if(!current||!detail.data)return <div className="page"><PageHeader eyebrow="Meal planning" title="This week" description="Your accepted plan will appear here."/><EmptyState icon={<Clock3/>} title="No active plan" description="Generate a plan after adding planner-ready recipes."/></div>
  const dates=Array.from(new Set(detail.data.occurrences.map(item=>item.meal_date))).sort()
  const date=dates[Math.min(selected,Math.max(0,dates.length-1))]
  const meals=detail.data.occurrences.filter(item=>item.meal_date===date).sort((left,right)=>compareMealTypes(left.meal_type,right.meal_type))
  const memberId=session.data?.member_id
  const totals=meals.reduce((sum,item)=>{const servings=Number(item.portions.find(portion=>portion.member_id===memberId)?.servings??0);const nutrition=item.nutrition_per_serving??{};return{calories:sum.calories+Number(nutrition.energy_kcal??0)*servings,protein:sum.protein+Number(nutrition.protein_g??0)*servings,carbs:sum.carbs+Number(nutrition.carbohydrate_g??0)*servings,fat:sum.fat+Number(nutrition.fat_g??0)*servings}},{calories:0,protein:0,carbs:0,fat:0})
  const targetCalories=target.data?.mode==='calorie'?Number(target.data.calorie_target??0):Number(target.data?.protein_target_g??0)*4+Number(target.data?.carbohydrate_target_g??0)*4+Number(target.data?.fat_target_g??0)*9
  const markCooked=async(batchId:string)=>{await api.markBatchCooked(current.id,batchId);await Promise.all([queryClient.invalidateQueries({queryKey:['plan',current.id]}),queryClient.invalidateQueries({queryKey:['pantry']})])}
  return <div className="page"><PageHeader eyebrow={`${current.start_date} – ${current.end_date}`} title="This week" description="Accepted batches reserve pantry stock and consume it only when you mark them cooked." actions={<Button>Plan next week</Button>}/>{current.status==='ready'&&<Notice tone="warning" title="Draft plan">Accept this plan from the Plan page before pantry stock is reserved.</Notice>}<div className="day-tabs">{dates.map((item,index)=><button key={item} className={selected===index?'active':''} onClick={()=>setSelected(index)}><span>{new Date(`${item}T12:00:00`).toLocaleDateString(undefined,{weekday:'short'})}</span><strong>{new Date(`${item}T12:00:00`).getDate()}</strong></button>)}</div><div className="week-layout"><section><div className="section-heading"><div><h2>{new Date(`${date}T12:00:00`).toLocaleDateString(undefined,{weekday:'long'})}</h2><p>{date} · {meals.length} planned meals</p></div>{targetCalories>0&&<Badge tone="green">{Math.round(totals.calories/targetCalories*100)}% of target</Badge>}</div><div className="meal-list">{meals.map(meal=>{const servings=Number(meal.portions.find(portion=>portion.member_id===memberId)?.servings??0);const kcal=Number(meal.nutrition_per_serving?.energy_kcal??0)*servings;return <Card className="meal-card" key={meal.id}><div className="meal-kind"><span>{meal.meal_type}</span><small><Clock3 size={13}/>Batch {meal.batch_servings} servings</small></div><div className="meal-body"><div><h3>{meal.recipe_title}</h3><p>{servings} serving · {Math.round(kcal)} kcal</p></div></div><div className="meal-actions">{meal.cooked_at?<Badge tone="green">Cooked</Badge>:<Button variant="ghost" onClick={()=>markCooked(meal.batch_id)}>Mark cooked</Button>}</div></Card>})}</div></section><aside className="day-summary"><Card><h2>Daily nutrition</h2><NutritionRings calories={Math.round(totals.calories)} target={Math.round(targetCalories||totals.calories||1)} protein={Math.round(totals.protein)} carbs={Math.round(totals.carbs)} fat={Math.round(totals.fat)}/><div className="target-note"><span/>Hard tolerance {target.data?.tolerance_percent??5}%</div></Card></aside></div></div>
}
