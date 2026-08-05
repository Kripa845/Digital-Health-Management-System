import { useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { Menu, X, LogOut, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuth } from '@/lib/auth'
import { session } from '@/lib/api'
import { Wordmark } from '@/components/brand'
import { ThemeToggle } from '@/components/theme-toggle'
import { NotificationsBell } from '@/components/notifications-bell'
import { NAV, ROLE_LABEL } from '@/components/nav-config'
import { UserAvatar } from '@/components/ui/avatar'
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import type { Role } from '@/lib/types'

function SidebarNav({ role, onNavigate }: { role: Role; onNavigate?: () => void }) {
  return (
    <nav className="flex flex-1 flex-col gap-6 overflow-y-auto px-3 py-4">
      {NAV[role].map((sectionData, i) => (
        <div key={i} className="space-y-1">
          {sectionData.heading && (
            <p className="px-3 pb-1 text-[0.68rem] font-semibold uppercase tracking-wider text-subtle-foreground">
              {sectionData.heading}
            </p>
          )}
          {sectionData.items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  'group flex items-center gap-3 rounded-[var(--radius-md)] px-3 py-2.5 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary-soft text-primary-soft-foreground'
                    : 'text-muted-foreground hover:bg-surface-2 hover:text-foreground',
                )
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon className={cn('size-4.5 shrink-0', isActive ? 'text-primary' : 'text-subtle-foreground group-hover:text-foreground')} />
                  {item.label}
                </>
              )}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  )
}

function UserMenu() {
  const { user, logout } = useAuth()
  const name = session.name || user?.username || 'User'
  const role = (user?.role ?? session.role) as Role
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex items-center gap-2 rounded-full p-1 pr-2 transition-colors hover:bg-surface-2 outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
          <UserAvatar name={name} src={user?.doctor_profile?.photo || user?.patient_profile?.photo} className="size-8" />
          <span className="hidden text-left sm:block">
            <span className="block text-sm font-medium leading-tight max-w-[9rem] truncate">{name}</span>
            <span className="block text-[11px] leading-tight text-subtle-foreground">{role && ROLE_LABEL[role]}</span>
          </span>
          <ChevronDown className="hidden size-4 text-muted-foreground sm:block" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>
          <span className="block text-sm font-medium text-foreground normal-case">{name}</span>
          <span className="block truncate text-xs font-normal text-subtle-foreground">{user?.email}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem destructive onSelect={logout}>
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { role } = useAuth()
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const effectiveRole = (role ?? session.role ?? 'PATIENT') as Role

  return (
    <div className="min-h-dvh bg-background">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-border bg-surface lg:flex">
        <div className="flex h-16 items-center px-5">
          <NavLink to={`/${effectiveRole.toLowerCase()}/dashboard`}><Wordmark /></NavLink>
        </div>
        <SidebarNav role={effectiveRole} />
        <div className="border-t border-border p-3">
          <p className="px-3 py-1 text-[11px] text-subtle-foreground">
            Mero Care Card · Secure health records
          </p>
        </div>
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[85%] flex-col border-r border-border bg-surface animate-in slide-in-from-left duration-200">
            <div className="flex h-16 items-center justify-between px-5">
              <Wordmark />
              <button onClick={() => setMobileOpen(false)} className="rounded-md p-1.5 text-muted-foreground hover:bg-surface-2" aria-label="Close menu">
                <X className="size-5" />
              </button>
            </div>
            <SidebarNav role={effectiveRole} onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      {/* Main column */}
      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-3 border-b border-border glass px-4 sm:px-6">
          <div className="flex items-center gap-2">
            <button onClick={() => setMobileOpen(true)} className="rounded-md p-2 text-muted-foreground hover:bg-surface-2 lg:hidden" aria-label="Open menu">
              <Menu className="size-5" />
            </button>
            <div className="flex items-center gap-2 lg:hidden">
              <Wordmark size="sm" />
            </div>
          </div>
          <div className="flex items-center gap-1 sm:gap-2">
            <ThemeToggle />
            <NotificationsBell />
            <div className="mx-1 h-6 w-px bg-border" />
            <UserMenu />
          </div>
        </header>

        <main key={location.pathname} className="mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-8 animate-fade-up">
          {children}
        </main>
      </div>
    </div>
  )
}
