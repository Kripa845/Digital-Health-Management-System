import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip as ChartTooltip, XAxis, YAxis,
} from 'recharts'
import {
  Activity, AlertTriangle, Check, CheckCircle2, ChevronDown, Info, Radar, Send, ShieldCheck, Siren, Users,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Field, Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Switch, Tooltip } from '@/components/ui/misc'
import { SimpleSelect } from '@/components/ui/select'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { PageHeader, DataState, ListSkeleton } from '@/components/patterns'
import { SUSPICIOUS_ALERTS_PATH } from '@/components/suspicious-alerts'
import { activityAnalysisService, activitySettingsService } from '@/lib/api'
import type { ActivityAnalysis, ActivityAnalysisParams, ActivityAnalysisUser, AnalysisAlert } from '@/lib/types'
import { formatDate } from '@/lib/utils'
import { cn } from '@/lib/utils'
import { apiError, tableHeadClass } from './admin-utils'
import {
  Z_THRESHOLD, activityTotals, beyondEps, compareToTypical, featureLabel, featureSpread, isLowActivity, kdistPoints,
  kindLabel, num, pct, plainReason, reasonCounts, roleNoun, signed, sortUsers, unusualUsers, zBars, zDomain,
} from './activity-analysis-utils'

const PRIMARY = 'var(--color-primary)'
const DANGER = 'var(--color-danger)'
const MUTED = 'var(--color-muted-foreground)'
const SURFACE = 'var(--color-surface)'
const GRID = 'var(--color-border)'
const AXIS_TICK = { fontSize: 11, fill: 'var(--color-subtle-foreground)' }
const TOOLTIP_STYLE = {
  fontSize: 12, background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: 8,
}

const ROLE_OPTIONS = [
  { value: 'DOCTOR', label: 'Doctors' },
  { value: 'PATIENT', label: 'Patients' },
  { value: 'ADMIN', label: 'Administrators' },
]

const PERIOD_OPTIONS = [
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
]
const DEFAULT_PERIOD = '30'
const LONGEST_PERIOD = 90

type Form = {
  role: ActivityAnalysisParams['role']
  period: string
  /** Advanced: overrides period when filled in. */
  customDays: string
  eps: string
  min_samples: string
  /** Advanced: the admin edited eps or min_samples, so use them instead of the automatic values. */
  manual: boolean
}

const INITIAL_FORM: Form = { role: 'DOCTOR', period: DEFAULT_PERIOD, customDays: '', eps: '', min_samples: '', manual: false }
const INITIAL_PARAMS: ActivityAnalysisParams = { role: 'DOCTOR', days: Number(DEFAULT_PERIOD), demo: false, auto: true }

const formDays = (f: Form) => Number(f.customDays.trim() || f.period)

function kindVariant(kind: ActivityAnalysisUser['kind']) {
  return kind === 'noise' ? 'danger' : kind === 'border' ? 'info' : kind === 'core' ? 'primary' : 'neutral'
}

/** Lines a table's first and last columns up with the card's own padding. */
const TABLE_EDGES = '[&_tr>*:first-child]:pl-5 sm:[&_tr>*:first-child]:pl-6 [&_tr>*:last-child]:pr-5 sm:[&_tr>*:last-child]:pr-6'
const CELL = 'px-4 py-2.5'

// ── Small building blocks ─────────────────────────────────────────────

/** A titled block of the page; every section uses the same heading and gap. */
function PageSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4">
      <h2 className="font-display text-lg font-semibold">{title}</h2>
      {children}
    </section>
  )
}

function LabelWithTip({ htmlFor, label, tip }: { htmlFor: string; label: string; tip: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      <Tooltip content={<span className="block max-w-60">{tip}</span>}>
        <button type="button" aria-label={`About ${label}`}
          className="rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60">
          <Info className="size-3.5" />
        </button>
      </Tooltip>
    </div>
  )
}

/** A button that shows or hides the section below it. */
function Disclosure({ open, onToggle, controls, children, className }: {
  open: boolean
  onToggle: () => void
  controls: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <button type="button" aria-expanded={open} aria-controls={controls} onClick={onToggle}
      className={cn('flex items-center gap-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground', className)}>
      <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} />
      {children}
    </button>
  )
}

// ── Form: role, period, Analyse (+ advanced settings) ─────────────────

function Controls({
  form, setForm, demo, setDemo, onRun, running, dirty, lastRun,
}: {
  form: Form
  setForm: (f: Form) => void
  demo: boolean
  setDemo: (v: boolean) => void
  onRun: () => void
  running: boolean
  dirty: boolean
  lastRun?: ActivityAnalysis
}) {
  const [advanced, setAdvanced] = useState(false)
  const set = (k: keyof Form, v: string) => setForm({ ...form, [k]: v })
  const setParam = (k: 'eps' | 'min_samples', v: string) => setForm({ ...form, [k]: v, manual: true })
  return (
    <Card>
      <CardContent className="p-5 sm:p-6">
        <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); onRun() }}>
          <div className="grid items-end gap-4 sm:grid-cols-[minmax(0,14rem)_minmax(0,14rem)_auto]">
            <div className="flex flex-col gap-2">
              <LabelWithTip htmlFor="aa-role" label="Role"
                tip="Which group to check. People are only compared with others in the same role." />
              <SimpleSelect id="aa-role" value={form.role} options={ROLE_OPTIONS} onValueChange={(v) => set('role', v)} />
            </div>
            <div className="flex flex-col gap-2">
              <LabelWithTip htmlFor="aa-period" label="Period"
                tip="How far back to look. A longer period includes more people, which makes the comparison fairer." />
              <SimpleSelect id="aa-period" value={form.period} options={PERIOD_OPTIONS}
                onValueChange={(v) => setForm({ ...form, period: v, customDays: '' })} />
            </div>
            <Button type="submit" loading={running} className="sm:w-fit"><Radar className="size-4" />Analyse</Button>
          </div>
          {dirty && (
            <p className="text-sm text-warning" role="status">Press Analyse to update the results below.</p>
          )}

          <div className="border-t border-border pt-4">
            <Disclosure open={advanced} onToggle={() => setAdvanced(!advanced)} controls="aa-advanced">
              Advanced settings
            </Disclosure>
            {advanced && (
              <div id="aa-advanced" className="mt-4 space-y-5 rounded-[var(--radius-md)] border border-border bg-surface-2/50 p-5">
                <div className="grid gap-4 sm:grid-cols-3">
                  <Field label="Custom period (days)" htmlFor="aa-days" hint="Leave blank to use the Period above.">
                    <Input id="aa-days" type="number" min={1} max={365} value={form.customDays} placeholder={form.period}
                      onChange={(e) => set('customDays', e.target.value)} />
                  </Field>
                  <Field label="eps" htmlFor="aa-eps" hint="How close two users must be to count as similar.">
                    <Input id="aa-eps" type="number" step="any" min={0.01} max={100} value={form.eps}
                      onChange={(e) => setParam('eps', e.target.value)} />
                  </Field>
                  <Field label="min_samples" htmlFor="aa-min" hint="How many similar users make a normal group.">
                    <Input id="aa-min" type="number" min={2} max={100} value={form.min_samples}
                      onChange={(e) => setParam('min_samples', e.target.value)} />
                  </Field>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
                  {form.manual ? (
                    <p className="text-muted-foreground">
                      Using the eps and min_samples above.{' '}
                      <button type="button" className="font-medium text-primary hover:underline"
                        onClick={() => setForm({ ...form, manual: false })}>
                        Use automatic values
                      </button>
                    </p>
                  ) : (
                    <p className="text-muted-foreground">
                      Using automatic values picked from the data
                      {lastRun?.auto && !lastRun.skipped ? ` (last run: eps ${lastRun.eps}, min_samples ${lastRun.min_samples})` : ''}.
                      Edit eps or min_samples to use your own.
                    </p>
                  )}
                  <label className="flex items-center gap-2 text-muted-foreground" htmlFor="aa-demo">
                    <Switch id="aa-demo" checked={demo} onCheckedChange={setDemo} />
                    Demo data
                  </label>
                </div>
              </div>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

// ── Plain-language result ─────────────────────────────────────────────

function Banner({ tone, icon: Icon, children, action }: {
  tone: 'success' | 'danger' | 'warning' | 'info'
  icon: React.ComponentType<{ className?: string }>
  children: React.ReactNode
  action?: React.ReactNode
}) {
  const tones = {
    success: 'border-success/30 bg-success-soft text-success',
    danger: 'border-danger/30 bg-danger-soft text-danger',
    warning: 'border-warning/30 bg-warning-soft text-warning',
    info: 'border-info/30 bg-info-soft text-info',
  }
  return (
    <div role="status" className={cn('flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-lg)] border px-5 py-4', tones[tone])}>
      <p className="flex items-start gap-3 text-sm font-medium leading-relaxed"><Icon className="mt-0.5 size-4 shrink-0" />{children}</p>
      {action}
    </div>
  )
}

function NotEnoughActivity({ a }: { a: ActivityAnalysis }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 px-6 py-12 text-center sm:px-6 sm:py-12">
        <Users className="size-8 text-muted-foreground" />
        <p className="font-semibold">Not enough activity yet</p>
        <p className="max-w-md text-sm leading-relaxed text-muted-foreground">
          Fewer than {a.min_users} {roleNoun(a.role)} have used the system in the last {LONGEST_PERIOD} days, so there is
          nobody to compare them with yet. Check back once more {roleNoun(a.role)} are active.
        </p>
      </CardContent>
    </Card>
  )
}

function TooFewBanner({ a, manual, onTryLonger, onUseAuto }: {
  a: ActivityAnalysis
  manual: boolean
  onTryLonger: () => void
  onUseAuto: () => void
}) {
  const active = a.n_users === 0
    ? `No ${roleNoun(a.role)} were active`
    : `Only ${roleNoun(a.role, a.n_users)} ${a.n_users === 1 ? 'was' : 'were'} active`
  // Enough people for the automatic values, but the advanced settings ask for a bigger group.
  if (manual && a.n_users >= 6) {
    return (
      <Banner tone="warning" icon={AlertTriangle}
        action={<Button size="sm" variant="outline" onClick={onUseAuto}>Use automatic settings</Button>}>
        {active} in the last {a.days} days. Your advanced settings need at least {a.min_users} to compare fairly.
      </Banner>
    )
  }
  return (
    <Banner tone="warning" icon={AlertTriangle}
      action={a.days < LONGEST_PERIOD && (
        <Button size="sm" variant="outline" onClick={onTryLonger}>Try last {LONGEST_PERIOD} days</Button>
      )}>
      {active} in the last {a.days} days. We need at least {a.min_users} to compare fairly.
    </Banner>
  )
}

function ResultBanner({ a, shown, onSendAll, sending, canSend }: {
  a: ActivityAnalysis
  shown: number
  onSendAll: () => void
  sending: boolean
  canSend: boolean
}) {
  if (shown === 0) {
    return (
      <Banner tone="success" icon={CheckCircle2}>
        No unusual activity found among {roleNoun(a.role, a.n_users)}.
      </Banner>
    )
  }
  return (
    <Banner tone="danger" icon={AlertTriangle}
      action={shown > 1 && (
        <Button size="sm" variant="outline" onClick={onSendAll} loading={sending} disabled={!canSend}>
          <Send className="size-4" />Send all {shown} for review
        </Button>
      )}>
      {shown} of {roleNoun(a.role, a.n_users)} {shown === 1 ? 'has' : 'have'} unusual activity.
    </Banner>
  )
}

function UnusualUserCard({ a, user, alerted, sent, sending, canSend, onSend }: {
  a: ActivityAnalysis
  user: ActivityAnalysisUser
  alerted: boolean
  sent: boolean
  sending: boolean
  canSend: boolean
  onSend: () => void
}) {
  return (
    <Card className="flex flex-col">
      <div className="flex items-center gap-3 border-b border-border px-5 py-4">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-danger-soft text-danger">
          <AlertTriangle className="size-4" />
        </span>
        <p className="min-w-0 truncate font-semibold">{user.username}</p>
        {alerted && <Badge variant="danger" className="ml-auto shrink-0">Suspicious alert</Badge>}
      </div>
      <ul className="flex-1 space-y-2 p-5 text-sm leading-relaxed">
        {user.reasons.map((r) => <li key={r.feature}>{plainReason(r, a.role, a.days)}</li>)}
      </ul>
      <div className="border-t border-border px-5 py-4">
        <Button size="sm" variant={sent ? 'outline' : 'primary'}
          onClick={onSend} loading={sending} disabled={sent || !canSend}
          title={a.demo ? 'Demo users cannot be sent for review.' : undefined}>
          {sent ? <><Check className="size-4" />Sent for review</> : <><Send className="size-4" />Send for review</>}
        </Button>
      </div>
    </Card>
  )
}

// ── Suspicious alerts for this role and period ───────────────────────

const ALERT_FILTERS = [
  { value: 'all', label: 'All alerts' },
  { value: 'NEW', label: 'New' },
  { value: 'REVIEWED', label: 'Reviewed' },
  { value: 'DISMISSED', label: 'Dismissed' },
]
const alertVariant = (s: AnalysisAlert['status']) => (s === 'NEW' ? 'danger' : s === 'REVIEWED' ? 'success' : 'neutral')

/** One card per user with a suspicious alert (failed logins or a day unlike their normal ones) in the window. */
function SuspiciousAlertsSection({ a, unusualIds, sent, pending, canSend, onSend }: {
  a: ActivityAnalysis
  unusualIds: Set<number>
  sent: Set<number>
  pending: Set<number>
  canSend: boolean
  onSend: (id: number) => void
}) {
  const [filter, setFilter] = useState('all')
  const shown = a.suspicious_alerts.filter((x) => filter === 'all' || x.status === filter)
  const byUser = new Map<number, AnalysisAlert[]>()
  for (const x of shown) byUser.set(x.user_id, [...(byUser.get(x.user_id) ?? []), x])
  // Users with a NEW alert first.
  const hasNew = (xs: AnalysisAlert[]) => Number(xs.some((x) => x.status === 'NEW'))
  const users = [...byUser.entries()].sort(([, x], [, y]) => hasNew(y) - hasNew(x))
  const total = a.suspicious_alerts.length
  const newCount = a.suspicious_alerts.filter((x) => x.status === 'NEW').length

  return (
    <PageSection title="Suspicious alerts">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted-foreground">
          {total} alert{total === 1 ? '' : 's'} for {roleNoun(a.role)} in the last {a.days} days
          {newCount > 0 && <>, <span className="font-medium text-danger">{newCount} new</span></>}: repeated failed
          logins, or a day unlike the user&apos;s normal ones.
        </p>
        <div className="w-full sm:w-44">
          <SimpleSelect value={filter} onValueChange={setFilter} options={ALERT_FILTERS} />
        </div>
      </div>
      {users.length === 0 ? (
        <p className="rounded-[var(--radius-lg)] border border-dashed border-border px-5 py-8 text-center text-sm text-muted-foreground">
          No suspicious alerts match this filter.
        </p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {users.map(([userId, alerts]) => {
            const done = sent.has(userId)
            return (
              <Card key={userId} className="flex flex-col">
                <div className="flex items-center gap-3 border-b border-border px-5 py-4">
                  <span className="grid size-8 shrink-0 place-items-center rounded-full bg-danger-soft text-danger">
                    <Siren className="size-4" />
                  </span>
                  <div className="min-w-0">
                    <p className="truncate font-semibold">{alerts[0].full_name || alerts[0].username}</p>
                    <p className="truncate text-xs text-subtle-foreground">{alerts[0].username}</p>
                  </div>
                  {unusualIds.has(userId) && <Badge variant="danger" className="ml-auto shrink-0">Also stood out</Badge>}
                </div>
                <ul className="flex-1 space-y-3 p-5 text-sm leading-relaxed">
                  {alerts.map((x) => (
                    <li key={x.id} className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium tabular-nums">{formatDate(x.day)}</span>
                        <Badge variant={alertVariant(x.status)} dot={x.status === 'NEW'}>{x.status}</Badge>
                      </div>
                      <ul className="text-muted-foreground">
                        {x.reason.split('; ').map((r) => <li key={r}>{r}</li>)}
                      </ul>
                    </li>
                  ))}
                </ul>
                <div className="flex flex-wrap items-center gap-2 border-t border-border px-5 py-4">
                  <Button size="sm" variant={done ? 'outline' : 'primary'} onClick={() => onSend(userId)}
                    loading={pending.size === 1 && pending.has(userId)} disabled={done || !canSend}>
                    {done ? <><Check className="size-4" />Sent for review</> : <><Send className="size-4" />Send for review</>}
                  </Button>
                  <Button asChild size="sm" variant="ghost"><Link to={SUSPICIOUS_ALERTS_PATH}>Open alert page</Link></Button>
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </PageSection>
  )
}

// ── Summary of the run: headline numbers, how people were sorted, and why some stood out ─

const optPct = (x: number | null) => (x == null ? '—' : pct(x))
const people = (n: number) => `${n} ${n === 1 ? 'person' : 'people'}`

/** One bar split into typical / close to typical / stands out, with a 2px surface gap between segments. */
function GroupBar({ a }: { a: ActivityAnalysis }) {
  const parts = [
    { key: 'core', label: kindLabel('core'), n: a.counts.core, className: 'bg-primary', hint: 'behaves like many others' },
    { key: 'border', label: kindLabel('border'), n: a.counts.border, className: 'bg-primary/40', hint: 'a little different, still normal' },
    { key: 'noise', label: kindLabel('noise'), n: a.counts.noise, className: 'bg-danger', hint: 'not like anyone else' },
  ]
  const total = parts.reduce((t, p) => t + p.n, 0) || 1
  return (
    <div className="space-y-3">
      <div className="flex h-3 w-full gap-0.5 overflow-hidden rounded-full bg-surface-2" role="img"
        aria-label={parts.map((p) => `${p.label} ${p.n}`).join(', ')}>
        {parts.filter((p) => p.n > 0).map((p) => (
          <Tooltip key={p.key} content={`${p.label}: ${people(p.n)} (${pct(p.n / total)}) – ${p.hint}`}>
            <div className={cn('h-full first:rounded-l-full last:rounded-r-full', p.className)} style={{ width: `${(100 * p.n) / total}%` }} />
          </Tooltip>
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted-foreground">
        {parts.map((p) => (
          <li key={p.key} className="flex items-center gap-1.5">
            <span className={cn('size-2.5 rounded-full', p.className)} aria-hidden />
            {p.label}: <span className="tabular-nums text-foreground">{p.n}</span> ({pct(p.n / total)}) – {p.hint}
          </li>
        ))}
      </ul>
    </div>
  )
}

function SummaryTile({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    // Same layout in every tile: label on top, value below it, hint pinned to the bottom edge.
    <div className="flex h-full min-w-0 flex-col rounded-[var(--radius-md)] border border-border bg-surface-2/50 p-4">
      <p className="truncate text-xs font-medium text-muted-foreground" title={label}>{label}</p>
      <p className="mt-3 mb-4 flex items-baseline font-display text-2xl font-semibold tabular-nums leading-none">{value}</p>
      {hint && (
        <p className="mt-auto line-clamp-2 border-t border-border pt-3 text-xs leading-snug text-subtle-foreground" title={hint}>
          {hint}
        </p>
      )}
    </div>
  )
}

function AnalysisSummary({ a, unusual, quiet }: { a: ActivityAnalysis; unusual: ActivityAnalysisUser[]; quiet: number }) {
  const t = activityTotals(a)
  const reasons = reasonCounts(a, unusual)
  const spread = featureSpread(a, unusual)
  const grouped = a.counts.core + a.counts.border
  const one = roleNoun(a.role, 1).replace(/^1 /, '')
  return (
    <section className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Summary of the results</CardTitle>
          <CardDescription>
            Based on the activity of {roleNoun(a.role, a.n_users)}
            {a.demo ? ' (demo data)' : ` from ${formatDate(a.window_start)} to ${formatDate(lastDay(a.window_end))}`}.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid auto-rows-fr grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <SummaryTile label="People checked" value={a.n_users} hint={`Over the last ${a.days} days`} />
            <SummaryTile label="Groups of similar people" value={a.n_clusters}
              hint={`${grouped} of ${a.n_users} people behave like others in a group`} />
            <SummaryTile label="Stood out from the rest"
              value={<>{a.counts.noise}<span className="ml-1.5 text-sm font-medium text-muted-foreground">({pct(a.counts.noise / (a.n_users || 1))})</span></>}
              hint={`${unusual.length} to review, ${quiet} had too little activity to judge`} />
            <SummaryTile label={`Actions by a typical ${one}`} value={num(t.medianActions)}
              hint={`Active on about ${num(t.medianActiveDays)} days. Half did more, half did less.`} />
            <SummaryTile label="All actions" value={t.actions.toLocaleString()} hint="Added up for everyone" />
            <SummaryTile label="Done late at night" value={optPct(t.offHoursShare)} hint="Share of actions between 10 pm and 6 am" />
            <SummaryTile label="Record requests declined" value={optPct(t.deniedShare)}
              hint={`Out of ${t.requests.toLocaleString()} requests to see patient records`} />
            <SummaryTile label="Wrong-password sign-ins" value={t.failedLogins.toLocaleString()}
              hint={`${people(t.usersWithFailedLogins)} had at least one`} />
          </div>
          <div className="space-y-3 border-t border-border pt-6">
            <p className="text-sm font-medium">How people were sorted</p>
            <GroupBar a={a} />
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Why people stood out</CardTitle>
            <CardDescription>
              What made people stand out. One person can have several reasons.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {reasons.length === 0 ? (
              <p className="py-16 text-center text-sm text-muted-foreground">Nobody needs review, so there are no reasons to show.</p>
            ) : (
              <figure className="w-full" style={{ height: 48 + reasons.length * 36 }} role="img"
                aria-label={reasons.map((r) => `${r.label}: ${r.count}`).join(', ')}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={reasons} layout="vertical" margin={{ top: 4, right: 32, bottom: 4, left: 8 }} barCategoryGap={8}>
                    <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={false} />
                    <XAxis type="number" allowDecimals={false} domain={[0, unusual.length]} tick={AXIS_TICK} stroke={GRID} />
                    <YAxis type="category" dataKey="label" tick={{ ...AXIS_TICK, fill: MUTED }} width={150} stroke={GRID} />
                    <ChartTooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--color-surface-2)' }}
                      formatter={(n: number) => [`${n} of ${people(unusual.length)}`, 'People']} />
                    <Bar dataKey="count" fill={DANGER} radius={4} isAnimationActive={false} maxBarSize={18}>
                      <LabelList dataKey="count" position="right" style={{ fontSize: 11, fill: 'var(--color-foreground)' }} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </figure>
            )}
          </CardContent>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>Normal vs unusual activity</CardTitle>
            <CardDescription>
              What a typical {one} did in this period
              {unusual.length > 0 ? ', compared with the people who stood out.' : '.'}{' '}
              &ldquo;Typical&rdquo; is the middle value: half of the {roleNoun(a.role)} did more, half did less.
            </CardDescription>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className={cn('w-full text-sm', TABLE_EDGES)}>
              <thead className="border-y border-border bg-surface-2">
                <tr>
                  <th className={tableHeadClass()}>Activity</th>
                  <th className={tableHeadClass('text-right')}>Typical</th>
                  <th className={tableHeadClass('text-right')}>Busiest 10% did</th>
                  <th className={tableHeadClass('text-right')}>Highest</th>
                  {unusual.length > 0 && <th className={tableHeadClass('text-right')}>People who stood out</th>}
                  {unusual.length > 0 && <th className={tableHeadClass('text-right')}>Compared with typical</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-border tabular-nums">
                {spread.map((s) => (
                  <tr key={s.feature}>
                    <td className={cn(CELL, 'whitespace-nowrap')}>{s.label}</td>
                    <td className={cn(CELL, 'text-right')}>{num(s.median)}</td>
                    <td className={cn(CELL, 'whitespace-nowrap text-right')}>{num(s.p90)} or more</td>
                    <td className={cn(CELL, 'text-right')}>{num(s.max)}</td>
                    {unusual.length > 0 && <td className={cn(CELL, 'text-right')}>{num(s.unusualMedian ?? 0)}</td>}
                    {unusual.length > 0 && (
                      <td className={cn(CELL, 'whitespace-nowrap text-right',
                        ((s.ratio != null && s.ratio >= 2) || (s.median === 0 && (s.unusualMedian ?? 0) > 0)) && 'font-semibold text-danger')}>
                        {compareToTypical(s.unusualMedian, s.median)}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </section>
  )
}

/** The window ends at the next midnight, so its last whole day is the one before window_end. */
function lastDay(windowEnd: string) {
  return new Date(new Date(windowEnd).getTime() - 1)
}

// ── Map of everyone (a flat 2-D picture of the 7 counts) ─────────────

type Point = ActivityAnalysisUser & { selected: boolean; label: string }

/** Direct labels stay readable: the three people who stand out most plus the selected person. */
function labelledIds(a: ActivityAnalysis, selected?: number) {
  const top = sortUsers(a.users).filter((u) => u.kind === 'noise').slice(0, 3).map((u) => u.user_id)
  return new Set(selected == null ? top : [...top, selected])
}

function pointShape(kind: 'core' | 'border' | 'noise') {
  return function Shape(props: { cx?: number; cy?: number; payload?: Point }) {
    const { cx = 0, cy = 0, payload } = props
    const ring = payload?.selected ? <circle cx={cx} cy={cy} r={10} fill="none" stroke="var(--color-foreground)" strokeWidth={2} /> : null
    if (kind === 'noise') {
      const r = 7
      return (
        <g style={{ cursor: 'pointer' }}>
          {ring}
          <path d={`M${cx},${cy - r} L${cx + r},${cy + r * 0.8} L${cx - r},${cy + r * 0.8} Z`}
            fill={DANGER} stroke={SURFACE} strokeWidth={2} />
        </g>
      )
    }
    return (
      <g style={{ cursor: 'pointer' }}>
        {ring}
        <circle cx={cx} cy={cy} r={5.5}
          fill={kind === 'core' ? PRIMARY : SURFACE}
          stroke={kind === 'border' ? PRIMARY : SURFACE}
          strokeWidth={2} />
      </g>
    )
  }
}

function PointTooltip({ a, active, payload }: { a: ActivityAnalysis; active?: boolean; payload?: { payload: Point }[] }) {
  const p = payload?.[0]?.payload
  if (!active || !p) return null
  return (
    <div style={TOOLTIP_STYLE} className="space-y-0.5 px-3 py-2 shadow-[var(--shadow-md)]">
      <p className="font-medium">{p.username}</p>
      <p className="text-muted-foreground">{kindLabel(p.kind)}</p>
      {p.reasons[0] && <p className="max-w-60 text-danger">{plainReason(p.reasons[0], a.role, a.days)}</p>}
    </div>
  )
}

function ClusterScatter({ a, selected, onSelect }: { a: ActivityAnalysis; selected?: number; onSelect: (id: number) => void }) {
  const labelled = labelledIds(a, selected)
  const points: Point[] = a.users.map((u) => ({
    ...u, selected: u.user_id === selected, label: labelled.has(u.user_id) ? u.username : '',
  }))
  const series = [
    { kind: 'core' as const, data: points.filter((p) => p.kind === 'core') },
    { kind: 'border' as const, data: points.filter((p) => p.kind === 'border') },
    { kind: 'noise' as const, data: points.filter((p) => p.kind === 'noise') },
  ]
  const key = [
    { label: `${kindLabel('core')} (${a.counts.core})`, mark: <circle cx={6} cy={6} r={4.5} fill={PRIMARY} /> },
    { label: `${kindLabel('border')} (${a.counts.border})`, mark: <circle cx={6} cy={6} r={4} fill={SURFACE} stroke={PRIMARY} strokeWidth={2} /> },
    { label: `${kindLabel('noise')} (${a.counts.noise})`, mark: <path d="M6,1 L11.5,10.5 L0.5,10.5 Z" fill={DANGER} /> },
  ]
  return (
    <Card>
      <CardHeader>
        <CardTitle>Map of everyone</CardTitle>
        <CardDescription>
          Each dot is one person; red triangles stood out. Click a dot for details.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="mb-4 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted-foreground">
          {key.map((k) => (
            <li key={k.label} className="flex items-center gap-1.5"><svg className="size-3" viewBox="0 0 12 12" aria-hidden>{k.mark}</svg>{k.label}</li>
          ))}
        </ul>
        <figure className="h-80 w-full" role="img"
          aria-label={`Map of ${people(a.n_users)}: ${a.counts.core} typical, ${a.counts.border} close to typical, ${a.counts.noise} stand out.`}>
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 16, right: 16, bottom: 8, left: 16 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
              <XAxis type="number" dataKey="x" tick={false} stroke={GRID} />
              <YAxis type="number" dataKey="y" tick={false} stroke={GRID} width={8} />
              <ChartTooltip content={<PointTooltip a={a} />} cursor={{ strokeDasharray: '3 3', stroke: GRID }} />
              {series.map((s) => (
                <Scatter key={s.kind} name={kindLabel(s.kind)} data={s.data} shape={pointShape(s.kind)} isAnimationActive={false}
                  fill={s.kind === 'noise' ? DANGER : PRIMARY}
                  onClick={(p: { payload?: Point }) => p?.payload && onSelect(p.payload.user_id)}>
                  <LabelList dataKey="label" position="top" offset={12}
                    style={{ fontSize: 11, fill: 'var(--color-foreground)' }} />
                </Scatter>
              ))}
            </ScatterChart>
          </ResponsiveContainer>
        </figure>
      </CardContent>
    </Card>
  )
}

// ── How strict the check is (k-distance curve) ───────────────────────

function KDistanceChart({ a, onUseSuggested }: { a: ActivityAnalysis; onUseSuggested: () => void }) {
  const data = kdistPoints(a)
  const over = beyondEps(a)
  const s = a.suggested
  const differs = s != null && (s.min_samples !== a.min_samples || Math.abs(s.eps - a.eps) > 0.05)
  return (
    <Card>
      <CardHeader>
        <CardTitle>How strict the check is</CardTitle>
        <CardDescription>
          People above the red line ({over} of {data.length}) are too far from others to count as typical.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {data.length > 0 && (
          <ul className="flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted-foreground">
            <li className="flex items-center gap-1.5"><svg className="h-3 w-5" aria-hidden><line x1="0" y1="6" x2="20" y2="6" stroke={PRIMARY} strokeWidth={2} /></svg>Distance from similar people</li>
            <li className="flex items-center gap-1.5"><svg className="h-3 w-5" aria-hidden><line x1="0" y1="6" x2="20" y2="6" stroke={DANGER} strokeWidth={2} /></svg>Limit used ({a.eps})</li>
            {a.suggested_eps != null && (
              <li className="flex items-center gap-1.5"><svg className="h-3 w-5" aria-hidden><line x1="0" y1="6" x2="20" y2="6" stroke={MUTED} strokeWidth={2} strokeDasharray="5 4" /></svg>Suggested limit ({a.suggested_eps})</li>
            )}
          </ul>
        )}
        {data.length === 0 ? (
          <p className="py-16 text-center text-sm text-muted-foreground">Not enough people to draw this chart.</p>
        ) : (
          <figure className="h-64 w-full" role="img"
            aria-label={`Distance from similar people, from ${data[0].distance} to ${data[data.length - 1].distance}; limit used ${a.eps}${a.suggested_eps ? `, suggested ${a.suggested_eps}` : ''}.`}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 16, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="rank" tick={AXIS_TICK} stroke={GRID}
                  label={{ value: 'people, closest to furthest', position: 'insideBottomRight', offset: -4, fontSize: 11, fill: MUTED }} />
                <YAxis tick={AXIS_TICK} stroke={GRID} width={40} />
                <ChartTooltip contentStyle={TOOLTIP_STYLE}
                  formatter={(v: number) => [v.toFixed(2), 'Distance']} labelFormatter={(r) => `Person ${r}`} />
                <ReferenceLine y={a.eps} stroke={DANGER} strokeWidth={2} />
                {a.suggested_eps != null && (
                  <ReferenceLine y={a.suggested_eps} stroke={MUTED} strokeDasharray="5 4" />
                )}
                <Line type="monotone" dataKey="distance" stroke={PRIMARY} strokeWidth={2}
                  dot={{ r: 3 }} activeDot={{ r: 5 }} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </figure>
        )}
        {s != null && differs && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-md)] bg-surface-2 px-4 py-3 text-sm">
            <span className="text-muted-foreground">
              For {people(a.n_users)} we suggest a group size of at least{' '}
              <span className="font-medium text-foreground">{s.min_samples}</span> and a limit of{' '}
              <span className="font-medium text-foreground">{s.eps}</span>.
            </span>
            <Button size="sm" variant="outline" onClick={onUseSuggested}>Use suggested</Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── One person: why they stand out ───────────────────────────────────

function UserDetail({ a, user }: { a: ActivityAnalysis; user: ActivityAnalysisUser }) {
  const bars = zBars(user, a.features)
  const domain = zDomain(user, a.features)
  const typical = Object.fromEntries(featureSpread(a, []).map((s) => [s.feature, s.median]))
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle>{user.username}</CardTitle>
          <Badge variant={kindVariant(user.kind)}>{kindLabel(user.kind)}</Badge>
          {isLowActivity(user) && <Badge variant="neutral">Too little activity</Badge>}
        </div>
        <CardDescription>
          How far each activity is from a typical {roleNoun(a.role, 1).replace(/^1 /, '')}. 0 means typical. Bars past
          the dashed red lines ({Z_THRESHOLD} either way) are very unusual.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 lg:grid-cols-2">
        <figure className="h-64 w-full" role="img"
          aria-label={bars.map((b) => `${b.label} score ${b.z}`).join(', ')}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={bars} layout="vertical" margin={{ top: 4, right: 40, bottom: 4, left: 8 }} barCategoryGap={6}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" domain={domain} tick={AXIS_TICK} stroke={GRID}
                ticks={[domain[0], -Z_THRESHOLD, 0, Z_THRESHOLD, domain[1]]} />
              <YAxis type="category" dataKey="label" tick={{ ...AXIS_TICK, fill: MUTED }} width={150} stroke={GRID} />
              <ChartTooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--color-surface-2)' }}
                formatter={(z: number, _n, item) => [`${signed(z, 1)} (count ${item.payload.value})`, 'Difference']} />
              <ReferenceLine x={0} stroke={MUTED} />
              <ReferenceLine x={Z_THRESHOLD} stroke={DANGER} strokeDasharray="4 3" />
              <ReferenceLine x={-Z_THRESHOLD} stroke={DANGER} strokeDasharray="4 3" />
              <Bar dataKey="z" radius={4} isAnimationActive={false} maxBarSize={18}>
                {bars.map((b) => <Cell key={b.feature} fill={b.out ? DANGER : PRIMARY} fillOpacity={b.out ? 1 : 0.55} />)}
                <LabelList dataKey="z" position="right"
                  formatter={(z: number) => (Math.abs(z) >= Z_THRESHOLD ? signed(z, 1) : '')}
                  style={{ fontSize: 11, fill: 'var(--color-foreground)' }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </figure>
        <div className="space-y-4">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-border">
                <tr>
                  <th className={tableHeadClass('px-3 first:pl-0')}>Activity</th>
                  <th className={tableHeadClass('px-3 text-right')}>{user.username}</th>
                  <th className={tableHeadClass('px-3 text-right')}>Typical</th>
                  <th className={tableHeadClass('px-3 pr-0 text-right')}>Difference</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border tabular-nums">
                {bars.map((b) => (
                  <tr key={b.feature} className={cn(b.out && 'font-medium text-danger')}>
                    <td className="py-2 pl-0 pr-3">{b.label}</td>
                    <td className="px-3 py-2 text-right">{user.raw[b.feature]}</td>
                    <td className="px-3 py-2 text-right">{num(typical[b.feature])}</td>
                    <td className="py-2 pl-3 pr-0 text-right">{signed(b.z, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {user.reasons.length > 0 ? (
            <ul className="space-y-2 rounded-[var(--radius-md)] bg-danger-soft p-4 text-sm leading-relaxed">
              {user.reasons.map((r) => (
                <li key={r.feature} className="flex gap-2">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" />{plainReason(r, a.role, a.days)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">Nothing unusual: this person&apos;s activity is like others in their group.</p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ── Table of everyone ────────────────────────────────────────────────

function UsersTable({ a, selected, onSelect }: { a: ActivityAnalysis; selected?: number; onSelect: (id: number) => void }) {
  const rows = sortUsers(a.users)
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>Everyone checked</CardTitle>
        <CardDescription>
          People who stood out are listed first. Click a row for details.
        </CardDescription>
      </CardHeader>
      <div className="max-h-[28rem] overflow-auto">
        <table className={cn('w-full text-sm', TABLE_EDGES)}>
          <thead className="sticky top-0 border-y border-border bg-surface-2">
            <tr>
              <th className={tableHeadClass()}>Person</th>
              <th className={tableHeadClass()}>Result</th>
              {a.features.map((f) => <th key={f} className={tableHeadClass('text-right')}>{featureLabel(f)}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-border tabular-nums">
            {rows.map((u) => (
              <tr key={u.user_id} onClick={() => onSelect(u.user_id)}
                className={cn('cursor-pointer transition-colors hover:bg-surface-2/60', u.user_id === selected && 'bg-primary-soft/60')}>
                <td className={cn(CELL, 'whitespace-nowrap font-medium')}>{u.username}</td>
                <td className={cn(CELL, 'whitespace-nowrap')}>
                  <Badge variant={kindVariant(u.kind)}>{kindLabel(u.kind)}</Badge>
                  {u.kind === 'noise' && isLowActivity(u) && <span className="ml-2 text-xs text-muted-foreground">too little activity</span>}
                </td>
                {a.features.map((f) => (
                  <td key={f} className={cn(CELL, 'text-right', Math.abs(u.z[f]) >= Z_THRESHOLD && 'font-semibold text-danger')}>
                    {u.raw[f]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function TechnicalDetails({ a, onUseSuggested }: { a: ActivityAnalysis; onUseSuggested: () => void }) {
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<number | undefined>()

  // Keep a sensible selection: the person who stands out most after each run.
  useEffect(() => {
    if (!a.users.some((u) => u.user_id === selected)) setSelected(sortUsers(a.users)[0]?.user_id)
  }, [a, selected])

  const user = a.users.find((u) => u.user_id === selected)
  return (
    <section className="space-y-6 border-t border-border pt-6">
      <Disclosure open={open} onToggle={() => setOpen(!open)} controls="aa-technical"
        className="font-display text-base font-semibold text-foreground">
        How the results were worked out
      </Disclosure>
      {open && (
        <div id="aa-technical" className="space-y-6">
          <div className="grid gap-6 xl:grid-cols-2">
            <ClusterScatter a={a} selected={selected} onSelect={setSelected} />
            <KDistanceChart a={a} onUseSuggested={onUseSuggested} />
          </div>
          {user && <UserDetail a={a} user={user} />}
          <UsersTable a={a} selected={selected} onSelect={setSelected} />
        </div>
      )}
    </section>
  )
}

// ── Page ──────────────────────────────────────────────────────────────

export function AdminActivityAnalysis() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const settingsQ = useQuery({ queryKey: ['admin', 'activity-settings'], queryFn: () => activitySettingsService.get() })
  const [form, setForm] = useState<Form>(INITIAL_FORM)
  const [params, setParams] = useState<ActivityAnalysisParams>(INITIAL_PARAMS)
  const [sent, setSent] = useState<Set<number>>(new Set())

  // Advanced settings start from the saved Admin Settings; they are only used once the admin edits them.
  useEffect(() => {
    const s = settingsQ.data
    if (!s) return
    setForm((f) => (f.eps || f.min_samples ? f : { ...f, eps: String(s.dbscan_eps), min_samples: String(s.dbscan_min_samples) }))
  }, [settingsQ.data])

  const analysisQ = useQuery({
    queryKey: ['admin', 'activity-analysis', params],
    queryFn: () => activityAnalysisService.preview(params),
  })
  const a = analysisQ.data

  // Too few users: check whether the longest period would have enough, to offer it (or say there is not enough yet).
  const longer = { ...params, days: LONGEST_PERIOD }
  const longerQ = useQuery({
    queryKey: ['admin', 'activity-analysis', longer],
    queryFn: () => activityAnalysisService.preview(longer),
    enabled: !!a && a.skipped && !a.demo && a.days < LONGEST_PERIOD,
  })

  useEffect(() => { setSent(new Set()) }, [a])

  const dirty = form.role !== params.role || formDays(form) !== params.days || form.manual === !!params.auto
    || (form.manual && (Number(form.eps) !== params.eps || Number(form.min_samples) !== params.min_samples))

  function run(next: Form = form, demo = params.demo) {
    const days = formDays(next)
    if (!Number.isInteger(days) || days < 1 || days > 365) return toast.error('Custom period must be 1–365 days.')
    if (!next.manual) return setParams({ role: next.role, days, demo, auto: true })
    const eps = Number(next.eps)
    const min_samples = Number(next.min_samples)
    if (!(eps >= 0.01 && eps <= 100)) return toast.error('eps must be between 0.01 and 100.')
    if (!Number.isInteger(min_samples) || min_samples < 2 || min_samples > 100) return toast.error('min_samples must be 2–100.')
    setParams({ role: next.role, days, demo, auto: false, eps, min_samples })
  }

  function runWith(changes: Partial<Form>) {
    const next = { ...form, ...changes }
    setForm(next)
    run(next)
  }

  const send = useMutation({
    mutationFn: (ids: number[]) => activityAnalysisService.saveFlags({
      role: a!.role, days: a!.days, eps: a!.eps, min_samples: a!.min_samples, user_ids: ids,
    }),
    onSuccess: (r, ids) => {
      if (r.flagged === 0) {
        toast.info('Activity has changed since this page loaded. Press Analyse to refresh, then try again.')
        return
      }
      setSent((s) => new Set([...s, ...ids]))
      toast.success(`${r.flagged === 1 ? '1 user' : `${r.flagged} users`} sent for review.`, {
        description: 'Listed under Unusual activity on the Audit log page.',
        action: { label: 'Open Audit log', onClick: () => navigate('/admin/audit') },
      })
      qc.invalidateQueries({ queryKey: ['admin', 'activity-flags'] })
      qc.invalidateQueries({ queryKey: ['notifications'] })
    },
    onError: (err) => toast.error(apiError(err, 'Could not send for review.')),
  })

  const unusual = a && !a.skipped ? unusualUsers(a) : []
  const quiet = a && !a.skipped ? a.users.filter((u) => u.kind === 'noise' && isLowActivity(u)).length : 0
  const notEnoughEver = !!a && a.skipped && !a.demo && !(params.auto === false && a.n_users >= 6)
    && (a.days >= LONGEST_PERIOD || longerQ.data?.skipped === true)
  const canSend = !!a && !a.demo && !send.isPending
  const pending = new Set(send.isPending ? send.variables : [])
  const unsent = unusual.filter((u) => !sent.has(u.user_id)).map((u) => u.user_id)
  const analysisAlerts = a?.suspicious_alerts ?? []
  const alertedIds = new Set(analysisAlerts.map((x) => x.user_id))
  const alertsSection = a && analysisAlerts.length > 0 && (
    <SuspiciousAlertsSection a={a} unusualIds={new Set(unusual.map((u) => u.user_id))} sent={sent}
      pending={pending} canSend={canSend} onSend={(id) => send.mutate([id])} />
  )

  return (
    <div className="space-y-8">
      <PageHeader
        title="Activity analysis"
        description="People whose activity differs from others in the same role. For review only."
        icon={Activity}
      />

      <Controls
        form={form} setForm={setForm} demo={params.demo} setDemo={(v) => run(form, v)}
        onRun={() => run()} running={analysisQ.isFetching} dirty={dirty} lastRun={a}
      />

      <DataState
        isLoading={analysisQ.isLoading}
        isError={analysisQ.isError}
        onRetry={() => analysisQ.refetch()}
        skeleton={<ListSkeleton rows={4} />}
      >
        {a && (notEnoughEver ? <div className="space-y-8"><NotEnoughActivity a={a} />{alertsSection}</div> : (
          <div className="space-y-8">
            <div className="space-y-4">
              {a.demo && (
                <Banner tone="info" icon={Info}>
                  Demo data: {a.n_users} made-up users, three of them planted as unusual. Nothing here is a real account.
                </Banner>
              )}

              {a.skipped ? (
                <TooFewBanner a={a} manual={params.auto === false}
                  onTryLonger={() => runWith({ period: String(LONGEST_PERIOD), customDays: '' })}
                  onUseAuto={() => runWith({ manual: false })} />
              ) : (
                <ResultBanner a={a} shown={unusual.length} canSend={canSend && unsent.length > 0}
                  sending={send.isPending && pending.size > 1} onSendAll={() => send.mutate(unsent)} />
              )}

              {!a.skipped && (
                <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-[var(--radius-lg)] border border-border bg-surface-2/50 px-5 py-3 text-sm text-muted-foreground">
                  <p className="flex items-center gap-2">
                    <ShieldCheck className="size-4 shrink-0 text-primary" />Flagged users are for review only. No account is blocked.
                  </p>
                  {quiet > 0 && (
                    <p>{quiet === 1 ? '1 person' : `${quiet} people`} with very little activity {quiet === 1 ? 'was' : 'were'} left out.</p>
                  )}
                </div>
              )}
            </div>

            {alertsSection}

            {unusual.length > 0 && (
              <PageSection title="Unusual users">
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {unusual.map((u) => (
                    <UnusualUserCard key={u.user_id} a={a} user={u} alerted={alertedIds.has(u.user_id)} sent={sent.has(u.user_id)}
                      sending={send.isPending && pending.size === 1 && pending.has(u.user_id)}
                      canSend={canSend} onSend={() => send.mutate([u.user_id])} />
                  ))}
                </div>
              </PageSection>
            )}

            {!a.skipped && a.users.length > 0 && <AnalysisSummary a={a} unusual={unusual} quiet={quiet} />}

            {!a.skipped && a.users.length > 0 && (
              <TechnicalDetails a={a} onUseSuggested={() => runWith({ manual: false })} />
            )}
          </div>
        ))}
      </DataState>
    </div>
  )
}
