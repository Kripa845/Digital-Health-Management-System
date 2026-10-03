/**
 * HealthVitalsCard
 * ─────────────────
 * The patient's health cards, built from GET /dashboard/. Every value, status
 * (Low / Normal / High), history point and trend comes from the server; this
 * component only displays them.
 */

import { Link } from 'react-router-dom'
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, ChevronRight, Droplets, FlaskConical, Heart,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/misc'
import { formatDate } from '@/lib/utils'
import type { DashboardTest } from '@/lib/types'
import { useDashboard } from '@/features/lab-reports/hooks'
import { ResultStatusBadge } from '@/features/lab-reports/LabStatusBadge'
import { TrendChart } from '@/features/lab-reports/TrendChart'

const MAIN_TESTS = ['hemoglobin', 'cholesterol_total', 'blood_sugar_random']
// Labels whose letter case carries meaning ("HbA1C") are shown as written, not in capitals.
const KEEP_CASE = ['hba1c']
const labelCase = (test: string) => (KEEP_CASE.includes(test) ? 'normal-case' : 'uppercase')

function TrendIcon({ trend }: { trend: DashboardTest['trend'] }) {
  if (!trend) return null
  const Icon = trend === 'up' ? ArrowUpRight : trend === 'down' ? ArrowDownRight : ArrowRight
  const label = trend === 'up' ? 'Rising' : trend === 'down' ? 'Falling' : 'Stable'
  return (
    <span className="inline-flex items-center text-xs text-muted-foreground" title={label}>
      <Icon className="size-3.5" aria-hidden="true" /><span className="sr-only">{label}</span>
    </span>
  )
}

function Value({ value, unit }: { value?: string | number | null; unit?: string }) {
  if (value == null || value === '') return <span className="text-xl font-bold text-muted-foreground/40">—</span>
  return (
    <span className="flex items-baseline gap-1">
      <span className="text-2xl font-bold leading-tight tabular-nums">{value}</span>
      {unit && <span className="text-xs text-muted-foreground">{unit}</span>}
    </span>
  )
}

/** A main lab card: latest value, date, status badge and trend chart. */
function LabCard({ test }: { test: DashboardTest }) {
  return (
    <section aria-label={test.label} className="flex flex-col gap-2 rounded-[var(--radius-lg)] border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-2">
        <h3 className={`text-[11px] font-medium ${labelCase(test.test)} tracking-wide text-subtle-foreground`}>{test.label}</h3>
        <ResultStatusBadge status={test.status} severe={test.severe} />
      </div>
      <div className="flex items-center gap-2">
        <Value value={test.latest?.value} unit={test.latest ? test.unit : undefined} />
        <TrendIcon trend={test.trend} />
      </div>
      <p className="text-[11px] text-muted-foreground">
        {test.latest
          ? test.latest.date ? `Report of ${formatDate(test.latest.date)}` : 'Entered by your care team'
          : 'Not recorded yet'}
        {test.reference && ` · normal ${test.reference}`}
      </p>
      {test.latest && <TrendChart test={test} />}
    </section>
  )
}

/** A compact tile for the other values. */
function SmallTile({ test }: { test: DashboardTest }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-3 py-2.5">
      <div className="min-w-0">
        <p className={`truncate text-[11px] font-medium ${labelCase(test.test)} tracking-wide text-subtle-foreground`}>{test.label}</p>
        <p className="text-sm font-semibold tabular-nums">
          {test.latest ? `${test.latest.value} ${test.unit}` : <span className="text-muted-foreground/50">—</span>}
        </p>
      </div>
      <div className="flex items-center gap-1.5">
        <TrendIcon trend={test.trend} />
        <ResultStatusBadge status={test.status} severe={test.severe} />
      </div>
    </div>
  )
}

export function HealthVitalsCard() {
  const { data, isLoading, isError, refetch } = useDashboard()

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-surface-2/40 px-5 py-3.5">
        <div className="flex items-center gap-2.5">
          <span className="grid size-7 place-items-center rounded-[var(--radius-sm)] bg-primary-soft text-primary">
            <Activity className="size-4" aria-hidden="true" />
          </span>
          <h2 className="text-sm font-semibold">Health vitals</h2>
        </div>
        <Link
          to="/patient/lab-reports/upload"
          className="flex items-center gap-1 rounded-[var(--radius-sm)] px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary-soft/40"
        >
          <FlaskConical className="size-3" aria-hidden="true" />Upload lab report<ChevronRight className="size-3" aria-hidden="true" />
        </Link>
      </div>

      <CardContent className="space-y-5 p-5">
        {isLoading && (
          <div className="grid gap-3 sm:grid-cols-3" aria-busy="true" aria-label="Loading health vitals">
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-40 rounded-[var(--radius-lg)]" />)}
          </div>
        )}

        {isError && (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-3 text-sm">
            <p className="text-muted-foreground">Your health vitals could not be loaded.</p>
            <Button size="sm" variant="secondary" onClick={() => refetch()}>Retry</Button>
          </div>
        )}

        {data && (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-[var(--radius-md)] border border-border bg-surface px-3 py-2.5">
                <p className="text-[11px] font-medium uppercase tracking-wide text-subtle-foreground">Age</p>
                <p className="text-lg font-bold tabular-nums">{data.age != null ? `${data.age} yrs` : '—'}</p>
              </div>
              <div className="rounded-[var(--radius-md)] border border-border bg-surface px-3 py-2.5">
                <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-subtle-foreground">
                  <Droplets className="size-3 text-danger" aria-hidden="true" />Blood group
                </p>
                <p className="text-lg font-bold">{data.blood_group ?? '—'}</p>
              </div>
              <div className="rounded-[var(--radius-md)] border border-border bg-surface px-3 py-2.5">
                <p className="text-[11px] font-medium uppercase tracking-wide text-subtle-foreground">Height · Weight</p>
                <p className="text-sm font-semibold tabular-nums">
                  {data.body.height ? `${Number(data.body.height)} cm` : '—'} · {data.body.weight ? `${Number(data.body.weight)} kg` : '—'}
                </p>
              </div>
              <div className="flex items-center justify-between rounded-[var(--radius-md)] border border-border bg-surface px-3 py-2.5">
                <div>
                  <p className="text-[11px] font-medium uppercase tracking-wide text-subtle-foreground">BMI</p>
                  <p className="text-lg font-bold tabular-nums">{data.body.bmi ?? '—'}</p>
                </div>
                <ResultStatusBadge status={data.body.bmi_status} severe={data.body.bmi_severe} />
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-3">
              {data.tests.filter((t) => MAIN_TESTS.includes(t.test)).map((t) => <LabCard key={t.test} test={t} />)}
            </div>

            <div>
              <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-subtle-foreground">
                <Heart className="size-3.5" aria-hidden="true" />More results
              </p>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {data.tests.filter((t) => !MAIN_TESTS.includes(t.test)).map((t) => <SmallTile key={t.test} test={t} />)}
              </div>
            </div>

            {!data.tests.some((t) => t.latest) && (
              <p className="text-sm text-muted-foreground">
                No lab results yet.{' '}
                <Link to="/patient/lab-reports/upload" className="font-medium text-primary underline">Upload a lab report</Link>{' '}
                to fill in your cards.
              </p>
            )}

            <p className="border-t border-border pt-3 text-[11px] italic text-muted-foreground">{data.disclaimer}</p>
          </>
        )}
      </CardContent>
    </Card>
  )
}
