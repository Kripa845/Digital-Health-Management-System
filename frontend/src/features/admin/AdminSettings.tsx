import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Settings, ShieldCheck, ShieldAlert, UserPlus, Lock, Info, Database, KeyRound, Scale,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Field } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { SimpleSelect } from '@/components/ui/select'
import { UserAvatar } from '@/components/ui/avatar'
import {
  Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose,
} from '@/components/ui/dialog'
import { PageHeader, DataState, EmptyState, ListSkeleton, InfoRow } from '@/components/patterns'
import { activitySettingsService, authService, rankingSettingsService } from '@/lib/api'
import type { ActivitySettings, CurrentUser, RankingSettings } from '@/lib/types'
import {
  apiError, fullMatrix, saatyLabel, SAATY, upperOf,
} from './admin-utils'

type AdminForm = { username: string; email: string; first_name: string; last_name: string; password: string }
const EMPTY_ADMIN: AdminForm = { username: '', email: '', first_name: '', last_name: '', password: '' }

function AddAdminDialog() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<AdminForm>(EMPTY_ADMIN)
  const [errors, setErrors] = useState<Partial<Record<keyof AdminForm, string>>>({})

  const set = <K extends keyof AdminForm>(k: K, v: AdminForm[K]) => setForm((s) => ({ ...s, [k]: v }))

  const mutation = useMutation({
    mutationFn: () => authService.createAdmin(form),
    onSuccess: () => {
      toast.success(`Administrator "${form.username}" created.`)
      qc.invalidateQueries({ queryKey: ['admin', 'admins'] })
      setForm(EMPTY_ADMIN)
      setOpen(false)
    },
    onError: (err) => toast.error(apiError(err, 'Could not create administrator.')),
  })

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const errs: Partial<Record<keyof AdminForm, string>> = {}
    if (!form.username.trim()) errs.username = 'Username is required.'
    if (!form.email.trim()) errs.email = 'Email is required.'
    else if (form.email !== form.email.toLowerCase()) errs.email = 'Email must be lowercase.'
    if (!form.password || form.password.length < 8) errs.password = 'Password must be at least 8 characters.'
    setErrors(errs)
    if (Object.keys(errs).length) return
    mutation.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button><UserPlus className="size-4" />Add admin</Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Add administrator</DialogTitle>
          <DialogDescription>Create a new system administrator account.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <Field label="Username" required error={errors.username}>
            <Input value={form.username} onChange={(e) => set('username', e.target.value)} />
          </Field>
          <Field label="Email" required error={errors.email}>
            <Input type="email" value={form.email} onChange={(e) => set('email', e.target.value)} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="First name">
              <Input value={form.first_name} onChange={(e) => set('first_name', e.target.value)} />
            </Field>
            <Field label="Last name">
              <Input value={form.last_name} onChange={(e) => set('last_name', e.target.value)} />
            </Field>
          </div>
          <Field label="Password" required error={errors.password} hint="At least 8 characters with letters and digits">
            <Input type="password" value={form.password} onChange={(e) => set('password', e.target.value)} />
          </Field>
          <DialogFooter>
            <DialogClose asChild><Button type="button" variant="secondary">Cancel</Button></DialogClose>
            <Button type="submit" loading={mutation.isPending}>Create admin</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function AdministratorsTab() {
  const adminsQ = useQuery({
    queryKey: ['admin', 'admins'],
    queryFn: () => authService.listAdmins(),
  })
  const admins = adminsQ.data ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">System administrators can manage every record and other admins.</p>
        <AddAdminDialog />
      </div>
      <DataState
        isLoading={adminsQ.isLoading}
        isError={adminsQ.isError}
        isEmpty={admins.length === 0}
        onRetry={() => adminsQ.refetch()}
        skeleton={<ListSkeleton rows={3} />}
        empty={<EmptyState icon={ShieldCheck} title="No administrators" />}
      >
        <Card className="divide-y divide-border">
          {admins.map((a: CurrentUser) => (
            <div key={a.id} className="flex items-center gap-3.5 p-3.5">
              <UserAvatar name={`${a.first_name} ${a.last_name}`.trim() || a.username} className="size-10" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{`${a.first_name ?? ''} ${a.last_name ?? ''}`.trim() || a.username}</p>
                <p className="truncate text-xs text-muted-foreground">{a.email || 'No email on file'}</p>
              </div>
              <Badge variant="primary"><ShieldCheck className="size-3" />Admin</Badge>
            </div>
          ))}
        </Card>
      </DataState>
    </div>
  )
}

function SecurityTab() {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Card>
        <CardHeader>
          <div className="mb-1 grid size-11 place-items-center rounded-[var(--radius-md)] bg-primary-soft text-primary-soft-foreground">
            <Lock className="size-5.5" />
          </div>
          <CardTitle>Your password</CardTitle>
          <CardDescription>Change your administrator password.</CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild variant="secondary">
            <Link to="/change-password"><KeyRound className="size-4" />Change password</Link>
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="mb-1 grid size-11 place-items-center rounded-[var(--radius-md)] bg-info-soft text-info">
            <ShieldCheck className="size-5.5" />
          </div>
          <CardTitle>Security posture</CardTitle>
          <CardDescription>Protections active across Mero Care Card.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="flex items-center gap-2"><Badge variant="success" dot>Email 2FA</Badge><span className="text-muted-foreground">One-time codes on sign-in</span></div>
          <div className="flex items-center gap-2"><Badge variant="success" dot>JWT rotation</Badge><span className="text-muted-foreground">Refresh tokens rotate and blacklist</span></div>
          <div className="flex items-center gap-2"><Badge variant="success" dot>Audit trail</Badge><span className="text-muted-foreground">Every sensitive action is logged</span></div>
        </CardContent>
      </Card>

      <Card className="sm:col-span-2">
        <CardHeader>
          <div className="mb-1 grid size-11 place-items-center rounded-[var(--radius-md)] bg-surface-2 text-muted-foreground">
            <Database className="size-5.5" />
          </div>
          <CardTitle>Database backup &amp; restore</CardTitle>
          <CardDescription>Automated backup and restore tooling is planned for a future release.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Button variant="secondary" disabled>Generate backup</Button>
          <Button variant="secondary" disabled>Restore snapshot</Button>
          <Badge variant="warning">Coming soon</Badge>
        </CardContent>
      </Card>
    </div>
  )
}

function RankingTab() {
  const qc = useQueryClient()
  const settingsQ = useQuery({ queryKey: ['admin', 'ranking-settings'], queryFn: () => rankingSettingsService.get() })
  const [upper, setUpper] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (settingsQ.data) setUpper(upperOf(settingsQ.data.ahp_pairwise))
  }, [settingsQ.data])

  const data = settingsQ.data
  const criteria = data?.criteria ?? []
  const pairs = criteria.flatMap((a, i) => criteria.slice(i + 1).map((b, k) => ({ i, j: i + 1 + k, a, b })))

  const mutation = useMutation({
    mutationFn: () => rankingSettingsService.update(fullMatrix(criteria.length, upper)),
    onSuccess: (saved: RankingSettings) => {
      setError(null)
      qc.setQueryData(['admin', 'ranking-settings'], saved)
      toast.success('Doctor ranking weights saved.')
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.ahp_pairwise
      setError(Array.isArray(msg) ? msg.join(' ') : (msg ?? null))
      toast.error(apiError(err, 'Could not save the comparisons.'))
    },
  })

  return (
    <DataState
      isLoading={settingsQ.isLoading}
      isError={settingsQ.isError}
      onRetry={() => settingsQ.refetch()}
      skeleton={<ListSkeleton rows={4} />}
    >
      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <Card>
          <CardHeader>
            <CardTitle>Compare the criteria</CardTitle>
            <CardDescription>
              For each pair, choose which matters more when ranking doctors (1–9).
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); mutation.mutate() }}>
              {pairs.map(({ i, j, a, b }) => (
                <div key={`${i}-${j}`} className="grid items-center gap-2 sm:grid-cols-[1fr_17rem_1fr]">
                  <span className="text-sm font-medium">{a.label}</span>
                  <SimpleSelect
                    id={`pair-${i}-${j}`}
                    value={upper[`${i}-${j}`] ?? '1'}
                    onValueChange={(v) => setUpper((u) => ({ ...u, [`${i}-${j}`]: v }))}
                    options={SAATY.map((o) => ({ value: o.value, label: saatyLabel(o.value, a.label, b.label) }))}
                  />
                  <span className="text-sm font-medium sm:text-right">{b.label}</span>
                </div>
              ))}
              {error && <p className="text-sm text-danger" role="alert">{error}</p>}
              <div className="flex justify-end pt-2">
                <Button type="submit" loading={mutation.isPending}>Save comparisons</Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="mb-1 grid size-11 place-items-center rounded-[var(--radius-md)] bg-primary-soft text-primary-soft-foreground">
              <Scale className="size-5.5" />
            </div>
            <CardTitle>Resulting weights</CardTitle>
            <CardDescription>Used by both symptom checkers to rank doctors with TOPSIS.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {criteria.map((c) => {
              const w = data?.ahp_weights[c.key] ?? 0
              return (
                <div key={c.key}>
                  <div className="flex justify-between gap-2 text-sm">
                    <span>
                      {c.label}{' '}
                      <span className="text-xs text-subtle-foreground">({c.benefit ? 'more is better' : 'less is better'})</span>
                    </span>
                    <span className="font-medium tabular-nums">{(100 * w).toFixed(1)}%</span>
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-surface-2">
                    <div className="h-1.5 rounded-full bg-primary" style={{ width: `${100 * w}%` }} />
                  </div>
                </div>
              )
            })}
            {data && (
              <div className="flex items-center gap-2 pt-1 text-sm">
                <span className="text-muted-foreground">Consistency ratio</span>
                <Badge variant={data.ahp_cr < 0.1 ? 'success' : 'warning'}>CR {data.ahp_cr.toFixed(3)}</Badge>
              </div>
            )}
            <p className="text-xs text-subtle-foreground">Comparisons are saved only when CR is below 0.10.</p>
          </CardContent>
        </Card>
      </div>
    </DataState>
  )
}

type ActivityForm = { activity_window_days: string; dbscan_eps: string; dbscan_min_samples: string }

function ActivityReviewTab() {
  const qc = useQueryClient()
  const settingsQ = useQuery({ queryKey: ['admin', 'activity-settings'], queryFn: () => activitySettingsService.get() })
  const [form, setForm] = useState<ActivityForm>({ activity_window_days: '', dbscan_eps: '', dbscan_min_samples: '' })
  const [errors, setErrors] = useState<Partial<Record<keyof ActivityForm, string>>>({})

  useEffect(() => {
    const d = settingsQ.data
    if (d) setForm({
      activity_window_days: String(d.activity_window_days),
      dbscan_eps: String(d.dbscan_eps),
      dbscan_min_samples: String(d.dbscan_min_samples),
    })
  }, [settingsQ.data])

  const set = (k: keyof ActivityForm, v: string) => setForm((s) => ({ ...s, [k]: v }))

  const mutation = useMutation({
    mutationFn: () => activitySettingsService.update({
      activity_window_days: Number(form.activity_window_days),
      dbscan_eps: Number(form.dbscan_eps),
      dbscan_min_samples: Number(form.dbscan_min_samples),
    }),
    onSuccess: (saved: ActivitySettings) => {
      qc.setQueryData(['admin', 'activity-settings'], saved)
      toast.success('Activity review settings saved.')
    },
    onError: (err: any) => {
      const data = err?.response?.data ?? {}
      const pick = (k: keyof ActivityForm) => (Array.isArray(data[k]) ? data[k].join(' ') : data[k])
      setErrors({
        activity_window_days: pick('activity_window_days'),
        dbscan_eps: pick('dbscan_eps'),
        dbscan_min_samples: pick('dbscan_min_samples'),
      })
      toast.error(apiError(err, 'Could not save the settings.'))
    },
  })

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const errs: Partial<Record<keyof ActivityForm, string>> = {}
    const days = Number(form.activity_window_days)
    const eps = Number(form.dbscan_eps)
    const min = Number(form.dbscan_min_samples)
    if (!Number.isInteger(days) || days < 1 || days > 365) errs.activity_window_days = 'Enter whole days from 1 to 365.'
    if (!form.dbscan_eps || !(eps >= 0.01 && eps <= 100)) errs.dbscan_eps = 'Enter a number from 0.01 to 100.'
    if (!Number.isInteger(min) || min < 2 || min > 100) errs.dbscan_min_samples = 'Enter a whole number from 2 to 100.'
    setErrors(errs)
    if (Object.keys(errs).length) return
    mutation.mutate()
  }

  return (
    <DataState
      isLoading={settingsQ.isLoading}
      isError={settingsQ.isError}
      onRetry={() => settingsQ.refetch()}
      skeleton={<ListSkeleton rows={3} />}
    >
      <Card>
        <CardHeader>
          <div className="mb-1 grid size-11 place-items-center rounded-[var(--radius-md)] bg-primary-soft text-primary-soft-foreground">
            <ShieldAlert className="size-5.5" />
          </div>
          <CardTitle>Unusual activity review</CardTitle>
          <CardDescription>
            Compares each user with others in the same role. Flags never block an account.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Activity window (days)" htmlFor="activity-days" required error={errors.activity_window_days}>
                <Input id="activity-days" type="number" min={1} max={365} value={form.activity_window_days}
                  onChange={(e) => set('activity_window_days', e.target.value)} />
              </Field>
              <Field label="DBSCAN eps" htmlFor="activity-eps" required error={errors.dbscan_eps}
                hint="Neighbourhood radius on scaled features.">
                <Input id="activity-eps" type="number" step="0.01" min={0.01} max={100} value={form.dbscan_eps}
                  onChange={(e) => set('dbscan_eps', e.target.value)} />
              </Field>
              <Field label="DBSCAN min samples" htmlFor="activity-min" required error={errors.dbscan_min_samples}>
                <Input id="activity-min" type="number" min={2} max={100} value={form.dbscan_min_samples}
                  onChange={(e) => set('dbscan_min_samples', e.target.value)} />
              </Field>
            </div>
            <div className="flex justify-end">
              <Button type="submit" loading={mutation.isPending}>Save settings</Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </DataState>
  )
}

function AboutTab() {
  return (
    <Card>
      <CardHeader>
        <div className="mb-1 grid size-11 place-items-center rounded-[var(--radius-md)] bg-primary-soft text-primary-soft-foreground">
          <Info className="size-5.5" />
        </div>
        <CardTitle>Mero Care Card</CardTitle>
        <CardDescription>Secure digital health records with QR-based patient cards.</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-4 sm:grid-cols-3">
          <InfoRow label="Application" value="Mero Care Card" />
          <InfoRow label="Environment" value="Production" />
          <InfoRow label="Support" value="support@merocarecard.app" />
        </dl>
      </CardContent>
    </Card>
  )
}

export function AdminSettings() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Administrators, doctor ranking, activity review and security."
        icon={Settings}
      />
      <Tabs defaultValue="administrators">
        <TabsList>
          <TabsTrigger value="administrators">Administrators</TabsTrigger>
          <TabsTrigger value="ranking">Doctor ranking</TabsTrigger>
          <TabsTrigger value="activity">Activity review</TabsTrigger>
          <TabsTrigger value="security">Security</TabsTrigger>
          <TabsTrigger value="about">About</TabsTrigger>
        </TabsList>
        <TabsContent value="administrators"><AdministratorsTab /></TabsContent>
        <TabsContent value="ranking"><RankingTab /></TabsContent>
        <TabsContent value="activity"><ActivityReviewTab /></TabsContent>
        <TabsContent value="security"><SecurityTab /></TabsContent>
        <TabsContent value="about"><AboutTab /></TabsContent>
      </Tabs>
    </div>
  )
}
