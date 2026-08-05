import { createContext, useContext, useEffect, useMemo, useState } from 'react'

type Theme = 'light' | 'dark' | 'system'
type Resolved = 'light' | 'dark'

interface ThemeCtx {
  theme: Theme
  resolved: Resolved
  setTheme: (t: Theme) => void
  toggle: () => void
}

const Ctx = createContext<ThemeCtx | null>(null)
const STORAGE_KEY = 'mcc-theme'

function systemPref(): Resolved {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(
    () => (localStorage.getItem(STORAGE_KEY) as Theme) || 'system',
  )
  const [resolved, setResolved] = useState<Resolved>(() =>
    theme === 'system' ? systemPref() : theme,
  )

  useEffect(() => {
    const apply = () => {
      const r = theme === 'system' ? systemPref() : theme
      setResolved(r)
      document.documentElement.setAttribute('data-theme', r)
    }
    apply()
    if (theme === 'system') {
      const mq = window.matchMedia('(prefers-color-scheme: dark)')
      mq.addEventListener('change', apply)
      return () => mq.removeEventListener('change', apply)
    }
  }, [theme])

  const value = useMemo<ThemeCtx>(() => ({
    theme,
    resolved,
    setTheme: (t) => { localStorage.setItem(STORAGE_KEY, t); setThemeState(t) },
    toggle: () => {
      const next = resolved === 'dark' ? 'light' : 'dark'
      localStorage.setItem(STORAGE_KEY, next); setThemeState(next)
    },
  }), [theme, resolved])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTheme() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
