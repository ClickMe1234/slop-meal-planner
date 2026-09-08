import { ArrowLeft, ArrowRight, Check, ExternalLink, Heart, KeyRound, ShieldCheck } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Card, Loading, Notice, ProgressBar, Segmented } from '../components/ui'
import { api, ApiError, isDemoMode, type IngredientLocale, type MeasurementSystem } from '../api/client'
import { USDA_KEY_SIGNUP_URL } from '../components/UsdaKeyGuidance'
import { clearOfflineShoppingData } from '../lib/offlineShopping'

export function LoginPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const session = useQuery({ queryKey: ['session'], queryFn: api.me, enabled: !isDemoMode, retry: false, refetchOnMount: 'always' })
  const [loading, setLoading] = useState(false)
  const [username, setUsername] = useState(isDemoMode ? 'zach' : '')
  const [password, setPassword] = useState(isDemoMode ? 'password' : '')
  const [rememberMe, setRememberMe] = useState(true)
  const [error, setError] = useState('')
  const [showHelp, setShowHelp] = useState(false)
  useEffect(() => {
    if (!isDemoMode) {
      api.setupStatus().then(status => status.setup_required && navigate('/setup')).catch(() => undefined)
    }
  }, [navigate])
  useEffect(() => {
    if (!isDemoMode && session.isSuccess && !session.isFetching && session.data) {
      navigate(session.data.must_change_password ? '/change-password' : '/week', { replace: true })
    }
  }, [navigate, session.data, session.isFetching, session.isSuccess])
  if (!isDemoMode && (session.isLoading || session.isFetching)) return <div className="page"><Loading label="Checking your household session…" /></div>
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setLoading(true); setError('')
    try {
      if (isDemoMode) {
        await new Promise(resolve => window.setTimeout(resolve, 350))
        localStorage.setItem('slop-demo-session', 'active')
      } else {
        const result = await api.login(username.trim(), password, rememberMe)
        queryClient.clear()
        await clearOfflineShoppingData()
        if (result.user.must_change_password) { navigate('/change-password'); return }
      }
      navigate('/week')
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Sign-in failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }
  return <div className="auth-layout">
    <section className="auth-art">
      <div className="brand brand--light"><div className="brand-mark"><Heart size={20} fill="currentColor" /></div><div><strong>Slop</strong><span>meal planner</span></div></div>
      <div><p className="eyebrow">Your week, made easier</p><h1>Plan once.<br/>Eat well all week.</h1><p>Recipes you trust, nutrition calculated consistently and one shopping list for the household.</p></div>
      <blockquote>“Dinner is sorted before the week even begins.”</blockquote>
    </section>
    <section className="auth-panel"><Card className="auth-card"><div className="auth-heading"><div className="mobile-auth-mark"><Heart fill="currentColor" /></div><p className="eyebrow">Welcome home</p><h2>Sign in to your household</h2><p>Your meal plan is waiting.</p></div><form onSubmit={submit} className="form-stack"><label>Username<input required value={username} onChange={event => setUsername(event.target.value)} autoComplete="username" /></label><label>Password<input required type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" /></label>{error && <p role="alert" className="field-error">{error}</p>}<div className="form-inline"><label className="check-label"><input type="checkbox" checked={rememberMe} onChange={event => setRememberMe(event.target.checked)} /> Keep me signed in</label><button className="text-button" type="button" aria-expanded={showHelp} aria-controls="login-help" onClick={() => setShowHelp(value => !value)}>{showHelp ? 'Hide help' : 'Need help?'}</button></div><Button type="submit" disabled={loading}>{loading ? 'Signing in…' : 'Sign in'}<ArrowRight size={18} /></Button></form>{showHelp && <div id="login-help" role="region" aria-label="Sign-in help"><Notice tone="info" title="Need help signing in?">Use the username and password created for this household. If you do not know them, contact the household owner; this private installation does not provide a self-service password reset.</Notice></div>}<div className="secure-note"><ShieldCheck size={17} /><span>Private to your home network</span></div></Card></section>
  </div>
}

export function ChangePasswordPage(){
  const navigate=useNavigate()
  const [current,setCurrent]=useState('')
  const [next,setNext]=useState('')
  const [confirm,setConfirm]=useState('')
  const [error,setError]=useState('')
  const [saving,setSaving]=useState(false)
  const submit=async(event:FormEvent)=>{event.preventDefault();if(next!==confirm){setError('The new passwords do not match.');return}setSaving(true);setError('');try{await api.changePassword(current,next);navigate('/week')}catch(reason){setError(reason instanceof ApiError?reason.message:'The password could not be changed.')}finally{setSaving(false)}}
  return <div className="auth-layout"><section className="auth-art"><div className="brand brand--light"><div className="brand-mark"><Heart fill="currentColor"/></div><div><strong>Slop</strong><span>meal planner</span></div></div><div><p className="eyebrow">Account security</p><h1>Choose your own password.</h1><p>Temporary passwords cannot be used to access household data.</p></div></section><section className="auth-panel"><Card className="auth-card"><div className="auth-heading"><h2>Change temporary password</h2><p>Use at least 12 characters.</p></div><form className="form-stack" onSubmit={submit}><label>Temporary password<input required type="password" value={current} onChange={event=>setCurrent(event.target.value)} autoComplete="current-password"/></label><label>New password<input required minLength={12} type="password" value={next} onChange={event=>setNext(event.target.value)} autoComplete="new-password"/></label><label>Confirm new password<input required minLength={12} type="password" value={confirm} onChange={event=>setConfirm(event.target.value)} autoComplete="new-password"/></label>{error&&<p role="alert" className="field-error">{error}</p>}<Button disabled={saving}>{saving?'Changing…':'Change password'}<ArrowRight/></Button></form></Card></section></div>
}

export function SetupPage() {
  const navigate = useNavigate()
  const [householdName, setHouseholdName] = useState('Our household')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [setupToken, setSetupToken] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setLoading(true); setError('')
    try {
      await api.setup({ setup_token: setupToken, household_name: householdName, username, password })
      navigate('/onboarding')
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Setup failed. Check the token and try again.')
    } finally {
      setLoading(false)
    }
  }
  return <div className="auth-layout"><section className="auth-art"><div className="brand brand--light"><div className="brand-mark"><Heart size={20} fill="currentColor" /></div><div><strong>Slop</strong><span>meal planner</span></div></div><div><p className="eyebrow">First run</p><h1>Create your private household.</h1><p>This owner account controls members, backups and system settings.</p></div></section><section className="auth-panel"><Card className="auth-card"><div className="auth-heading"><p className="eyebrow">Owner setup</p><h2>Start your household</h2><p>Use the one-time setup token from your Docker configuration.</p></div><form onSubmit={submit} className="form-stack"><label>Household name<input required value={householdName} onChange={event => setHouseholdName(event.target.value)}/></label><label>Owner username<input required minLength={3} value={username} onChange={event => setUsername(event.target.value)} autoComplete="username"/></label><label>Password<input required minLength={12} type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="new-password"/></label><label>Setup token<input required type="password" value={setupToken} onChange={event => setSetupToken(event.target.value)}/></label>{error && <p role="alert" className="field-error">{error}</p>}<Button disabled={loading}>{loading ? 'Creating household…' : 'Create owner account'}<ArrowRight/></Button></form></Card></section></div>
}

const steps = ['Household', 'API key', 'Targets', 'Meals', 'Preferences', 'Language', 'Pantry']

type OnboardingTarget = {
  mode: 'calorie' | 'macros'
  tolerance: number
  calorieTarget: number
  proteinTarget: number
  carbohydrateTarget: number
  fatTarget: number
  allocations: { Breakfast: number; Lunch: number; Dinner: number; Snacks: number }
}

const newOnboardingTarget = (): OnboardingTarget => ({
  mode: 'calorie', tolerance: 5, calorieTarget: 2000,
  proteinTarget: 130, carbohydrateTarget: 225, fatTarget: 67,
  allocations: { Breakfast: 25, Lunch: 30, Dinner: 35, Snacks: 10 },
})

export function OnboardingPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [step, setStep] = useState(0)
  const [targetDrafts, setTargetDrafts] = useState<Record<string, OnboardingTarget>>({})
  const [activeTargetMemberId, setActiveTargetMemberId] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [error, setError] = useState('')
  const [newMemberName, setNewMemberName] = useState('')
  const [editingMemberId, setEditingMemberId] = useState<string | null>(null)
  const [editingMemberName, setEditingMemberName] = useState('')
  const [memberSaving, setMemberSaving] = useState(false)
  const [allergies, setAllergies] = useState<string[]>([])
  const [avoids, setAvoids] = useState<string[]>([])
  const [preferences, setPreferences] = useState<string[]>([])
  const [ingredientLocale, setIngredientLocale] = useState<IngredientLocale>('uk')
  const [measurementSystem, setMeasurementSystem] = useState<MeasurementSystem>('source')
  const [staples, setStaples] = useState([{name:'Olive oil',selected:true},{name:'Basmati rice',selected:true},{name:'Eggs',selected:true}])
  const [stapleDraft, setStapleDraft] = useState('')
  const members = useQuery({queryKey:['members'],queryFn:api.listMembers,enabled:!isDemoMode})
  const integration = useQuery({queryKey:['usda-integration'],queryFn:api.usdaIntegration,enabled:!isDemoMode})

  useEffect(() => {
    const householdMembers = members.data ?? []
    if (!householdMembers.length) return
    setTargetDrafts(current => {
      const next = { ...current }
      for (const member of householdMembers) next[member.id] ??= newOnboardingTarget()
      return next
    })
    if (!activeTargetMemberId || !householdMembers.some(member => member.id === activeTargetMemberId)) {
      setActiveTargetMemberId(householdMembers[0].id)
    }
  }, [activeTargetMemberId, members.data])

  const activeTarget = targetDrafts[activeTargetMemberId] ?? newOnboardingTarget()
  const updateActiveTarget = (update: Partial<OnboardingTarget>) => {
    if (!activeTargetMemberId) return
    setTargetDrafts(current => ({
      ...current,
      [activeTargetMemberId]: { ...(current[activeTargetMemberId] ?? newOnboardingTarget()), ...update },
    }))
  }

  const addMember = async () => {
    const name = newMemberName.trim()
    if (!name) return
    setMemberSaving(true); setError('')
    try {
      await api.createMember(name)
      setNewMemberName('')
      await queryClient.invalidateQueries({queryKey:['members']})
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The person could not be added.')
    } finally { setMemberSaving(false) }
  }

  const saveMember = async () => {
    const member = members.data?.find(item=>item.id===editingMemberId)
    const name = editingMemberName.trim()
    if (!member || !name) return
    setMemberSaving(true); setError('')
    try {
      await api.updateMember(member.id,{expected_version:member.version,name})
      setEditingMemberId(null)
      await queryClient.invalidateQueries({queryKey:['members']})
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The person could not be updated.')
    } finally { setMemberSaving(false) }
  }

  const finish = async () => {
    if (isDemoMode) { navigate('/week'); return }
    setError('')
    try {
      const user = await api.me()
      if (!user.member_id) throw new Error('The owner has no linked planning profile.')
      if (apiKey.trim() && !integration.data?.configured) await api.saveUsdaIntegration(apiKey.trim())
      for (const member of members.data ?? []) {
        const target = targetDrafts[member.id] ?? newOnboardingTarget()
        await api.setTarget(member.id, {
          mode:target.mode,
          tolerance_percent:target.tolerance,
          calorie_target:target.mode==='calorie'?target.calorieTarget:null,
          protein_target_g:target.mode==='macros'?target.proteinTarget:null,
          carbohydrate_target_g:target.mode==='macros'?target.carbohydrateTarget:null,
          fat_target_g:target.mode==='macros'?target.fatTarget:null,
          allocations:Object.entries(target.allocations).map(([name,percentage])=>({meal_type:name==='Snacks'?'snack':name.toLowerCase(),percentage})),
        })
      }
      await api.updateMe({
        ingredient_locale: ingredientLocale,
        method_view_preference: 'written',
        measurement_system: measurementSystem,
      })
      const existingRestrictions = await api.listRestrictions(user.member_id)
      const requested = [
        ...allergies.map(value=>({kind:'allergy' as const,value,hard:true})),
        ...avoids.map(value=>({kind:'dislike' as const,value,hard:false})),
        ...preferences.map(value=>({kind:'prefer' as const,value,hard:false})),
      ]
      for (const restriction of requested) {
        if (!existingRestrictions.some(item=>item.kind===restriction.kind&&item.value===restriction.value)) {
          await api.addRestriction(user.member_id,restriction)
        }
      }
      const pantry = await api.listPantry()
      const existingPantry = new Set(pantry.map(item=>item.display_name.toLowerCase()))
      for (const staple of staples.filter(item=>item.selected)) {
        if (!existingPantry.has(staple.name.toLowerCase())) {
          await api.addPantry({display_name:staple.name,quantity:1,unit:'item',always_have:true})
        }
      }
      navigate('/week')
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Your onboarding choices could not be saved.')
    }
  }

  const allocationTotal = Object.values(activeTarget.allocations).reduce((sum,value)=>sum+value,0)
  const everyAllocationValid = (members.data ?? []).every(member => Object.values(targetDrafts[member.id]?.allocations ?? newOnboardingTarget().allocations).reduce((sum,value)=>sum+value,0) === 100)
  const activeTargetValid = activeTarget.mode === 'calorie'
    ? activeTarget.calorieTarget > 0
    : activeTarget.proteinTarget >= 0 && activeTarget.carbohydrateTarget >= 0 && activeTarget.fatTarget >= 0
  return <div className="onboarding-page"><header className="onboarding-header"><div className="brand"><div className="brand-mark"><Heart size={20} fill="currentColor"/></div><div><strong>Slop</strong><span>meal planner</span></div></div><span>Setup {step+1} of {steps.length}</span></header><div className="onboarding-progress"><ProgressBar value={(step+1)/steps.length*100}/><ol>{steps.map((name,index)=><li key={name} className={index<=step?'active':''}><span>{index<step?<Check size={14}/>:index+1}</span>{name}</li>)}</ol></div>
    <main className="onboarding-main"><div className="onboarding-copy"><p className="eyebrow">{steps[step]}</p><h1>{['Who are we planning for?','Connect ingredient search','Set nutrition targets','Shape each day','Food that works for you','Words & measurements','What is already at home?'][step]}</h1><p>{['Add everyone sharing meals. Each person gets their own portions and nutrition target.','A free USDA key gives your household reliable ingredient and nutrition search.','Choose calories or macros for every person. Targets stay separate and can be changed later.','Allocate each person’s target across the meals they normally eat.','Hard exclusions are always respected; preferences help rank good options.','Choose the ingredient names and measurements that feel natural.','A quick pantry start makes your first shopping list more useful.'][step]}</p></div>
      <Card className="onboarding-card">
        {step===0&&<div className="form-stack"><div className="member-cards">{(members.data??[]).map(member=><div className="member-row" key={member.id}><span>{member.name.slice(0,1).toUpperCase()}</span>{editingMemberId===member.id?<><label className="grow">Display name<input value={editingMemberName} onChange={event=>setEditingMemberName(event.target.value)}/></label><Button type="button" disabled={memberSaving} onClick={saveMember}>Save</Button><Button type="button" variant="ghost" onClick={()=>setEditingMemberId(null)}>Cancel</Button></>:<><div><strong>{member.name}</strong><small>{member.active?'Planning profile active':'Inactive'}</small></div><Button type="button" variant="ghost" onClick={()=>{setEditingMemberId(member.id);setEditingMemberName(member.name)}}>Edit</Button></>}</div>)}</div><div className="form-inline"><label className="grow">Another person's name<input value={newMemberName} onChange={event=>setNewMemberName(event.target.value)} placeholder="e.g. Maya" onKeyDown={event=>{if(event.key==='Enter'){event.preventDefault();void addMember()}}}/></label><Button type="button" variant="secondary" disabled={memberSaving||!newMemberName.trim()} onClick={addMember}>+ Add person</Button></div></div>}
        {step===1&&<div className="form-stack onboarding-integration"><div className="onboarding-integration-head"><span><KeyRound/></span><div><strong>USDA FoodData Central</strong><small>General ingredients and nutrition data</small></div><Badge tone={integration.data?.configured?'green':'warning'}>{integration.isLoading?'Checking…':integration.data?.configured?'Connected':'Optional'}</Badge></div>{integration.data?.configured?<Notice tone="success" title="Ingredient search is connected">{integration.data.source==='environment'?'This installation already supplies a server API key.':'This household already has a private API key saved.'}</Notice>:<><Notice tone="info" title="You can skip this step">Slop can still import recipes and packaged foods. A private USDA key makes general ingredient search more reliable.</Notice><label>USDA API key<input type="password" minLength={8} maxLength={200} autoComplete="off" value={apiKey} onChange={event=>setApiKey(event.target.value)} placeholder="Paste your free API key"/><small className="field-help">Stored encrypted and never displayed again after setup.</small></label><a className="source-link" href={USDA_KEY_SIGNUP_URL} target="_blank" rel="noreferrer">Get a free USDA API key <ExternalLink/></a></>}</div>}
        {step===2&&<div className="form-stack"><OnboardingMemberTabs members={members.data??[]} activeMemberId={activeTargetMemberId} onSelect={setActiveTargetMemberId}/><label>Planning method<Segmented value={activeTarget.mode} onChange={mode=>updateActiveTarget({mode})} label="Nutrition target mode" options={[{value:'calorie',label:'Calories'},{value:'macros',label:'Macros'}]}/></label>{activeTarget.mode==='calorie'?<label>Daily calorie target<div className="input-suffix"><input type="number" min="1" value={activeTarget.calorieTarget} onChange={event=>updateActiveTarget({calorieTarget:Number(event.target.value)})}/><span>kcal</span></div></label>:<div className="form-grid form-grid--3"><label>Protein<input type="number" min="0" value={activeTarget.proteinTarget} onChange={event=>updateActiveTarget({proteinTarget:Number(event.target.value)})}/></label><label>Carbs<input type="number" min="0" value={activeTarget.carbohydrateTarget} onChange={event=>updateActiveTarget({carbohydrateTarget:Number(event.target.value)})}/></label><label>Fat<input type="number" min="0" value={activeTarget.fatTarget} onChange={event=>updateActiveTarget({fatTarget:Number(event.target.value)})}/></label></div>}<label>Allowed tolerance<div className="range-header"><strong>{activeTarget.tolerance}%</strong><span>Planner must stay within this range</span></div><input type="range" min="1" max="15" value={activeTarget.tolerance} onChange={event=>updateActiveTarget({tolerance:Number(event.target.value)})}/></label></div>}
        {step===3&&<div className="form-stack"><OnboardingMemberTabs members={members.data??[]} activeMemberId={activeTargetMemberId} onSelect={setActiveTargetMemberId}/><div className="allocation-list">{(Object.keys(activeTarget.allocations) as Array<keyof typeof activeTarget.allocations>).map(name=><label key={name}><span>{name}</span><div className="input-suffix"><input type="number" min="0" max="100" value={activeTarget.allocations[name]} onChange={event=>updateActiveTarget({allocations:{...activeTarget.allocations,[name]:Number(event.target.value)}})}/><span>%</span></div></label>)}<div className="total-row"><span>Total allocation</span><strong>{allocationTotal===100&&<Check size={16}/>} {allocationTotal}%</strong></div></div></div>}
        {step===4&&<div className="form-stack"><TagEditor label="Allergies and strict exclusions" placeholder="e.g. peanuts" tone="danger" items={allergies} setItems={setAllergies}/><TagEditor label="Foods you would rather avoid" placeholder="e.g. olives, blue cheese" items={avoids} setItems={setAvoids}/><TagEditor label="Recipes you enjoy" placeholder="e.g. curries, traybakes" tone="warm" items={preferences} setItems={setPreferences}/></div>}
        {step===5&&<div className="form-stack"><p className="muted">These defaults shape recipe cards and planned-batch methods.</p><label>Ingredient language<Segmented value={ingredientLocale} onChange={setIngredientLocale} label="Ingredient language" options={[{value:'uk',label:'British · courgette'},{value:'us',label:'American · zucchini'}]}/></label><div className="ingredient-language-example"><span>Your choice</span><strong>{ingredientLocale==='uk'?'courgette · aubergine · coriander':'zucchini · eggplant · cilantro'}</strong></div><label>Measurements<Segmented value={measurementSystem} onChange={setMeasurementSystem} label="Method measurement system" options={[{value:'source',label:'As written'},{value:'metric',label:'Metric'},{value:'us',label:'US customary'}]}/></label><p className="muted">A search for either ingredient name checks both Good Food and Allrecipes automatically.</p></div>}
        {step===6&&<div className="form-stack"><p className="muted">Add a few staples now, or skip and fill your pantry later.</p>{staples.map((item,index)=><label className="check-card" key={`${item.name}-${index}`}><input type="checkbox" checked={item.selected} onChange={event=>setStaples(values=>values.map((value,itemIndex)=>itemIndex===index?{...value,selected:event.target.checked}:value))}/><span><strong>{item.name}</strong><small>Keep as a household staple</small></span></label>)}<div className="form-inline"><label className="grow">Another staple<input value={stapleDraft} onChange={event=>setStapleDraft(event.target.value)} placeholder="e.g. oats"/></label><Button type="button" variant="secondary" disabled={!stapleDraft.trim()} onClick={()=>{setStaples(items=>[...items,{name:stapleDraft.trim(),selected:true}]);setStapleDraft('')}}>+ Add staple</Button></div></div>}
      </Card>
      {error&&<p role="alert" className="field-error">{error}</p>}<div className="wizard-actions"><Button variant="ghost" disabled={step===0} onClick={()=>setStep(value=>value-1)}><ArrowLeft size={18}/>Back</Button><Button disabled={(step===1&&apiKey.trim().length>0&&apiKey.trim().length<8)||(step===2&&!activeTargetValid)||(step===3&&!everyAllocationValid)} onClick={()=>step===steps.length-1?finish():setStep(value=>value+1)}>{step===steps.length-1?'Finish setup':'Continue'}<ArrowRight size={18}/></Button></div>
    </main>
  </div>
}

function OnboardingMemberTabs({ members, activeMemberId, onSelect }: { members: Array<{ id: string; name: string }>; activeMemberId: string; onSelect: (memberId: string) => void }) {
  return <div className="onboarding-member-tabs" role="tablist" aria-label="Household member target">{members.map(member=><button type="button" role="tab" aria-selected={activeMemberId===member.id} className={activeMemberId===member.id?'active':''} key={member.id} onClick={()=>onSelect(member.id)}><span>{member.name.slice(0,1).toUpperCase()}</span>{member.name}</button>)}</div>
}

function TagEditor({label,placeholder,items,setItems,tone}:{label:string;placeholder:string;items:string[];setItems:(items:string[])=>void;tone?:'danger'|'warm'}) {
  const [draft,setDraft]=useState('')
  const add=()=>{const value=draft.trim().toLowerCase();if(value&&!items.includes(value))setItems([...items,value]);setDraft('')}
  return <div className="form-stack"><label>{label}<input value={draft} onChange={event=>setDraft(event.target.value)} placeholder={placeholder} onKeyDown={event=>{if(event.key==='Enter'){event.preventDefault();add()}}}/></label><Button type="button" variant="secondary" disabled={!draft.trim()} onClick={add}>Add</Button><div className="tag-row">{items.map(value=><button type="button" className={`tag${tone?` tag--${tone}`:''}`} key={value} onClick={()=>setItems(items.filter(item=>item!==value))}>{value} ×</button>)}</div></div>
}
