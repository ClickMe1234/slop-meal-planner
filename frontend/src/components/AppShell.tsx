import { CalendarDays, ChefHat, ClipboardList, Heart, LogOut, Menu, Moon, PackageOpen, Settings, Sun, WandSparkles, Wheat, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, isDemoMode } from '../api/client'
import { clearOfflineShoppingData } from '../lib/offlineShopping'
import type { ThemeChoice } from '../types'

const items = [
  { to: '/week', label: 'Week', icon: CalendarDays },
  { to: '/plan', label: 'Plan', icon: WandSparkles },
  { to: '/recipes', label: 'Recipes', icon: ChefHat },
  { to: '/ingredients', label: 'Ingredients', icon: Wheat },
  { to: '/pantry', label: 'Pantry', icon: PackageOpen },
  { to: '/shopping', label: 'Shopping', icon: ClipboardList }
]

export function AppShell({ theme, setTheme }: { theme: ThemeChoice; setTheme: (theme: ThemeChoice) => void }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [logoutError, setLogoutError] = useState('')
  const [loggingOut, setLoggingOut] = useState(false)
  const session = useQuery({ queryKey: ['session'], queryFn: api.me, enabled: !isDemoMode, retry: false })
  const username = session.data?.username ?? 'Zach'
  const role = session.data?.role ?? 'owner'
  const nextTheme: ThemeChoice = theme === 'dark' ? 'light' : 'dark'
  const currentItem = items.find(item => location.pathname.startsWith(item.to))
  useEffect(() => {
    document.body.classList.toggle('nav-is-open', menuOpen)
    return () => document.body.classList.remove('nav-is-open')
  }, [menuOpen])
  const logout = async () => {
    if (loggingOut) return
    try {
      setLogoutError('')
      setLoggingOut(true)
      let result: { redirect_url: string | null } = { redirect_url: null }
      if (!isDemoMode) {
        result = (await api.logout()) ?? { redirect_url: null }
        await queryClient.cancelQueries()
        queryClient.clear()
        await clearOfflineShoppingData()
      }
      localStorage.removeItem('slop-demo-session')
      if (result.redirect_url) window.location.assign(result.redirect_url)
      else navigate('/login')
    } catch {
      setLogoutError('Sign out could not be confirmed. You are still signed in; check your connection and try again.')
    } finally { setLoggingOut(false) }
  }
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <aside className={`sidebar ${menuOpen ? 'sidebar--open' : ''}`}>
      <div className="brand"><div className="brand-mark"><Heart size={20} fill="currentColor" /></div><div><strong>Slop</strong><span>meal planner</span></div></div>
      <button className="mobile-close" aria-label="Close navigation" onClick={() => setMenuOpen(false)}><X /></button>
      <nav aria-label="Primary navigation">{items.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} onClick={() => setMenuOpen(false)} className={({ isActive }) => isActive ? 'active' : ''}><Icon size={20} /><span>{label}</span></NavLink>)}</nav>
      <div className="sidebar-bottom">
        <NavLink to="/settings" className={location.pathname.startsWith('/settings') ? 'active' : ''}><Settings size={20} /><span>Settings</span></NavLink>
        <button className="theme-shortcut" onClick={() => setTheme(nextTheme)} aria-label={`Use ${nextTheme} theme`}>{theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}<span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span></button>
        {logoutError && <p className="field-error" role="alert">{logoutError}</p>}
        <div className="profile-chip"><span>{username.slice(0, 1).toUpperCase()}</span><div><strong>{username}</strong><small>Household {role}</small></div><button type="button" aria-label="Sign out" disabled={loggingOut} onClick={logout}>{loggingOut ? '…' : <LogOut size={16}/>}</button></div>
      </div>
    </aside>
    {menuOpen && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}
    <div className="app-main">
      <div className="mobile-topbar"><button aria-label="Open account and navigation" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}><Menu /></button><div className="mobile-context"><span>{currentItem?.label ?? 'Slop'}</span><strong>Slop</strong></div><NavLink to="/settings" aria-label="Settings"><Settings /></NavLink></div>
      <main id="main-content"><Outlet /></main>
    </div>
    <nav className="bottom-nav" aria-label="Mobile navigation">{items.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} className={({ isActive }) => isActive ? 'active' : ''}><Icon size={21} /><span>{label}</span></NavLink>)}</nav>
  </div>
}
