import { Link } from 'react-router-dom'
import {
  UserCircle, KeyRound, IdCard, HeartPulse, Phone, ShieldCheck, AlertTriangle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { UserAvatar } from '@/components/ui/avatar'
import { PageHeader, InfoRow, EmptyState } from '@/components/patterns'
import { ActiveStatusBadge } from '@/components/status-badge'
import { Skeleton } from '@/components/ui/misc'
import { useAuth } from '@/lib/auth'
import { formatDate } from '@/lib/utils'

export function PatientProfile() {
  const { user, loading } = useAuth()
  const patient = user?.patient_profile

  if (loading) {
    return (
      <div className="space-y-8">
        <Skeleton className="h-16 w-72" />
        <Skeleton className="h-32 rounded-[var(--radius-lg)]" />
        <div className="grid gap-6 sm:grid-cols-2">
          <Skeleton className="h-56 rounded-[var(--radius-lg)]" />
          <Skeleton className="h-56 rounded-[var(--radius-lg)]" />
        </div>
      </div>
    )
  }

  if (!patient) {
    return (
      <div className="space-y-8">
        <PageHeader title="My profile" icon={UserCircle} description="Your personal and medical details." />
        <EmptyState icon={UserCircle} title="No patient profile found" description="Your account isn't linked to a patient record yet. Please contact your care team." />
      </div>
    )
  }

  const fullName = [patient.first_name, patient.middle_name, patient.last_name].filter(Boolean).join(' ')

  return (
    <div className="space-y-8">
      <PageHeader
        title="My profile"
        description="A read-only view of the details your care team keeps on file."
        icon={UserCircle}
        actions={
          <Button asChild variant="secondary">
            <Link to="/change-password"><KeyRound className="size-4" /> Change password</Link>
          </Button>
        }
      />

      {/* Identity header */}
      <Card>
        <CardContent className="flex flex-col items-center gap-5 p-6 text-center sm:flex-row sm:text-left">
          <UserAvatar name={fullName} src={patient.photo} className="size-20" />
          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-center gap-2 sm:justify-start">
              <h2 className="font-display text-xl font-semibold">{fullName}</h2>
              <ActiveStatusBadge status={patient.status} />
            </div>
            <p className="font-mono text-sm text-primary">{patient.patient_id}</p>
          </div>
        </CardContent>
      </Card>

      {/* Allergy alert */}
      <div className={`flex items-start gap-3 rounded-[var(--radius-md)] border p-4 ${patient.allergies ? 'border-danger/30 bg-danger-soft' : 'border-border bg-surface-2/50'}`}>
        <AlertTriangle className={`mt-0.5 size-5 shrink-0 ${patient.allergies ? 'text-danger' : 'text-primary'}`} />
        <div>
          <p className={`text-xs font-semibold uppercase tracking-wide ${patient.allergies ? 'text-danger' : 'text-subtle-foreground'}`}>Allergies / medical alert</p>
          <p className="text-sm font-medium text-pretty">{patient.allergies || 'No known allergies reported.'}</p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Personal */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <IdCard className="size-4.5 text-primary" /> Personal
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-4">
              <InfoRow label="Patient ID" value={patient.patient_id} mono />
              <InfoRow label="Date of birth" value={formatDate(patient.dob)} />
              <InfoRow label="Age" value={patient.age != null ? `${patient.age} yrs` : undefined} />
              <InfoRow label="Gender" value={patient.gender} />
              <InfoRow label="Registered" value={formatDate(patient.registration_date)} />
            </dl>
          </CardContent>
        </Card>

        {/* Medical */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <HeartPulse className="size-4.5 text-primary" /> Medical
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-4">
              <InfoRow label="Blood group" value={patient.blood_group} mono />
              <InfoRow label="Height" value={patient.height != null ? `${patient.height} cm` : undefined} />
              <InfoRow label="Weight" value={patient.weight != null ? `${patient.weight} kg` : undefined} />
              <InfoRow label="Current medication" value={patient.current_medication || 'None recorded'} />
            </dl>
          </CardContent>
        </Card>

        {/* Contact */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Phone className="size-4.5 text-primary" /> Contact
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-4">
              <InfoRow label="Phone" value={patient.phone} mono />
              <InfoRow label="Emergency" value={patient.emergency_contact} mono />
              <InfoRow label="Email" value={patient.email || undefined} />
              <InfoRow label="Address" value={patient.address} />
            </dl>
          </CardContent>
        </Card>
      </div>

      <div className="flex items-start gap-3 rounded-[var(--radius-md)] border border-border bg-surface-2/50 p-4">
        <ShieldCheck className="mt-0.5 size-5 shrink-0 text-primary" />
        <p className="text-sm text-muted-foreground text-pretty">
          Contact your care team to update records. To keep your medical information accurate, core profile
          details can only be changed by an administrator.
        </p>
      </div>
    </div>
  )
}
