import { useEffect, useState } from 'react'
import type { ThemeChoice } from '../types'

const storageKey = 'savour-theme'

function applyTheme(choice: ThemeChoice) {
  const systemPrefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
  const dark = choice === 'dark' || (choice === 'system' && systemPrefersDark)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
}

export function useTheme() {
  const [theme, setThemeState] = useState<ThemeChoice>(() => (localStorage.getItem(storageKey) as ThemeChoice | null) ?? 'system')

  useEffect(() => {
    applyTheme(theme)
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    const listener = () => theme === 'system' && applyTheme(theme)
    media?.addEventListener('change', listener)
    return () => media?.removeEventListener('change', listener)
  }, [theme])

  const setTheme = (next: ThemeChoice) => {
    localStorage.setItem(storageKey, next)
    setThemeState(next)
  }

  return { theme, setTheme }
}
