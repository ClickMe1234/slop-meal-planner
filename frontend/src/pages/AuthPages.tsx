import { ArrowLeft, ArrowRight, Check, Heart, ShieldCheck } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, ProgressBar, Segmented } from '../components/ui'
import { api, ApiError, isDemoMode } from '../api/client'

export function LoginPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [username, setUsername] = useState(isDemoMode ? 'zach' : '')
  const [password, setPassword] = useState(isDemoMode ? 'password' : '')
  const [error, setError] = useState('')
  useEffect(() => {
    if (!isDemoMode) {
      api.setupStatus().then(status => status.setup_required && navigate('/setup')).catch(() => undefined)
    }
  }, [navigate])
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setLoading(true); setError('')
    try {
      if (isDemoMode) {
        await new Promise(resolve => window.setTimeout(resolve, 350))
        localStorage.setItem('savour-demo-session', 'active')
      } else {
        const result = await api.login(username, password)
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
      <div className="brand brand--light"><div className="brand-mark"><Heart size={20} fill="currentColor" /></div><div><strong>Savour</strong><span>meal planner</span></div></div>
      <div><p className="eyebrow">Your week, made easier</p><h1>Plan once.<br/>Eat well all week.</h1><p>Recipes you trust, nutrition calculated consistently and one shopping list for the household.</p></div>
      <blockquote>“Dinner is sorted before the week even begins.”</blockquote>
    </section>
    <section className="auth-panel"><Card className="auth-card"><div className="auth-heading"><div className="mobile-auth-mark"><Heart fill="currentColor" /></div><p className="eyebrow">Welcome home</p><h2>Sign in to your household</h2><p>Your meal plan is waiting.</p></div><form onSubmit={submit} className="form-stack"><label>Username<input required value={username} onChange={event => setUsername(event.target.value)} autoComplete="username" /></label><label>Password<input required type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" /></label>{error && <p role="alert" className="field-error">{error}</p>}<div className="form-inline"><label className="check-label"><input type="checkbox" defaultChecked /> Keep me signed in</label><button className="text-button" type="button">Need help?</button></div><Button type="submit" disabled={loading}>{loading ? 'Signing in…' : 'Sign in'}<ArrowRight size={18} /></Button></form><div className="secure-note"><ShieldCheck size={17} /><span>Private to your home network</span></div></Card></section>
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
  return <div className="auth-layout"><section className="auth-art"><div className="brand brand--light"><div className="brand-mark"><Heart fill="currentColor"/></div><div><strong>Savour</strong><span>meal planner</span></div></div><div><p className="eyebrow">Account security</p><h1>Choose your own password.</h1><p>Temporary passwords cannot be used to access household data.</p></div></section><section className="auth-panel"><Card className="auth-card"><div className="auth-heading"><h2>Change temporary password</h2><p>Use at least 12 characters.</p></div><form className="form-stack" onSubmit={submit}><label>Temporary password<input required type="password" value={current} onChange={event=>setCurrent(event.target.value)} autoComplete="current-password"/></label><label>New password<input required minLength={12} type="password" value={next} onChange={event=>setNext(event.target.value)} autoComplete="new-password"/></label><label>Confirm new password<input required minLength={12} type="password" value={confirm} onChange={event=>setConfirm(event.target.value)} autoComplete="new-password"/></label>{error&&<p role="alert" className="field-error">{error}</p>}<Button disabled={saving}>{saving?'Changing…':'Change password'}<ArrowRight/></Button></form></Card></section></div>
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
  return <div className="auth-layout"><section className="auth-art"><div className="brand brand--light"><div className="brand-mark"><Heart size={20} fill="currentColor" /></div><div><strong>Savour</strong><span>meal planner</span></div></div><div><p className="eyebrow">First run</p><h1>Create your private household.</h1><p>This owner account controls members, backups and system settings.</p></div></section><section className="auth-panel"><Card className="auth-card"><div className="auth-heading"><p className="eyebrow">Owner setup</p><h2>Start your household</h2><p>Use the one-time setup token from your Docker configuration.</p></div><form onSubmit={submit} className="form-stack"><label>Household name<input required value={householdName} onChange={event => setHouseholdName(event.target.value)}/></label><label>Owner username<input required minLength={3} value={username} onChange={event => setUsername(event.target.value)} autoComplete="username"/></label><label>Password<input required minLength={12} type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="new-password"/></label><label>Setup token<input required type="password" value={setupToken} onChange={event => setSetupToken(event.target.value)}/></label>{error && <p role="alert" className="field-error">{error}</p>}<Button disabled={loading}>{loading ? 'Creating household…' : 'Create owner account'}<ArrowRight/></Button></form></Card></section></div>
}

const steps = ['Household', 'Targets', 'Meals', 'Preferences', 'Pantry']

export function OnboardingPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [mode, setMode] = useState<'calorie' | 'macros'>('calorie')
  const [tolerance, setTolerance] = useState(5)
  const [calorieTarget, setCalorieTarget] = useState(2000)
  const [proteinTarget, setProteinTarget] = useState(130)
  const [carbohydrateTarget, setCarbohydrateTarget] = useState(225)
  const [fatTarget, setFatTarget] = useState(67)
  const [allocations, setAllocations] = useState({ Breakfast:25, Lunch:30, Dinner:35, Snacks:10 })
  const [error, setError] = useState('')
  const finish = async () => {
    if (isDemoMode) { navigate('/week'); return }
    try {
      const user = await api.me()
      if (!user.member_id) throw new Error('The owner has no linked planning profile.')
      await api.setTarget(user.member_id, {
        mode,
        tolerance_percent:tolerance,
        calorie_target:mode==='calorie'?calorieTarget:null,
        protein_target_g:mode==='macros'?proteinTarget:null,
        carbohydrate_target_g:mode==='macros'?carbohydrateTarget:null,
        fat_target_g:mode==='macros'?fatTarget:null,
        allocations:Object.entries(allocations).map(([name,percentage])=>({meal_type:name==='Snacks'?'snack':name.toLowerCase(),percentage})),
      })
      navigate('/week')
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : 'Your nutrition target could not be saved.') }
  }
  return <div className="onboarding-page"><header className="onboarding-header"><div className="brand"><div className="brand-mark"><Heart size={20} fill="currentColor" /></div><div><strong>Savour</strong><span>meal planner</span></div></div><span>Setup {step + 1} of {steps.length}</span></header><div className="onboarding-progress"><ProgressBar value={(step + 1) / steps.length * 100} /><ol>{steps.map((name, index) => <li key={name} className={index <= step ? 'active' : ''}><span>{index < step ? <Check size={14} /> : index + 1}</span>{name}</li>)}</ol></div>
    <main className="onboarding-main"><div className="onboarding-copy"><p className="eyebrow">{steps[step]}</p><h1>{['Who are we planning for?','Set your nutrition targets','Shape your day','Food that works for you','What is already at home?'][step]}</h1><p>{['Add the people sharing meals. You can give everyone their own portions and targets.','Choose one clear way to guide the planner. We will never widen your tolerance silently.','Allocate your target across the meals you normally eat.','Hard exclusions are always respected; preferences help rank good options.','A quick pantry start makes your first shopping list more useful.'][step]}</p></div>
      <Card className="onboarding-card">{step === 0 && <div className="form-stack"><label>Your display name<input defaultValue="Zach" /></label><label>Household name<input defaultValue="Our household" /></label><div className="member-row"><span>Z</span><div><strong>Zach</strong><small>Owner · planning profile linked</small></div><Button variant="ghost">Edit</Button></div><Button variant="secondary" type="button">+ Add another person</Button></div>}
        {step === 1 && <div className="form-stack"><label>Planning method<Segmented value={mode} onChange={setMode} label="Nutrition target mode" options={[{ value:'calorie', label:'Calories' },{ value:'macros', label:'Macros' }]} /></label>{mode === 'calorie' ? <label>Daily calorie target<div className="input-suffix"><input type="number" min="1" value={calorieTarget} onChange={event=>setCalorieTarget(Number(event.target.value))}/><span>kcal</span></div></label> : <div className="form-grid form-grid--3"><label>Protein<input type="number" min="0" value={proteinTarget} onChange={event=>setProteinTarget(Number(event.target.value))}/></label><label>Carbs<input type="number" min="0" value={carbohydrateTarget} onChange={event=>setCarbohydrateTarget(Number(event.target.value))}/></label><label>Fat<input type="number" min="0" value={fatTarget} onChange={event=>setFatTarget(Number(event.target.value))}/></label></div>}<label>Allowed tolerance<div className="range-header"><strong>{tolerance}%</strong><span>Planner must stay within this range</span></div><input type="range" min="1" max="15" value={tolerance} onChange={e => setTolerance(Number(e.target.value))} /></label></div>}
        {step === 2 && <div className="allocation-list">{(Object.keys(allocations) as Array<keyof typeof allocations>).map(name => <label key={name}><span>{name}</span><div className="input-suffix"><input type="number" min="0" max="100" value={allocations[name]} onChange={event=>setAllocations(values=>({...values,[name]:Number(event.target.value)}))}/><span>%</span></div></label>)}<div className="total-row"><span>Total allocation</span><strong><Check size={16}/>{Object.values(allocations).reduce((sum,value)=>sum+value,0)}%</strong></div></div>}
        {step === 3 && <div className="form-stack"><label>Allergies and strict exclusions<input placeholder="Search an ingredient…" /></label><div className="tag-row"><span className="tag tag--danger">Peanuts ×</span></div><label>Foods you would rather avoid<input placeholder="e.g. olives, blue cheese…" /></label><label>Recipes you enjoy<input placeholder="e.g. curries, traybakes…" /></label></div>}
        {step === 4 && <div className="form-stack"><p className="muted">Add a few staples now, or skip and fill your pantry later.</p>{['Olive oil','Basmati rice','Eggs'].map(item => <label className="check-card" key={item}><input type="checkbox" defaultChecked/><span><strong>{item}</strong><small>Keep as a household staple</small></span></label>)}<Button variant="secondary">+ Add another staple</Button></div>}
      </Card>
      {error&&<p role="alert" className="field-error">{error}</p>}<div className="wizard-actions"><Button variant="ghost" disabled={step === 0} onClick={() => setStep(value => value - 1)}><ArrowLeft size={18}/>Back</Button><Button onClick={() => step === steps.length - 1 ? finish() : setStep(value => value + 1)}>{step === steps.length - 1 ? 'Finish setup' : 'Continue'}<ArrowRight size={18}/></Button></div>
    </main>
  </div>
}
