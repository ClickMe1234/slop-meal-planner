import { CalendarDays, ChefHat, ClipboardList, Heart, LogOut, Menu, Moon, PackageOpen, Settings, Sun, WandSparkles, X } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, isDemoMode } from '../api/client'
import type { ThemeChoice } from '../types'

const items = [
  { to: '/week', label: 'Week', icon: CalendarDays },
  { to: '/plan', label: 'Plan', icon: WandSparkles },
  { to: '/recipes', label: 'Recipes', icon: ChefHat },
  { to: '/pantry', label: 'Pantry', icon: PackageOpen },
  { to: '/shopping', label: 'Shopping', icon: ClipboardList }
]

export function AppShell({ theme, setTheme }: { theme: ThemeChoice; setTheme: (theme: ThemeChoice) => void }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const session = useQuery({ queryKey: ['session'], queryFn: api.me, enabled: !isDemoMode, retry: false })
  const username = session.data?.username ?? 'Zach'
  const role = session.data?.role ?? 'owner'
  const nextTheme: ThemeChoice = theme === 'dark' ? 'light' : 'dark'
  const logout = async () => {
    if (!isDemoMode) await api.logout()
    localStorage.removeItem('savour-demo-session')
    navigate('/login')
  }
  return <div className="app-shell">
    <aside className={`sidebar ${menuOpen ? 'sidebar--open' : ''}`}>
      <div className="brand"><div className="brand-mark"><Heart size={20} fill="currentColor" /></div><div><strong>Savour</strong><span>meal planner</span></div></div>
      <button className="mobile-close" aria-label="Close navigation" onClick={() => setMenuOpen(false)}><X /></button>
      <nav aria-label="Primary navigation">{items.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} onClick={() => setMenuOpen(false)} className={({ isActive }) => isActive ? 'active' : ''}><Icon size={20} /><span>{label}</span></NavLink>)}</nav>
      <div className="sidebar-bottom">
        <NavLink to="/settings" className={location.pathname.startsWith('/settings') ? 'active' : ''}><Settings size={20} /><span>Settings</span></NavLink>
        <button className="theme-shortcut" onClick={() => setTheme(nextTheme)} aria-label={`Use ${nextTheme} theme`}>{theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}<span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span></button>
        <div className="profile-chip"><span>{username.slice(0, 1).toUpperCase()}</span><div><strong>{username}</strong><small>Household {role}</small></div><button type="button" aria-label="Sign out" onClick={logout}><LogOut size={16}/></button></div>
      </div>
    </aside>
    {menuOpen && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}
    <div className="app-main">
      <div className="mobile-topbar"><button aria-label="Open navigation" onClick={() => setMenuOpen(true)}><Menu /></button><div className="brand"><div className="brand-mark"><Heart size={17} fill="currentColor" /></div><strong>Savour</strong></div><NavLink to="/settings" aria-label="Settings"><Settings /></NavLink></div>
      <main id="main-content"><Outlet /></main>
    </div>
    <nav className="bottom-nav" aria-label="Mobile navigation">{items.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} className={({ isActive }) => isActive ? 'active' : ''}><Icon size={21} /><span>{label}</span></NavLink>)}</nav>
  </div>
}
