import { useMemo, useState } from 'react'
import { CalendarDays, Plus, Stethoscope, X } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Textarea } from '@/components/ui/input'
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
import { AvailableDatePicker } from './AvailableDatePicker'

const UPCOMING: Appointment['status'][] = ['PENDING', 'ACCEPTED']
const CANCELLABLE: Appointment['status'][] = ['PENDING', 'ACCEPTED']

/** The slot was taken by someone else between loading the times and booking. */
function isSlotTaken(err: any) {
  return err?.response?.status === 409 || err?.response?.data?.code === 'slot_taken'
}

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

  const datesQ = useQuery({
    queryKey: ['doctor-availability', doctor, 'dates'],
    queryFn: () => doctorService.availableDates(doctor),
    enabled: open && !!doctor,
    staleTime: 0,
  })

  const slotsQ = useQuery({
    queryKey: ['doctor-availability', doctor, 'slots', date],
    queryFn: () => doctorService.availableSlots(doctor, date),
    enabled: open && !!doctor && !!date,
    staleTime: 0,
  })

  const doctorOptions = useMemo(
    () =>
      (doctorsQ.data ?? []).map((d) => ({
        value: String(d.id),
        label: `Dr. ${d.first_name ?? ''} ${d.last_name ?? ''}`.trim() + (d.department ? ` · ${d.department}` : ''),
      })),
    [doctorsQ.data],
  )

  const availableDates = datesQ.data?.dates ?? []
  const slots = slotsQ.data?.slots ?? []

  function chooseDoctor(value: string) {
    setDoctor(value); setDate(''); setTime('')
  }

  function chooseDate(value: string) {
    setDate(value); setTime('')
  }

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
      qc.invalidateQueries({ queryKey: ['doctor-availability'] })
      reset()
      setOpen(false)
    },
    onError: (err: any) => {
      const data = err?.response?.data
      if (isSlotTaken(err)) {
        // Someone else got there first: drop the choice and reload what is left.
        setTime('')
        qc.invalidateQueries({ queryKey: ['doctor-availability', doctor] })
        toast.error(data?.detail || 'That time was just booked. Please choose another time.')
        return
      }
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
          <DialogDescription>
            Choose a doctor and an open time (Nepal time).
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <Field label="Doctor" htmlFor="appt-doctor" required hint={doctorsQ.isLoading ? 'Loading doctors…' : undefined}>
            <SimpleSelect
              id="appt-doctor"
              value={doctor}
              onValueChange={chooseDoctor}
              options={doctorOptions}
              placeholder={doctorsQ.isLoading ? 'Loading…' : 'Select a doctor'}
            />
          </Field>

          {doctor && (
            <Field label="Date" htmlFor="appt-date" required>
              {datesQ.isLoading ? (
                <p className="text-sm text-muted-foreground">Loading the doctor’s schedule…</p>
              ) : datesQ.isError || !datesQ.data ? (
                <p className="text-sm text-danger">
                  Could not load the schedule.{' '}
                  <button type="button" className="underline" onClick={() => datesQ.refetch()}>Try again</button>
                </p>
              ) : availableDates.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  This doctor has no open appointments in the next {datesQ.data.days} days.
                </p>
              ) : (
                <AvailableDatePicker
                  id="appt-date"
                  today={datesQ.data.today}
                  days={datesQ.data.days}
                  available={availableDates}
                  value={date}
                  onChange={chooseDate}
                />
              )}
            </Field>
          )}

          {doctor && date && (
            <Field label={`Time on ${formatDate(date, { weekday: 'short', month: 'short', day: 'numeric' })}`} htmlFor="appt-time" required>
              {slotsQ.isLoading ? (
                <p className="text-sm text-muted-foreground">Loading open times…</p>
              ) : slotsQ.isError ? (
                <p className="text-sm text-danger">
                  Could not load times.{' '}
                  <button type="button" className="underline" onClick={() => slotsQ.refetch()}>Try again</button>
                </p>
              ) : slots.length === 0 ? (
                <p className="text-sm text-muted-foreground">No open times left on this day. Please pick another date.</p>
              ) : (
                <div id="appt-time" role="group" aria-label="Available times" className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                  {slots.map((s) => (
                    <Button
                      key={s}
                      type="button"
                      size="sm"
                      variant={s === time ? 'primary' : 'outline'}
                      aria-pressed={s === time}
                      onClick={() => setTime(s)}
                    >
                      {formatTime(s)}
                    </Button>
                  ))}
                </div>
              )}
            </Field>
          )}

          <Field label="Reason" htmlFor="appt-reason" hint="Optional — a short note about your visit.">
            <Textarea id="appt-reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. persistent cough for two weeks…" />
          </Field>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="secondary">Cancel</Button>
            </DialogClose>
            <Button type="submit" loading={createM.isPending} disabled={!time}>Request appointment</Button>
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
