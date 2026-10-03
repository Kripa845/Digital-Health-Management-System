import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertCircle, FlaskConical, Info, RotateCcw, ShieldAlert, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Field } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/patterns'
import { apiErrorBody } from '@/lib/api'
import type { LabReport } from '@/lib/types'
import { FileDropzone } from './FileDropzone'
import { useUploadReport } from './hooks'

// Titles for the error codes the server returns; the server's message is shown under it.
const ERROR_TITLES: Record<string, string> = {
  patient_id_mismatch: 'Patient ID does not match this account',
  duplicate: 'This report was already uploaded',
  invalid_file: 'This file cannot be used',
  file_too_large: 'The file is too large',
  unreadable: 'The file could not be read',
  no_text: 'No text was found in the file',
  values_not_usable: 'The values on this report could not be used',
  network_error: 'Could not reach the server',
}

export function LabUploadPage() {
  const navigate = useNavigate()
  const upload = useUploadReport()
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [progress, setProgress] = useState(0)
  const [review, setReview] = useState<LabReport | null>(null)

  const error = upload.error ? apiErrorBody(upload.error) : null

  function start() {
    if (!file || fileError) return
    setProgress(0)
    upload.mutate({ file, name: name || file.name.replace(/\.[^.]+$/, ''), onProgress: setProgress }, {
      onSuccess: (report) => {
        if (report.status === 'NO_VALUES_SAVEABLE') toast.info('No card values were found. You can still save this report as a document. Health cards will not change.')
        if (report.status === 'PENDING_CONFIRMATION' || report.status === 'NO_VALUES_SAVEABLE') {
          navigate(`/patient/lab-reports/${report.id}/confirm`)
        } else setReview(report)
      },
    })
  }

  function reset() {
    upload.reset()
    setReview(null)
    setFile(null)
    setFileError(null)
    setProgress(0)
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <PageHeader
        title="Upload a lab report"
        description="Your report is read automatically. You check the values before anything on your dashboard changes."
        icon={FlaskConical}
      />

      {review ? (
        <Card>
          <CardContent className="space-y-4 p-6" role="status">
            <div className="flex items-start gap-3">
              <ShieldAlert className="mt-0.5 size-6 shrink-0 text-info" aria-hidden="true" />
              <div className="space-y-1">
                <h2 className="font-semibold">Your report is being checked by the care team</h2>
                <p className="text-sm text-muted-foreground">
                  We couldn't confirm automatically that this report is yours, so a member of the care team will check
                  it. You'll get a notification when it's ready for you to confirm. Nothing on your dashboard has changed.
                </p>
                {!!review.review_messages?.length && (
                  <ul className="list-disc pl-5 text-sm">{review.review_messages.map((m) => <li key={m}>{m}</li>)}</ul>
                )}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button asChild variant="secondary"><Link to="/patient/lab-reports">View my reports</Link></Button>
              <Button onClick={reset}>Upload another report</Button>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="space-y-5 p-6">
            <FileDropzone
              file={file}
              disabled={upload.isPending}
              onFile={(f, err) => { upload.reset(); setFile(err ? null : f); setFileError(err) }}
            />
            {fileError && <p role="alert" className="text-sm text-danger">{fileError}</p>}

            <Field label="Report name (optional)" htmlFor="lab-name" hint="For example: Lipid profile, Complete blood count">
              <Input id="lab-name" value={name} maxLength={255} disabled={upload.isPending}
                onChange={(e) => setName(e.target.value)} />
            </Field>

            <div className="flex items-start gap-2.5 rounded-[var(--radius-md)] border border-info/30 bg-info-soft/40 px-3.5 py-3 text-sm text-info">
              <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <p>The report must show your Mero Care Card patient ID. If it doesn't, the care team checks it before you can confirm the values.</p>
            </div>

            {upload.isPending && (
              <div className="space-y-1.5" aria-live="polite">
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>{progress < 100 ? 'Uploading…' : 'Reading your report…'}</span>
                  <span>{progress}%</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2" role="progressbar"
                  aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress} aria-label="Upload progress">
                  <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${progress}%` }} />
                </div>
              </div>
            )}

            {error && (
              <div role="alert" className="flex items-start gap-3 rounded-[var(--radius-md)] border border-danger/30 bg-danger-soft/40 px-4 py-3">
                <AlertCircle className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden="true" />
                <div className="space-y-1 text-sm">
                  <p className="font-semibold text-danger">{ERROR_TITLES[error.code] ?? 'Upload failed'}</p>
                  <p className="text-muted-foreground">{error.message}</p>
                  {error.code === 'patient_id_mismatch' && (
                    <p className="text-muted-foreground">Nothing was saved. Check that this is your report.</p>
                  )}
                  {error.code === 'duplicate' && (
                    <Link to="/patient/lab-reports" className="font-medium text-primary underline">See your reports</Link>
                  )}
                </div>
              </div>
            )}

            <div className="flex flex-wrap justify-end gap-2">
              <Button asChild variant="secondary"><Link to="/patient/lab-reports">Cancel</Link></Button>
              {error?.code === 'network_error' ? (
                <Button onClick={start}><RotateCcw className="size-4" />Retry</Button>
              ) : (
                <Button onClick={start} disabled={!file || !!fileError} loading={upload.isPending}>
                  {!upload.isPending && <Upload className="size-4" />}
                  Upload and read
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
