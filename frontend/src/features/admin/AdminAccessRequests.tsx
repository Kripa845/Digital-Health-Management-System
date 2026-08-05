import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ShieldCheck, Check, X, KeyRound } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { SimpleSelect } from '@/components/ui/select'
import { Card } from '@/components/ui/card'
import { UserAvatar } from '@/components/ui/avatar'
import { PageHeader, DataState, EmptyState, ListSkeleton } from '@/components/patterns'
import { AccessStatusBadge } from '@/components/status-badge'
import { accessRequestService } from '@/lib/api'
import type { AccessRequest } from '@/lib/types'
import { formatDateTime } from '@/lib/utils'
import { apiError } from './admin-common'

const STATUS_OPTIONS = [
  { value: 'PENDING', label: 'Pending' },
  { value: 'APPROVED', label: 'Approved' },
  { value: 'DECLINED', label: 'Declined' },
  { value: 'all', label: 'All statuses' },
]

function reqDoctorName(r: AccessRequest) {
  return r.doctor_name || `Dr. ${r.doctor_detail?.first_name ?? ''} ${r.doctor_detail?.last_name ?? ''}`.trim() || '—'
}
function reqPatientName(r: AccessRequest) {
  return r.patient_name || `${r.patient_detail?.first_name ?? ''} ${r.patient_detail?.last_name ?? ''}`.trim() || '—'
}

export function AdminAccessRequests() {
  const qc = useQueryClient()
  const [status, setStatus] = useState('PENDING')

  const listQ = useQuery({
    queryKey: ['admin', 'access-requests', status],
    queryFn: () => accessRequestService.list(status !== 'all' ? { status } : undefined),
  })
  const requests = listQ.data ?? []

  const invalidate = () => qc.invalidateQueries({ queryKey: ['admin', 'access-requests'] })

  const approveMut = useMutation({
    mutationFn: (id: number) => accessRequestService.approve(id),
    onSuccess: () => { toast.success('Request approved — patient assigned to the doctor.'); invalidate() },
    onError: (err) => toast.error(apiError(err, 'Could not approve request.')),
  })
  const declineMut = useMutation({
    mutationFn: (id: number) => accessRequestService.decline(id),
    onSuccess: () => { toast.success('Request declined.'); invalidate() },
    onError: (err) => toast.error(apiError(err, 'Could not decline request.')),
  })

  return (
    <div className="space-y-6">
      <PageHeader
        title="Access requests"
        description="Doctors request access to patient records here. Approving assigns the patient to the doctor."
        icon={ShieldCheck}
        actions={
          <div className="w-48">
            <SimpleSelect value={status} onValueChange={setStatus} options={STATUS_OPTIONS} />
          </div>
        }
      />

      <DataState
        isLoading={listQ.isLoading}
        isError={listQ.isError}
        isEmpty={requests.length === 0}
        onRetry={() => listQ.refetch()}
        skeleton={<ListSkeleton rows={4} />}
        empty={<EmptyState icon={KeyRound} title="No access requests" description="Requests from doctors will appear here." />}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          {requests.map((r) => {
            const busy = (approveMut.isPending && approveMut.variables === r.id) || (declineMut.isPending && declineMut.variables === r.id)
            return (
              <Card key={r.id} className="flex flex-col gap-4 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <UserAvatar name={reqDoctorName(r)} src={r.doctor_detail?.photo} className="size-10" />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold">{reqDoctorName(r)}</p>
                      <p className="truncate text-xs text-muted-foreground">{r.doctor_detail?.department || 'Requesting access'}</p>
                    </div>
                  </div>
                  <AccessStatusBadge status={r.status} />
                </div>

                <div className="space-y-1.5 rounded-[var(--radius-md)] border border-border bg-surface-2 p-3 text-sm">
                  <p><span className="text-muted-foreground">Patient: </span><span className="font-medium">{reqPatientName(r)}</span></p>
                  {r.reason && <p className="text-muted-foreground">“{r.reason}”</p>}
                  <p className="text-xs text-subtle-foreground">{formatDateTime(r.created_at)}</p>
                </div>

                {r.status === 'PENDING' && (
                  <div className="flex gap-2">
                    <Button size="sm" className="flex-1" loading={busy && approveMut.isPending} onClick={() => approveMut.mutate(r.id)}>
                      <Check className="size-4" />Approve
                    </Button>
                    <Button size="sm" variant="secondary" className="flex-1 text-danger" loading={busy && declineMut.isPending} onClick={() => declineMut.mutate(r.id)}>
                      <X className="size-4" />Decline
                    </Button>
                  </div>
                )}
              </Card>
            )
          })}
        </div>
      </DataState>
    </div>
  )
}
