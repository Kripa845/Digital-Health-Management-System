import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ShieldCheck, Check, X, KeyRound, QrCode, Phone, Ban } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { SimpleSelect } from '@/components/ui/select'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { UserAvatar } from '@/components/ui/avatar'
import { PageHeader, DataState, EmptyState, ListSkeleton } from '@/components/patterns'
import { AccessStatusBadge } from '@/components/status-badge'
import { accessRequestService, qrAccessService } from '@/lib/api'
import type { AccessRequest, QrAccessRequest } from '@/lib/types'
import { formatDateTime } from '@/lib/utils'
import {
  apiError,
} from './admin-utils'

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
  const [status, setStatus] = useState('PENDING')
  const qrPendingQ = useQuery({
    queryKey: ['admin', 'qr-access-requests', 'PENDING'],
    queryFn: () => qrAccessService.list({ status: 'PENDING' }),
    refetchInterval: 15000,
  })
  const qrPending = qrPendingQ.data?.length ?? 0

  return (
    <div className="space-y-6">
      <PageHeader
        title="Access requests"
        description="Approve or decline requests to see patient records: from doctors, and from people who scanned a patient's QR card."
        icon={ShieldCheck}
        actions={
          <div className="w-48">
            <SimpleSelect value={status} onValueChange={setStatus} options={STATUS_OPTIONS} />
          </div>
        }
      />
      <Tabs defaultValue="doctors">
        <TabsList>
          <TabsTrigger value="doctors">Doctors</TabsTrigger>
          <TabsTrigger value="qr">
            QR card{qrPending > 0 && <Badge variant="warning" className="ml-1.5">{qrPending}</Badge>}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="doctors" className="mt-4"><DoctorRequests status={status} /></TabsContent>
        <TabsContent value="qr" className="mt-4"><QrCardRequests status={status} /></TabsContent>
      </Tabs>
    </div>
  )
}

function DoctorRequests({ status }: { status: string }) {
  const qc = useQueryClient()

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
  )
}

function QrCardRequests({ status }: { status: string }) {
  const qc = useQueryClient()
  const listQ = useQuery({
    queryKey: ['admin', 'qr-access-requests', status],
    queryFn: () => qrAccessService.list(status !== 'all' ? { status } : undefined),
    refetchInterval: 15000,
  })
  const requests: QrAccessRequest[] = listQ.data ?? []
  const invalidate = () => qc.invalidateQueries({ queryKey: ['admin', 'qr-access-requests'] })

  const approveMut = useMutation({
    mutationFn: (id: number) => qrAccessService.approve(id),
    onSuccess: () => { toast.success('Approved — the requester can see the record for 24 hours.'); invalidate() },
    onError: (err) => toast.error(apiError(err, 'Could not approve request.')),
  })
  const declineMut = useMutation({
    mutationFn: (id: number) => qrAccessService.decline(id),
    onSuccess: () => { toast.success('Request declined.'); invalidate() },
    onError: (err) => toast.error(apiError(err, 'Could not decline request.')),
  })
  const revokeMut = useMutation({
    mutationFn: (id: number) => qrAccessService.revoke(id),
    onSuccess: () => { toast.success('Access ended.'); invalidate() },
    onError: (err) => toast.error(apiError(err, 'Could not end access.')),
  })

  return (
    <DataState
      isLoading={listQ.isLoading}
      isError={listQ.isError}
      isEmpty={requests.length === 0}
      onRetry={() => listQ.refetch()}
      skeleton={<ListSkeleton rows={4} />}
      empty={<EmptyState icon={QrCode} title="No QR card requests" description="When someone scans a patient's card and asks for more information, it appears here." />}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {requests.map((r) => {
          const busy = [approveMut, declineMut, revokeMut].some((m) => m.isPending && m.variables === r.id)
          const expired = r.status === 'APPROVED' && !r.is_active
          return (
            <Card key={r.id} className="flex flex-col gap-4 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <UserAvatar name={r.requester_name} className="size-10" />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{r.requester_name}</p>
                    <a href={`tel:${r.requester_phone}`} className="inline-flex items-center gap-1 text-xs text-primary">
                      <Phone className="size-3" />{r.requester_phone}
                    </a>
                  </div>
                </div>
                <AccessStatusBadge status={expired ? 'EXPIRED' : r.status} />
              </div>

              <div className="space-y-1.5 rounded-[var(--radius-md)] border border-border bg-surface-2 p-3 text-sm">
                <p><span className="text-muted-foreground">Patient: </span><span className="font-medium">{r.patient_name}</span> <span className="font-mono text-xs text-muted-foreground">{r.patient_id_code}</span></p>
                <p className="text-muted-foreground">“{r.reason}”</p>
                <p className="text-xs text-subtle-foreground">
                  Requested {formatDateTime(r.created_at)}
                  {r.is_active && r.expires_at && ` · access until ${formatDateTime(r.expires_at)}`}
                </p>
              </div>

              {r.status === 'PENDING' && (
                <div className="flex gap-2">
                  <Button size="sm" className="flex-1" loading={busy && approveMut.isPending} onClick={() => approveMut.mutate(r.id)}>
                    <Check className="size-4" />Approve 24 h
                  </Button>
                  <Button size="sm" variant="secondary" className="flex-1 text-danger" loading={busy && declineMut.isPending} onClick={() => declineMut.mutate(r.id)}>
                    <X className="size-4" />Decline
                  </Button>
                </div>
              )}
              {r.is_active && (
                <Button size="sm" variant="secondary" className="text-danger" loading={busy && revokeMut.isPending} onClick={() => revokeMut.mutate(r.id)}>
                  <Ban className="size-4" />End access now
                </Button>
              )}
            </Card>
          )
        })}
      </div>
    </DataState>
  )
}
