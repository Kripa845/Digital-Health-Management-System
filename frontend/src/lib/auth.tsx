import { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { authService, session } from './api'
import type { CurrentUser, Role } from './types'

interface AuthState {
  user: CurrentUser | null
  role: Role | null
  loading: boolean
  isAuthenticated: boolean
  refresh: () => Promise<void>
  logout: () => void
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    if (!session.access) { setUser(null); setLoading(false); return }
    try {
      const me = await authService.me()
      setUser(me)
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const logout = useCallback(() => {
    authService.logout()
    setUser(null)
    window.location.href = '/login'
  }, [])

  const role = (user?.role ?? session.role ?? null) as Role | null

  return (
    <Ctx.Provider value={{
      user,
      role,
      loading,
      isAuthenticated: !!user || !!session.access,
      refresh,
      logout,
    }}>
      {children}
    </Ctx.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

// eslint-disable-next-line react-refresh/only-export-components
export function homePathFor(role?: Role | null) {
  switch (role) {
    case 'ADMIN': return '/admin/dashboard'
    case 'DOCTOR': return '/doctor/dashboard'
    case 'PATIENT': return '/patient/dashboard'
    default: return '/login'
  }
}
