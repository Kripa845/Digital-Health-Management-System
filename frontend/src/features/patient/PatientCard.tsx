import { motion } from 'framer-motion'
import {
  IdCard, Printer, ShieldCheck, Phone, Droplet, ScanLine, HeartPulse,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { PageHeader, EmptyState } from '@/components/patterns'
import { ActiveStatusBadge } from '@/components/status-badge'
import { Skeleton } from '@/components/ui/misc'
import { useAuth } from '@/lib/auth'
import { formatDate } from '@/lib/utils'
import { printHealthCard } from '@/lib/qr'
import { HealthCardQr } from '@/components/health-card-qr'

const QR_ELEMENT_ID = 'patient-card-qr'

export function PatientCard() {
  const { user, loading } = useAuth()
  const patient = user?.patient_profile

  const fullName = patient
    ? [patient.first_name, patient.middle_name, patient.last_name].filter(Boolean).join(' ')
    : ''

  function handlePrint() {
    if (!patient) return
    printHealthCard(QR_ELEMENT_ID, {
      fullName,
      patientId: patient.patient_id,
      bloodGroup: patient.blood_group,
      emergencyContact: patient.emergency_contact,
    })
  }

  if (loading) {
    return (
      <div className="space-y-8">
        <Skeleton className="h-16 w-72" />
        <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
          <Skeleton className="h-96 rounded-[var(--radius-lg)]" />
          <Skeleton className="h-96 rounded-[var(--radius-lg)]" />
        </div>
      </div>
    )
  }

  if (!patient) {
    return (
      <div className="space-y-8">
        <PageHeader title="Health card" icon={IdCard} description="Your secure digital health card." />
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
        title="Your health card"
        description="A secure, scannable identity you can carry anywhere — for the moments that matter."
        icon={IdCard}
        actions={
          <Button variant="secondary" onClick={handlePrint}>
            <Printer className="size-4" /> Print card
          </Button>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[1.15fr_1fr] lg:items-start">
        {/* The card */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
        >
          <div className="relative overflow-hidden rounded-[var(--radius-2xl)] border border-border bg-gradient-to-br from-surface to-surface-2 p-6 shadow-[var(--shadow-lg)] sm:p-8">
            <div className="absolute -right-20 -top-20 size-56 rounded-full bg-primary/10 blur-3xl" aria-hidden />
            <div className="absolute -bottom-16 -left-16 size-48 rounded-full bg-info/10 blur-3xl" aria-hidden />

            <div className="relative flex items-start justify-between">
              <div className="flex items-center gap-2.5">
                <span className="grid size-10 place-items-center rounded-[var(--radius-md)] bg-primary text-primary-foreground">
                  <HeartPulse className="size-5" />
                </span>
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-primary">Mero Care Card</p>
                  <p className="text-xs text-muted-foreground">Digital Health Card</p>
                </div>
              </div>
              <ActiveStatusBadge status={patient.status} />
            </div>

            <div className="relative mt-7 flex flex-col items-center gap-5 sm:flex-row sm:items-center">
              <div className="grid size-40 shrink-0 place-items-center rounded-[var(--radius-lg)] border border-border bg-white p-3 shadow-[var(--shadow-sm)]">
                <HealthCardQr id={QR_ELEMENT_ID} uuidToken={patient.uuid_token} />
              </div>
              <div className="min-w-0 flex-1 space-y-4 text-center sm:text-left">
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-subtle-foreground">Patient</p>
                  <p className="font-display text-xl font-semibold leading-tight">{fullName}</p>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-subtle-foreground">Patient ID</p>
                    <p className="font-mono text-sm font-semibold">{patient.patient_id}</p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-subtle-foreground">Blood group</p>
                    <p className="font-mono text-sm font-semibold">{patient.blood_group}</p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-subtle-foreground">Emergency</p>
                    <p className="font-mono text-sm font-semibold">{patient.emergency_contact}</p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-subtle-foreground">Issued</p>
                    <p className="text-sm font-semibold">{formatDate(patient.registration_date)}</p>
                  </div>
                </div>
              </div>
            </div>

            <div className="relative mt-7 flex items-center justify-between border-t border-border pt-4 text-xs text-muted-foreground">
              <span className="flex items-center gap-1.5"><ScanLine className="size-3.5" /> Scan for emergency identity</span>
              <span className="font-mono">mero.care</span>
            </div>
          </div>
        </motion.div>

        {/* Side notes */}
        <div className="space-y-4">
          <Card>
            <CardContent className="space-y-4 p-6">
              <div className="flex items-start gap-3">
                <span className="grid size-10 shrink-0 place-items-center rounded-[var(--radius-md)] bg-success-soft text-success">
                  <ShieldCheck className="size-5" />
                </span>
                <div>
                  <p className="font-semibold">Private by design</p>
                  <p className="mt-1 text-sm text-muted-foreground text-pretty leading-relaxed">
                    A public scan of your QR code only shows identity essentials — your name, patient ID,
                    blood group, and emergency contact. Your allergies, medications, reports, and history
                    are never exposed to a public scan.
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <span className="grid size-10 shrink-0 place-items-center rounded-[var(--radius-md)] bg-primary-soft text-primary-soft-foreground">
                  <Droplet className="size-5" />
                </span>
                <div>
                  <p className="font-semibold">Ready in an emergency</p>
                  <p className="mt-1 text-sm text-muted-foreground text-pretty leading-relaxed">
                    Carry a printed copy in your wallet or save it to your phone. Care teams can scan it to
                    quickly confirm who you are and who to contact.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="flex items-center gap-3 p-5">
              <Phone className="size-5 shrink-0 text-primary" />
              <div className="min-w-0">
                <p className="text-xs text-subtle-foreground">Emergency contact on file</p>
                <p className="font-mono text-sm font-semibold">{patient.emergency_contact}</p>
              </div>
            </CardContent>
          </Card>

          <Button variant="secondary" className="w-full" onClick={handlePrint}>
            <Printer className="size-4" /> Print card
          </Button>
        </div>
      </div>
    </div>
  )
}
