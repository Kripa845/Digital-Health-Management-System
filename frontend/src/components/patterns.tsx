import * as React from 'react'
import { cn } from '@/lib/utils'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/misc'
import { Button } from '@/components/ui/button'
import type { LucideIcon } from 'lucide-react'
import { Inbox, AlertCircle } from 'lucide-react'

// ── Page header ───────────────────────────────────────────────────────
export function PageHeader({
  title, description, icon: Icon, actions, className,
}: {
  title: string
  description?: string
  icon?: LucideIcon
  actions?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between', className)}>
      <div className="flex items-start gap-3.5">
        {Icon && (
          <span className="mt-0.5 grid size-11 shrink-0 place-items-center rounded-[var(--radius-md)] bg-primary-soft text-primary-soft-foreground">
            <Icon className="size-5.5" />
          </span>
        )}
        <div className="space-y-1">
          <h1 className="font-display text-2xl font-semibold tracking-tight sm:text-[1.7rem]">{title}</h1>
          {description && <p className="text-sm text-muted-foreground max-w-2xl text-pretty">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

// ── Stat card ─────────────────────────────────────────────────────────
export function StatCard({
  label, value, icon: Icon, hint, tone = 'primary', trend, className,
}: {
  label: string
  value: React.ReactNode
  icon?: LucideIcon
  hint?: string
  tone?: 'primary' | 'info' | 'success' | 'warning' | 'danger' | 'neutral'
  trend?: { value: string; up?: boolean }
  className?: string
}) {
  const toneMap: Record<string, string> = {
    primary: 'bg-primary-soft text-primary-soft-foreground',
    info: 'bg-info-soft text-info',
    success: 'bg-success-soft text-success',
    warning: 'bg-warning-soft text-warning',
    danger: 'bg-danger-soft text-danger',
    neutral: 'bg-surface-2 text-muted-foreground',
  }
  return (
    <Card className={cn('p-5 transition-shadow hover:shadow-[var(--shadow-md)]', className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1.5">
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
          <p className="font-display text-3xl font-semibold tabular leading-none">{value}</p>
          {hint && <p className="text-xs text-subtle-foreground">{hint}</p>}
        </div>
        {Icon && (
          <span className={cn('grid size-11 place-items-center rounded-[var(--radius-md)]', toneMap[tone])}>
            <Icon className="size-5.5" />
          </span>
        )}
      </div>
      {trend && (
        <p className={cn('mt-3 text-xs font-medium', trend.up ? 'text-success' : 'text-muted-foreground')}>
          {trend.value}
        </p>
      )}
    </Card>
  )
}

// ── Empty state ───────────────────────────────────────────────────────
export function EmptyState({
  icon: Icon = Inbox, title, description, action, className,
}: {
  icon?: LucideIcon
  title: string
  description?: string
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-3 rounded-[var(--radius-lg)] border border-dashed border-border-strong bg-surface/50 px-6 py-14 text-center', className)}>
      <span className="grid size-14 place-items-center rounded-full bg-surface-2 text-muted-foreground">
        <Icon className="size-7" />
      </span>
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        {description && <p className="text-sm text-muted-foreground max-w-sm mx-auto text-pretty">{description}</p>}
      </div>
      {action}
    </div>
  )
}

// ── Async data state wrapper ──────────────────────────────────────────
export function DataState({
  isLoading, isError, isEmpty, onRetry, skeleton, empty, children,
}: {
  isLoading?: boolean
  isError?: boolean
  isEmpty?: boolean
  onRetry?: () => void
  skeleton?: React.ReactNode
  empty?: React.ReactNode
  children: React.ReactNode
}) {
  if (isLoading) return <>{skeleton ?? <ListSkeleton />}</>
  if (isError)
    return (
      <EmptyState
        icon={AlertCircle}
        title="Something went wrong"
        description="We couldn't load this just now. Please try again."
        action={onRetry && <Button variant="secondary" size="sm" onClick={onRetry}>Retry</Button>}
      />
    )
  if (isEmpty) return <>{empty ?? <EmptyState title="Nothing here yet" />}</>
  return <>{children}</>
}

export function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <Skeleton className="size-11 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-1/3" />
            <Skeleton className="h-3 w-1/2" />
          </div>
          <Skeleton className="h-7 w-20 rounded-full" />
        </div>
      ))}
    </div>
  )
}

export function StatCardSkeleton() {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <Skeleton className="h-3.5 w-24" />
          <Skeleton className="h-8 w-16" />
        </div>
        <Skeleton className="size-11 rounded-[var(--radius-md)]" />
      </div>
    </Card>
  )
}

// ── Labelled info row (profile detail) ────────────────────────────────
export function InfoRow({ label, value, mono }: { label: string; value?: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs font-medium uppercase tracking-wide text-subtle-foreground">{label}</dt>
      <dd className={cn('text-sm font-medium', mono && 'font-mono')}>{value ?? '—'}</dd>
    </div>
  )
}

// ── Section title ─────────────────────────────────────────────────────
export function SectionTitle({ children, className, action }: { children: React.ReactNode; className?: string; action?: React.ReactNode }) {
  return (
    <div className={cn('flex items-center justify-between gap-3', className)}>
      <h2 className="text-sm font-semibold uppercase tracking-wide text-subtle-foreground">{children}</h2>
      {action}
    </div>
  )
}
