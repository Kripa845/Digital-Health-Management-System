import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Stethoscope, Search, Plus, MoreHorizontal, Pencil, KeyRound, Trash2,
  UsersRound, TriangleAlert, X, Eye,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Field } from '@/components/ui/label'
import { SimpleSelect } from '@/components/ui/select'
import { Switch } from '@/components/ui/misc'
import { UserAvatar } from '@/components/ui/avatar'
import { Card } from '@/components/ui/card'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose,
} from '@/components/ui/dialog'
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { PageHeader, DataState, EmptyState, ListSkeleton, InfoRow } from '@/components/patterns'
import { ActiveStatusBadge } from '@/components/status-badge'
import { doctorService, patientService, assignmentService } from '@/lib/api'
import type { Doctor, DoctorAssignment, Patient } from '@/lib/types'
import { formatDate } from '@/lib/utils'
import {
  CredentialRow, CredentialsDialog, type GeneratedCreds,
} from './admin-common'
import {
  DEPARTMENTS, GENDERS, STATUSES, WEEKDAYS, NEPAL_PHONE, NAME_RE, NMC_RE, formatName, formatNmc, apiError, useDebounced, tableHeadClass,
} from './admin-utils'

type DaySchedule = { closed: boolean; start: string; end: string }
type ScheduleState = Record<string, DaySchedule>

function defaultSchedule(): ScheduleState {
  const s: ScheduleState = {}
  for (const day of WEEKDAYS) {
    const weekend = day === 'Saturday' || day === 'Sunday'
    s[day] = { closed: weekend, start: '09:00', end: '17:00' }
  }
  return s
}

function parseSchedule(raw?: Record<string, string>): ScheduleState {
  const base = defaultSchedule()
  if (!raw) return base
  for (const day of WEEKDAYS) {
    const value = raw[day]
    if (value == null) continue
    if (!value || value.trim().toLowerCase() === 'closed') {
      base[day] = { ...base[day], closed: true }
    } else {
      const [start, end] = value.split('-').map((t) => t.trim())
      base[day] = { closed: false, start: start || '09:00', end: end || '17:00' }
    }
  }
  return base
}

function serializeSchedule(s: ScheduleState): string {
  const out: Record<string, string> = {}
  for (const day of WEEKDAYS) {
    const d = s[day]
    out[day] = d.closed ? 'closed' : `${d.start}-${d.end}`
  }
  return JSON.stringify(out)
}

function ScheduleEditor({ value, onChange }: { value: ScheduleState; onChange: (s: ScheduleState) => void }) {
  return (
    <div className="space-y-2 rounded-[var(--radius-md)] border border-border bg-surface-2 p-3">
      {WEEKDAYS.map((day) => {
        const d = value[day]
        return (
          <div key={day} className="flex flex-wrap items-center gap-3">
            <span className="w-24 shrink-0 text-sm font-medium">{day}</span>
            <div className="flex items-center gap-2">
              <Switch
                checked={!d.closed}
                onCheckedChange={(open) => onChange({ ...value, [day]: { ...d, closed: !open } })}
              />
              <span className="w-14 text-xs text-muted-foreground">{d.closed ? 'Closed' : 'Open'}</span>
            </div>
            {!d.closed && (
              <div className="flex items-center gap-2">
                <Input
                  type="time"
                  className="h-9 w-32"
                  value={d.start}
                  onChange={(e) => onChange({ ...value, [day]: { ...d, start: e.target.value } })}
                />
                <span className="text-subtle-foreground">–</span>
                <Input
                  type="time"
                  className="h-9 w-32"
                  value={d.end}
                  onChange={(e) => onChange({ ...value, [day]: { ...d, end: e.target.value } })}
                />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}


type DoctorForm = {
  first_name: string
  last_name: string
  license_number: string
  department: string
  specialization: string
  dob: string
  gender: string
  phone: string
  email: string
  status: string
}

const EMPTY_DOCTOR: DoctorForm = {
  first_name: '', last_name: '', license_number: '', department: 'General Medicine',
  specialization: '', dob: '', gender: 'Male', phone: '', email: '', status: 'Active',
}

function toDoctorForm(d: Doctor): DoctorForm {
  return {
    first_name: d.first_name ?? '',
    last_name: d.last_name ?? '',
    license_number: d.license_number ?? '',
    department: d.department ?? 'General Medicine',
    specialization: d.specialization ?? '',
    dob: d.dob ?? '',
    gender: d.gender ?? 'Male',
    phone: d.phone ?? '',
    email: d.email ?? '',
    status: d.status ?? 'Active',
  }
}

function validateDoctor(f: DoctorForm): Record<string, string> {
  const e: Record<string, string> = {}
  if (!f.first_name.trim()) e.first_name = 'First name is required.'
  else if (f.first_name.trim().length < 2) e.first_name = 'First name must be at least 2 letters.'
  else if (!NAME_RE.test(f.first_name.trim())) e.first_name = 'Letters only — no numbers or symbols.'
  if (!f.last_name.trim()) e.last_name = 'Last name is required.'
  else if (f.last_name.trim().length < 2) e.last_name = 'Last name must be at least 2 letters.'
  else if (!NAME_RE.test(f.last_name.trim())) e.last_name = 'Letters only — no numbers or symbols.'
  if (!f.license_number.trim()) e.license_number = 'NMC number is required.'
  else if (!NMC_RE.test(f.license_number.trim())) e.license_number = 'Enter a valid NMC number, e.g. NMC-12345.'
  if (!f.specialization.trim()) e.specialization = 'Specialization is required.'
  if (!f.dob) e.dob = 'Date of birth is required.'
  else if (new Date(f.dob) > new Date()) e.dob = 'Date of birth cannot be in the future.'
  if (!NEPAL_PHONE.test(f.phone)) e.phone = 'Must start with 98 or 97 and be 10 digits.'
  if (!f.email.trim()) e.email = 'Email is required.'
  else if (f.email !== f.email.toLowerCase()) e.email = 'Email must be lowercase.'
  return e
}

function DoctorFormDialog({
  open, onOpenChange, doctor, onCredentials,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  doctor: Doctor | null
  /** Called when the welcome email failed and the admin must hand over the login details. */
  onCredentials?: (creds: GeneratedCreds) => void
}) {
  const qc = useQueryClient()
  const isEdit = !!doctor
  const [form, setForm] = useState<DoctorForm>(EMPTY_DOCTOR)
  const [schedule, setSchedule] = useState<ScheduleState>(defaultSchedule)
  const [photo, setPhoto] = useState<File | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const [seed, setSeed] = useState('')
  const key = doctor ? `d-${doctor.id}` : 'new'
  if (open && seed !== key) {
    setSeed(key)
    setForm(doctor ? toDoctorForm(doctor) : EMPTY_DOCTOR)
    setSchedule(parseSchedule(doctor?.availability_schedule))
    setPhoto(null)
    setErrors({})
  }
  if (!open && seed !== '') setSeed('')

  const set = <K extends keyof DoctorForm>(k: K, v: DoctorForm[K]) => setForm((s) => ({ ...s, [k]: v }))

  const mutation = useMutation({
    mutationFn: async () => {
      const fd = new FormData()
      const entries = Object.entries(form) as [keyof DoctorForm, string][]
      for (const [k, v] of entries) {
        if (isEdit && v === '') continue
        fd.append(k, v)
      }
      fd.append('availability_schedule', serializeSchedule(schedule))
      if (photo) fd.append('photo', photo)
      return isEdit ? doctorService.update(doctor!.id, fd) : doctorService.create(fd)
    },
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ['admin', 'doctors'] })
      qc.invalidateQueries({ queryKey: ['admin', 'stats'] })
      onOpenChange(false)
      if (isEdit) {
        toast.success('Doctor updated.')
      } else if (data.generated_username) {
        toast.warning(data.message || 'Doctor registered, but the welcome email could not be sent.')
        onCredentials?.({
          name: `Dr. ${form.first_name} ${form.last_name}`.trim(),
          username: data.generated_username,
          password: data.generated_password ?? '',
        })
      } else {
        toast.success(data.message || 'Doctor registered.')
      }
    },
    onError: (err) => toast.error(apiError(err, 'Could not save doctor.')),
  })

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const errs = validateDoctor(form)
    setErrors(errs)
    if (Object.keys(errs).length) {
      toast.error('Please fix the highlighted fields.')
      return
    }
    mutation.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit doctor · ${doctor!.doctor_id}` : 'Add doctor'}</DialogTitle>
          <DialogDescription>
            {isEdit ? 'Update this doctor record and availability.' : 'Register a new doctor. Login credentials are generated automatically.'}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="First name" required error={errors.first_name}>
              <Input value={form.first_name} onChange={(e) => set('first_name', formatName(e.target.value))}
                autoCapitalize="words" maxLength={50} />
            </Field>
            <Field label="Last name" required error={errors.last_name}>
              <Input value={form.last_name} onChange={(e) => set('last_name', formatName(e.target.value))}
                autoCapitalize="words" maxLength={50} />
            </Field>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="NMC number" required error={errors.license_number}
              hint={errors.license_number ? undefined : 'Nepal Medical Council registration number'}>
              <Input value={form.license_number} onChange={(e) => set('license_number', formatNmc(e.target.value))}
                maxLength={20} />
            </Field>
            <Field label="Department" required>
              <SimpleSelect value={form.department} onValueChange={(v) => set('department', v)} options={DEPARTMENTS as unknown as string[]} />
            </Field>
          </div>

          <Field label="Specialization" required error={errors.specialization}>
            <Input value={form.specialization} onChange={(e) => set('specialization', e.target.value)} />
          </Field>

          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Date of birth" required error={errors.dob}>
              <Input type="date" max={new Date().toISOString().split('T')[0]} value={form.dob} onChange={(e) => set('dob', e.target.value)} />
            </Field>
            <Field label="Gender" required>
              <SimpleSelect value={form.gender} onValueChange={(v) => set('gender', v)} options={GENDERS as unknown as string[]} />
            </Field>
            <Field label="Status">
              <SimpleSelect value={form.status} onValueChange={(v) => set('status', v)} options={STATUSES as unknown as string[]} />
            </Field>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Phone" required error={errors.phone} hint="Nepal mobile, e.g. 9812345678">
              <Input inputMode="numeric" value={form.phone} onChange={(e) => set('phone', e.target.value)} />
            </Field>
            <Field label="Email" required error={errors.email}>
              <Input type="email" value={form.email} onChange={(e) => set('email', e.target.value)} />
            </Field>
          </div>

          <Field label="Weekly availability">
            <ScheduleEditor value={schedule} onChange={setSchedule} />
          </Field>

          <Field label="Photo" hint="Optional · JPG or PNG, max 5MB">
            <Input type="file" accept="image/png,image/jpeg" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
          </Field>

          <DialogFooter>
            <DialogClose asChild><Button type="button" variant="secondary">Cancel</Button></DialogClose>
            <Button type="submit" loading={mutation.isPending}>{isEdit ? 'Save changes' : 'Register doctor'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ── Assignments manager ───────────────────────────────────────────────
function AssignmentsDialog({ doctor, onClose }: { doctor: Doctor | null; onClose: () => void }) {
  const qc = useQueryClient()
  const [selected, setSelected] = useState('')

  const assignmentsQ = useQuery({
    queryKey: ['admin', 'assignments', doctor?.id],
    queryFn: () => assignmentService.list({ doctor: doctor!.id }),
    enabled: !!doctor,
  })
  const patientsQ = useQuery({
    queryKey: ['admin', 'patients', 'active-picker'],
    queryFn: () => patientService.list({ status: 'Active' }),
    enabled: !!doctor,
  })
  const assignments = assignmentsQ.data ?? []
  const patients = patientsQ.data ?? []

  const createMut = useMutation({
    mutationFn: () => assignmentService.create(doctor!.id, Number(selected)),
    onSuccess: () => {
      toast.success('Patient assigned.')
      setSelected('')
      qc.invalidateQueries({ queryKey: ['admin', 'assignments', doctor?.id] })
    },
    onError: (err) => toast.error(apiError(err, 'Could not assign patient. They may already be assigned.')),
  })
  const removeMut = useMutation({
    mutationFn: (id: number) => assignmentService.remove(id),
    onSuccess: () => {
      toast.success('Assignment removed.')
      qc.invalidateQueries({ queryKey: ['admin', 'assignments', doctor?.id] })
    },
    onError: (err) => toast.error(apiError(err, 'Could not remove assignment.')),
  })

  const patientLabel = (a: DoctorAssignment) => {
    const p = a.patient_detail
    if (p) return `${p.first_name} ${p.last_name}`
    return `Patient #${a.patient}`
  }

  return (
    <Dialog open={!!doctor} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Manage assignments</DialogTitle>
          <DialogDescription>Assign or remove patients for Dr. {doctor?.first_name} {doctor?.last_name}.</DialogDescription>
        </DialogHeader>

        <div className="flex items-end gap-2">
          <Field label="Assign a patient" className="flex-1">
            <SimpleSelect
              value={selected}
              onValueChange={setSelected}
              placeholder="Choose an active patient"
              options={patients.map((p: Patient) => ({ value: String(p.id), label: `${p.patient_id} · ${p.first_name} ${p.last_name}` }))}
            />
          </Field>
          <Button disabled={!selected} loading={createMut.isPending} onClick={() => createMut.mutate()}>
            <Plus className="size-4" />Assign
          </Button>
        </div>

        <DataState
          isLoading={assignmentsQ.isLoading}
          isError={assignmentsQ.isError}
          isEmpty={assignments.length === 0}
          onRetry={() => assignmentsQ.refetch()}
          skeleton={<ListSkeleton rows={3} />}
          empty={<EmptyState icon={UsersRound} title="No patients assigned" description="Assign a patient using the picker above." />}
        >
          <div className="max-h-72 space-y-2 overflow-y-auto">
            {assignments.map((a) => (
              <div key={a.id} className="flex items-center justify-between gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-3.5 py-2.5">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{patientLabel(a)}</p>
                  <p className="truncate font-mono text-xs text-muted-foreground">
                    {a.patient_detail?.patient_id ?? ''} · assigned {formatDate(a.assigned_date)}
                  </p>
                </div>
                <Button variant="ghost" size="icon-sm" aria-label="Remove" loading={removeMut.isPending && removeMut.variables === a.id} onClick={() => removeMut.mutate(a.id)}>
                  <X />
                </Button>
              </div>
            ))}
          </div>
        </DataState>

        <DialogFooter>
          <DialogClose asChild><Button variant="secondary" className="w-full sm:w-auto">Done</Button></DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function AdminDoctors() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [department, setDepartment] = useState('all')
  const debouncedSearch = useDebounced(search)

  const [addOpen, setAddOpen] = useState(false)
  const [editDoctor, setEditDoctor] = useState<Doctor | null>(null)
  const [viewDoctor, setViewDoctor] = useState<Doctor | null>(null)
  const [creds, setCreds] = useState<GeneratedCreds | null>(null)
  const [assignDoctor, setAssignDoctor] = useState<Doctor | null>(null)
  const [deleteDoctor, setDeleteDoctor] = useState<Doctor | null>(null)
  const [resetResult, setResetResult] = useState<{ name: string; password: string } | null>(null)

  const params = useMemo(() => ({
    search: debouncedSearch || undefined,
    department: department !== 'all' ? department : undefined,
  }), [debouncedSearch, department])

  const listQ = useQuery({
    queryKey: ['admin', 'doctors', params],
    queryFn: () => doctorService.list(params),
  })
  const doctors = listQ.data ?? []

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['admin', 'doctors'] })
    qc.invalidateQueries({ queryKey: ['admin', 'stats'] })
  }

  const resetMut = useMutation({
    mutationFn: (d: Doctor) => doctorService.resetPassword(d.id),
    onSuccess: (data: { new_password?: string }, d) => {
      setResetResult({ name: `Dr. ${d.first_name} ${d.last_name}`.trim(), password: data?.new_password ?? '' })
    },
    onError: (err) => toast.error(apiError(err, 'Could not reset password.')),
  })
  const deleteMut = useMutation({
    mutationFn: (d: Doctor) => doctorService.remove(d.id),
    onSuccess: () => { toast.success('Doctor deleted.'); setDeleteDoctor(null); invalidate() },
    onError: (err) => toast.error(apiError(err, 'Could not delete doctor.')),
  })

  return (
    <div className="space-y-6">
      <PageHeader
        title="Doctors"
        description="Register clinicians, manage availability, and assign patients."
        icon={Stethoscope}
        actions={<Button onClick={() => setAddOpen(true)}><Plus className="size-4" />Add doctor</Button>}
      />

      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" />
          <Input
            className="pl-9"
            placeholder="Search by name, ID, license, specialization…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="w-full sm:w-56">
          <SimpleSelect
            value={department}
            onValueChange={setDepartment}
            options={[{ value: 'all', label: 'All departments' }, ...DEPARTMENTS.map((d) => ({ value: d, label: d }))]}
          />
        </div>
      </div>

      <DataState
        isLoading={listQ.isLoading}
        isError={listQ.isError}
        isEmpty={doctors.length === 0}
        onRetry={() => listQ.refetch()}
        skeleton={<ListSkeleton rows={6} />}
        empty={<EmptyState icon={Stethoscope} title="No doctors found" description="Try adjusting your search or add a new doctor." action={<Button onClick={() => setAddOpen(true)}><Plus className="size-4" />Add doctor</Button>} />}
      >
        {/* Desktop table */}
        <Card className="hidden overflow-hidden md:block">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-border bg-surface-2">
                <tr>
                  <th className={tableHeadClass()}>Doctor</th>
                  <th className={tableHeadClass()}>ID</th>
                  <th className={tableHeadClass()}>Department</th>
                  <th className={tableHeadClass()}>Phone</th>
                  <th className={tableHeadClass()}>Status</th>
                  <th className={tableHeadClass('text-right')}>Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {doctors.map((d) => (
                  <tr key={d.id} className="transition-colors hover:bg-surface-2/60">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <UserAvatar name={`${d.first_name} ${d.last_name}`} src={d.photo} className="size-9" />
                        <div className="min-w-0">
                          <p className="truncate font-medium">Dr. {d.first_name} {d.last_name}</p>
                          <p className="truncate text-xs text-muted-foreground">{d.specialization}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">{d.doctor_id}</td>
                    <td className="px-4 py-3">{d.department}</td>
                    <td className="px-4 py-3 font-mono tabular-nums">{d.phone ?? '—'}</td>
                    <td className="px-4 py-3"><ActiveStatusBadge status={d.status} /></td>
                    <td className="px-4 py-3 text-right">
                      <DoctorRowActions
                        onView={() => setViewDoctor(d)}
                        onEdit={() => setEditDoctor(d)}
                        onAssign={() => setAssignDoctor(d)}
                        onReset={() => resetMut.mutate(d)}
                        onDelete={() => setDeleteDoctor(d)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        {/* Mobile cards */}
        <div className="space-y-3 md:hidden">
          {doctors.map((d) => (
            <Card key={d.id} className="p-4">
              <div className="flex items-center gap-3">
                <UserAvatar name={`${d.first_name} ${d.last_name}`} src={d.photo} className="size-11" />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">Dr. {d.first_name} {d.last_name}</p>
                  <p className="truncate font-mono text-xs text-muted-foreground">{d.doctor_id}</p>
                </div>
                <DoctorRowActions
                  onView={() => setViewDoctor(d)}
                  onEdit={() => setEditDoctor(d)}
                  onAssign={() => setAssignDoctor(d)}
                  onReset={() => resetMut.mutate(d)}
                  onDelete={() => setDeleteDoctor(d)}
                />
              </div>
              <div className="mt-3 grid grid-cols-3 gap-3">
                <InfoRow label="Dept" value={d.department} />
                <InfoRow label="Phone" value={<span className="font-mono text-xs">{d.phone ?? '—'}</span>} />
                <InfoRow label="Status" value={<ActiveStatusBadge status={d.status} />} />
              </div>
            </Card>
          ))}
        </div>
      </DataState>

      {/* Dialogs */}
      <DoctorFormDialog open={addOpen} onOpenChange={setAddOpen} doctor={null} onCredentials={setCreds} />
      <CredentialsDialog creds={creds} onClose={() => setCreds(null)} emailed={false} />
      <DoctorFormDialog open={!!editDoctor} onOpenChange={(o) => { if (!o) setEditDoctor(null) }} doctor={editDoctor} />
      <AssignmentsDialog doctor={assignDoctor} onClose={() => setAssignDoctor(null)} />
      <DoctorDetailsDialog doctor={viewDoctor} onClose={() => setViewDoctor(null)}
        onEdit={() => { const d = viewDoctor; setViewDoctor(null); setEditDoctor(d) }} />

      {/* Reset password result */}
      <Dialog open={!!resetResult} onOpenChange={(o) => { if (!o) setResetResult(null) }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Password reset</DialogTitle>
            <DialogDescription>
              A new temporary password for {resetResult?.name} has been generated. Give it to the doctor; they
              will be asked to change it when they next sign in.
            </DialogDescription>
          </DialogHeader>
          {resetResult?.password && <CredentialRow label="New password" value={resetResult.password} />}
          <DialogFooter>
            <DialogClose asChild><Button className="w-full sm:w-auto">Done</Button></DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirm */}
      <Dialog open={!!deleteDoctor} onOpenChange={(o) => { if (!o) setDeleteDoctor(null) }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <div className="mb-1 grid size-11 place-items-center rounded-[var(--radius-md)] bg-danger-soft text-danger">
              <TriangleAlert className="size-5.5" />
            </div>
            <DialogTitle>Delete doctor?</DialogTitle>
            <DialogDescription>
              This permanently deletes Dr. {deleteDoctor?.first_name} {deleteDoctor?.last_name}
              {' '}(<span className="font-mono">{deleteDoctor?.doctor_id}</span>), all assignments, and login access. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild><Button variant="secondary">Cancel</Button></DialogClose>
            <Button variant="danger" loading={deleteMut.isPending} onClick={() => deleteDoctor && deleteMut.mutate(deleteDoctor)}>
              <Trash2 className="size-4" />Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function DField({ label, value }: { label: string; value?: string | number | null }) {
  const shown = value != null && String(value).trim() !== '' ? value : '—'
  return <InfoRow label={label} value={shown} />
}

function DoctorDetailsDialog({
  doctor, onClose, onEdit,
}: {
  doctor: Doctor | null
  onClose: () => void
  onEdit: () => void
}) {
  const d = doctor
  const name = d ? `Dr. ${d.first_name ?? ''} ${d.last_name ?? ''}`.trim() : ''
  const schedule = (d?.availability_schedule && typeof d.availability_schedule === 'object'
    ? d.availability_schedule
    : {}) as Record<string, string>
  return (
    <Dialog open={!!d} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-2xl">
        {d && (
          <>
            <DialogHeader>
              <div className="flex items-center gap-3">
                <UserAvatar name={name} src={d.photo} className="size-12" />
                <div className="min-w-0">
                  <DialogTitle className="truncate">{name}</DialogTitle>
                  <DialogDescription className="font-mono">{d.doctor_id}</DialogDescription>
                </div>
                <div className="ml-auto"><ActiveStatusBadge status={d.status} /></div>
              </div>
            </DialogHeader>

            <div className="space-y-6">
              <section>
                <p className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-subtle-foreground">Clinical</p>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3">
                  <DField label="Department" value={d.department} />
                  <DField label="Specialization" value={d.specialization} />
                  <DField label="NMC number" value={d.license_number} />
                </dl>
              </section>

              <section>
                <p className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-subtle-foreground">Personal</p>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3">
                  <DField label="Date of birth" value={d.dob ? formatDate(d.dob) : ''} />
                  <DField label="Age" value={d.age != null ? `${d.age} yrs` : ''} />
                  <DField label="Gender" value={d.gender} />
                  <DField label="Phone" value={d.phone} />
                  <DField label="Email" value={d.email} />
                </dl>
              </section>

              <section>
                <p className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-subtle-foreground">Weekly availability</p>
                <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                  {WEEKDAYS.map((day) => {
                    const slot = schedule[day]
                    const closed = !slot || String(slot).toLowerCase() === 'closed'
                    return (
                      <div key={day} className="flex items-center justify-between rounded-[var(--radius-sm)] border border-border px-3 py-1.5 text-sm">
                        <span className="text-muted-foreground">{day}</span>
                        <span className={`font-medium tabular ${closed ? 'text-subtle-foreground' : ''}`}>{closed ? 'Closed' : slot}</span>
                      </div>
                    )
                  })}
                </div>
              </section>

              <p className="text-xs text-subtle-foreground">Registered {formatDate(d.registration_date)}</p>
            </div>

            <DialogFooter>
              <DialogClose asChild><Button variant="secondary">Close</Button></DialogClose>
              <Button onClick={onEdit}><Pencil className="size-4" />Edit</Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

function DoctorRowActions({
  onView, onEdit, onAssign, onReset, onDelete,
}: {
  onView: () => void
  onEdit: () => void
  onAssign: () => void
  onReset: () => void
  onDelete: () => void
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label="Actions"><MoreHorizontal /></Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={onView}><Eye />View details</DropdownMenuItem>
        <DropdownMenuItem onSelect={onEdit}><Pencil />Edit</DropdownMenuItem>
        <DropdownMenuItem onSelect={onAssign}><UsersRound />Manage assignments</DropdownMenuItem>
        <DropdownMenuItem onSelect={onReset}><KeyRound />Reset password</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem destructive onSelect={onDelete}><Trash2 />Delete</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
