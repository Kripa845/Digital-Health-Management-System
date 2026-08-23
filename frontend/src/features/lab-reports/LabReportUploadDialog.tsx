/**
 * LabReportUploadDialog
 * ---------------------
 * Reusable upload dialog that runs the full OCR + CDSA pipeline on the
 * backend and surfaces the processing summary to the user.
 *
 * Props
 *   patientId   – numeric Patient.id to upload for (required)
 *   trigger     – custom trigger element; defaults to a "Upload lab report" Button
 *   onSuccess   – callback fired with the completed LabReport after processing
 */

import { useRef, useState } from 'react'
import {
  FlaskConical, Upload, X, FileText, Loader2, CheckCircle2, AlertCircle, Info,
} from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Field } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
  DialogFooter, DialogClose,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { labReportService } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { formatBytes } from '@/lib/utils'
import type { LabReport } from '@/lib/types'
import { LabReportSummary } from './LabReportSummary'

const MAX_SIZE = 10 * 1024 * 1024 // 10 MB
const ALLOWED = ['pdf', 'png', 'jpg', 'jpeg']

function validateFile(f: File): string | null {
  const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
  if (!ALLOWED.includes(ext)) return 'Unsupported format. Allowed: PDF, PNG, JPG, JPEG.'
  if (f.size > MAX_SIZE) return 'File is too large. Maximum size is 10 MB.'
  return null
}

type Step = 'form' | 'uploading' | 'processing' | 'done' | 'error'

interface Props {
  patientId: number
  trigger?: React.ReactNode
  /** invalidation key prefix – pass 'admin' or 'patient' */
  queryScope?: string
  onSuccess?: (report: LabReport) => void
}

export function LabReportUploadDialog({
  patientId,
  trigger,
  queryScope = 'patient',
  onSuccess,
}: Props) {
  const qc = useQueryClient()
  const { refresh: refreshAuth } = useAuth()
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<Step>('form')
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState<LabReport | null>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  function reset() {
    setStep('form')
    setName('')
    setFile(null)
    setProgress(0)
    setResult(null)
    setErrorMsg('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const uploadMut = useMutation({
    mutationFn: () =>
      labReportService.upload(patientId, name.trim(), file as File, (pct) => {
        // 0-70 = upload transfer; 70-100 is server-side OCR (we fake-animate later)
        setProgress(Math.min(pct * 0.7, 70))
      }),
    onMutate: () => {
      setStep('uploading')
      setProgress(0)
    },
    onSuccess: async (data) => {
      setProgress(100)
      setResult(data)
      setStep('done')

      // 1. Refresh the AuthProvider's user state — this is what drives
      //    user.patient_profile in every component that calls useAuth().
      //    Awaiting it means the new vitals are in React state before the
      //    user dismisses the dialog and navigates back to the dashboard.
      await refreshAuth()

      // 2. Invalidate TanStack Query caches so any other consumers
      //    (lab-report list, patient records) also refetch.
      qc.invalidateQueries({ queryKey: [queryScope, 'lab-reports', patientId] })
      qc.invalidateQueries({ queryKey: [queryScope, 'lab-reports'] })
      qc.invalidateQueries({ queryKey: ['auth', 'me'] })
      qc.invalidateQueries({ queryKey: [queryScope, 'patients'] })

      if (onSuccess) onSuccess(data)
    },
    onError: (err: any) => {
      const httpStatus = err?.response?.status
      const detail =
        err?.response?.data?.detail ||
        err?.response?.data?.file?.[0] ||
        err?.response?.data?.name?.[0] ||
        err?.message ||
        'Upload failed. Please try again.'

      // 409 = duplicate already completed — surface as a warning, not a failure
      if (httpStatus === 409) {
        toast.warning(detail)
        setOpen(false)
        reset()
        return
      }

      setErrorMsg(detail)
      setStep('error')
    },
  })

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null
    if (!f) { setFile(null); return }
    const err = validateFile(f)
    if (err) {
      toast.error(err)
      e.target.value = ''
      setFile(null)
      return
    }
    setFile(f)
    // Auto-fill name from filename if the user hasn't typed one yet
    if (!name.trim()) {
      const withoutExt = f.name.replace(/\.[^.]+$/, '').replace(/[-_]/g, ' ')
      setName(withoutExt.charAt(0).toUpperCase() + withoutExt.slice(1))
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) { toast.error('Please enter a report name.'); return }
    if (!file) { toast.error('Please select a file.'); return }
    const err = validateFile(file)
    if (err) { toast.error(err); return }
    uploadMut.mutate()
  }

  const canClose = step === 'form' || step === 'done' || step === 'error'

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o && !canClose) return // block close while in flight
        setOpen(o)
        if (!o) reset()
      }}
    >
      {/* Trigger */}
      <span onClick={() => setOpen(true)} style={{ display: 'contents', cursor: 'pointer' }}>
        {trigger ?? (
          <Button type="button">
            <FlaskConical className="size-4" />
            Upload lab report
          </Button>
        )}
      </span>

      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FlaskConical className="size-5 text-primary" />
            Upload laboratory report
          </DialogTitle>
          <DialogDescription>
            Upload a PDF or image of a laboratory report. The system will automatically
            extract clinical values and update the patient's health record.
          </DialogDescription>
        </DialogHeader>

        {/* ── FORM step ─────────────────────────────────────────────── */}
        {step === 'form' && (
          <form onSubmit={handleSubmit} className="space-y-4">
            <Field label="Report name" htmlFor="lr-name" required>
              <Input
                id="lr-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Complete Blood Count, Lipid Profile"
                maxLength={255}
              />
            </Field>

            <Field
              label="File"
              htmlFor="lr-file"
              required
              hint="PDF, PNG, JPG or JPEG · max 10 MB"
            >
              <Input
                id="lr-file"
                ref={fileInputRef}
                type="file"
                accept=".pdf,.png,.jpg,.jpeg"
                onChange={handleFileChange}
              />
            </Field>

            {/* File preview strip */}
            {file && (
              <div className="flex items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface-2 px-3.5 py-2.5">
                <FileText className="size-5 shrink-0 text-info" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{file.name}</p>
                  <p className="text-xs text-muted-foreground">{formatBytes(file.size)}</p>
                </div>
                <Badge variant="info">{file.name.split('.').pop()?.toUpperCase()}</Badge>
                <button
                  type="button"
                  className="text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    setFile(null)
                    if (fileInputRef.current) fileInputRef.current.value = ''
                  }}
                  aria-label="Remove file"
                >
                  <X className="size-4" />
                </button>
              </div>
            )}

            {/* Info callout */}
            <div className="flex items-start gap-2.5 rounded-[var(--radius-md)] border border-info/30 bg-info-soft/40 px-3.5 py-3 text-sm text-info">
              <Info className="mt-0.5 size-4 shrink-0" />
              <p>
                The original file will be stored unchanged. OCR extracts clinical values
                automatically — the report itself is never modified.
              </p>
            </div>

            <DialogFooter>
              <DialogClose asChild>
                <Button type="button" variant="secondary">Cancel</Button>
              </DialogClose>
              <Button type="submit">
                <Upload className="size-4" />
                Upload &amp; process
              </Button>
            </DialogFooter>
          </form>
        )}

        {/* ── UPLOADING / PROCESSING step ───────────────────────────── */}
        {(step === 'uploading') && (
          <div className="space-y-6 py-4">
            <div className="flex flex-col items-center gap-4 text-center">
              <span className="grid size-16 place-items-center rounded-full bg-primary-soft text-primary">
                <Loader2 className="size-8 animate-spin" />
              </span>
              <div>
                <p className="font-semibold">
                  {progress < 70 ? 'Uploading report…' : 'Running OCR & extracting values…'}
                </p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {progress < 70
                    ? 'Transferring your file securely.'
                    : 'Reading clinical data — this may take a few seconds.'}
                </p>
              </div>
            </div>

            {/* Progress bar */}
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>
                  {progress < 30 ? 'Uploading…' : progress < 70 ? 'Transfer complete' : 'Analysing report…'}
                </span>
                <span>{Math.round(progress)}%</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full bg-primary transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>

            {/* Steps indicator */}
            <ol className="space-y-2">
              {[
                { label: 'File uploaded', done: progress >= 70 },
                { label: 'OCR text extraction', done: progress >= 85 },
                { label: 'Medical value extraction', done: progress >= 95 },
                { label: 'Patient record update (CDSA)', done: progress >= 100 },
              ].map((s) => (
                <li key={s.label} className="flex items-center gap-2.5 text-sm">
                  {s.done
                    ? <CheckCircle2 className="size-4 shrink-0 text-success" />
                    : <span className="size-4 shrink-0 rounded-full border-2 border-border" />}
                  <span className={s.done ? 'text-foreground' : 'text-muted-foreground'}>{s.label}</span>
                </li>
              ))}
            </ol>
          </div>
        )}

        {/* ── DONE step ─────────────────────────────────────────────── */}
        {step === 'done' && result && (
          <div className="space-y-4">
            <div className="flex items-center gap-3 rounded-[var(--radius-md)] border border-success/30 bg-success-soft/40 px-4 py-3">
              <CheckCircle2 className="size-5 shrink-0 text-success" />
              <div>
                <p className="text-sm font-semibold text-success">Lab report processed successfully</p>
                <p className="text-xs text-muted-foreground">
                  Patient health record updated · Original file stored unchanged
                </p>
              </div>
            </div>

            <LabReportSummary report={result} />

            <DialogFooter>
              <Button
                onClick={() => { setOpen(false); reset() }}
                className="w-full sm:w-auto"
              >
                Done
              </Button>
            </DialogFooter>
          </div>
        )}

        {/* ── ERROR step ────────────────────────────────────────────── */}
        {step === 'error' && (
          <div className="space-y-4">
            <div className="flex items-start gap-3 rounded-[var(--radius-md)] border border-danger/30 bg-danger-soft/40 px-4 py-3">
              <AlertCircle className="mt-0.5 size-5 shrink-0 text-danger" />
              <div>
                <p className="text-sm font-semibold text-danger">Processing failed</p>
                <p className="mt-1 text-sm text-muted-foreground">{errorMsg}</p>
              </div>
            </div>

            <div className="rounded-[var(--radius-md)] border border-border bg-surface-2 p-4 text-sm text-muted-foreground space-y-1">
              <p className="font-medium text-foreground">Common causes:</p>
              <ul className="list-disc pl-4 space-y-0.5">
                <li>Blurry or low-resolution scan</li>
                <li>Handwritten report (not machine-printed)</li>
                <li>Unsupported language or non-standard layout</li>
                <li>Tesseract OCR not installed on the server</li>
              </ul>
            </div>

            <DialogFooter>
              <Button variant="secondary" onClick={reset}>Try again</Button>
              <Button onClick={() => { setOpen(false); reset() }}>Close</Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
