import { Link, useNavigate, useParams } from 'react-router-dom'
import { CheckCircle2, ClipboardCheck, FileText, ShieldAlert, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { EmptyState, PageHeader } from '@/components/patterns'
import { Skeleton } from '@/components/ui/misc'
import { apiErrorBody } from '@/lib/api'
import { LabReportPreview } from './LabReportPreview'
import { ReportStatusBadge } from './LabStatusBadge'
import { ReportScan } from './ReportScan'
import { useLabReport } from './hooks'

export function LabConfirmPage() {
  const { id } = useParams()
  const reportId = Number(id)
  const navigate = useNavigate()
  const { data: report, isLoading, error, refetch } = useLabReport(reportId)

  if (isLoading) {
    return <div className="space-y-4"><Skeleton className="h-12 w-72" /><Skeleton className="h-96 w-full" /></div>
  }
  if (error || !report) {
    const body = error ? apiErrorBody(error) : null
    return (
      <EmptyState
        icon={XCircle}
        title={body?.status === 404 ? 'Report not found' : 'Could not load the report'}
        description={body?.message}
        action={body?.code === 'network_error'
          ? <Button variant="secondary" onClick={() => refetch()}>Retry</Button>
          : <Button asChild variant="secondary"><Link to="/patient/lab-reports">Back to my reports</Link></Button>}
      />
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Check and confirm"
        description={report.name}
        icon={ClipboardCheck}
        actions={<ReportStatusBadge status={report.status} />}
      />

      {report.status === 'PENDING_CONFIRMATION' || report.status === 'NO_VALUES_SAVEABLE' ? (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="min-w-0">
            <CardContent className="space-y-2 p-4">
              <p className="flex items-center gap-1.5 text-sm font-semibold"><FileText className="size-4" />Your report</p>
              <ReportScan id={report.id} type={report.file_type} />
            </CardContent>
          </Card>
          <Card className="min-w-0">
            <CardContent className="p-4">
              <LabReportPreview
                report={report}
                showScan={false}
                onConfirmed={() => navigate('/patient/dashboard')}
                onDiscarded={() => navigate('/patient/lab-reports')}
              />
            </CardContent>
          </Card>
        </div>
      ) : (
        <Card>
          <CardContent className="space-y-3 p-6" role="status">
            {report.status === 'NEEDS_REVIEW' && (
              <p className="flex items-start gap-2 text-sm"><ShieldAlert className="mt-0.5 size-4 text-info" />
                This report is being checked by the care team. You'll be able to confirm it once they have.</p>
            )}
            {report.status === 'SAVED_NO_VALUES' && (
              <p className="text-sm text-muted-foreground">Saved as a document. No health card values were found.</p>
            )}
            {report.status === 'CONFIRMED' && (
              <p className="flex items-start gap-2 text-sm"><CheckCircle2 className="mt-0.5 size-4 text-success" />
                This report has already been confirmed.</p>
            )}
            {report.status === 'REJECTED' && (
              <p className="flex items-start gap-2 text-sm"><XCircle className="mt-0.5 size-4 text-danger" />
                This report was not accepted{report.review_note ? `: ${report.review_note}` : '.'}</p>
            )}
            <div className="flex flex-wrap gap-2">
              <Button asChild variant="secondary"><Link to="/patient/lab-reports">My reports</Link></Button>
              <Button asChild><Link to="/patient/dashboard">Dashboard</Link></Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
