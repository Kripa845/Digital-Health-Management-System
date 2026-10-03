import { AlertCircle, CheckCircle2, Clock, Eye, Loader2, ShieldAlert, XCircle, FileText } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { LabReportStatus, LabResultStatus } from '@/lib/types'

/** Low / Normal / High badge for a test result (status decided by the server). */
export function ResultStatusBadge({ status, severe }: { status: LabResultStatus | null; severe?: boolean }) {
  if (!status) return null
  const variant = status === 'Normal' ? 'success' : severe ? 'danger' : 'warning'
  return (
    <Badge variant={variant} aria-label={`${status}${severe ? ', well outside the normal range' : ''}`}>
      {status}
    </Badge>
  )
}

/** Status of an uploaded report. */
export function ReportStatusBadge({ status }: { status: LabReportStatus }) {
  switch (status) {
    case 'CONFIRMED':
      return <Badge variant="success"><CheckCircle2 />Confirmed</Badge>
    case 'SAVED_NO_VALUES':
      return <Badge variant="neutral"><FileText />Saved - no card values</Badge>
    case 'NO_VALUES_SAVEABLE':
      return <Badge variant="warning"><Eye />Waiting for you to save</Badge>
    case 'PENDING_CONFIRMATION':
      return <Badge variant="warning"><Eye />Waiting for you to confirm</Badge>
    case 'NEEDS_REVIEW':
      return <Badge variant="info"><ShieldAlert />Being checked by the care team</Badge>
    case 'REJECTED':
      return <Badge variant="danger"><XCircle />Not accepted</Badge>
    case 'PROCESSING':
      return <Badge variant="info"><Loader2 className="animate-spin" />Processing</Badge>
    case 'FAILED':
      return <Badge variant="danger"><AlertCircle />Failed</Badge>
    default:
      return <Badge variant="neutral"><Clock />Pending</Badge>
  }
}
