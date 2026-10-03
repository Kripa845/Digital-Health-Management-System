/**
 * LabReportRow
 * ------------
 * One uploaded report: file info, status, view, download and delete (any status,
 * after a confirmation step), and an
 * expandable area — the processing summary once confirmed, the confirm form
 * while it waits for confirmation, or the reason while it is under review.
 */

import { useState } from 'react'
import { FlaskConical, Download, Eye, Trash2, ChevronDown, ChevronUp, CheckCircle2, ShieldAlert } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose,
} from '@/components/ui/dialog'
import { apiErrorBody, labReportService } from '@/lib/api'
import { formatBytes, formatDate, formatDateTime, saveBlob } from '@/lib/utils'
import type { LabReport } from '@/lib/types'
import { LabReportSummary } from './LabReportSummary'
import { LabReportPreview } from './LabReportPreview'
import { LabReportViewer } from './LabReportViewer'
import { ReportStatusBadge } from './LabStatusBadge'
import { invalidateLab } from './hooks'

interface Props {
  report: LabReport
  patientId: number
  /** Kept for older callers; refreshing is handled centrally. */
  queryScope?: string
  canDelete?: boolean
}

export function LabReportRow({ report, canDelete = true }: Props) {
  const qc = useQueryClient()
  const pending = report.status === 'PENDING_CONFIRMATION' || report.status === 'NO_VALUES_SAVEABLE'
  const savedDocument = report.status === 'SAVED_NO_VALUES'
  const confirmed = report.status === 'CONFIRMED'
  const inReview = report.status === 'NEEDS_REVIEW'
  // A report waiting for confirmation opens straight to its preview.
  const [expanded, setExpanded] = useState(pending)
  const [downloading, setDownloading] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [viewing, setViewing] = useState(false)
  const expandable = confirmed || pending || inReview || savedDocument || report.status === 'REJECTED'

  async function download() {
    setDownloading(true)
    try {
      saveBlob(await labReportService.download(report.id), report.name || `lab-report-${report.id}`)
    } catch (err) {
      toast.error(apiErrorBody(err).message)
    } finally {
      setDownloading(false)
    }
  }

  const deleteMut = useMutation({
    mutationFn: () => labReportService.remove(report.id),
    onSuccess: () => {
      setConfirmDelete(false)
      toast.success(confirmed ? 'Lab report deleted and its values removed from the dashboard.' : 'Lab report deleted.')
      invalidateLab(qc)
      qc.invalidateQueries({ queryKey: ['admin', 'patients'] })
    },
    onError: (err) => toast.error(apiErrorBody(err).message),
  })

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 p-4">
        <span className="grid size-10 shrink-0 place-items-center rounded-[var(--radius-md)] bg-primary-soft text-primary">
          <FlaskConical className="size-5" aria-hidden="true" />
        </span>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{report.name}</p>
          <p className="truncate text-xs text-muted-foreground">
            {report.file_type || '—'}
            {report.size ? ` · ${formatBytes(report.size)}` : ''}
            {' · uploaded '}{formatDateTime(report.uploaded_at)}
            {report.report_date ? ` · report dated ${formatDate(report.report_date)}` : ''}
            {report.uploaded_by_name ? ` · by ${report.uploaded_by_name}` : ''}
          </p>
        </div>

        {confirmed && report.updated_count > 0 && (
          <span className="hidden items-center gap-1 text-xs text-success sm:flex">
            <CheckCircle2 className="size-3" aria-hidden="true" />{report.updated_count} updated
          </span>
        )}

        <ReportStatusBadge status={report.status} />

        {expandable && (
          <Button variant="ghost" size="icon-sm" onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded} aria-label={expanded ? 'Hide details' : pending ? 'Review values' : 'Show details'}>
            {expanded ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
          </Button>
        )}

        {report.status !== 'REJECTED' && (
          <Button variant="ghost" size="icon-sm" onClick={() => setViewing(true)} aria-label="View report">
            <Eye className="size-4" />
          </Button>
        )}

        {report.status !== 'REJECTED' && (
          <Button variant="ghost" size="icon-sm" onClick={download} loading={downloading} aria-label="Download original report">
            {!downloading && <Download className="size-4" />}
          </Button>
        )}

        {canDelete && (
          <Button variant="ghost" size="icon-sm" className="text-danger hover:text-danger"
            onClick={() => setConfirmDelete(true)} aria-label="Delete lab report">
            <Trash2 className="size-4" />
          </Button>
        )}
      </div>

      {expanded && (
        <div className="border-t border-border bg-surface-2/40 px-4 pb-4 pt-3">
          {confirmed && <LabReportSummary report={report} compact />}
          {savedDocument && (
            <p className="text-sm text-muted-foreground">Saved as a document only. No health card values were found, so the dashboard did not change.</p>
          )}
          {pending && (canDelete
            ? <LabReportPreview report={report} />
            : <p className="text-sm text-muted-foreground">Waiting for the patient or an administrator to confirm these values.</p>)}
          {inReview && (
            <div className="space-y-1.5 text-sm" role="status">
              <p className="flex items-center gap-1.5 font-medium"><ShieldAlert className="size-4 text-info" />
                The care team is checking this report. Nothing on the dashboard has changed.</p>
              {!!report.review_messages?.length && (
                <ul className="list-disc pl-5 text-muted-foreground">{report.review_messages.map((m) => <li key={m}>{m}</li>)}</ul>
              )}
            </div>
          )}
          {report.status === 'REJECTED' && (
            <p className="text-sm text-muted-foreground">
              This report was not accepted{report.review_note ? `: ${report.review_note}` : '.'} Nothing was changed and the file was deleted.
            </p>
          )}
        </div>
      )}

      {report.status !== 'REJECTED' && (
        <LabReportViewer report={report} open={viewing} onOpenChange={setViewing} />
      )}

      <Dialog open={confirmDelete} onOpenChange={(o) => { if (!deleteMut.isPending) setConfirmDelete(o) }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Delete lab report?</DialogTitle>
            <DialogDescription>
              {confirmed
                ? `"${report.name}" and the file will be deleted. The values it added are removed from the dashboard and its history; where an earlier report has the same test, that value is shown again.`
                : `"${report.name}" and the file will be deleted. Nothing on the dashboard changes.`}
              {' '}This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild><Button variant="secondary" disabled={deleteMut.isPending}>Cancel</Button></DialogClose>
            <Button variant="danger" loading={deleteMut.isPending} onClick={() => deleteMut.mutate()}>
              {!deleteMut.isPending && <Trash2 className="size-4" />}Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
