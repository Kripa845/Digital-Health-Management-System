import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import QRCode from 'react-qr-code'
import {
  Users, Search, Plus, MoreHorizontal, QrCode, Pencil, Eye,
  RefreshCw, Trash2, TriangleAlert, FlaskConical,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input, Textarea } from '@/components/ui/input'
import { Field } from '@/components/ui/label'
import { SimpleSelect } from '@/components/ui/select'
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
import { patientService, labReportService } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import type { Patient } from '@/lib/types'
import { LabReportUploadDialog } from '@/features/lab-reports/LabReportUploadDialog'
import { LabReportRow } from '@/features/lab-reports/LabReportRow'
import {
  BLOOD_GROUPS, GENDERS, STATUSES, NEPAL_PHONE, NAME_RE, formatName, apiError, useDebounced, CopyButton,
  tableHeadClass,
} from './admin-common'

type PatientForm = {
  first_name: string
  middle_name: string
  last_name: string
  dob: string
  gender: string
  blood_group: string
  phone: string
  emergency_contact: string
  email: string
  address: string
  height: string
  weight: string
  allergies: string
  current_medication: string
  status: string
}

const EMPTY_FORM: PatientForm = {
  first_name: '', middle_name: '', last_name: '', dob: '', gender: 'Male', blood_group: 'A+',
  phone: '', emergency_contact: '', email: '', address: '', height: '', weight: '',
  allergies: '', current_medication: '', status: 'Active',
}

function toForm(p: Patient): PatientForm {
  return {
    first_name: p.first_name ?? '',
    middle_name: p.middle_name ?? '',
    last_name: p.last_name ?? '',
    dob: p.dob ?? '',
    gender: p.gender ?? 'Male',
    blood_group: p.blood_group ?? 'A+',
    phone: p.phone ?? '',
    emergency_contact: p.emergency_contact ?? '',
    email: p.email ?? '',
    address: p.address ?? '',
    height: p.height != null ? String(p.height) : '',
    weight: p.weight != null ? String(p.weight) : '',
    allergies: p.allergies ?? '',
    current_medication: p.current_medication ?? '',
    status: p.status ?? 'Active',
  }
}

function validate(f: PatientForm): Record<string, string> {
  const e: Record<string, string> = {}
  if (!f.first_name.trim()) e.first_name = 'First name is required.'
  else if (f.first_name.trim().length < 2) e.first_name = 'First name must be at least 2 letters.'
  else if (!NAME_RE.test(f.first_name.trim())) e.first_name = 'Letters only — no numbers or symbols.'
  if (f.middle_name.trim() && !NAME_RE.test(f.middle_name.trim())) e.middle_name = 'Letters only — no numbers or symbols.'
  if (!f.last_name.trim()) e.last_name = 'Last name is required.'
  else if (f.last_name.trim().length < 2) e.last_name = 'Last name must be at least 2 letters.'
  else if (!NAME_RE.test(f.last_name.trim())) e.last_name = 'Letters only — no numbers or symbols.'
  if (!f.dob) e.dob = 'Date of birth is required.'
  else if (new Date(f.dob) > new Date()) e.dob = 'Date of birth cannot be in the future.'
  if (!NEPAL_PHONE.test(f.phone)) e.phone = 'Must start with 98 or 97 and be 10 digits.'
  if (!NEPAL_PHONE.test(f.emergency_contact)) e.emergency_contact = 'Must start with 98 or 97 and be 10 digits.'
  if (f.phone && f.emergency_contact && f.phone === f.emergency_contact) e.emergency_contact = 'Must differ from the primary phone.'
  if (f.email && f.email !== f.email.toLowerCase()) e.email = 'Email must be lowercase.'
  if (!f.address.trim() || f.address.trim().length < 5) e.address = 'Address must be at least 5 characters.'
  const h = parseFloat(f.height)
  if (!f.height || Number.isNaN(h) || h < 30 || h > 250) e.height = 'Height must be between 30 and 250 cm.'
  const w = parseFloat(f.weight)
  if (!f.weight || Number.isNaN(w) || w < 1 || w > 300) e.weight = 'Weight must be between 1 and 300 kg.'
  return e
}

function PatientFormDialog({
  open, onOpenChange, patient,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  patient: Patient | null
}) {
  const qc = useQueryClient()
  const isEdit = !!patient
  const [form, setForm] = useState<PatientForm>(EMPTY_FORM)
  const [photo, setPhoto] = useState<File | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Reset the form whenever the dialog opens for a (different) target.
  const [seed, setSeed] = useState<string>('')
  const key = patient ? `p-${patient.id}` : 'new'
  if (open && seed !== key) {
    setSeed(key)
    setForm(patient ? toForm(patient) : EMPTY_FORM)
    setPhoto(null)
    setErrors({})
  }
  if (!open && seed !== '') setSeed('')

  const set = <K extends keyof PatientForm>(k: K, v: PatientForm[K]) => setForm((s) => ({ ...s, [k]: v }))

  const mutation = useMutation({
    mutationFn: async () => {
      const fd = new FormData()
      const entries = Object.entries(form) as [keyof PatientForm, string][]
      for (const [k, v] of entries) {
        // On edit (PATCH) only send fields that carry a value.
        if (isEdit && v === '') continue
        fd.append(k, v)
      }
      if (photo) fd.append('photo', photo)
      return isEdit ? patientService.update(patient!.id, fd) : patientService.create(fd)
    },
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ['admin', 'patients'] })
      qc.invalidateQueries({ queryKey: ['admin', 'stats'] })
      onOpenChange(false)
      if (isEdit) {
        toast.success('Patient updated.')
      } else {
        toast.success(data.message || 'Patient registered.')
      }
    },
    onError: (err) => toast.error(apiError(err, 'Could not save patient.')),
  })

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const errs = validate(form)
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
          <DialogTitle>{isEdit ? `Edit patient · ${patient!.patient_id}` : 'Add patient'}</DialogTitle>
          <DialogDescription>
            {isEdit ? 'Update this patient record.' : 'Register a new patient. Login credentials are generated automatically.'}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="First name" required error={errors.first_name}>
              <Input value={form.first_name} onChange={(e) => set('first_name', formatName(e.target.value))}
                autoCapitalize="words" maxLength={50} />
            </Field>
            <Field label="Middle name" error={errors.middle_name}>
              <Input value={form.middle_name} onChange={(e) => set('middle_name', formatName(e.target.value))}
                autoCapitalize="words" maxLength={50} />
            </Field>
            <Field label="Last name" required error={errors.last_name}>
              <Input value={form.last_name} onChange={(e) => set('last_name', formatName(e.target.value))}
                autoCapitalize="words" maxLength={50} />
            </Field>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Date of birth" required error={errors.dob}>
              <Input type="date" max={new Date().toISOString().split('T')[0]} value={form.dob} onChange={(e) => set('dob', e.target.value)} />
            </Field>
            <Field label="Gender" required>
              <SimpleSelect value={form.gender} onValueChange={(v) => set('gender', v)} options={GENDERS as unknown as string[]} />
            </Field>
            <Field label="Blood group" required>
              <SimpleSelect value={form.blood_group} onValueChange={(v) => set('blood_group', v)} options={BLOOD_GROUPS as unknown as string[]} />
            </Field>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Phone" required error={errors.phone} hint="Nepal mobile, e.g. 9812345678">
              <Input inputMode="numeric" value={form.phone} onChange={(e) => set('phone', e.target.value)} />
            </Field>
            <Field label="Emergency contact" required error={errors.emergency_contact}>
              <Input inputMode="numeric" value={form.emergency_contact} onChange={(e) => set('emergency_contact', e.target.value)} />
            </Field>
            <Field label="Email" error={errors.email}>
              <Input type="email" value={form.email} onChange={(e) => set('email', e.target.value)} />
            </Field>
          </div>

          <Field label="Address" required error={errors.address}>
            <Input value={form.address} onChange={(e) => set('address', e.target.value)} />
          </Field>

          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Height (cm)" required error={errors.height}>
              <Input type="number" step="0.1" value={form.height} onChange={(e) => set('height', e.target.value)} />
            </Field>
            <Field label="Weight (kg)" required error={errors.weight}>
              <Input type="number" step="0.1" value={form.weight} onChange={(e) => set('weight', e.target.value)} />
            </Field>
            <Field label="Status">
              <SimpleSelect value={form.status} onValueChange={(v) => set('status', v)} options={STATUSES as unknown as string[]} />
            </Field>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Allergies">
              <Textarea rows={2} value={form.allergies} onChange={(e) => set('allergies', e.target.value)} />
            </Field>
            <Field label="Current medication">
              <Textarea rows={2} value={form.current_medication} onChange={(e) => set('current_medication', e.target.value)} />
            </Field>
          </div>

          <Field label="Photo" hint="Optional · JPG or PNG, max 5MB">
            <Input type="file" accept="image/png,image/jpeg" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
          </Field>

          <DialogFooter>
            <DialogClose asChild><Button type="button" variant="secondary">Cancel</Button></DialogClose>
            <Button type="submit" loading={mutation.isPending}>{isEdit ? 'Save changes' : 'Register patient'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function QrDialog({ patient, onClose }: { patient: Patient | null; onClose: () => void }) {
  const link = patient ? `${window.location.origin}/public-profile/${patient.uuid_token}` : ''
  return (
    <Dialog open={!!patient} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Health card QR</DialogTitle>
          <DialogDescription>Scan to open the public identifier profile for {patient?.first_name} {patient?.last_name}.</DialogDescription>
        </DialogHeader>
        {patient && (
          <div className="flex flex-col items-center gap-4">
            <div className="rounded-[var(--radius-lg)] border border-border bg-white p-4">
              <QRCode value={link} size={180} level="M" />
            </div>
            <div className="w-full">
              <div className="flex items-center justify-between gap-3 rounded-[var(--radius-md)] border border-border bg-surface-2 px-3.5 py-2.5">
                <code className="min-w-0 select-all truncate font-mono text-xs">{patient.patient_id}</code>
                <CopyButton value={link} />
              </div>
            </div>
          </div>
        )}
        <DialogFooter>
          <DialogClose asChild><Button variant="secondary" className="w-full sm:w-auto">Close</Button></DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function AdminPatients() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const debouncedSearch = useDebounced(search)

  const [addOpen, setAddOpen] = useState(false)
  const [editPatient, setEditPatient] = useState<Patient | null>(null)
  const [viewPatient, setViewPatient] = useState<Patient | null>(null)
  const [qrPatient, setQrPatient] = useState<Patient | null>(null)
  const [deletePatient, setDeletePatient] = useState<Patient | null>(null)

  const params = useMemo(() => ({
    search: debouncedSearch || undefined,
    status: status !== 'all' ? status : undefined,
  }), [debouncedSearch, status])

  const listQ = useQuery({
    queryKey: ['admin', 'patients', params],
    queryFn: () => patientService.list(params),
  })
  const patients = listQ.data ?? []

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['admin', 'patients'] })
    qc.invalidateQueries({ queryKey: ['admin', 'stats'] })
  }

  const toggleMut = useMutation({
    mutationFn: (p: Patient) => patientService.toggleStatus(p.id),
    onSuccess: () => { toast.success('Status updated.'); invalidate() },
    onError: (err) => toast.error(apiError(err, 'Could not update status.')),
  })
  const deleteMut = useMutation({
    mutationFn: (p: Patient) => patientService.remove(p.id),
    onSuccess: () => { toast.success('Patient deleted.'); setDeletePatient(null); invalidate() },
    onError: (err) => toast.error(apiError(err, 'Could not delete patient.')),
  })

  return (
    <div className="space-y-6">
      <PageHeader
        title="Patients"
        description="Register, search, and manage every patient record and their access."
        icon={Users}
        actions={<Button onClick={() => setAddOpen(true)}><Plus className="size-4" />Add patient</Button>}
      />

      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" />
          <Input
            className="pl-9"
            placeholder="Search by name, ID, phone, allergies…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="w-full sm:w-48">
          <SimpleSelect
            value={status}
            onValueChange={setStatus}
            options={[{ value: 'all', label: 'All statuses' }, ...STATUSES.map((s) => ({ value: s, label: s }))]}
          />
        </div>
      </div>

      <DataState
        isLoading={listQ.isLoading}
        isError={listQ.isError}
        isEmpty={patients.length === 0}
        onRetry={() => listQ.refetch()}
        skeleton={<ListSkeleton rows={6} />}
        empty={<EmptyState icon={Users} title="No patients found" description="Try adjusting your search or add a new patient." action={<Button onClick={() => setAddOpen(true)}><Plus className="size-4" />Add patient</Button>} />}
      >
        {/* Desktop table */}
        <Card className="hidden overflow-hidden md:block">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-border bg-surface-2">
                <tr>
                  <th className={tableHeadClass()}>Patient</th>
                  <th className={tableHeadClass()}>ID</th>
                  <th className={tableHeadClass()}>Blood</th>
                  <th className={tableHeadClass()}>Phone</th>
                  <th className={tableHeadClass()}>Status</th>
                  <th className={tableHeadClass('text-right')}>Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {patients.map((p) => (
                  <tr key={p.id} className="transition-colors hover:bg-surface-2/60">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <UserAvatar name={`${p.first_name} ${p.last_name}`} src={p.photo} className="size-9" />
                        <div className="min-w-0">
                          <p className="truncate font-medium">{p.first_name} {p.middle_name ? `${p.middle_name} ` : ''}{p.last_name}</p>
                          <p className="truncate text-xs text-muted-foreground">{p.age != null ? `${p.age} yrs` : '—'} · {p.gender}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">{p.patient_id}</td>
                    <td className="px-4 py-3 font-mono tabular-nums">{p.blood_group}</td>
                    <td className="px-4 py-3 font-mono tabular-nums">{p.phone}</td>
                    <td className="px-4 py-3"><ActiveStatusBadge status={p.status} /></td>
                    <td className="px-4 py-3 text-right">
                      <RowActions
                        patient={p}
                        onQr={() => setQrPatient(p)}
                        onView={() => setViewPatient(p)}
                        onEdit={() => setEditPatient(p)}
                        onToggle={() => toggleMut.mutate(p)}
                        onDelete={() => setDeletePatient(p)}
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
          {patients.map((p) => (
            <Card key={p.id} className="p-4">
              <div className="flex items-center gap-3">
                <UserAvatar name={`${p.first_name} ${p.last_name}`} src={p.photo} className="size-11" />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{p.first_name} {p.last_name}</p>
                  <p className="truncate font-mono text-xs text-muted-foreground">{p.patient_id}</p>
                </div>
                <RowActions
                  patient={p}
                  onQr={() => setQrPatient(p)}
                  onView={() => setViewPatient(p)}
                  onEdit={() => setEditPatient(p)}
                  onToggle={() => toggleMut.mutate(p)}
                  onDelete={() => setDeletePatient(p)}
                />
              </div>
              <div className="mt-3 grid grid-cols-3 gap-3">
                <InfoRow label="Blood" value={<span className="font-mono">{p.blood_group}</span>} />
                <InfoRow label="Phone" value={<span className="font-mono text-xs">{p.phone}</span>} />
                <InfoRow label="Status" value={<ActiveStatusBadge status={p.status} />} />
              </div>
            </Card>
          ))}
        </div>
      </DataState>

      {/* Dialogs */}
      <PatientFormDialog open={addOpen} onOpenChange={setAddOpen} patient={null} />
      <PatientFormDialog open={!!editPatient} onOpenChange={(o) => { if (!o) setEditPatient(null) }} patient={editPatient} />
      <QrDialog patient={qrPatient} onClose={() => setQrPatient(null)} />
      <PatientDetailsDialog patient={viewPatient} onClose={() => setViewPatient(null)}
        onEdit={() => { const p = viewPatient; setViewPatient(null); setEditPatient(p) }} />

      {/* Delete confirm */}
      <Dialog open={!!deletePatient} onOpenChange={(o) => { if (!o) setDeletePatient(null) }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <div className="mb-1 grid size-11 place-items-center rounded-[var(--radius-md)] bg-danger-soft text-danger">
              <TriangleAlert className="size-5.5" />
            </div>
            <DialogTitle>Delete patient?</DialogTitle>
            <DialogDescription>
              This permanently deletes {deletePatient?.first_name} {deletePatient?.last_name}
              {' '}(<span className="font-mono">{deletePatient?.patient_id}</span>), all their records, and login access. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild><Button variant="secondary">Cancel</Button></DialogClose>
            <Button variant="danger" loading={deleteMut.isPending} onClick={() => deletePatient && deleteMut.mutate(deletePatient)}>
              <Trash2 className="size-4" />Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function DetailField({ label, value }: { label: string; value?: string | number | null }) {
  const shown = value != null && String(value).trim() !== '' ? value : '—'
  return <InfoRow label={label} value={shown} />
}

function PatientDetailsDialog({
  patient, onClose, onEdit,
}: {
  patient: Patient | null
  onClose: () => void
  onEdit: () => void
}) {
  const p = patient
  const fullName = p ? [p.first_name, p.middle_name, p.last_name].filter(Boolean).join(' ') : ''
  const [tab, setTab] = useState<'info' | 'lab'>('info')

  const labReportsQ = useQuery({
    queryKey: ['admin', 'lab-reports', p?.id],
    queryFn: () => labReportService.list({ patient: p!.id }),
    enabled: !!p && tab === 'lab',
  })
  const labReports = labReportsQ.data ?? []

  // Reset tab when dialog closes
  const handleOpenChange = (open: boolean) => { if (!open) { setTab('info'); onClose() } }

  return (
    <Dialog open={!!p} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl">
        {p && (
          <>
            <DialogHeader>
              <div className="flex items-center gap-3">
                <UserAvatar name={fullName} src={p.photo} className="size-12" />
                <div className="min-w-0">
                  <DialogTitle className="truncate">{fullName}</DialogTitle>
                  <DialogDescription className="font-mono">{p.patient_id}</DialogDescription>
                </div>
                <div className="ml-auto"><ActiveStatusBadge status={p.status} /></div>
              </div>
            </DialogHeader>

            {/* Tab switcher */}
            <div className="flex gap-1 rounded-[var(--radius-md)] border border-border bg-surface-2 p-1">
              {([
                { key: 'info', label: 'Patient info' },
                { key: 'lab', label: 'Lab reports' },
              ] as const).map((t) => (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={`flex-1 rounded-[calc(var(--radius-md)-2px)] px-3 py-1.5 text-sm font-medium transition-colors ${
                    tab === t.key
                      ? 'bg-background shadow-sm text-foreground'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {/* ── Info tab ─────────────────────────────────────── */}
            {tab === 'info' && (
              <div className="space-y-6">
                <section>
                  <p className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-subtle-foreground">Personal</p>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3">
                    <DetailField label="Date of birth" value={formatDate(p.dob)} />
                    <DetailField label="Age" value={p.age != null ? `${p.age} yrs` : '—'} />
                    <DetailField label="Gender" value={p.gender} />
                    <DetailField label="Blood group" value={p.blood_group} />
                    <DetailField label="Height" value={p.height ? `${p.height} cm` : ''} />
                    <DetailField label="Weight" value={p.weight ? `${p.weight} kg` : ''} />
                  </dl>
                </section>

                <section>
                  <p className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-subtle-foreground">Contact</p>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3">
                    <DetailField label="Phone" value={p.phone} />
                    <DetailField label="Emergency" value={p.emergency_contact} />
                    <DetailField label="Email" value={p.email} />
                  </dl>
                  <div className="mt-4"><DetailField label="Address" value={p.address} /></div>
                </section>

                <section>
                  <p className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-subtle-foreground">Medical</p>
                  <div className="space-y-4">
                    <DetailField label="Allergies" value={p.allergies} />
                    <DetailField label="Current medication" value={p.current_medication} />
                    <DetailField label="Prescription" value={p.prescription} />
                  </div>
                </section>

                <p className="text-xs text-subtle-foreground">Registered {formatDate(p.registration_date)}</p>
              </div>
            )}

            {/* ── Lab reports tab ───────────────────────────────── */}
            {tab === 'lab' && (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <p className="text-sm text-muted-foreground">
                    Uploaded lab reports and OCR processing results for this patient.
                  </p>
                  <LabReportUploadDialog
                    patientId={p.id}
                    queryScope="admin"
                    trigger={
                      <Button size="sm" variant="secondary">
                        <FlaskConical className="size-3.5" />
                        Upload lab report
                      </Button>
                    }
                  />
                </div>

                <DataState
                  isLoading={labReportsQ.isLoading}
                  isError={labReportsQ.isError}
                  isEmpty={labReports.length === 0}
                  onRetry={() => labReportsQ.refetch()}
                  empty={
                    <EmptyState
                      icon={FlaskConical}
                      title="No lab reports yet"
                      description="Upload a laboratory report to auto-extract clinical values."
                      action={
                        <LabReportUploadDialog
                          patientId={p.id}
                          queryScope="admin"
                        />
                      }
                    />
                  }
                >
                  <div className="max-h-80 space-y-2 overflow-y-auto pr-1">
                    {labReports.map((lr) => (
                      <LabReportRow
                        key={lr.id}
                        report={lr}
                        patientId={p.id}
                        queryScope="admin"
                        canDelete
                      />
                    ))}
                  </div>
                </DataState>
              </div>
            )}

            <DialogFooter>
              <DialogClose asChild><Button variant="secondary">Close</Button></DialogClose>
              {tab === 'info' && <Button onClick={onEdit}><Pencil className="size-4" />Edit</Button>}
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

function RowActions({
  patient, onQr, onView, onEdit, onToggle, onDelete,
}: {
  patient: Patient
  onQr: () => void
  onView: () => void
  onEdit: () => void
  onToggle: () => void
  onDelete: () => void
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label="Actions"><MoreHorizontal /></Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={onQr}><QrCode />View QR</DropdownMenuItem>
        <DropdownMenuItem onSelect={onView}><Eye />View details</DropdownMenuItem>
        <DropdownMenuItem onSelect={onEdit}><Pencil />Edit</DropdownMenuItem>
        <DropdownMenuItem onSelect={onToggle}><RefreshCw />{patient.status === 'Active' ? 'Set inactive' : 'Set active'}</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem destructive onSelect={onDelete}><Trash2 />Delete</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
