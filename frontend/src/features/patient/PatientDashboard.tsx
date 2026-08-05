import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import QRCode from 'react-qr-code'
import {
  CalendarDays, FileText, Pill, IdCard, HeartPulse, ArrowRight,
  Stethoscope, ChevronRight,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  PageHeader, StatCard, StatCardSkeleton, DataState, EmptyState, SectionTitle,
} from '@/components/patterns'
import { AppointmentStatusBadge } from '@/components/status-badge'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/misc'
import { useAuth } from '@/lib/auth'
import { appointmentService, documentService, prescriptionService } from '@/lib/api'
import { formatDate, formatTime } from '@/lib/utils'
import type { Appointment } from '@/lib/types'
import { HealthVitalsCard } from './HealthVitalsCard'

const ACTIVE_STATUSES: Appointment['status'][] = ['PENDING', 'ACCEPTED']

function apptSortKey(a: Appointment) {
  return `${a.appointment_date}T${a.appointment_time}`
}

export function PatientDashboard() {
  const { user, loading, refresh } = useAuth()
  const patient = user?.patient_profile
  const patientId = patient?.id
  const firstName = patient?.first_name || user?.first_name || 'there'

  // Re-fetch /auth/me every time the dashboard mounts (e.g. after navigating
  // back from the reports page where a lab report was just uploaded).
  // refreshAuth() in LabReportUploadDialog already did this eagerly, but this
  // acts as a safety net for any navigation path.
  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])   // run once on mount only — intentionally omit refresh from deps

  const appointmentsQ = useQuery({
    queryKey: ['patient', 'appointments', 'mine'],
    queryFn: () => appointmentService.mine(),
    enabled: !!patientId,
  })
  const documentsQ = useQuery({
    queryKey: ['patient', 'documents', patientId],
    queryFn: () => documentService.list({ patient: patientId }),
    enabled: !!patientId,
  })
  const prescriptionsQ = useQuery({
    queryKey: ['patient', 'prescriptions', patientId],
    queryFn: () => prescriptionService.list({ patient: patientId }),
    enabled: !!patientId,
  })

  // patient_profile is always the freshest copy: AuthProvider.refresh() updates
  // the user state in-place, so patient here reflects the latest DB values
  // including any vitals written by the CDSA after a lab report upload.
  const livePatient = patient

  const appointments = appointmentsQ.data ?? []
  const upcoming = appointments
    .filter((a) => ACTIVE_STATUSES.includes(a.status))
    .sort((a, b) => apptSortKey(a).localeCompare(apptSortKey(b)))
  const reports = documentsQ.data ?? []
  const prescriptions = prescriptionsQ.data ?? []

  const qrLink = patient ? `${window.location.origin}/public-profile/${patient.uuid_token}` : ''

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

  if (!patient) {
    return (
      <div className="space-y-8">
        <PageHeader title="Dashboard" icon={HeartPulse} description="Your personal health overview." />
        <EmptyState
          icon={IdCard}
          title="No patient profile found"
          description="Your account isn't linked to a patient record yet. Please contact your care team."
        />
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title={`Welcome back, ${firstName}`}
        description="Here's a gentle overview of your care — appointments, records, and your health card."
        icon={HeartPulse}
        actions={
          <>
            <Button asChild variant="secondary"><Link to="/patient/find-care"><Stethoscope className="size-4" />Find a doctor</Link></Button>
            <Button asChild><Link to="/patient/appointments"><CalendarDays className="size-4" />Book appointment</Link></Button>
          </>
        }
      />

      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard
          label="Upcoming appointments"
          value={appointmentsQ.isLoading ? '—' : upcoming.length}
          icon={CalendarDays}
          tone="primary"
          hint="Pending or accepted"
        />
        <StatCard
          label="My reports"
          value={documentsQ.isLoading ? '—' : reports.length}
          icon={FileText}
          tone="info"
          hint="Documents on file"
        />
        <StatCard
          label="Prescriptions"
          value={prescriptionsQ.isLoading ? '—' : prescriptions.length}
          icon={Pill}
          tone="success"
          hint="Issued by your clinicians"
        />
      </div>

      {/* ── Health Vitals ── */}
      <HealthVitalsCard patient={livePatient} />

      <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        {/* Upcoming appointments */}
        <section className="space-y-3">
          <SectionTitle action={<Button asChild variant="link" size="sm"><Link to="/patient/appointments">View all</Link></Button>}>
            Upcoming appointments
          </SectionTitle>
          <DataState
            isLoading={appointmentsQ.isLoading}
            isError={appointmentsQ.isError}
            isEmpty={upcoming.length === 0}
            onRetry={() => appointmentsQ.refetch()}
            empty={
              <EmptyState
                icon={CalendarDays}
                title="No upcoming appointments"
                description="When you book a visit, it will appear here."
                action={<Button asChild size="sm"><Link to="/patient/appointments">Book appointment</Link></Button>}
              />
            }
          >
            <div className="space-y-3">
              {upcoming.slice(0, 5).map((a) => (
                <Card key={a.id} className="p-4">
                  <div className="flex items-center gap-4">
                    <span className="grid size-11 shrink-0 place-items-center rounded-[var(--radius-md)] bg-primary-soft text-primary-soft-foreground">
                      <Stethoscope className="size-5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold">
                        {a.doctor_name || `Dr. ${a.doctor_detail?.first_name ?? ''} ${a.doctor_detail?.last_name ?? ''}`.trim()}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {a.doctor_department || a.doctor_detail?.department || 'General'} · {formatDate(a.appointment_date)} · {formatTime(a.appointment_time)}
                      </p>
                    </div>
                    <AppointmentStatusBadge status={a.status} />
                  </div>
                </Card>
              ))}
            </div>
          </DataState>

          {/* Recent reports */}
          <div className="pt-4">
            <SectionTitle action={<Button asChild variant="link" size="sm"><Link to="/patient/reports">View all</Link></Button>}>
              Recent reports
            </SectionTitle>
          </div>
          <DataState
            isLoading={documentsQ.isLoading}
            isError={documentsQ.isError}
            isEmpty={reports.length === 0}
            onRetry={() => documentsQ.refetch()}
            empty={<EmptyState icon={FileText} title="No reports yet" description="Your medical reports and uploads will show here." />}
          >
            <div className="space-y-2">
              {reports.slice(0, 4).map((d) => (
                <Link
                  key={d.id}
                  to="/patient/reports"
                  className="flex items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-3.5 transition-colors hover:bg-surface-2"
                >
                  <span className="grid size-9 shrink-0 place-items-center rounded-[var(--radius-md)] bg-info-soft text-info">
                    <FileText className="size-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{d.name}</p>
                    <p className="truncate text-xs text-muted-foreground">{formatDate(d.uploaded_at)}</p>
                  </div>
                  <Badge variant={d.report_type === 'MEDICAL' ? 'primary' : 'neutral'}>
                    {d.report_type === 'MEDICAL' ? 'Medical' : 'Additional'}
                  </Badge>
                </Link>
              ))}
            </div>
          </DataState>
        </section>

        {/* Health card preview + quick actions */}
        <aside className="space-y-4">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
            <Card className="overflow-hidden">
              <div className="relative bg-gradient-to-br from-primary-soft/60 to-surface-2 p-5">
                <div className="absolute -right-12 -top-12 size-40 rounded-full bg-primary/10 blur-2xl" />
                <div className="relative flex items-start justify-between">
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-primary">Digital Health Card</p>
                    <p className="font-display text-lg font-semibold">
                      {patient.first_name} {patient.last_name}
                    </p>
                  </div>
                  <IdCard className="size-7 text-primary" />
                </div>
                <div className="relative mt-4 flex items-center gap-4">
                  <div className="grid size-20 place-items-center rounded-[var(--radius-md)] border border-border bg-white p-1.5">
                    {qrLink && <QRCode value={qrLink} size={72} level="M" style={{ height: '100%', width: '100%' }} />}
                  </div>
                  <div className="space-y-1.5">
                    <div>
                      <p className="text-[10px] uppercase tracking-wide text-subtle-foreground">Patient ID</p>
                      <p className="font-mono text-sm font-medium">{patient.patient_id}</p>
                    </div>
                    <div>
                      <p className="text-[10px] uppercase tracking-wide text-subtle-foreground">Blood group</p>
                      <p className="font-mono text-sm font-medium">{patient.blood_group}</p>
                    </div>
                  </div>
                </div>
              </div>
              <CardContent className="p-4">
                <Button asChild variant="secondary" className="w-full">
                  <Link to="/patient/card">
                    Open health card <ArrowRight className="size-4" />
                  </Link>
                </Button>
              </CardContent>
            </Card>
          </motion.div>

          <Card className="p-4">
            <SectionTitle className="mb-3">Quick actions</SectionTitle>
            <div className="space-y-2">
              {[
                { to: '/patient/appointments', icon: CalendarDays, label: 'Book appointment' },
                { to: '/patient/find-care', icon: HeartPulse, label: 'Find a doctor' },
                { to: '/patient/reports', icon: FileText, label: 'Upload a report' },
                { to: '/patient/card', icon: IdCard, label: 'View health card' },
              ].map((q) => (
                <Link
                  key={q.to}
                  to={q.to}
                  className="flex items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-3.5 py-2.5 text-sm font-medium transition-colors hover:bg-surface-2"
                >
                  <q.icon className="size-4.5 text-primary" />
                  <span className="flex-1">{q.label}</span>
                  <ChevronRight className="size-4 text-subtle-foreground" />
                </Link>
              ))}
            </div>
          </Card>
        </aside>
      </div>
    </div>
  )
}
