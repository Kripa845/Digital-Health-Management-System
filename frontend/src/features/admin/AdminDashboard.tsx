import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  LayoutDashboard, Users, Stethoscope, CalendarDays, ShieldCheck, TrendingUp,
  ArrowRight, UserPlus, ScrollText, Settings, Sparkles,
} from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { UserAvatar } from '@/components/ui/avatar'
import { Tooltip } from '@/components/ui/misc'
import {
  PageHeader, StatCard, StatCardSkeleton, DataState, EmptyState, SectionTitle,
} from '@/components/patterns'
import { ActiveStatusBadge } from '@/components/status-badge'
import { authService } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import type { AdminStats } from '@/lib/types'

const QUICK_LINKS = [
  { to: '/admin/patients', icon: Users, label: 'Manage patients' },
  { to: '/admin/doctors', icon: Stethoscope, label: 'Manage doctors' },
  { to: '/admin/audit', icon: ScrollText, label: 'Inspect audit log' },
  { to: '/admin/settings', icon: Settings, label: 'Admin settings' },
]

export function AdminDashboard() {
  const statsQ = useQuery({
    queryKey: ['admin', 'stats'],
    queryFn: () => authService.adminStats(),
  })
  const stats: AdminStats | undefined = statsQ.data

  const chart = stats?.registration_chart ?? []
  const dayTotal = (d: { patients: number; doctors: number }) => d.patients + d.doctors
  const maxCount = Math.max(1, ...chart.map(dayTotal))

  return (
    <div className="space-y-8">
      <PageHeader
        title="System overview"
        description="A live snapshot of registrations, care teams, and activity across Mero Care Card."
        icon={LayoutDashboard}
        actions={
          <>
            <Button asChild variant="secondary"><Link to="/admin/doctors"><UserPlus className="size-4" />Add doctor</Link></Button>
            <Button asChild><Link to="/admin/patients"><UserPlus className="size-4" />Add patient</Link></Button>
          </>
        }
      />

      {/* Primary stats */}
      {statsQ.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCardSkeleton /><StatCardSkeleton /><StatCardSkeleton /><StatCardSkeleton />
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Total patients" value={stats?.total_patients ?? '—'} icon={Users} tone="primary" hint={`${stats?.today_registrations ?? 0} registered today`} />
          <StatCard label="Total doctors" value={stats?.total_doctors ?? '—'} icon={Stethoscope} tone="info" hint={`${stats?.active_users ?? 0} active accounts`} />
          <StatCard label="Administrators" value={stats?.total_admins ?? '—'} icon={ShieldCheck} tone="success" hint="System moderators" />
          <StatCard label="Total users" value={stats?.total_users ?? '—'} icon={CalendarDays} tone="neutral" hint={`${stats?.inactive_users ?? 0} inactive`} />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1.7fr_1fr]">
        {/* Registration chart */}
        <Card className="p-5 sm:p-6">
          <SectionTitle className="mb-5">
            <span className="flex items-center gap-2">
              <TrendingUp className="size-4 text-primary" />
              Registrations · last 7 days
            </span>
          </SectionTitle>
          <DataState
            isLoading={statsQ.isLoading}
            isError={statsQ.isError}
            isEmpty={chart.length === 0}
            onRetry={() => statsQ.refetch()}
            skeleton={<div className="h-52 animate-pulse rounded-[var(--radius-md)] bg-surface-2" />}
            empty={<EmptyState icon={TrendingUp} title="No registration data yet" />}
          >
            <div className="flex h-52 items-end justify-between gap-2 border-b border-border pb-2">
              {chart.map((d) => {
                const total = dayTotal(d)
                const pct = (total / maxCount) * 100
                return (
                  <Tooltip key={d.date} content={`${total} registration${total === 1 ? '' : 's'} (${d.patients} patient${d.patients === 1 ? '' : 's'}, ${d.doctors} doctor${d.doctors === 1 ? '' : 's'}) · ${formatDate(d.date)}`}>
                    <div className="flex h-full flex-1 cursor-default flex-col items-center justify-end gap-1.5">
                      <span className="text-xs font-semibold tabular-nums text-muted-foreground">{total}</span>
                      <div
                        className="w-full max-w-10 rounded-t-[var(--radius-sm)] bg-primary transition-all hover:bg-primary-hover"
                        style={{ height: `${Math.max(4, pct)}%` }}
                      />
                    </div>
                  </Tooltip>
                )
              })}
            </div>
            <div className="mt-2 flex justify-between gap-2">
              {chart.map((d) => (
                <span key={d.date} className="flex-1 text-center text-[0.68rem] font-medium text-subtle-foreground">
                  {formatDate(d.date, { month: 'short', day: 'numeric' })}
                </span>
              ))}
            </div>
          </DataState>
        </Card>

        {/* Quick links */}
        <Card className="p-5 sm:p-6">
          <SectionTitle className="mb-4">Quick links</SectionTitle>
          <div className="space-y-2">
            {QUICK_LINKS.map((q) => (
              <Link
                key={q.to}
                to={q.to}
                className="flex items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-3.5 py-2.5 text-sm font-medium transition-colors hover:bg-surface-2"
              >
                <q.icon className="size-4.5 text-primary" />
                <span className="flex-1">{q.label}</span>
                <ArrowRight className="size-4 text-subtle-foreground" />
              </Link>
            ))}
            <Link
              to="/admin/recommendations"
              className="flex items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-3.5 py-2.5 text-sm font-medium transition-colors hover:bg-surface-2"
            >
              <Sparkles className="size-4.5 text-primary" />
              <span className="flex-1">Recommendation history</span>
              <ArrowRight className="size-4 text-subtle-foreground" />
            </Link>
          </div>
        </Card>
      </div>

      {/* Recent patients & doctors */}
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="space-y-3">
          <SectionTitle action={<Button asChild variant="link" size="sm"><Link to="/admin/patients">View all</Link></Button>}>
            Recent patients
          </SectionTitle>
          <DataState
            isLoading={statsQ.isLoading}
            isError={statsQ.isError}
            isEmpty={(stats?.recent_patients ?? []).length === 0}
            onRetry={() => statsQ.refetch()}
            empty={<EmptyState icon={Users} title="No patients yet" />}
          >
            <Card className="divide-y divide-border">
              {(stats?.recent_patients ?? []).map((p) => (
                <div key={p.id} className="flex items-center gap-3.5 p-3.5">
                  <UserAvatar name={`${p.first_name} ${p.last_name}`} src={p.photo} className="size-10" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">{p.first_name} {p.last_name}</p>
                    <p className="truncate font-mono text-xs text-muted-foreground">{p.patient_id}</p>
                  </div>
                  <ActiveStatusBadge status={p.status} />
                </div>
              ))}
            </Card>
          </DataState>
        </section>

        <section className="space-y-3">
          <SectionTitle action={<Button asChild variant="link" size="sm"><Link to="/admin/doctors">View all</Link></Button>}>
            Recent doctors
          </SectionTitle>
          <DataState
            isLoading={statsQ.isLoading}
            isError={statsQ.isError}
            isEmpty={(stats?.recent_doctors ?? []).length === 0}
            onRetry={() => statsQ.refetch()}
            empty={<EmptyState icon={Stethoscope} title="No doctors yet" />}
          >
            <Card className="divide-y divide-border">
              {(stats?.recent_doctors ?? []).map((d) => (
                <div key={d.id} className="flex items-center gap-3.5 p-3.5">
                  <UserAvatar name={`${d.first_name} ${d.last_name}`} src={d.photo} className="size-10" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">Dr. {d.first_name} {d.last_name}</p>
                    <p className="truncate text-xs text-muted-foreground">{d.department}</p>
                  </div>
                  <ActiveStatusBadge status={d.status} />
                </div>
              ))}
            </Card>
          </DataState>
        </section>
      </div>
    </div>
  )
}
