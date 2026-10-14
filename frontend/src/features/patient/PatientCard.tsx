import { motion } from 'framer-motion'
import {
  IdCard, Printer, ShieldCheck, Phone, Droplet, ScanLine, HeartPulse,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { PageHeader, EmptyState } from '@/components/patterns'
import { ActiveStatusBadge } from '@/components/status-badge'
import { Skeleton } from '@/components/ui/misc'
import { useAuth } from '@/lib/auth'
import { cn, formatDate } from '@/lib/utils'
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
        description="A secure, scannable identity you can carry anywhere."
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
          <div className="relative overflow-hidden rounded-[var(--radius-2xl)] border border-border bg-gradient-to-br from-surface to-surface-2 shadow-[var(--shadow-lg)]">
            <div className="absolute -right-20 -top-20 size-56 rounded-full bg-primary/10 blur-3xl" aria-hidden />
            <div className="absolute -bottom-16 -left-16 size-48 rounded-full bg-info/10 blur-3xl" aria-hidden />

            {/* Brand row */}
            <div className="relative flex items-center justify-between gap-4 border-b border-border px-6 py-5 sm:px-8">
              <div className="flex items-center gap-3">
                <span className="grid size-10 shrink-0 place-items-center rounded-[var(--radius-md)] bg-primary text-primary-foreground">
                  <HeartPulse className="size-5" />
                </span>
                <div className="space-y-0.5">
                  <p className="text-xs font-semibold uppercase tracking-wider text-primary">Mero Care Card</p>
                  <p className="text-xs text-muted-foreground">Digital Health Card</p>
                </div>
              </div>
              <ActiveStatusBadge status={patient.status} />
            </div>

            {/* QR + details */}
            <div className="relative grid gap-6 px-6 py-6 sm:grid-cols-[auto_minmax(0,1fr)] sm:items-center sm:gap-8 sm:px-8">
              <div className="mx-auto grid size-40 shrink-0 place-items-center rounded-[var(--radius-lg)] border border-border bg-white p-3 shadow-[var(--shadow-sm)] sm:mx-0">
                <HealthCardQr id={QR_ELEMENT_ID} uuidToken={patient.uuid_token} />
              </div>
              <div className="min-w-0 space-y-5">
                <dl>
                  <CardFact label="Patient">
                    <span className="font-display text-xl font-semibold leading-tight">{fullName}</span>
                  </CardFact>
                </dl>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-4 border-t border-border pt-5">
                  <CardFact label="Patient ID" mono>{patient.patient_id}</CardFact>
                  <CardFact label="Blood group" mono>{patient.blood_group}</CardFact>
                  <CardFact label="Emergency" mono>{patient.emergency_contact}</CardFact>
                  <CardFact label="Issued">{formatDate(patient.registration_date)}</CardFact>
                </dl>
              </div>
            </div>

            {/* Footer */}
            <div className="relative flex items-center justify-between gap-4 border-t border-border px-6 py-4 text-xs text-muted-foreground sm:px-8">
              <span className="flex items-center gap-2"><ScanLine className="size-4 shrink-0" /> Scan for emergency identity</span>
              <span className="font-mono">mero.care</span>
            </div>
          </div>
        </motion.div>

        {/* Side notes */}
        <div className="space-y-6">
          <Card className="divide-y divide-border">
            <Note icon={ShieldCheck} tone="bg-success-soft text-success" title="Private by design">
              A public scan shows only your name, patient ID, blood group and emergency contact.
              Allergies, medications, reports and history stay private.
            </Note>
            <Note icon={Droplet} tone="bg-primary-soft text-primary-soft-foreground" title="Ready in an emergency">
              Keep a printed copy in your wallet or save it to your phone so care teams can confirm
              who you are and who to contact.
            </Note>
          </Card>

          <Card className="flex items-center gap-4 p-6">
            <span className="grid size-10 shrink-0 place-items-center rounded-[var(--radius-md)] bg-surface-2 text-primary">
              <Phone className="size-5" />
            </span>
            <div className="min-w-0 space-y-1">
              <p className="text-xs uppercase tracking-wide text-subtle-foreground">Emergency contact on file</p>
              <p className="font-mono text-sm font-semibold wrap-break-word">{patient.emergency_contact}</p>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}

/** One labelled value on the card: small caps label above, value below. */
function CardFact({ label, mono, children }: { label: string; mono?: boolean; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-1">
      <dt className="text-xs uppercase tracking-wide text-subtle-foreground">{label}</dt>
      <dd className={cn('text-sm font-semibold wrap-break-word', mono && 'font-mono')}>{children}</dd>
    </div>
  )
}

function Note({ icon: Icon, tone, title, children }: {
  icon: typeof ShieldCheck; tone: string; title: string; children: React.ReactNode
}) {
  return (
    <div className="flex items-start gap-4 p-6">
      <span className={cn('grid size-10 shrink-0 place-items-center rounded-[var(--radius-md)]', tone)}>
        <Icon className="size-5" />
      </span>
      <div className="min-w-0 space-y-1.5">
        <p className="font-semibold leading-tight">{title}</p>
        <p className="text-sm leading-relaxed text-muted-foreground text-pretty">{children}</p>
      </div>
    </div>
  )
}
