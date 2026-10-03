import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarDays, Ban, Check, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SimpleSelect } from '@/components/ui/select'
import { Card } from '@/components/ui/card'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose,
} from '@/components/ui/dialog'
import { PageHeader, DataState, EmptyState, ListSkeleton, InfoRow } from '@/components/patterns'
import { AppointmentStatusBadge } from '@/components/status-badge'
import { appointmentService } from '@/lib/api'
import type { Appointment } from '@/lib/types'
import { formatDate, formatTime } from '@/lib/utils'
import {
  apiError, tableHeadClass,
} from './admin-utils'

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: 'all', label: 'All statuses' },
  { value: 'PENDING', label: 'Pending' },
  { value: 'ACCEPTED', label: 'Accepted' },
  { value: 'COMPLETED', label: 'Completed' },
  { value: 'DECLINED', label: 'Declined' },
  { value: 'CANCELLED', label: 'Cancelled' },
]

function patientName(a: Appointment) {
  return a.patient_name || `${a.patient_detail?.first_name ?? ''} ${a.patient_detail?.last_name ?? ''}`.trim() || '—'
}
function doctorName(a: Appointment) {
  return a.doctor_name || `Dr. ${a.doctor_detail?.first_name ?? ''} ${a.doctor_detail?.last_name ?? ''}`.trim() || '—'
}

export function AdminAppointments() {
  const qc = useQueryClient()
  const [status, setStatus] = useState('all')
  const [date, setDate] = useState('')
  const [cancelTarget, setCancelTarget] = useState<Appointment | null>(null)

  const params = useMemo(() => ({
    status: status !== 'all' ? status : undefined,
    appointment_date: date || undefined,
  }), [status, date])

  const listQ = useQuery({
    queryKey: ['admin', 'appointments', params],
    queryFn: () => appointmentService.list(params),
  })
  const appointments = listQ.data ?? []

  const cancelMut = useMutation({
    mutationFn: (a: Appointment) => appointmentService.cancel(a.id),
    onSuccess: () => {
      toast.success('Appointment cancelled.')
      setCancelTarget(null)
      qc.invalidateQueries({ queryKey: ['admin', 'appointments'] })
    },
    onError: (err) => toast.error(apiError(err, 'Could not cancel appointment.')),
  })

  const decideMut = useMutation({
    mutationFn: ({ a, action }: { a: Appointment; action: 'accept' | 'decline' }) => appointmentService[action](a.id),
    onSuccess: (_d, vars) => {
      toast.success(vars.action === 'accept' ? 'Appointment accepted.' : 'Appointment declined.')
      qc.invalidateQueries({ queryKey: ['admin', 'appointments'] })
    },
    onError: (err) => toast.error(apiError(err, 'Could not update the appointment.')),
  })
  const decideBusy = (a: Appointment) => decideMut.isPending && decideMut.variables?.a.id === a.id

  return (
    <div className="space-y-6">
      <PageHeader
        title="Appointments"
        description="Review incoming requests — accept or decline pending bookings, and cancel accepted visits when needed."
        icon={CalendarDays}
      />

      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="w-full sm:w-52">
          <SimpleSelect value={status} onValueChange={setStatus} options={STATUS_OPTIONS} placeholder="All statuses" />
        </div>
        <div className="w-full sm:w-52">
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Filter by date" />
        </div>
        {(status !== 'all' || date) && (
          <Button variant="ghost" size="sm" onClick={() => { setStatus('all'); setDate('') }}>Clear filters</Button>
        )}
      </div>

      <DataState
        isLoading={listQ.isLoading}
        isError={listQ.isError}
        isEmpty={appointments.length === 0}
        onRetry={() => listQ.refetch()}
        skeleton={<ListSkeleton rows={6} />}
        empty={<EmptyState icon={CalendarDays} title="No appointments" description="No appointments match the current filters." />}
      >
        {/* Desktop table */}
        <Card className="hidden overflow-hidden md:block">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-border bg-surface-2">
                <tr>
                  <th className={tableHeadClass()}>Patient</th>
                  <th className={tableHeadClass()}>Doctor</th>
                  <th className={tableHeadClass()}>Date</th>
                  <th className={tableHeadClass()}>Time</th>
                  <th className={tableHeadClass()}>Status</th>
                  <th className={tableHeadClass('text-right')}>Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {appointments.map((a) => (
                  <tr key={a.id} className="transition-colors hover:bg-surface-2/60">
                    <td className="px-4 py-3 font-medium">{patientName(a)}</td>
                    <td className="px-4 py-3">
                      <p>{doctorName(a)}</p>
                      <p className="text-xs text-muted-foreground">{a.doctor_department || a.doctor_detail?.department || ''}</p>
                    </td>
                    <td className="px-4 py-3 tabular-nums">{formatDate(a.appointment_date)}</td>
                    <td className="px-4 py-3 tabular-nums">{formatTime(a.appointment_time)}</td>
                    <td className="px-4 py-3"><AppointmentStatusBadge status={a.status} /></td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-2">
                        {a.status === 'PENDING' && (
                          <>
                            <Button size="sm" variant="soft" disabled={decideBusy(a)} loading={decideBusy(a) && decideMut.variables?.action === 'accept'}
                              onClick={() => decideMut.mutate({ a, action: 'accept' })}>
                              <Check className="size-4" />Accept
                            </Button>
                            <Button size="sm" variant="outline" disabled={decideBusy(a)} loading={decideBusy(a) && decideMut.variables?.action === 'decline'}
                              onClick={() => decideMut.mutate({ a, action: 'decline' })}>
                              <X className="size-4" />Decline
                            </Button>
                          </>
                        )}
                        {a.status === 'ACCEPTED' && (
                          <Button variant="ghost" size="sm" className="text-danger hover:bg-danger-soft" onClick={() => setCancelTarget(a)}>
                            <Ban className="size-4" />Cancel
                          </Button>
                        )}
                        {a.status !== 'PENDING' && a.status !== 'ACCEPTED' && (
                          <span className="text-xs text-subtle-foreground">—</span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        {/* Mobile cards */}
        <div className="space-y-3 md:hidden">
          {appointments.map((a) => (
            <Card key={a.id} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-medium">{patientName(a)}</p>
                  <p className="truncate text-xs text-muted-foreground">{doctorName(a)}</p>
                </div>
                <AppointmentStatusBadge status={a.status} />
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <InfoRow label="Date" value={<span className="tabular-nums">{formatDate(a.appointment_date)}</span>} />
                <InfoRow label="Time" value={<span className="tabular-nums">{formatTime(a.appointment_time)}</span>} />
              </div>
              {a.status === 'PENDING' && (
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <Button size="sm" variant="soft" disabled={decideBusy(a)} loading={decideBusy(a) && decideMut.variables?.action === 'accept'}
                    onClick={() => decideMut.mutate({ a, action: 'accept' })}>
                    <Check className="size-4" />Accept
                  </Button>
                  <Button size="sm" variant="outline" disabled={decideBusy(a)} loading={decideBusy(a) && decideMut.variables?.action === 'decline'}
                    onClick={() => decideMut.mutate({ a, action: 'decline' })}>
                    <X className="size-4" />Decline
                  </Button>
                </div>
              )}
              {a.status === 'ACCEPTED' && (
                <Button variant="secondary" size="sm" className="mt-3 w-full text-danger" onClick={() => setCancelTarget(a)}>
                  <Ban className="size-4" />Cancel appointment
                </Button>
              )}
            </Card>
          ))}
        </div>
      </DataState>

      {/* Cancel confirm */}
      <Dialog open={!!cancelTarget} onOpenChange={(o) => { if (!o) setCancelTarget(null) }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Cancel this appointment?</DialogTitle>
            <DialogDescription>
              The appointment for {cancelTarget ? patientName(cancelTarget) : ''} with {cancelTarget ? doctorName(cancelTarget) : ''} will be
              cancelled and both parties notified.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild><Button variant="secondary">Keep it</Button></DialogClose>
            <Button variant="danger" loading={cancelMut.isPending} onClick={() => cancelTarget && cancelMut.mutate(cancelTarget)}>
              <Ban className="size-4" />Cancel appointment
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
