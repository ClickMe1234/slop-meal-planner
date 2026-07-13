import { Bell, ChevronRight, Database, Download, HardDrive, KeyRound, Moon, Network, RefreshCw, Server, Shield, Sun, UserRound, Users } from 'lucide-react'
import { ReactNode, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Badge, Button, Card, Notice, PageHeader, Segmented } from '../components/ui'
import type { ThemeChoice } from '../types'

const nav = [
  { to:'/settings', label:'Household', icon:Users, end:true },
  { to:'/settings/targets', label:'Targets & meals', icon:UserRound },
  { to:'/settings/preferences', label:'Preferences', icon:Bell },
  { to:'/settings/appearance', label:'Appearance', icon:Moon },
  { to:'/settings/data', label:'Data & backup', icon:Database },
  { to:'/settings/system', label:'System', icon:Server }
]

function SettingsLayout({children}: {children:ReactNode}) {
  return <div className="page"><PageHeader eyebrow="Savour" title="Settings" description="Household profiles, planning defaults and this local installation."/><div className="settings-layout"><nav className="settings-nav" aria-label="Settings sections">{nav.map(({to,label,icon:Icon,end})=><NavLink key={to} to={to} end={end}><Icon/>{label}<ChevronRight/></NavLink>)}</nav><section className="settings-content">{children}</section></div></div>
}

export function HouseholdSettings() {
  return <SettingsLayout><div className="settings-heading"><div><h2>Household</h2><p>People who share recipes, plans, pantry stock and shopping lists.</p></div><Button>+ Add person</Button></div><div className="member-cards"><Card><div className="settings-member"><span>Z</span><div><strong>Zach</strong><small>Owner · linked login</small></div><Badge tone="green">2,000 kcal</Badge><Button variant="ghost">Edit</Button></div></Card><Card><div className="settings-member"><span>M</span><div><strong>Maya</strong><small>Collaborator · linked login</small></div><Badge tone="green">1,700 kcal</Badge><Button variant="ghost">Edit</Button></div></Card></div><Card className="settings-section"><h3>Planning defaults</h3><label className="switch-row"><span><strong>Reserve allowance for unplanned meals</strong><small>Eating-out calories are not redistributed automatically.</small></span><input type="checkbox" defaultChecked/></label><label className="switch-row"><span><strong>Quarter-serving portions</strong><small>People can receive different portions of a shared recipe.</small></span><input type="checkbox" defaultChecked/></label><label>Default planning period<select defaultValue="7"><option value="7">7 days</option><option value="5">5 days</option><option value="14">14 days</option></select></label></Card></SettingsLayout>
}

export function TargetSettings() {
  const[mode,setMode]=useState<'calorie'|'macros'>('calorie')
  return <SettingsLayout><div className="settings-heading"><div><h2>Targets & meal allocation</h2><p>Targets are user supplied. Savour does not assess whether they are medically suitable.</p></div><Button>Save changes</Button></div><Card className="settings-section"><h3>Zach's targets</h3><label>Planning mode<Segmented value={mode} onChange={setMode} label="Target mode" options={[{value:'calorie',label:'Calories'},{value:'macros',label:'Macros'}]}/></label>{mode==='calorie'?<div className="form-grid"><label>Daily calories<input type="number" defaultValue="2000"/></label><label>Hard tolerance<div className="input-suffix"><input type="number" defaultValue="5"/><span>%</span></div></label></div>:<div className="form-grid form-grid--3"><label>Protein<input type="number" defaultValue="130"/></label><label>Carbohydrate<input type="number" defaultValue="225"/></label><label>Fat<input type="number" defaultValue="67"/></label></div>}<Notice title="How calories and macros work">Choose one target mode. In calorie mode, optional macro minimums and maximums are hard guardrails. 4/4/9 is used only to validate those bounds.</Notice></Card><Card className="settings-section"><h3>Meal allocation</h3><div className="allocation-list allocation-list--compact">{[['Breakfast',25],['Lunch',30],['Dinner',35],['Snacks',10]].map(([name,value])=><label key={name}><span>{name}</span><div className="input-suffix"><input type="number" defaultValue={value}/><span>%</span></div></label>)}</div></Card></SettingsLayout>
}

export function PreferenceSettings() {
  return <SettingsLayout><div className="settings-heading"><div><h2>Preferences & restrictions</h2><p>Allergies are hard exclusions. Preferences only influence recipe ranking.</p></div><Button>Save changes</Button></div><Card className="settings-section"><h3>Household allergies</h3><label>Strictly exclude<input placeholder="Search an ingredient…"/></label><div className="tag-row"><span className="tag tag--danger">Peanuts ×</span></div></Card><Card className="settings-section"><h3>Food preferences</h3><label>Prefer<input placeholder="Add cuisine, ingredient or recipe style…"/></label><div className="tag-row"><span className="tag tag--warm">Curries ×</span><span className="tag tag--warm">Traybakes ×</span></div><label>Dislike<input placeholder="Add ingredient or recipe style…"/></label></Card></SettingsLayout>
}

export function AppearanceSettings({theme,setTheme}:{theme:ThemeChoice;setTheme:(theme:ThemeChoice)=>void}) {
  return <SettingsLayout><div className="settings-heading"><div><h2>Appearance</h2><p>Use the device setting or choose a theme for Savour.</p></div></div><div className="theme-cards">{([['system','System',Network],['light','Light',Sun],['dark','Dark',Moon]] as const).map(([value,label,Icon])=><button key={value} className={theme===value?'active':''} onClick={()=>setTheme(value)}><div className={`theme-preview theme-preview--${value}`}><div/><span/><span/></div><div><Icon/><strong>{label}</strong>{theme===value&&<Badge tone="green">Active</Badge>}</div></button>)}</div></SettingsLayout>
}

export function DataSettings() {
  return <SettingsLayout><div className="settings-heading"><div><h2>Data & backup</h2><p>Protect your local household data and export it when needed.</p></div><Button><Download/>Back up now</Button></div><Card className="settings-section"><div className="backup-status"><HardDrive/><div><strong>Last backup</strong><span>Today at 03:00 · verified successfully</span></div><Badge tone="green">Healthy</Badge></div></Card><Card className="settings-section"><h3>Retention</h3><p>14 daily · 8 weekly · 12 monthly backups</p><Notice tone="warning" title="Keep a second copy">Unraid parity is not a backup. Copy archives to another physical device.</Notice></Card></SettingsLayout>
}

export function SystemSettings() {
  return <SettingsLayout><div className="settings-heading"><div><h2>System</h2><p>Health, datasets and optional integrations for this installation.</p></div><Button variant="secondary"><RefreshCw/>Refresh status</Button></div><div className="system-grid"><StatusCard icon={<Server/>} title="Application" value="Healthy" detail="v0.1.0 · schema current"/><StatusCard icon={<Database/>} title="PostgreSQL" value="Connected" detail="12 ms · 1.2 GB"/><StatusCard icon={<RefreshCw/>} title="Workers" value="2 online" detail="0 queued · 0 failed"/><StatusCard icon={<Shield/>} title="Network" value="LAN only" detail="Allowed hosts configured"/></div><Card className="settings-section"><h3>Nutrition datasets</h3><div className="system-row"><div><strong>UK CoFID</strong><span>Primary generic foods · release 2021</span></div><Badge tone="green">Active</Badge><Button variant="ghost">Check updates</Button></div><div className="system-row"><div><strong>USDA FoodData Central</strong><span>Fallback generic foods</span></div><Badge tone="green">Connected</Badge><Button variant="ghost">Test</Button></div><div className="system-row"><div><strong>Open Food Facts</strong><span>Identified packaged products only</span></div><Badge tone="green">Connected</Badge><Button variant="ghost">Test</Button></div></Card><Card className="settings-section"><div className="settings-heading"><div><h3>OpenClaw extraction bridge</h3><p>Optional fallback after deterministic import fails.</p></div><Badge>Disabled</Badge></div><label className="switch-row"><span><strong>Enable OpenClaw</strong><small>Requires a separately administered, restricted LAN agent.</small></span><input type="checkbox"/></label><Button variant="secondary" disabled><KeyRound/>Configure connection</Button></Card></SettingsLayout>
}

function StatusCard({icon,title,value,detail}:{icon:ReactNode;title:string;value:string;detail:string}) { return <Card className="status-card"><span>{icon}</span><div><small>{title}</small><strong>{value}</strong><p>{detail}</p></div><i/></Card> }
