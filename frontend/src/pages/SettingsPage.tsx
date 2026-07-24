import { Archive, Bell, Check, ChevronRight, Database, Download, ExternalLink, HardDrive, KeyRound, LockKeyhole, Moon, Network, RefreshCw, Server, Shield, Sun, Upload, UserRound, Users } from 'lucide-react'
import { FormEvent, ReactNode, useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { NavLink } from 'react-router-dom'
import { api, ApiError, type BackendRestoreComponent, type BackendRestorePreview, type BackendRestriction, type IngredientLocale, type RestoreComponent } from '../api/client'
import { Badge, Button, Card, Loading, Notice, PageHeader, Segmented } from '../components/ui'
import type { ThemeChoice } from '../types'
import { USDA_KEY_SIGNUP_URL } from '../components/UsdaKeyGuidance'

const nav = [
  { to: '/settings', label: 'Household', icon: Users, end: true },
  { to: '/settings/targets', label: 'Targets & meals', icon: UserRound },
  { to: '/settings/preferences', label: 'Preferences', icon: Bell },
  { to: '/settings/appearance', label: 'Appearance', icon: Moon },
  { to: '/settings/data', label: 'Data & backup', icon: Database },
  { to: '/settings/system', label: 'System', icon: Server },
]

function SettingsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="page">
      <PageHeader eyebrow="Slop" title="Settings" description="Household profiles, planning defaults and this local installation." />
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Settings sections">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}>
              <Icon />
              {label}
              <ChevronRight />
            </NavLink>
          ))}
        </nav>
        <section className="settings-content">{children}</section>
      </div>
    </div>
  )
}

export function HouseholdSettings() {
  const queryClient = useQueryClient()
  const members = useQuery({ queryKey: ['members'], queryFn: api.listMembers })
  const session = useQuery({ queryKey: ['session'], queryFn: api.me })
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['members'] })
  const addMember = async (event: FormEvent) => {
    event.preventDefault()
    const name = newName.trim()
    if (!name) return
    setSaving(true)
    setError('')
    setMessage('')
    try {
      await api.createMember(name)
      setNewName('')
      setAdding(false)
      await refresh()
      setMessage(`${name} was added.`)
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The person could not be added.')
    } finally {
      setSaving(false)
    }
  }
  const saveMember = async () => {
    const member = members.data?.find((item) => item.id === editingId)
    const name = editingName.trim()
    if (!member || !name) return
    setSaving(true)
    setError('')
    setMessage('')
    try {
      await api.updateMember(member.id, {
        expected_version: member.version,
        name,
      })
      setEditingId(null)
      await refresh()
      setMessage('The profile was updated.')
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The profile could not be updated.')
    } finally {
      setSaving(false)
    }
  }
  const toggleMember = async (memberId: string) => {
    const member = members.data?.find((item) => item.id === memberId)
    if (!member) return
    setSaving(true)
    setError('')
    try {
      await api.updateMember(member.id, {
        expected_version: member.version,
        active: !member.active,
      })
      await refresh()
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The profile could not be updated.')
    } finally {
      setSaving(false)
    }
  }
  const changePassword = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    setMessage('')
    if (newPassword !== confirmPassword) {
      setError('The new passwords do not match.')
      return
    }
    setSaving(true)
    try {
      await api.changePassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setMessage('Your password has been changed.')
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Your password could not be changed.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <SettingsLayout>
      <div className="settings-heading">
        <div>
          <h2>Household</h2>
          <p>People who share recipes, plans, pantry stock and shopping lists.</p>
        </div>
        <Button onClick={() => setAdding((value) => !value)}>+ Add person</Button>
      </div>
      {error && (
        <Notice tone="warning" title="Could not save">
          {error}
        </Notice>
      )}
      {message && (
        <Notice tone="success" title="Saved">
          {message}
        </Notice>
      )}
      {adding && (
        <Card className="settings-section">
          <form className="form-inline" onSubmit={addMember}>
            <label className="grow">
              Person's name
              <input autoFocus value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="e.g. Maya" />
            </label>
            <Button disabled={saving || !newName.trim()}>Add</Button>
            <Button type="button" variant="ghost" onClick={() => setAdding(false)}>
              Cancel
            </Button>
          </form>
        </Card>
      )}
      {members.isLoading ? (
        <Loading label="Loading household…" />
      ) : (
        <div className="member-cards">
          {members.data?.map((member) => (
            <Card key={member.id}>
              <div className="settings-member">
                <span>{member.name.slice(0, 1).toUpperCase()}</span>
                {editingId === member.id ? (
                  <>
                    <label className="grow">
                      Display name
                      <input value={editingName} onChange={(event) => setEditingName(event.target.value)} />
                    </label>
                    <Button disabled={saving} onClick={saveMember}>
                      Save
                    </Button>
                    <Button variant="ghost" onClick={() => setEditingId(null)}>
                      Cancel
                    </Button>
                  </>
                ) : (
                  <>
                    <div>
                      <strong>{member.name}</strong>
                      <small>
                        {session.data?.member_id === member.id ? 'Your linked login' : 'Planning profile'} · {member.active ? 'Active' : 'Inactive'}
                      </small>
                    </div>
                    <Badge tone={member.active ? 'green' : 'default'}>{member.active ? 'Active' : 'Inactive'}</Badge>
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setEditingId(member.id)
                        setEditingName(member.name)
                      }}
                    >
                      Edit
                    </Button>
                    <Button variant="ghost" disabled={saving || session.data?.member_id === member.id} onClick={() => toggleMember(member.id)}>
                      {member.active ? 'Deactivate' : 'Reactivate'}
                    </Button>
                  </>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
      <Card className="settings-section">
        <h3>Change your password</h3>
        <p className="muted">Use at least 12 characters. Your current password is required.</p>
        <form className="form-stack" onSubmit={changePassword}>
          <label>
            Current password
            <input type="password" required value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} autoComplete="current-password" />
          </label>
          <div className="form-grid">
            <label>
              New password
              <input type="password" required minLength={12} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" />
            </label>
            <label>
              Confirm new password
              <input type="password" required minLength={12} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" />
            </label>
          </div>
          <Button disabled={saving || !currentPassword || newPassword.length < 12}>Change password</Button>
        </form>
      </Card>
      <Card className="settings-section">
        <h3>Planning defaults</h3>
        <label className="switch-row">
          <span>
            <strong>Reserve allowance for unplanned meals</strong>
            <small>Eating-out calories are not redistributed automatically.</small>
          </span>
          <input type="checkbox" defaultChecked />
        </label>
        <label className="switch-row">
          <span>
            <strong>Quarter-serving portions</strong>
            <small>People can receive different portions of a shared recipe.</small>
          </span>
          <input type="checkbox" defaultChecked />
        </label>
        <label>
          Default planning period
          <select defaultValue="7">
            <option value="7">7 days</option>
            <option value="5">5 days</option>
            <option value="14">14 days</option>
          </select>
        </label>
      </Card>
    </SettingsLayout>
  )
}

export function TargetSettings() {
  const queryClient = useQueryClient()
  const members = useQuery({ queryKey: ['members'], queryFn: api.listMembers })
  const [memberId, setMemberId] = useState('')
  const selectedMemberId = memberId || members.data?.[0]?.id || ''
  const target = useQuery({
    queryKey: ['target', selectedMemberId],
    queryFn: () => api.getTarget(selectedMemberId),
    enabled: Boolean(selectedMemberId),
    retry: false,
  })
  const [mode, setMode] = useState<'calorie' | 'macros'>('calorie')
  const [calories, setCalories] = useState(2000)
  const [protein, setProtein] = useState(130)
  const [carbs, setCarbs] = useState(225)
  const [fat, setFat] = useState(67)
  const [proteinMin, setProteinMin] = useState(0)
  const [carbsMin, setCarbsMin] = useState(0)
  const [fatMin, setFatMin] = useState(0)
  const [tolerance, setTolerance] = useState(5)
  const [allocations, setAllocations] = useState({
    breakfast: 25,
    lunch: 30,
    dinner: 35,
    snack: 10,
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  useEffect(() => {
    setMode('calorie')
    setCalories(2000)
    setProtein(130)
    setCarbs(225)
    setFat(67)
    setProteinMin(0)
    setCarbsMin(0)
    setFatMin(0)
    setTolerance(5)
    setAllocations({ breakfast: 25, lunch: 30, dinner: 35, snack: 10 })
    setSaved(false)
    setError('')
  }, [selectedMemberId])
  useEffect(() => {
    if (!target.data) return
    setMode(target.data.mode)
    setCalories(Number(target.data.calorie_target ?? 2000))
    setProtein(Number(target.data.protein_target_g ?? 130))
    setCarbs(Number(target.data.carbohydrate_target_g ?? 225))
    setFat(Number(target.data.fat_target_g ?? 67))
    setProteinMin(Number(target.data.protein_min_g ?? 0))
    setCarbsMin(Number(target.data.carbohydrate_min_g ?? 0))
    setFatMin(Number(target.data.fat_min_g ?? 0))
    setTolerance(Number(target.data.tolerance_percent))
    setAllocations((values) => ({
      ...values,
      ...Object.fromEntries(target.data.allocations.map((item) => [item.meal_type, Number(item.percentage)])),
    }))
  }, [target.data])
  const total = Object.values(allocations).reduce((sum, value) => sum + value, 0)
  const save = async () => {
    if (!selectedMemberId || total !== 100) return
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      await api.setTarget(selectedMemberId, {
        mode,
        tolerance_percent: tolerance,
        calorie_target: mode === 'calorie' ? calories : null,
        protein_target_g: mode === 'macros' ? protein : null,
        carbohydrate_target_g: mode === 'macros' ? carbs : null,
        fat_target_g: mode === 'macros' ? fat : null,
        protein_min_g: mode === 'calorie' ? proteinMin : null,
        carbohydrate_min_g: mode === 'calorie' ? carbsMin : null,
        fat_min_g: mode === 'calorie' ? fatMin : null,
        allocations: Object.entries(allocations).map(([meal_type, percentage]) => ({ meal_type, percentage })),
      })
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['target', selectedMemberId],
        }),
        queryClient.invalidateQueries({ queryKey: ['targets'] }),
      ])
      setSaved(true)
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The target could not be saved.')
    } finally {
      setSaving(false)
    }
  }
  return (
    <SettingsLayout>
      <div className="settings-heading">
        <div>
          <h2>Targets & meal allocation</h2>
          <p>Targets are user supplied. Slop does not assess whether they are medically suitable.</p>
        </div>
        <Button disabled={saving || total !== 100} onClick={save}>
          {saving ? 'Saving…' : 'Save changes'}
        </Button>
      </div>
      {error && (
        <Notice tone="warning" title="Could not save">
          {error}
        </Notice>
      )}
      {saved && (
        <Notice tone="success" title="Saved">
          Nutrition targets and meal allocation were updated.
        </Notice>
      )}
      <Card className="settings-section">
        <label>
          Household member
          <select value={selectedMemberId} onChange={(event) => setMemberId(event.target.value)}>
            {members.data?.map((member) => (
              <option value={member.id} key={member.id}>
                {member.name}
              </option>
            ))}
          </select>
        </label>
        <h3>Nutrition target</h3>
        <label>
          Planning mode
          <Segmented
            value={mode}
            onChange={setMode}
            label="Target mode"
            options={[
              { value: 'calorie', label: 'Calories' },
              { value: 'macros', label: 'Macros' },
            ]}
          />
        </label>
        {mode === 'calorie' ? (
          <>
            <div className="form-grid">
              <label>
                Daily calories
                <input type="number" min="1" value={calories} onChange={(event) => setCalories(Number(event.target.value))} />
              </label>
              <label>
                Hard tolerance
                <div className="input-suffix">
                  <input type="number" min="1" max="25" value={tolerance} onChange={(event) => setTolerance(Number(event.target.value))} />
                  <span>%</span>
                </div>
              </label>
            </div>
            <h4>Daily macro minimums</h4>
            <p className="muted">Set only the macros you care about. Leave a minimum at 0 to plan without constraining that macro.</p>
            <div className="form-grid form-grid--3">
              <MacroMinimumInput label="Minimum protein" value={proteinMin} onChange={setProteinMin} />
              <MacroMinimumInput label="Minimum carbohydrate" value={carbsMin} onChange={setCarbsMin} />
              <MacroMinimumInput label="Minimum fat" value={fatMin} onChange={setFatMin} />
            </div>
          </>
        ) : (
          <div className="form-grid form-grid--3">
            <label>
              Protein
              <input type="number" min="0" value={protein} onChange={(event) => setProtein(Number(event.target.value))} />
            </label>
            <label>
              Carbohydrate
              <input type="number" min="0" value={carbs} onChange={(event) => setCarbs(Number(event.target.value))} />
            </label>
            <label>
              Fat
              <input type="number" min="0" value={fat} onChange={(event) => setFat(Number(event.target.value))} />
            </label>
          </div>
        )}
        <Notice title="How calories and macros work">In calorie mode, calories stay the main target and positive macro minimums steer recipe selection and act as daily floors with a 10 g allowance. For example, a 130 g minimum accepts 120 g or more. A 0 g minimum is ignored.</Notice>
      </Card>
      <Card className="settings-section">
        <h3>Meal allocation</h3>
        <div className="allocation-list allocation-list--compact">
          {Object.entries(allocations).map(([name, value]) => (
            <label key={name}>
              <span>{name[0].toUpperCase() + name.slice(1)}</span>
              <div className="input-suffix">
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={value}
                  onChange={(event) =>
                    setAllocations((values) => ({
                      ...values,
                      [name]: Number(event.target.value),
                    }))
                  }
                />
                <span>%</span>
              </div>
            </label>
          ))}
        </div>
        <p className={total === 100 ? 'muted' : 'field-error'}>
          Total: {total}% {total !== 100 && '— allocations must total 100%'}
        </p>
      </Card>
    </SettingsLayout>
  )
}

function MacroMinimumInput({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <label>
      {label}
      <div className="input-suffix">
        <input type="number" min="0" value={value} onChange={(event) => onChange(Number(event.target.value))} />
        <span>g</span>
      </div>
    </label>
  )
}

export function PreferenceSettings() {
  const queryClient = useQueryClient()
  const session = useQuery({ queryKey: ['session'], queryFn: api.me })
  const members = useQuery({ queryKey: ['members'], queryFn: api.listMembers })
  const [memberId, setMemberId] = useState('')
  const selectedMemberId = memberId || members.data?.[0]?.id || ''
  const restrictions = useQuery({
    queryKey: ['restrictions', selectedMemberId],
    queryFn: () => api.listRestrictions(selectedMemberId),
    enabled: Boolean(selectedMemberId),
  })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const saveLocale = async (value: IngredientLocale) => {
    setSaving(true)
    setError('')
    try {
      await api.updateMe(value)
      await queryClient.invalidateQueries({ queryKey: ['session'] })
      await queryClient.invalidateQueries()
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The ingredient language could not be saved.')
    } finally {
      setSaving(false)
    }
  }
  const refresh = () =>
    queryClient.invalidateQueries({
      queryKey: ['restrictions', selectedMemberId],
    })
  const add = async (kind: BackendRestriction['kind'], value: string) => {
    const cleaned = value.trim()
    if (!selectedMemberId || !cleaned) return
    setSaving(true)
    setError('')
    try {
      await api.addRestriction(selectedMemberId, {
        kind,
        value: cleaned,
        hard: kind === 'allergy' || kind === 'exclude',
      })
      await refresh()
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The preference could not be added.')
    } finally {
      setSaving(false)
    }
  }
  const remove = async (item: BackendRestriction) => {
    setSaving(true)
    setError('')
    try {
      await api.deleteRestriction(selectedMemberId, item.id)
      await refresh()
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The preference could not be removed.')
    } finally {
      setSaving(false)
    }
  }
  const items = restrictions.data ?? []
  return (
    <SettingsLayout>
      <div className="settings-heading">
        <div>
          <h2>Preferences & restrictions</h2>
          <p>Choose the food words you recognise, then set rules for planning.</p>
        </div>
        <Badge tone="green">Saved automatically</Badge>
      </div>
      {error && (
        <Notice tone="warning" title="Could not save">
          {error}
        </Notice>
      )}
      <Card className="settings-section ingredient-language-card">
        <div>
          <p className="eyebrow">Ingredient language</p>
          <h3>Which names should Slop use?</h3>
          <p className="muted">Searches still check both British and American recipe sites. Recipe ingredients, pantry items and shopping lists appear in your choice.</p>
        </div>
        <Segmented
          value={session.data?.ingredient_locale ?? 'uk'}
          onChange={saveLocale}
          label="Ingredient language"
          options={[
            { value: 'uk', label: 'British · courgette' },
            { value: 'us', label: 'American · zucchini' },
          ]}
        />
        <div className="ingredient-language-example">
          <span>Also converts</span>
          <strong>{session.data?.ingredient_locale === 'us' ? 'aubergine → eggplant · coriander → cilantro' : 'eggplant → aubergine · cilantro → coriander'}</strong>
        </div>
      </Card>
      <Card className="settings-section">
        <label>
          Household member
          <select value={selectedMemberId} onChange={(event) => setMemberId(event.target.value)}>
            {members.data?.map((member) => (
              <option key={member.id} value={member.id}>
                {member.name}
              </option>
            ))}
          </select>
        </label>
      </Card>
      <RestrictionSection title="Household allergies" label="Strictly exclude" placeholder="e.g. peanuts" kind="allergy" tone="danger" items={items.filter((item) => item.kind === 'allergy')} disabled={saving} onAdd={add} onRemove={remove} />
      <RestrictionSection title="Ingredient exclusions" label="Never use" placeholder="e.g. shellfish" kind="exclude" tone="danger" items={items.filter((item) => item.kind === 'exclude')} disabled={saving} onAdd={add} onRemove={remove} />
      <RestrictionSection title="Food preferences" label="Prefer" placeholder="e.g. curries or traybakes" kind="prefer" tone="warm" items={items.filter((item) => item.kind === 'prefer')} disabled={saving} onAdd={add} onRemove={remove} />
      <RestrictionSection title="Dislikes" label="Prefer not to use" placeholder="e.g. olives" kind="dislike" items={items.filter((item) => item.kind === 'dislike')} disabled={saving} onAdd={add} onRemove={remove} />
    </SettingsLayout>
  )
}

function RestrictionSection({ title, label, placeholder, kind, tone, items, disabled, onAdd, onRemove }: { title: string; label: string; placeholder: string; kind: BackendRestriction['kind']; tone?: 'danger' | 'warm'; items: BackendRestriction[]; disabled: boolean; onAdd: (kind: BackendRestriction['kind'], value: string) => Promise<void>; onRemove: (item: BackendRestriction) => Promise<void> }) {
  const [draft, setDraft] = useState('')
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    await onAdd(kind, draft)
    setDraft('')
  }
  return (
    <Card className="settings-section">
      <h3>{title}</h3>
      <form className="form-inline" onSubmit={submit}>
        <label className="grow">
          {label}
          <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={placeholder} />
        </label>
        <Button disabled={disabled || !draft.trim()}>Add</Button>
      </form>
      <div className="tag-row">
        {items.map((item) => (
          <button type="button" disabled={disabled} className={`tag${tone ? ` tag--${tone}` : ''}`} key={item.id} onClick={() => onRemove(item)} aria-label={`Remove ${item.value}`}>
            {item.value} ×
          </button>
        ))}
      </div>
      {!items.length && <p className="muted">Nothing added yet.</p>}
    </Card>
  )
}

export function AppearanceSettings({ theme, setTheme }: { theme: ThemeChoice; setTheme: (theme: ThemeChoice) => void }) {
  return (
    <SettingsLayout>
      <div className="settings-heading">
        <div>
          <h2>Appearance</h2>
          <p>Use the device setting or choose a theme for Slop.</p>
        </div>
      </div>
      <div className="theme-cards">
        {(
          [
            ['system', 'System', Network],
            ['light', 'Light', Sun],
            ['dark', 'Dark', Moon],
          ] as const
        ).map(([value, label, Icon]) => (
          <button key={value} className={theme === value ? 'active' : ''} onClick={() => setTheme(value)}>
            <div className={`theme-preview theme-preview--${value}`}>
              <div />
              <span />
              <span />
            </div>
            <div>
              <Icon />
              <strong>{label}</strong>
              {theme === value && <Badge tone="green">Active</Badge>}
            </div>
          </button>
        ))}
      </div>
    </SettingsLayout>
  )
}

export function DataSettings() {
  const queryClient = useQueryClient()
  const session = useQuery({ queryKey: ['session'], queryFn: api.me })
  const isOwner = session.data?.role === 'owner'
  const status = useQuery({
    queryKey: ['backup-status'],
    queryFn: api.backupStatus,
  })
  const archives = useQuery({
    queryKey: ['restore-archives'],
    queryFn: api.restoreArchives,
    enabled: isOwner,
  })
  const [running, setRunning] = useState(false)
  const [restoreArchive, setRestoreArchive] = useState('')
  const [restorePreview, setRestorePreview] = useState<BackendRestorePreview | null>(null)
  const [restoreComponents, setRestoreComponents] = useState<RestoreComponent[]>(['recipes', 'ingredients'])
  const [previewing, setPreviewing] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const backup = async () => {
    setRunning(true)
    setError('')
    setMessage('')
    try {
      await api.createBackup()
      await queryClient.invalidateQueries({ queryKey: ['backup-status'] })
      setMessage('The backup completed and its archive was verified.')
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The backup could not be created.')
    } finally {
      setRunning(false)
    }
  }
  const inspectRestore = async (archive = restoreArchive, sourceHouseholdId?: string) => {
    if (!archive) return
    setPreviewing(true)
    setError('')
    setMessage('')
    try {
      const result = await api.previewRestore(archive, sourceHouseholdId)
      setRestoreArchive(result.archive)
      setRestorePreview(result)
      setRestoreComponents((current) => {
        const available = new Set(result.components.map((component) => component.key))
        const retained = current.filter((component) => available.has(component))
        return retained.length ? retained : result.components.some((component) => component.key === 'recipes') ? ['recipes', 'ingredients'] : [result.components[0]?.key ?? 'recipes']
      })
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The backup could not be inspected.')
      setRestorePreview(null)
    } finally {
      setPreviewing(false)
    }
  }
  const toggleRestoreComponent = (key: RestoreComponent) => {
    setRestoreComponents((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key])
  }
  const restoreSelected = async () => {
    if (!restorePreview || !restoreComponents.length) return
    if (!window.confirm('Import the selected data into this household? Existing matching records will be kept.')) return
    setRestoring(true)
    setError('')
    setMessage('')
    try {
      const result = await api.restoreSelected(restorePreview.archive, restoreComponents, restorePreview.selected_household.id)
      await queryClient.invalidateQueries()
      const imported = Object.entries(result.imported).map(([key, count]) => `${count} ${key.replaceAll('_', ' ')}`).join(' · ')
      setMessage(imported ? `Imported ${imported}. Existing matching records were kept.` : 'Nothing new was imported; matching records were already present.')
      setRestorePreview(null)
      await queryClient.invalidateQueries({ queryKey: ['restore-archives'] })
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The selected data could not be restored.')
    } finally {
      setRestoring(false)
    }
  }
  const last = status.data?.last_backup
  return (
    <SettingsLayout>
      <div className="settings-heading">
        <div>
          <h2>Data & backup</h2>
          <p>Protect your local household data and export it when needed.</p>
        </div>
        <Button disabled={running} onClick={backup}>
          <Download />
          {running ? 'Backing up…' : 'Back up now'}
        </Button>
      </div>
      {error && (
        <Notice tone="warning" title="Backup failed">
          {error}
        </Notice>
      )}
      {message && (
        <Notice tone="success" title="Backup complete">
          {message}
        </Notice>
      )}
      <Card className="settings-section">
        <div className="backup-status">
          <HardDrive />
          <div>
            <strong>Last backup</strong>
            <span>{last ? `${last} · ${status.data?.tier ?? 'archive'}` : 'No backup has been created yet'}</span>
          </div>
          <Badge tone={last ? 'green' : 'default'}>{last ? 'Healthy' : 'Not run'}</Badge>
        </div>
      </Card>
      <Card className="settings-section">
        <h3>Retention</h3>
        <p>14 daily · 8 weekly · 12 monthly backups</p>
        <Notice tone="warning" title="Keep a second copy">
          Unraid parity is not a backup. Copy archives to another physical device.
        </Notice>
      </Card>
      {isOwner && (
        <Card className="settings-section restore-card">
          <div className="restore-heading">
            <div>
              <span className="eyebrow">Migration tool</span>
              <h3>Restore selected data</h3>
              <p>Bring recipes and household lists into this installation without replacing your login or encrypted settings.</p>
            </div>
            <Archive aria-hidden />
          </div>
          <div className="restore-selector">
            <label htmlFor="restore-archive">Backup archive</label>
            <div className="restore-selector-row">
              <select id="restore-archive" value={restoreArchive} onChange={(event) => { setRestoreArchive(event.target.value); setRestorePreview(null) }}>
                <option value="">Choose a backup folder…</option>
                {(archives.data?.archives ?? []).map((archive) => (
                  <option key={archive.archive} value={archive.archive}>{archive.timestamp} · {archive.tier}</option>
                ))}
              </select>
              <Button variant="secondary" disabled={!restoreArchive || previewing} onClick={() => inspectRestore()}>
                <Upload />
                {previewing ? 'Reading archive…' : 'Inspect archive'}
              </Button>
            </div>
            {!archives.isLoading && !archives.data?.archives.length && (
              <small className="muted">No database archives are available under the configured /backups folder.</small>
            )}
          </div>
          {restorePreview && (
            <div className="restore-workspace">
              {restorePreview.households.length > 1 && (
                <label className="restore-household-select">
                  Source household
                  <select value={restorePreview.selected_household.id} onChange={(event) => inspectRestore(restorePreview.archive, event.target.value)} disabled={previewing}>
                    {restorePreview.households.map((household) => <option key={household.id} value={household.id}>{household.name}</option>)}
                  </select>
                </label>
              )}
              <div className="restore-preview-banner">
                <div>
                  <strong>{restorePreview.selected_household.name}</strong>
                  <span>{restorePreview.archive} · {restorePreview.files.data_archive ? 'application files included' : 'database only'}</span>
                </div>
                <LockKeyhole aria-hidden />
              </div>
              <div className="restore-component-grid">
                {restorePreview.components.map((component) => (
                  <RestoreComponentCard key={component.key} component={component} selected={restoreComponents.includes(component.key)} onToggle={() => toggleRestoreComponent(component.key)} />
                ))}
              </div>
              <Notice tone="warning" title="Safe merge">
                Active sessions and encrypted API credentials are never imported. Matching records stay in place; only missing records are added.
              </Notice>
              <div className="button-row restore-actions">
                <Button disabled={restoring || !restoreComponents.length} onClick={restoreSelected}>
                  <Check />
                  {restoring ? 'Restoring…' : `Restore ${restoreComponents.length} selected`}
                </Button>
                <Button variant="ghost" disabled={restoring} onClick={() => setRestorePreview(null)}>Cancel</Button>
              </div>
            </div>
          )}
        </Card>
      )}
    </SettingsLayout>
  )
}

function RestoreComponentCard({ component, selected, onToggle }: { component: BackendRestoreComponent; selected: boolean; onToggle: () => void }) {
  const summary = Object.entries(component.counts).map(([key, count]) => `${count} ${key.replaceAll('_', ' ')}`).join(' · ')
  return (
    <label className={`restore-component ${selected ? 'selected' : ''}`}>
      <input type="checkbox" checked={selected} onChange={onToggle} />
      <span className="restore-component-check" aria-hidden>{selected && <Check />}</span>
      <span className="restore-component-copy">
        <strong>{component.label}</strong>
        <small>{component.description}</small>
        <em>{summary || 'Nothing found'}</em>
      </span>
    </label>
  )
}

export function SystemSettings() {
  const queryClient = useQueryClient()
  const session = useQuery({ queryKey: ['session'], queryFn: api.me })
  const isOwner = session.data?.role === 'owner'
  const integration = useQuery({
    queryKey: ['usda-integration'],
    queryFn: api.usdaIntegration,
    enabled: isOwner,
  })
  const [apiKey, setApiKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const saveKey = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setError('')
    setMessage('')
    try {
      await api.saveUsdaIntegration(apiKey.trim())
      setApiKey('')
      await queryClient.invalidateQueries({ queryKey: ['usda-integration'] })
      setMessage('The USDA API key is saved and ready to use.')
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The API key could not be saved.')
    } finally {
      setSaving(false)
    }
  }
  const removeKey = async () => {
    setSaving(true)
    setError('')
    setMessage('')
    try {
      await api.removeUsdaIntegration()
      await queryClient.invalidateQueries({ queryKey: ['usda-integration'] })
      setMessage('The saved key was removed. Slop will use the server configuration instead.')
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The API key could not be removed.')
    } finally {
      setSaving(false)
    }
  }
  const source = integration.data?.source
  const configured = integration.data?.configured ?? false
  const statusLabel = source === 'saved' ? 'Connected' : source === 'environment' ? 'Server key' : 'Key needed'
  return (
    <SettingsLayout>
      <div className="settings-heading">
        <div>
          <h2>System</h2>
          <p>Health, datasets and optional integrations for this installation.</p>
        </div>
        <Button variant="secondary" onClick={() => window.location.reload()}>
          <RefreshCw />
          Refresh status
        </Button>
      </div>
      <div className="system-grid">
        <StatusCard icon={<Server />} title="Application" value="Healthy" detail="v0.1.0 · schema current" />
        <StatusCard icon={<Database />} title="PostgreSQL" value="Connected" detail="Local household database" />
        <StatusCard icon={<RefreshCw />} title="Workers" value="Online" detail="Imports and maintenance" />
        <StatusCard icon={<Shield />} title="Network" value="Local only" detail="Allowed hosts configured" />
      </div>
      <Card className="settings-section">
        <h3>Nutrition datasets</h3>
        <div className="system-row">
          <div>
            <strong>UK CoFID</strong>
            <span>Optional bulk-imported generic foods</span>
          </div>
          <Badge>Not bundled</Badge>
        </div>
        <div className="system-row">
          <div>
            <strong>USDA FoodData Central</strong>
            <span>Real generic food records cached on demand</span>
          </div>
          <Badge tone={configured ? 'green' : 'warning'}>{isOwner && integration.isLoading ? 'Checking…' : isOwner ? statusLabel : 'Owner managed'}</Badge>
        </div>
        <div className="system-row">
          <div>
            <strong>Open Food Facts</strong>
            <span>Identified packaged products only</span>
          </div>
          <Badge>Available by provider</Badge>
        </div>
      </Card>
      <Card className="settings-section integration-card">
        <div className="settings-heading">
          <div>
            <p className="eyebrow">Ingredient search integration</p>
            <h3 className="integration-title">
              USDA FoodData Central{' '}
              <span className="integration-help" tabIndex={0} aria-label="About the USDA API key" data-tooltip="Slop encrypts the key using this installation's secret key. The saved value is never sent back to your browser or displayed again.">
                <KeyRound aria-hidden="true" />
              </span>
            </h3>
            <p>Use your own free key for reliable general ingredient and nutrition searches.</p>
          </div>
          <Badge tone={configured ? 'green' : 'warning'}>{statusLabel}</Badge>
        </div>
        {!isOwner ? (
          <Notice tone="info" title="Owner setting">
            Only a household owner can change integration credentials.
          </Notice>
        ) : (
          <>
            {error && (
              <Notice tone="warning" title="Could not save key">
                {error}
              </Notice>
            )}
            {message && (
              <Notice tone="success" title="Integration updated">
                {message}
              </Notice>
            )}
            {!configured && (
              <Notice tone="warning" title={source === 'demo' ? 'Shared demo quota' : 'General search needs a key'}>
                Without a private key, FoodData Central searches may be unavailable or quickly reach the shared demo limit.
              </Notice>
            )}
            <form className="integration-key-form" onSubmit={saveKey}>
              <label className="grow">
                {source === 'saved' ? 'Replace API key' : 'API key'}
                <input type="password" required minLength={8} maxLength={200} autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Paste your USDA API key" />
                <small className="field-help">Stored encrypted. For security, Slop will not display it after saving.</small>
              </label>
              <Button disabled={saving || apiKey.trim().length < 8}>
                <KeyRound />
                {saving ? 'Saving…' : source === 'saved' ? 'Replace key' : 'Save key'}
              </Button>
            </form>
            <div className="integration-footer">
              <a className="source-link" href={USDA_KEY_SIGNUP_URL} target="_blank" rel="noreferrer">
                Get a free USDA API key <ExternalLink />
              </a>
              {source === 'saved' && (
                <Button variant="ghost" disabled={saving} onClick={() => void removeKey()}>
                  Remove saved key
                </Button>
              )}
              {source === 'environment' && <small>Currently supplied by the server environment.</small>}
            </div>
          </>
        )}
      </Card>
      <Card className="settings-section">
        <div className="settings-heading">
          <div>
            <h3>OpenClaw extraction bridge</h3>
            <p>Optional fallback after deterministic import fails.</p>
          </div>
          <Badge>Disabled</Badge>
        </div>
        <Button variant="secondary" disabled>
          <KeyRound />
          Configure connection
        </Button>
      </Card>
    </SettingsLayout>
  )
}

function StatusCard({ icon, title, value, detail }: { icon: ReactNode; title: string; value: string; detail: string }) {
  return (
    <Card className="status-card">
      <span>{icon}</span>
      <div>
        <small>{title}</small>
        <strong>{value}</strong>
        <p>{detail}</p>
      </div>
      <i />
    </Card>
  )
}
