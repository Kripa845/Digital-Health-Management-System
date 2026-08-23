/**
 * LabReportRow
 * ------------
 * A single row in the lab reports list showing file info, processing status,
 * summary counts, download button, and expandable processing summary.
 */

import { useState } from 'react'
import {
  FlaskConical, Download, Trash2, ChevronDown, ChevronUp,
  CheckCircle2, AlertCircle, Loader2, Clock,
} from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { labReportService } from '@/lib/api'
import { formatBytes, formatDate } from '@/lib/utils'
import type { LabReport } from '@/lib/types'
import { LabReportSummary } from './LabReportSummary'

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: LabReport['status'] }) {
  switch (status) {
    case 'COMPLETED':
      return <Badge variant="success"><CheckCircle2 />Processed</Badge>
    case 'PROCESSING':
      return <Badge variant="info"><Loader2 className="animate-spin" />Processing</Badge>
    case 'FAILED':
      return <Badge variant="danger"><AlertCircle />Failed</Badge>
    default:
      return <Badge variant="neutral"><Clock />Pending</Badge>
  }
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

interface Props {
  report: LabReport
  patientId: number
  queryScope?: string
  canDelete?: boolean
}

export function LabReportRow({ report, patientId, queryScope = 'patient', canDelete = true }: Props) {
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const [downloading, setDownloading] = useState(false)

  async function download() {
    setDownloading(true)
    try {
      const blob = await labReportService.download(report.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = report.name || `lab-report-${report.id}`
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

  const deleteMut = useMutation({
    mutationFn: () => labReportService.remove(report.id),
    onSuccess: () => {
      toast.success('Lab report deleted.')
      qc.invalidateQueries({ queryKey: [queryScope, 'lab-reports', patientId] })
    },
    onError: (err: any) =>
      toast.error(err?.response?.data?.detail || 'Could not delete the report.'),
  })

  return (
    <Card className="overflow-hidden">
      {/* Main row */}
      <div className="flex items-center gap-3 p-4">
        <span className="grid size-10 shrink-0 place-items-center rounded-[var(--radius-md)] bg-primary-soft text-primary">
          <FlaskConical className="size-5" />
        </span>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{report.name}</p>
          <p className="truncate text-xs text-muted-foreground">
            {report.file_type || '—'}
            {report.size ? ` · ${formatBytes(report.size)}` : ''}
            {' · '}
            {formatDate(report.uploaded_at)}
            {report.uploaded_by_name ? ` · by ${report.uploaded_by_name}` : ''}
          </p>
        </div>

        {/* Summary pills – only when completed */}
        {report.status === 'COMPLETED' && report.detected_count > 0 && (
          <div className="hidden sm:flex items-center gap-2 text-xs">
            <span className="flex items-center gap-1 text-info">
              <FlaskConical className="size-3" />
              {report.detected_count} detected
            </span>
            {report.updated_count > 0 && (
              <span className="flex items-center gap-1 text-success">
                <CheckCircle2 className="size-3" />
                {report.updated_count} updated
              </span>
            )}
          </div>
        )}

        <StatusBadge status={report.status} />

        {/* Expand toggle (only for completed with fields) */}
        {report.status === 'COMPLETED' && (
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setExpanded((v) => !v)}
            aria-label={expanded ? 'Hide summary' : 'Show summary'}
          >
            {expanded ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
          </Button>
        )}

        <Button
          variant="ghost"
          size="icon-sm"
          onClick={download}
          loading={downloading}
          aria-label="Download original report"
        >
          {!downloading && <Download className="size-4" />}
        </Button>

        {canDelete && (
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-danger hover:text-danger"
            onClick={() => deleteMut.mutate()}
            loading={deleteMut.isPending}
            aria-label="Delete lab report"
          >
            {!deleteMut.isPending && <Trash2 className="size-4" />}
          </Button>
        )}
      </div>

      {/* Expandable summary */}
      {expanded && report.status === 'COMPLETED' && (
        <div className="border-t border-border bg-surface-2/40 px-4 pb-4 pt-3">
          <LabReportSummary report={report} compact />
        </div>
      )}
    </Card>
  )
}
