/**
 * LabReportUploadDialog
 * ---------------------
 * Upload → the server reads the report and checks the patient ID (and name, age) against
 * the patient → preview of the values (nothing saved yet) → confirm or discard.
 *
 * Props
 *   patientId   – numeric Patient.id to upload for (required)
 *   trigger     – custom trigger element; defaults to a "Upload lab report" Button
 *   onSuccess   – callback fired with the LabReport after the user confirms it
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
import { apiErrorBody, labReportService } from '@/lib/api'
import { invalidateLab } from './hooks'
import { formatBytes } from '@/lib/utils'
import type { LabReport, LabUploadErrorCode } from '@/lib/types'
import { LabReportSummary } from './LabReportSummary'
import { LabReportPreview } from './LabReportPreview'

const MAX_SIZE = 10 * 1024 * 1024 // 10 MB
const ALLOWED = ['pdf', 'png', 'jpg', 'jpeg']

function validateFile(f: File): string | null {
  const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
  if (!ALLOWED.includes(ext)) return 'Unsupported format. Allowed: PDF, PNG, JPG, JPEG.'
  if (f.size > MAX_SIZE) return 'File is too large. Maximum size is 10 MB.'
  return null
}

type Step = 'form' | 'uploading' | 'preview' | 'review' | 'done' | 'error'

const ERROR_HELP: Partial<Record<LabUploadErrorCode | 'network_error', { title: string; hints: string[] }>> = {
  patient_id_mismatch: {
    title: 'Patient ID does not match this patient',
    hints: [
      'Check that you selected the right report and the right patient.',
      'Nothing was saved and the file was not kept.',
    ],
  },
  invalid_file: { title: 'This file cannot be used', hints: ['Upload a PDF, PNG or JPG that is not damaged or renamed.'] },
  file_too_large: { title: 'The file is too large', hints: ['The limit is 10 MB.'] },
  unreadable: {
    title: 'The file could not be read',
    hints: ['Upload a sharper scan or photo', 'Use a machine-printed PDF if the lab provides one', 'Make sure the file is not password-protected'],
  },
  no_text: {
    title: 'No text was found in the file',
    hints: ['Blurry or very dark photo', 'Handwritten report', 'Scan of the wrong page'],
  },
  values_not_usable: {
    title: 'The values on this report could not be used',
    hints: [
      'They are outside the expected ranges or could not be read clearly',
      'Check the report, or enter the values in the patient record instead',
    ],
  },
  network_error: { title: 'Could not reach the server', hints: ['Check the connection and try again.'] },
  server_error: { title: 'Something went wrong', hints: ['Please try again in a moment.'] },
}

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
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<Step>('form')
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState<LabReport | null>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const [errorCode, setErrorCode] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  function reset() {
    setStep('form')
    setName('')
    setFile(null)
    setProgress(0)
    setResult(null)
    setErrorMsg('')
    setErrorCode(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const uploadMut = useMutation({
    mutationFn: () =>
      labReportService.upload(file as File, {
        name: name.trim(),
        patientId,
        // 0-70 = upload transfer; 70-100 is server-side reading
        onProgress: (pct) => setProgress(Math.min(pct * 0.7, 70)),
      }),
    onMutate: () => {
      setStep('uploading')
      setProgress(0)
    },
    onSuccess: (data) => {
      // The report is read and identity-checked but nothing is saved yet:
      // show the preview so the user can confirm or discard it.
      setProgress(100)
      setResult(data)
      setStep(data.status === 'NEEDS_REVIEW' ? 'review' : 'preview')
      if (data.status === 'NO_VALUES_SAVEABLE') toast.info('No card values were found. You can still save this report as a document. Health cards will not change.')
      invalidateLab(qc)
    },
    onError: (err) => {
      const body = apiErrorBody(err)
      // 409 = duplicate already uploaded — surface as a warning, not a failure
      if (body.code === 'duplicate') {
        toast.warning(body.message)
        setOpen(false)
        reset()
        return
      }
      setErrorMsg(body.message)
      setErrorCode(body.code)
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

  // Closing at the preview step keeps the report "awaiting confirmation" in the
  // reports list, where it can still be confirmed or discarded.
  const canClose = step !== 'uploading'

  function handleConfirmed(report: LabReport) {
    setResult(report)
    setStep('done')
    // Make sure every consumer of the patient record refetches.
    qc.invalidateQueries({ queryKey: ['auth', 'me'] })
    if (onSuccess) onSuccess(report)
  }

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
            Upload a PDF or image of a laboratory report. The values are read automatically and
            shown to you for checking before the health cards are updated.
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
                The patient ID on the report must match the patient, or nothing is changed.
                The original file is stored encrypted and can be downloaded later.
              </p>
            </div>

            <DialogFooter>
              <DialogClose asChild>
                <Button type="button" variant="secondary">Cancel</Button>
              </DialogClose>
              <Button type="submit">
                <Upload className="size-4" />
                Upload &amp; read
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
                { label: 'Name and age check', done: progress >= 95 },
                { label: 'Values ready to review', done: progress >= 100 },
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

        {/* ── PREVIEW step: nothing saved until confirmed ───────────── */}
        {step === 'preview' && result && (
          <LabReportPreview
            report={result}
            patientId={patientId}
            queryScope={queryScope}
            onConfirmed={handleConfirmed}
            onDiscarded={() => { setOpen(false); reset() }}
          />
        )}

        {/* ── REVIEW step: identity could not be verified ───────────── */}
        {step === 'review' && result && (
          <div className="space-y-4" role="status">
            <div className="rounded-[var(--radius-md)] border border-info/30 bg-info-soft/40 px-4 py-3 text-sm">
              <p className="font-semibold text-info">Sent for review</p>
              <p className="mt-1 text-muted-foreground">
                The report could not be verified automatically, so nothing was applied. Review it under
                Lab Report Review before the values can be confirmed.
              </p>
              {!!result.review_messages?.length && (
                <ul className="mt-2 list-disc pl-5">{result.review_messages.map((m) => <li key={m}>{m}</li>)}</ul>
              )}
            </div>
            <DialogFooter>
              <Button onClick={() => { setOpen(false); reset() }}>Close</Button>
            </DialogFooter>
          </div>
        )}

        {/* ── DONE step ─────────────────────────────────────────────── */}
        {step === 'done' && result && (
          <div className="space-y-4">
            <div className="flex items-center gap-3 rounded-[var(--radius-md)] border border-success/30 bg-success-soft/40 px-4 py-3">
              <CheckCircle2 className="size-5 shrink-0 text-success" />
              <div>
                <p className="text-sm font-semibold text-success">Health record updated</p>
                <p className="text-xs text-muted-foreground">
                  The report is saved in the history · Original file stored encrypted
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
                <p className="text-sm font-semibold text-danger">
                  {(errorCode && ERROR_HELP[errorCode as LabUploadErrorCode]?.title) || 'The report could not be used'}
                </p>
                <p className="mt-1 text-sm text-muted-foreground">{errorMsg}</p>
                <p className="mt-1 text-xs text-muted-foreground">Nothing was saved.</p>
              </div>
            </div>

            {!!(errorCode ? ERROR_HELP[errorCode as LabUploadErrorCode]?.hints.length : 1) && (
              <div className="rounded-[var(--radius-md)] border border-border bg-surface-2 p-4 text-sm text-muted-foreground space-y-1">
                <p className="font-medium text-foreground">What you can do:</p>
                <ul className="list-disc pl-4 space-y-0.5">
                  {((errorCode ? ERROR_HELP[errorCode as LabUploadErrorCode]?.hints : ERROR_HELP.unreadable?.hints) ?? []).map((h) => (
                    <li key={h}>{h}</li>
                  ))}
                </ul>
              </div>
            )}

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
