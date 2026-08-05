import { useMemo, useState } from 'react'
import { CalendarDays, Plus, Stethoscope, X } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Field } from '@/components/ui/label'
import { SimpleSelect } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import {
  Dialog, DialogContent, DialogHeader, DialogFooter, DialogTitle, DialogDescription, DialogTrigger, DialogClose,
} from '@/components/ui/dialog'
import { PageHeader, DataState, EmptyState, ListSkeleton } from '@/components/patterns'
import { AppointmentStatusBadge } from '@/components/status-badge'
import { appointmentService, doctorService } from '@/lib/api'
import { formatDate, formatTime } from '@/lib/utils'
import type { Appointment } from '@/lib/types'

const UPCOMING: Appointment['status'][] = ['PENDING', 'ACCEPTED']
const CANCELLABLE: Appointment['status'][] = ['PENDING', 'ACCEPTED']

const todayISO = () => new Date().toISOString().split('T')[0]

function BookDialog() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [doctor, setDoctor] = useState('')
  const [date, setDate] = useState('')
  const [time, setTime] = useState('')
  const [reason, setReason] = useState('')

  const doctorsQ = useQuery({
    queryKey: ['doctors', 'active'],
    queryFn: () => doctorService.list({ status: 'Active' }),
    enabled: open,
  })

  const doctorOptions = useMemo(
    () =>
      (doctorsQ.data ?? []).map((d) => ({
        value: String(d.id),
        label: `Dr. ${d.first_name ?? ''} ${d.last_name ?? ''}`.trim() + (d.department ? ` · ${d.department}` : ''),
      })),
    [doctorsQ.data],
  )

  function reset() {
    setDoctor(''); setDate(''); setTime(''); setReason('')
  }

  const createM = useMutation({
    mutationFn: () =>
      appointmentService.create({
        doctor: Number(doctor),
        appointment_date: date,
        appointment_time: time,
        reason: reason.trim() || undefined,
      }),
    onSuccess: () => {
      toast.success('Appointment requested — awaiting confirmation.')
      qc.invalidateQueries({ queryKey: ['patient', 'appointments', 'mine'] })
      reset()
      setOpen(false)
    },
    onError: (err: any) => {
      const data = err?.response?.data
      const msg =
        typeof data === 'string' ? data
          : data?.non_field_errors?.[0] || data?.detail
          || (data && typeof data === 'object' ? Object.values(data).flat().join(' ') : undefined)
          || 'Could not request the appointment.'
      toast.error(msg)
    },
  })

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!doctor) return toast.error('Please choose a doctor.')
    if (!date) return toast.error('Please choose a date.')
    if (!time) return toast.error('Please choose a time.')
    createM.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) reset() }}>
      <DialogTrigger asChild>
        <Button><Plus className="size-4" /> Book appointment</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Book an appointment</DialogTitle>
          <DialogDescription>Choose a doctor and a preferred time. Your care team will confirm the request.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <Field label="Doctor" htmlFor="appt-doctor" required hint={doctorsQ.isLoading ? 'Loading doctors…' : undefined}>
            <SimpleSelect
              id="appt-doctor"
              value={doctor}
              onValueChange={setDoctor}
              options={doctorOptions}
              placeholder={doctorsQ.isLoading ? 'Loading…' : 'Select a doctor'}
            />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Date" htmlFor="appt-date" required>
              <Input id="appt-date" type="date" min={todayISO()} value={date} onChange={(e) => setDate(e.target.value)} />
            </Field>
            <Field label="Time" htmlFor="appt-time" required>
              <Input id="appt-time" type="time" value={time} onChange={(e) => setTime(e.target.value)} />
            </Field>
          </div>
          <Field label="Reason" htmlFor="appt-reason" hint="Optional — a short note about your visit.">
            <Textarea id="appt-reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. persistent cough for two weeks…" />
          </Field>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="secondary">Cancel</Button>
            </DialogClose>
            <Button type="submit" loading={createM.isPending}>Request appointment</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function AppointmentRow({ appt }: { appt: Appointment }) {
  const qc = useQueryClient()
  const cancelM = useMutation({
    mutationFn: () => appointmentService.cancel(appt.id),
    onSuccess: () => {
      toast.success('Appointment cancelled.')
      qc.invalidateQueries({ queryKey: ['patient', 'appointments', 'mine'] })
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Could not cancel the appointment.'),
  })

  const doctorName = appt.doctor_name || `Dr. ${appt.doctor_detail?.first_name ?? ''} ${appt.doctor_detail?.last_name ?? ''}`.trim()
  const department = appt.doctor_department || appt.doctor_detail?.department || 'General'

  return (
    <Card className="p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <span className="grid size-11 shrink-0 place-items-center rounded-[var(--radius-md)] bg-primary-soft text-primary-soft-foreground">
          <Stethoscope className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{doctorName || 'Doctor'}</p>
          <p className="truncate text-xs text-muted-foreground">
            {department} · {formatDate(appt.appointment_date)} · {formatTime(appt.appointment_time)}
          </p>
          {appt.reason && <p className="mt-1 truncate text-xs text-subtle-foreground">“{appt.reason}”</p>}
        </div>
        <div className="flex items-center gap-2">
          <AppointmentStatusBadge status={appt.status} />
          {CANCELLABLE.includes(appt.status) && (
            <Button variant="ghost" size="sm" loading={cancelM.isPending} onClick={() => cancelM.mutate()}>
              <X className="size-4" /> Cancel
            </Button>
          )}
        </div>
      </div>
    </Card>
  )
}

export function PatientAppointments() {
  const appointmentsQ = useQuery({
    queryKey: ['patient', 'appointments', 'mine'],
    queryFn: () => appointmentService.mine(),
  })

  const all = appointmentsQ.data ?? []
  const upcoming = all.filter((a) => UPCOMING.includes(a.status))
  const past = all.filter((a) => !UPCOMING.includes(a.status))

  const lists: Record<string, Appointment[]> = { upcoming, past, all }

  function renderList(key: string) {
    const items = lists[key]
    return (
      <DataState
        isLoading={appointmentsQ.isLoading}
        isError={appointmentsQ.isError}
        isEmpty={items.length === 0}
        onRetry={() => appointmentsQ.refetch()}
        skeleton={<ListSkeleton />}
        empty={
          <EmptyState
            icon={CalendarDays}
            title={key === 'past' ? 'No past appointments' : 'No appointments yet'}
            description={key === 'past' ? 'Completed and cancelled visits will appear here.' : 'Book your first appointment to get started.'}
            action={key !== 'past' ? <BookDialog /> : undefined}
          />
        }
      >
        <div className="space-y-3">
          {items.map((a) => <AppointmentRow key={a.id} appt={a} />)}
        </div>
      </DataState>
    )
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Appointments"
        description="Request visits, track their status, and manage your schedule."
        icon={CalendarDays}
        actions={<BookDialog />}
      />

      <Tabs defaultValue="upcoming">
        <TabsList>
          <TabsTrigger value="upcoming">Upcoming{upcoming.length ? ` (${upcoming.length})` : ''}</TabsTrigger>
          <TabsTrigger value="past">Past{past.length ? ` (${past.length})` : ''}</TabsTrigger>
          <TabsTrigger value="all">All{all.length ? ` (${all.length})` : ''}</TabsTrigger>
        </TabsList>
        <TabsContent value="upcoming">{renderList('upcoming')}</TabsContent>
        <TabsContent value="past">{renderList('past')}</TabsContent>
        <TabsContent value="all">{renderList('all')}</TabsContent>
      </Tabs>
    </div>
  )
}
