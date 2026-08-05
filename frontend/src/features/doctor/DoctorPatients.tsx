import { useState } from 'react'
import { Users, Search, Eye, FileText, Download, Pill, Plus, HeartPulse } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Field } from '@/components/ui/label'
import { UserAvatar } from '@/components/ui/avatar'
import { Separator } from '@/components/ui/misc'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from '@/components/ui/dialog'
import {
  PageHeader, DataState, EmptyState, InfoRow, SectionTitle, ListSkeleton,
} from '@/components/patterns'
import { ActiveStatusBadge } from '@/components/status-badge'
import { documentService, patientService, prescriptionService } from '@/lib/api'
import { formatBytes, formatDate, formatDateTime } from '@/lib/utils'
import type { MedDocument, Patient, Prescription } from '@/lib/types'

export function DoctorPatients() {
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Patient | null>(null)

  const patientsQ = useQuery({
    queryKey: ['doctor', 'patients', search],
    queryFn: () => patientService.list(search.trim() ? { search: search.trim() } : undefined),
  })
  const patients = patientsQ.data ?? []

  return (
    <div className="space-y-8">
      <PageHeader
        title="My patients"
        description="Patients under your active care. Open a record to view full medical details and manage prescriptions."
        icon={Users}
      />

      <div className="relative max-w-md">
        <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name, ID, phone…"
          className="pl-10"
        />
      </div>

      <DataState
        isLoading={patientsQ.isLoading}
        isError={patientsQ.isError}
        isEmpty={patients.length === 0}
        onRetry={patientsQ.refetch}
        empty={<EmptyState icon={Users} title="No patients found"
          description={search ? 'No patients match your search.' : 'Patients assigned to you will appear here.'} />}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {patients.map((p) => (
            <Card key={p.id} className="transition-shadow hover:shadow-[var(--shadow-md)]">
              <CardContent className="flex items-center gap-3 p-4">
                <UserAvatar name={`${p.first_name} ${p.last_name}`} src={p.photo || undefined} className="size-11" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold">{p.first_name} {p.last_name}</p>
                  <p className="truncate text-xs text-muted-foreground font-mono">{p.patient_id}</p>
                  <div className="mt-1.5 flex items-center gap-2">
                    <ActiveStatusBadge status={p.status} />
                    <span className="text-xs text-subtle-foreground">{p.blood_group} · {p.age ?? '—'} yrs</span>
                  </div>
                </div>
                <Button size="icon-sm" variant="ghost" aria-label="View record" onClick={() => setSelected(p)}>
                  <Eye className="size-4" />
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      </DataState>

      <PatientDialog patient={selected} onOpenChange={(open) => !open && setSelected(null)} />
    </div>
  )
}

function PatientDialog({ patient, onOpenChange }: { patient: Patient | null; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={!!patient} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        {patient && <PatientDetail patient={patient} />}
      </DialogContent>
    </Dialog>
  )
}

function PatientDetail({ patient }: { patient: Patient }) {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [diagnosis, setDiagnosis] = useState('')
  const [medications, setMedications] = useState('')
  const [notes, setNotes] = useState('')

  const fullQ = useQuery({
    queryKey: ['doctor', 'patient', patient.id],
    queryFn: () => patientService.retrieve(patient.id),
    initialData: patient,
  })
  const docsQ = useQuery({
    queryKey: ['doctor', 'patient', patient.id, 'documents'],
    queryFn: () => documentService.list({ patient: patient.id }),
  })
  const rxQ = useQuery({
    queryKey: ['doctor', 'patient', patient.id, 'prescriptions'],
    queryFn: () => prescriptionService.list({ patient: patient.id }),
  })

  const p = fullQ.data
  const docs: MedDocument[] = docsQ.data ?? []
  const prescriptions: Prescription[] = rxQ.data ?? []

  const createRx = useMutation({
    mutationFn: () => prescriptionService.create({
      patient: patient.id,
      diagnosis: diagnosis.trim(),
      medications: medications.trim(),
      notes: notes.trim() || undefined,
    }),
    onSuccess: () => {
      toast.success('Prescription added.')
      setDiagnosis(''); setMedications(''); setNotes(''); setShowForm(false)
      qc.invalidateQueries({ queryKey: ['doctor', 'patient', patient.id, 'prescriptions'] })
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Could not add the prescription.'),
  })

  function submitRx(e: React.FormEvent) {
    e.preventDefault()
    if (!diagnosis.trim() || !medications.trim()) {
      toast.error('Diagnosis and medications are required.')
      return
    }
    createRx.mutate()
  }

  return (
    <>
      <DialogHeader>
        <div className="flex items-center gap-3">
          <UserAvatar name={`${p.first_name} ${p.last_name}`} src={p.photo || undefined} className="size-12" />
          <div className="min-w-0">
            <DialogTitle>{p.first_name} {p.middle_name ? `${p.middle_name} ` : ''}{p.last_name}</DialogTitle>
            <DialogDescription className="font-mono">{p.patient_id}</DialogDescription>
          </div>
        </div>
      </DialogHeader>

      {/* Medical details */}
      <section className="space-y-3">
        <SectionTitle>Medical details</SectionTitle>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3">
          <InfoRow label="Age" value={p.age != null ? `${p.age} yrs` : '—'} />
          <InfoRow label="Gender" value={p.gender} />
          <InfoRow label="Blood group" value={p.blood_group} />
          <InfoRow label="Date of birth" value={formatDate(p.dob)} />
          <InfoRow label="Phone" value={p.phone} mono />
          <InfoRow label="Emergency" value={p.emergency_contact} mono />
          <InfoRow label="Height" value={p.height ? `${p.height} cm` : '—'} />
          <InfoRow label="Weight" value={p.weight ? `${p.weight} kg` : '—'} />
          <InfoRow label="Status" value={p.status} />
          <InfoRow label="Address" value={p.address} />
          <InfoRow label="Allergies" value={p.allergies || 'None recorded'} />
          <InfoRow label="Current medication" value={p.current_medication || 'None recorded'} />
        </dl>
      </section>

      <Separator />

      {/* Documents */}
      <section className="space-y-3">
        <SectionTitle>Documents</SectionTitle>
        <DataState
          isLoading={docsQ.isLoading}
          isError={docsQ.isError}
          isEmpty={docs.length === 0}
          onRetry={docsQ.refetch}
          skeleton={<ListSkeleton rows={2} />}
          empty={<EmptyState icon={FileText} title="No documents" description="This patient has no uploaded reports." />}
        >
          <ul className="space-y-2">
            {docs.map((d) => (
              <li key={d.id} className="flex items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-[var(--radius-md)] bg-surface-2 text-muted-foreground">
                  <FileText className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{d.name}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {d.report_type === 'MEDICAL' ? 'Medical report' : 'Additional report'}
                    {d.size ? ` · ${formatBytes(d.size)}` : ''}
                  </p>
                </div>
                <Button asChild size="icon-sm" variant="ghost" aria-label="Open document">
                  <a href={d.file} target="_blank" rel="noopener noreferrer"><Download className="size-4" /></a>
                </Button>
              </li>
            ))}
          </ul>
        </DataState>
      </section>

      <Separator />

      {/* Prescriptions */}
      <section className="space-y-3">
        <SectionTitle action={
          !showForm && (
            <Button size="sm" variant="soft" onClick={() => setShowForm(true)}>
              <Plus className="size-4" /> Add prescription
            </Button>
          )
        }>Prescriptions</SectionTitle>

        {showForm && (
          <form onSubmit={submitRx} className="space-y-4 rounded-[var(--radius-md)] border border-border bg-surface-2/50 p-4">
            <Field label="Diagnosis" htmlFor="rx-diagnosis" required>
              <Textarea id="rx-diagnosis" rows={2} value={diagnosis}
                onChange={(e) => setDiagnosis(e.target.value)} placeholder="Primary diagnosis…" />
            </Field>
            <Field label="Medications" htmlFor="rx-medications" required>
              <Textarea id="rx-medications" rows={2} value={medications}
                onChange={(e) => setMedications(e.target.value)} placeholder="One medication per line…" />
            </Field>
            <Field label="Notes" htmlFor="rx-notes" hint="Optional guidance for the patient.">
              <Textarea id="rx-notes" rows={2} value={notes}
                onChange={(e) => setNotes(e.target.value)} placeholder="Dosage instructions, follow-up…" />
            </Field>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={() => setShowForm(false)}>Cancel</Button>
              <Button type="submit" size="sm" loading={createRx.isPending}>Save prescription</Button>
            </div>
          </form>
        )}

        <DataState
          isLoading={rxQ.isLoading}
          isError={rxQ.isError}
          isEmpty={prescriptions.length === 0}
          onRetry={rxQ.refetch}
          skeleton={<ListSkeleton rows={2} />}
          empty={<EmptyState icon={Pill} title="No prescriptions" description="Prescriptions you record will appear here." />}
        >
          <ul className="space-y-2.5">
            {prescriptions.map((rx) => (
              <li key={rx.id} className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-subtle-foreground">
                    <HeartPulse className="size-3.5" /> Prescription
                  </span>
                  <span className="text-xs text-muted-foreground">{formatDateTime(rx.prescription_date)}</span>
                </div>
                <p className="text-sm font-medium">Diagnosis: {rx.diagnosis}</p>
                <p className="mt-0.5 text-sm text-muted-foreground">Medications: {rx.medications}</p>
                {rx.notes && <p className="mt-0.5 text-sm text-muted-foreground">Notes: {rx.notes}</p>}
                {rx.doctor_name && <p className="mt-2 text-xs text-subtle-foreground">— {rx.doctor_name}</p>}
              </li>
            ))}
          </ul>
        </DataState>
      </section>
    </>
  )
}
