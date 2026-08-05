import { useState } from 'react'
import {
  FileText, Upload, Download, Trash2, Pill, Plus, ShieldCheck, FlaskConical,
} from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Field } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Dialog, DialogContent, DialogHeader, DialogFooter, DialogTitle, DialogDescription, DialogTrigger, DialogClose,
} from '@/components/ui/dialog'
import {
  PageHeader, DataState, EmptyState, SectionTitle, ListSkeleton,
} from '@/components/patterns'
import { Skeleton } from '@/components/ui/misc'
import { useAuth } from '@/lib/auth'
import { documentService, prescriptionService, labReportService } from '@/lib/api'
import { formatBytes, formatDate } from '@/lib/utils'
import type { MedDocument } from '@/lib/types'
import { LabReportUploadDialog } from '@/features/lab-reports/LabReportUploadDialog'
import { LabReportRow } from '@/features/lab-reports/LabReportRow'

const MAX_FILE_SIZE = 5 * 1024 * 1024
const ALLOWED_EXT = ['pdf', 'png', 'jpg', 'jpeg']

function validateFile(f: File): string | null {
  const ext = f.name.split('.').pop()?.toLowerCase() || ''
  if (!ALLOWED_EXT.includes(ext)) return 'Unsupported file type. Allowed: PDF, PNG, JPG, JPEG.'
  if (f.size > MAX_FILE_SIZE) return 'File is too large. Maximum size is 5MB.'
  return null
}

function UploadDialog({ patientId }: { patientId: number }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)

  function reset() { setName(''); setFile(null) }

  const uploadM = useMutation({
    mutationFn: () => documentService.upload(patientId, name.trim(), file as File, 'ADDITIONAL'),
    onSuccess: () => {
      toast.success('Report uploaded.')
      qc.invalidateQueries({ queryKey: ['patient', 'documents', patientId] })
      reset()
      setOpen(false)
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Could not upload the report.'),
  })

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return toast.error('Please enter a report name.')
    if (!file) return toast.error('Please choose a file.')
    const err = validateFile(file)
    if (err) return toast.error(err)
    uploadM.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) reset() }}>
      <DialogTrigger asChild>
        <Button><Plus className="size-4" /> Upload report</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Upload a report</DialogTitle>
          <DialogDescription>Add your own additional report — PDF, PNG, or JPG up to 5MB.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <Field label="Report name" htmlFor="doc-name" required>
            <Input id="doc-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Blood test, X-Ray, MRI report" />
          </Field>
          <Field label="File" htmlFor="doc-file" required hint="PDF, PNG, JPG or JPEG · max 5MB">
            <Input
              id="doc-file"
              type="file"
              accept=".pdf,.png,.jpg,.jpeg"
              onChange={(e) => {
                const f = e.target.files?.[0] || null
                if (f) {
                  const err = validateFile(f)
                  if (err) { toast.error(err); e.target.value = ''; setFile(null); return }
                }
                setFile(f)
              }}
            />
          </Field>
          {file && <p className="text-xs text-muted-foreground">Selected: {file.name} ({formatBytes(file.size)})</p>}
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="secondary">Cancel</Button>
            </DialogClose>
            <Button type="submit" loading={uploadM.isPending}><Upload className="size-4" /> Upload</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function ReportRow({ doc, patientId }: { doc: MedDocument; patientId: number }) {
  const qc = useQueryClient()
  const [downloading, setDownloading] = useState(false)

  async function download() {
    setDownloading(true)
    try {
      const blob = await documentService.download(doc.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = doc.name || `report-${doc.id}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch {
      toast.error('Could not download the report.')
    } finally {
      setDownloading(false)
    }
  }

  const deleteM = useMutation({
    mutationFn: () => documentService.remove(doc.id),
    onSuccess: () => {
      toast.success('Report deleted.')
      qc.invalidateQueries({ queryKey: ['patient', 'documents', patientId] })
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Could not delete the report.'),
  })

  const isMedical = doc.report_type === 'MEDICAL'

  return (
    <Card className="p-4">
      <div className="flex items-center gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-[var(--radius-md)] bg-info-soft text-info">
          <FileText className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{doc.name}</p>
          <p className="truncate text-xs text-muted-foreground">
            {doc.file_type || '—'} · {formatBytes(doc.size)} · {formatDate(doc.uploaded_at)}
          </p>
        </div>
        <Badge variant={isMedical ? 'primary' : 'neutral'}>{isMedical ? 'Medical' : 'Additional'}</Badge>
        <Button variant="ghost" size="icon-sm" onClick={download} loading={downloading} aria-label="Download report">
          {!downloading && <Download className="size-4" />}
        </Button>
        {!isMedical && (
          <Button variant="ghost" size="icon-sm" className="text-danger hover:text-danger" onClick={() => deleteM.mutate()} loading={deleteM.isPending} aria-label="Delete report">
            {!deleteM.isPending && <Trash2 className="size-4" />}
          </Button>
        )}
      </div>
    </Card>
  )
}

export function PatientReports() {
  const { user, loading } = useAuth()
  const patient = user?.patient_profile
  const patientId = patient?.id

  const documentsQ = useQuery({
    queryKey: ['patient', 'documents', patientId],
    queryFn: () => documentService.list({ patient: patientId }),
    enabled: !!patientId,
  })
  const prescriptionsQ = useQuery({
    queryKey: ['patient', 'prescriptions', patientId],
    queryFn: () => prescriptionService.list({ patient: patientId }),
    enabled: !!patientId,
  })
  const labReportsQ = useQuery({
    queryKey: ['patient', 'lab-reports', patientId],
    queryFn: () => labReportService.list({ patient: patientId }),
    enabled: !!patientId,
  })

  const reports = documentsQ.data ?? []
  const prescriptions = prescriptionsQ.data ?? []
  const labReports = labReportsQ.data ?? []

  if (loading) {
    return (
      <div className="space-y-8">
        <Skeleton className="h-16 w-72" />
        <ListSkeleton />
      </div>
    )
  }

  if (!patient || !patientId) {
    return (
      <div className="space-y-8">
        <PageHeader title="Reports" icon={FileText} description="Your medical reports and prescriptions." />
        <EmptyState icon={FileText} title="No patient profile found" description="Your account isn't linked to a patient record yet. Please contact your care team." />
      </div>
    )
  }

  return (
    <div className="space-y-10">
      <PageHeader
        title="Reports & prescriptions"
        description="Upload laboratory reports, view medical documents, and review prescriptions from your care team."
        icon={FileText}
        actions={
          <div className="flex flex-wrap gap-2">
            <LabReportUploadDialog patientId={patientId} queryScope="patient" />
            <UploadDialog patientId={patientId} />
          </div>
        }
      />

      {/* ── Lab Reports ─────────────────────────────────────────────── */}
      <section className="space-y-3">
        <SectionTitle
          action={<LabReportUploadDialog patientId={patientId} queryScope="patient" trigger={
            <Button variant="secondary" size="sm"><FlaskConical className="size-3.5" />Upload lab report</Button>
          } />}
        >
          Laboratory reports
        </SectionTitle>
        <DataState
          isLoading={labReportsQ.isLoading}
          isError={labReportsQ.isError}
          isEmpty={labReports.length === 0}
          onRetry={() => labReportsQ.refetch()}
          empty={
            <EmptyState
              icon={FlaskConical}
              title="No laboratory reports yet"
              description="Upload a blood test, imaging report, or any lab result. The system will automatically extract clinical values and update your health record."
              action={<LabReportUploadDialog patientId={patientId} queryScope="patient" />}
            />
          }
        >
          <div className="space-y-3">
            {labReports.map((lr) => (
              <LabReportRow key={lr.id} report={lr} patientId={patientId} queryScope="patient" canDelete />
            ))}
          </div>
        </DataState>
      </section>

      {/* ── General documents ───────────────────────────────────────── */}
      <section className="space-y-3">
        <SectionTitle action={<UploadDialog patientId={patientId} />}>My reports</SectionTitle>
        <DataState
          isLoading={documentsQ.isLoading}
          isError={documentsQ.isError}
          isEmpty={reports.length === 0}
          onRetry={() => documentsQ.refetch()}
          empty={
            <EmptyState
              icon={FileText}
              title="No reports yet"
              description="Medical reports added by your care team and your own uploads will appear here."
              action={<UploadDialog patientId={patientId} />}
            />
          }
        >
          <div className="space-y-3">
            {reports.map((d) => <ReportRow key={d.id} doc={d} patientId={patientId} />)}
          </div>
        </DataState>
      </section>

      {/* ── Prescriptions ───────────────────────────────────────────── */}
      <section className="space-y-3">
        <SectionTitle>Prescriptions</SectionTitle>
        <DataState
          isLoading={prescriptionsQ.isLoading}
          isError={prescriptionsQ.isError}
          isEmpty={prescriptions.length === 0}
          onRetry={() => prescriptionsQ.refetch()}
          empty={<EmptyState icon={Pill} title="No prescriptions yet" description="Prescriptions issued by your clinicians will appear here." />}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            {prescriptions.map((rx) => (
              <Card key={rx.id}>
                <CardContent className="space-y-3 p-5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="grid size-9 place-items-center rounded-[var(--radius-md)] bg-success-soft text-success">
                        <Pill className="size-4.5" />
                      </span>
                      <span className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">Prescription</span>
                    </div>
                    <span className="text-xs text-muted-foreground">{formatDate(rx.prescription_date)}</span>
                  </div>
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-subtle-foreground">Diagnosis</p>
                    <p className="text-sm font-medium text-pretty">{rx.diagnosis}</p>
                  </div>
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-subtle-foreground">Medications</p>
                    <p className="text-sm text-muted-foreground text-pretty leading-relaxed">{rx.medications}</p>
                  </div>
                  {rx.notes && (
                    <div>
                      <p className="text-xs font-medium uppercase tracking-wide text-subtle-foreground">Notes</p>
                      <p className="text-sm text-muted-foreground text-pretty leading-relaxed">{rx.notes}</p>
                    </div>
                  )}
                  {rx.doctor_name && (
                    <p className="border-t border-border pt-3 text-xs text-muted-foreground">Issued by {rx.doctor_name}</p>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </DataState>
      </section>

      <div className="flex items-start gap-3 rounded-[var(--radius-md)] border border-border bg-surface-2/50 p-4">
        <ShieldCheck className="mt-0.5 size-5 shrink-0 text-primary" />
        <p className="text-sm text-muted-foreground text-pretty">
          Medical reports and prescriptions are managed by your care team. You can upload and remove your own
          additional reports, but clinical records stay read-only to keep them accurate.
        </p>
      </div>
    </div>
  )
}
