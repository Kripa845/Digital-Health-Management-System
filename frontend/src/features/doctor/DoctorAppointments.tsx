import { useState } from 'react'
import { CalendarDays, CircleCheck, Ban, Clock } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { UserAvatar } from '@/components/ui/avatar'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { PageHeader, DataState, EmptyState, ListSkeleton } from '@/components/patterns'
import { AppointmentStatusBadge } from '@/components/status-badge'
import { appointmentService } from '@/lib/api'
import { formatDate, formatTime } from '@/lib/utils'
import type { Appointment, AppointmentStatus } from '@/lib/types'

const TABS: { value: string; label: string; match: (s: AppointmentStatus) => boolean }[] = [
  { value: 'ALL', label: 'All', match: () => true },
  { value: 'PENDING', label: 'Pending', match: (s) => s === 'PENDING' },
  { value: 'ACCEPTED', label: 'Accepted', match: (s) => s === 'ACCEPTED' },
  { value: 'COMPLETED', label: 'Completed', match: (s) => s === 'COMPLETED' },
  { value: 'ARCHIVE', label: 'Declined / Cancelled', match: (s) => s === 'DECLINED' || s === 'CANCELLED' },
]

function patientLabel(a: Appointment) {
  return a.patient_name
    || (a.patient_detail ? `${a.patient_detail.first_name} ${a.patient_detail.last_name}` : 'Patient')
}

function apptSortKey(a: Appointment) {
  return `${a.appointment_date}T${a.appointment_time}`
}

export function DoctorAppointments() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('ALL')

  const appointmentsQ = useQuery({
    queryKey: ['doctor', 'appointments'],
    queryFn: () => appointmentService.forDoctor(),
  })
  const appointments = (appointmentsQ.data ?? [])
    .slice()
    .sort((a, b) => apptSortKey(b).localeCompare(apptSortKey(a)))

  const transition = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'complete' | 'cancel' }) =>
      appointmentService[action](id),
    onSuccess: (_data, vars) => {
      const labels = { complete: 'completed', cancel: 'cancelled' }
      toast.success(`Appointment ${labels[vars.action]}.`)
      qc.invalidateQueries({ queryKey: ['doctor', 'appointments'] })
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Could not update the appointment.'),
  })

  return (
    <div className="space-y-8">
      <PageHeader
        title="Appointments"
        description="Your schedule at a glance. New requests are approved by an administrator; you complete visits once they're accepted."
        icon={CalendarDays}
      />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="flex-wrap h-auto">
          {TABS.map((t) => {
            const count = appointments.filter((a) => t.match(a.status)).length
            return (
              <TabsTrigger key={t.value} value={t.value}>
                {t.label}
                <span className="ml-1 text-xs text-subtle-foreground tabular">{count}</span>
              </TabsTrigger>
            )
          })}
        </TabsList>

        {TABS.map((t) => {
          const rows = appointments.filter((a) => t.match(a.status))
          return (
            <TabsContent key={t.value} value={t.value}>
              <DataState
                isLoading={appointmentsQ.isLoading}
                isError={appointmentsQ.isError}
                isEmpty={rows.length === 0}
                onRetry={appointmentsQ.refetch}
                skeleton={<ListSkeleton rows={3} />}
                empty={<EmptyState icon={CalendarDays} title="No appointments"
                  description="Appointments in this category will appear here." />}
              >
                <ul className="space-y-2.5">
                  {rows.map((a) => (
                    <AppointmentRow
                      key={a.id}
                      appt={a}
                      busy={transition.isPending && transition.variables?.id === a.id}
                      pendingAction={transition.isPending ? transition.variables?.action : undefined}
                      onAction={(action) => transition.mutate({ id: a.id, action })}
                    />
                  ))}
                </ul>
              </DataState>
            </TabsContent>
          )
        })}
      </Tabs>
    </div>
  )
}

function AppointmentRow({
  appt: a, busy, pendingAction, onAction,
}: {
  appt: Appointment
  busy: boolean
  pendingAction?: string
  onAction: (action: 'complete' | 'cancel') => void
}) {
  return (
    <li className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4 sm:flex-row sm:items-center">
      <UserAvatar name={patientLabel(a)} src={a.patient_detail?.photo || undefined} className="size-11" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold">{patientLabel(a)}</p>
        <p className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
          <Clock className="size-3.5" />
          {formatDate(a.appointment_date)} · {formatTime(a.appointment_time)}
        </p>
        {a.reason && <p className="mt-0.5 truncate text-xs text-subtle-foreground">{a.reason}</p>}
      </div>
      <div className="flex items-center gap-2">
        <AppointmentStatusBadge status={a.status} />
        {a.status === 'PENDING' && (
          <span className="text-xs text-subtle-foreground">Awaiting admin approval</span>
        )}
        {a.status === 'ACCEPTED' && (
          <>
            <Button size="sm" variant="soft" disabled={busy} loading={busy && pendingAction === 'complete'}
              onClick={() => onAction('complete')}>
              <CircleCheck className="size-4" /> Complete
            </Button>
            <Button size="sm" variant="outline" disabled={busy} loading={busy && pendingAction === 'cancel'}
              onClick={() => onAction('cancel')}>
              <Ban className="size-4" /> Cancel
            </Button>
          </>
        )}
      </div>
    </li>
  )
}
