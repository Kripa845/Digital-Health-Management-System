import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth, homePathFor } from '@/lib/auth'
import { session } from '@/lib/api'
import type { Role } from '@/lib/types'
import { Logo } from '@/components/brand'

function FullScreenLoader() {
  return (
    <div className="grid min-h-dvh place-items-center bg-background">
      <div className="flex flex-col items-center gap-4">
        <Logo className="size-12 animate-pulse" />
        <p className="text-sm text-muted-foreground">Loading your care space…</p>
      </div>
    </div>
  )
}

/** Requires any authenticated user; enforces mandatory password change. */
export function PrivateRoute() {
  const { loading, isAuthenticated } = useAuth()
  const location = useLocation()

  if (loading) return <FullScreenLoader />
  if (!isAuthenticated) return <Navigate to="/login" replace state={{ from: location }} />
  if (session.mustChangePassword && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />
  }
  return <Outlet />
}

/** Restricts a subtree to a specific role. */
export function RoleRoute({ role }: { role: Role }) {
  const { role: current, loading } = useAuth()
  if (loading) return <FullScreenLoader />
  if (current !== role) return <Navigate to={homePathFor(current)} replace />
  return <Outlet />
}

/** For pages (login) that should redirect authenticated users home. */
export function PublicOnlyRoute() {
  const { isAuthenticated, role, loading } = useAuth()
  if (loading) return <FullScreenLoader />
  if (isAuthenticated && !session.mustChangePassword) return <Navigate to={homePathFor(role)} replace />
  return <Outlet />
}
