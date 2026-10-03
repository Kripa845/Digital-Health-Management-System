import { Link } from 'react-router-dom'
import { FlaskConical, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DataState, EmptyState, ListSkeleton, PageHeader } from '@/components/patterns'
import { useAuth } from '@/lib/auth'
import { LabReportRow } from './LabReportRow'
import { useLabReports } from './hooks'

export function LabHistoryPage() {
  const { user } = useAuth()
  const patientId = user?.patient_profile?.id
  const { data = [], isLoading, isError, refetch } = useLabReports()

  return (
    <div className="space-y-6">
      <PageHeader
        title="My lab reports"
        description="Every report you've uploaded, with its status."
        icon={FlaskConical}
        actions={<Button asChild><Link to="/patient/lab-reports/upload"><Upload className="size-4" />Upload lab report</Link></Button>}
      />
      <DataState
        isLoading={isLoading}
        isError={isError}
        onRetry={() => refetch()}
        isEmpty={!data.length}
        skeleton={<ListSkeleton rows={3} />}
        empty={
          <EmptyState
            icon={FlaskConical}
            title="No lab reports yet"
            description="Upload a report to fill in your health cards."
            action={<Button asChild><Link to="/patient/lab-reports/upload">Upload lab report</Link></Button>}
          />
        }
      >
        <div className="space-y-3">
          {data.map((r) => <LabReportRow key={r.id} report={r} patientId={patientId ?? r.patient} canDelete />)}
        </div>
      </DataState>
    </div>
  )
}
