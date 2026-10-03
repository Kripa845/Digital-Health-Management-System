import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Settings, ShieldCheck, UserPlus, Lock, Info, Database, KeyRound,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Field } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { UserAvatar } from '@/components/ui/avatar'
import {
  Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose,
} from '@/components/ui/dialog'
import { PageHeader, DataState, EmptyState, ListSkeleton, InfoRow } from '@/components/patterns'
import { authService } from '@/lib/api'
import type { CurrentUser } from '@/lib/types'
import {
  apiError,
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
          <CardDescription>Keep your administrator account secure by rotating your password regularly.</CardDescription>
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
        description="Manage administrators, review security, and view application information."
        icon={Settings}
      />
      <Tabs defaultValue="administrators">
        <TabsList>
          <TabsTrigger value="administrators">Administrators</TabsTrigger>
          <TabsTrigger value="security">Security</TabsTrigger>
          <TabsTrigger value="about">About</TabsTrigger>
        </TabsList>
        <TabsContent value="administrators"><AdministratorsTab /></TabsContent>
        <TabsContent value="security"><SecurityTab /></TabsContent>
        <TabsContent value="about"><AboutTab /></TabsContent>
      </Tabs>
    </div>
  )
}
