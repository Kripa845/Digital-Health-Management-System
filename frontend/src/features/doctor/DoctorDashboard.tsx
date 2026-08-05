import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Users, CalendarClock, Inbox, Stethoscope, ArrowRight, Clock,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { UserAvatar } from '@/components/ui/avatar'
import {
  PageHeader, StatCard, StatCardSkeleton, DataState, EmptyState, SectionTitle,
} from '@/components/patterns'
import { AppointmentStatusBadge } from '@/components/status-badge'
import { Skeleton } from '@/components/ui/misc'
import { useAuth } from '@/lib/auth'
import { appointmentService, patientService } from '@/lib/api'
import { formatDate, formatTime } from '@/lib/utils'
import type { Appointment } from '@/lib/types'

const TODAY = new Date().toISOString().slice(0, 10)

function apptSortKey(a: Appointment) {
  return `${a.appointment_date}T${a.appointment_time}`
}

function patientLabel(a: Appointment) {
  return a.patient_name
    || (a.patient_detail ? `${a.patient_detail.first_name} ${a.patient_detail.last_name}` : 'Patient')
}

function greeting() {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

export function DoctorDashboard() {
  const { user, loading } = useAuth()
  const doctorName = `Dr. ${user?.first_name || ''} ${user?.last_name || ''}`.trim() || user?.username || 'Doctor'

  const patientsQ = useQuery({
    queryKey: ['doctor', 'patients'],
    queryFn: () => patientService.list(),
  })
  const appointmentsQ = useQuery({
    queryKey: ['doctor', 'appointments'],
    queryFn: () => appointmentService.forDoctor(),
  })

  const patients = patientsQ.data ?? []
  const appointments = appointmentsQ.data ?? []

  const todays = appointments
    .filter((a) => a.appointment_date === TODAY && (a.status === 'ACCEPTED' || a.status === 'PENDING'))
    .sort((a, b) => apptSortKey(a).localeCompare(apptSortKey(b)))
  const pending = appointments
    .filter((a) => a.status === 'PENDING')
    .sort((a, b) => apptSortKey(a).localeCompare(apptSortKey(b)))

  if (loading) {
    return (
      <div className="space-y-8">
        <Skeleton className="h-16 w-72" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <StatCardSkeleton />
          <StatCardSkeleton />
          <StatCardSkeleton />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title={`${greeting()}, ${doctorName}`}
        description="Here's what's happening across your patients and schedule today."
        icon={Stethoscope}
        actions={
          <Button asChild variant="secondary" size="sm">
            <Link to="/doctor/scan">Scan a card <ArrowRight className="size-4" /></Link>
          </Button>
        }
      />

      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {patientsQ.isLoading || appointmentsQ.isLoading ? (
          <>
            <StatCardSkeleton />
            <StatCardSkeleton />
            <StatCardSkeleton />
          </>
        ) : (
          <>
            <StatCard label="Assigned patients" value={patients.length} icon={Users} tone="primary"
              hint="Under your active care" />
            <StatCard label="Today's appointments" value={todays.length} icon={CalendarClock} tone="info"
              hint={formatDate(TODAY)} />
            <StatCard label="Pending requests" value={pending.length} icon={Inbox} tone="warning"
              hint="Awaiting your response" />
          </>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        {/* Today's schedule */}
        <Card>
          <CardContent className="space-y-4 p-5 sm:p-6">
            <SectionTitle>Today's schedule</SectionTitle>
            <DataState
              isLoading={appointmentsQ.isLoading}
              isError={appointmentsQ.isError}
              isEmpty={todays.length === 0}
              onRetry={appointmentsQ.refetch}
              empty={<EmptyState icon={CalendarClock} title="Nothing scheduled today"
                description="Accepted and pending appointments for today will show up here." />}
            >
              <ul className="space-y-2.5">
                {todays.map((a, i) => (
                  <motion.li
                    key={a.id}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25, delay: i * 0.03 }}
                    className="flex items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-3.5"
                  >
                    <span className="grid size-10 shrink-0 place-items-center rounded-[var(--radius-md)] bg-primary-soft text-primary-soft-foreground">
                      <Clock className="size-4.5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{patientLabel(a)}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {formatTime(a.appointment_time)}{a.reason ? ` · ${a.reason}` : ''}
                      </p>
                    </div>
                    <AppointmentStatusBadge status={a.status} />
                  </motion.li>
                ))}
              </ul>
            </DataState>
          </CardContent>
        </Card>

        {/* Your patients preview */}
        <Card>
          <CardContent className="space-y-4 p-5 sm:p-6">
            <SectionTitle action={
              <Button asChild variant="link" size="sm">
                <Link to="/doctor/patients">View all</Link>
              </Button>
            }>Your patients</SectionTitle>
            <DataState
              isLoading={patientsQ.isLoading}
              isError={patientsQ.isError}
              isEmpty={patients.length === 0}
              onRetry={patientsQ.refetch}
              empty={<EmptyState icon={Users} title="No assigned patients"
                description="Patients assigned by an admin — or granted via an approved access request — appear here." />}
            >
              <ul className="space-y-2">
                {patients.slice(0, 5).map((p) => (
                  <li key={p.id} className="flex items-center gap-3 rounded-[var(--radius-md)] px-2 py-1.5">
                    <UserAvatar name={`${p.first_name} ${p.last_name}`} src={p.photo || undefined} className="size-9" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{p.first_name} {p.last_name}</p>
                      <p className="truncate text-xs text-muted-foreground font-mono">{p.patient_id}</p>
                    </div>
                    <span className="text-xs text-subtle-foreground">{p.blood_group}</span>
                  </li>
                ))}
              </ul>
            </DataState>
          </CardContent>
        </Card>
      </div>

      {/* Pending requests — awaiting admin approval */}
      <Card>
        <CardContent className="space-y-4 p-5 sm:p-6">
          <SectionTitle>Pending requests</SectionTitle>
          <DataState
            isLoading={appointmentsQ.isLoading}
            isError={appointmentsQ.isError}
            isEmpty={pending.length === 0}
            onRetry={appointmentsQ.refetch}
            empty={<EmptyState icon={Inbox} title="No pending requests"
              description="New appointment requests from your patients appear here while an administrator reviews them." />}
          >
            <ul className="space-y-2.5">
              {pending.map((a) => (
                <li key={a.id}
                  className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4 sm:flex-row sm:items-center">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{patientLabel(a)}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {formatDate(a.appointment_date)} · {formatTime(a.appointment_time)}
                      {a.reason ? ` · ${a.reason}` : ''}
                    </p>
                  </div>
                  <span className="text-xs text-subtle-foreground">Awaiting admin approval</span>
                </li>
              ))}
            </ul>
          </DataState>
        </CardContent>
      </Card>
    </div>
  )
}
