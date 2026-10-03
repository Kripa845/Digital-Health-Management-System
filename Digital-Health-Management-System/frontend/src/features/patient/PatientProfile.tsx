import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import {
  UserCircle, KeyRound, IdCard, HeartPulse, Phone, ShieldCheck, AlertTriangle, Pencil,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input, Textarea } from '@/components/ui/input'
import { Field } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose,
} from '@/components/ui/dialog'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { UserAvatar } from '@/components/ui/avatar'
import { PageHeader, InfoRow, EmptyState } from '@/components/patterns'
import { ActiveStatusBadge } from '@/components/status-badge'
import { Skeleton } from '@/components/ui/misc'
import { useAuth } from '@/lib/auth'
import { patientService } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import type { Patient } from '@/lib/types'
import { NAME_RE, formatName } from '@/features/admin/admin-utils'

// Same rules the server applies (apps/patients/serializers.py).
const NEPAL_PHONE = /^(98|97)\d{8}$/
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const MAX_PHOTO = 5 * 1024 * 1024

type ContactForm = {
  first_name: string; middle_name: string; last_name: string
  phone: string; emergency_contact: string; email: string; address: string
}

function validateContact(f: ContactForm): Partial<Record<keyof ContactForm, string>> {
  const e: Partial<Record<keyof ContactForm, string>> = {}
  const NAME_HINT = 'Letters only (hyphens, apostrophes and dots are fine).'
  if (f.first_name.trim().length < 2) e.first_name = 'First name must be at least 2 characters.'
  else if (!NAME_RE.test(f.first_name.trim())) e.first_name = NAME_HINT
  if (f.middle_name.trim() && !NAME_RE.test(f.middle_name.trim())) e.middle_name = NAME_HINT
  if (f.last_name.trim().length < 2) e.last_name = 'Last name must be at least 2 characters.'
  else if (!NAME_RE.test(f.last_name.trim())) e.last_name = NAME_HINT
  if (!NEPAL_PHONE.test(f.phone.trim())) e.phone = 'Enter a 10-digit mobile number starting with 98 or 97.'
  if (!NEPAL_PHONE.test(f.emergency_contact.trim())) e.emergency_contact = 'Enter a 10-digit mobile number starting with 98 or 97.'
  else if (f.emergency_contact.trim() === f.phone.trim()) e.emergency_contact = 'Use a different number from your own.'
  if (!f.email.trim()) e.email = 'Email is required.'
  else if (!EMAIL_RE.test(f.email.trim())) e.email = 'Enter a valid email address.'
  else if (f.email.trim() !== f.email.trim().toLowerCase()) e.email = 'Use lowercase letters only.'
  if (f.address.trim().length < 5) e.address = 'Address must be at least 5 characters.'
  return e
}

/** Lets a patient change their contact details and photo. */
function EditProfileDialog({ patient, open, onOpenChange }: {
  patient: Patient
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { refresh } = useAuth()
  const initial: ContactForm = {
    first_name: patient.first_name ?? '',
    middle_name: patient.middle_name ?? '',
    last_name: patient.last_name ?? '',
    phone: patient.phone ?? '',
    emergency_contact: patient.emergency_contact ?? '',
    email: patient.email ?? '',
    address: patient.address ?? '',
  }
  const [form, setForm] = useState<ContactForm>(initial)
  const [photo, setPhoto] = useState<File | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Start from the saved values every time the dialog opens.
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) { setForm(initial); setPhoto(null); setErrors({}) }
  }

  const set = (k: keyof ContactForm, v: string) => setForm((s) => ({ ...s, [k]: v }))

  const save = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      for (const [k, v] of Object.entries(form) as [keyof ContactForm, string][]) {
        if (v.trim() !== (initial[k] ?? '').trim()) fd.append(k, v.trim())
      }
      if (photo) fd.append('photo', photo)
      return patientService.updateMe(fd)
    },
    onSuccess: async () => {
      await refresh()
      toast.success('Your profile has been updated.')
      onOpenChange(false)
    },
    onError: (err: any) => {
      const data = err?.response?.data
      if (data && typeof data === 'object' && !data.detail) {
        const fieldErrors: Record<string, string> = {}
        for (const [k, v] of Object.entries(data)) fieldErrors[k] = Array.isArray(v) ? String(v[0]) : String(v)
        setErrors(fieldErrors)
        toast.error('Please fix the highlighted fields.')
      } else {
        toast.error(data?.detail || 'Could not update your profile.')
      }
    },
  })

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const errs: Record<string, string> = { ...validateContact(form) }
    if (photo && photo.size > MAX_PHOTO) errs.photo = 'Photo must be 5 MB or smaller.'
    setErrors(errs)
    if (Object.keys(errs).length) return
    const changed = photo || (Object.keys(form) as (keyof ContactForm)[]).some((k) => form[k].trim() !== (initial[k] ?? '').trim())
    if (!changed) { onOpenChange(false); return }
    save.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!save.isPending) onOpenChange(o) }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit profile</DialogTitle>
          <DialogDescription>Update your name, how your care team can reach you, and your photo.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="First name" htmlFor="pp-first" required error={errors.first_name}>
              <Input id="pp-first" autoComplete="given-name" maxLength={50} value={form.first_name}
                onChange={(e) => set('first_name', formatName(e.target.value))} />
            </Field>
            <Field label="Middle name" htmlFor="pp-middle" error={errors.middle_name}>
              <Input id="pp-middle" autoComplete="additional-name" maxLength={50} value={form.middle_name}
                onChange={(e) => set('middle_name', formatName(e.target.value))} />
            </Field>
            <Field label="Last name" htmlFor="pp-last" required error={errors.last_name}>
              <Input id="pp-last" autoComplete="family-name" maxLength={50} value={form.last_name}
                onChange={(e) => set('last_name', formatName(e.target.value))} />
            </Field>
          </div>
          {(form.first_name.trim() !== initial.first_name.trim() || form.last_name.trim() !== initial.last_name.trim()
            || form.middle_name.trim() !== initial.middle_name.trim()) && (
            <p className="rounded-[var(--radius-md)] bg-warning-soft px-3 py-2 text-xs text-warning">
              Use your name exactly as it appears on your lab reports, or uploaded reports won't match.
              Your care team is notified when you change your name. You still sign in with the same username.
            </p>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Phone" htmlFor="pp-phone" required error={errors.phone}>
              <Input id="pp-phone" inputMode="numeric" maxLength={10} value={form.phone}
                onChange={(e) => set('phone', e.target.value.replace(/\D/g, ''))} />
            </Field>
            <Field label="Emergency contact" htmlFor="pp-emergency" required error={errors.emergency_contact}>
              <Input id="pp-emergency" inputMode="numeric" maxLength={10} value={form.emergency_contact}
                onChange={(e) => set('emergency_contact', e.target.value.replace(/\D/g, ''))} />
            </Field>
          </div>
          <Field label="Email" htmlFor="pp-email" required error={errors.email}>
            <Input id="pp-email" type="email" autoComplete="email" value={form.email}
              onChange={(e) => set('email', e.target.value)} />
          </Field>
          <Field label="Address" htmlFor="pp-address" required error={errors.address}>
            <Textarea id="pp-address" rows={2} maxLength={255} value={form.address}
              onChange={(e) => set('address', e.target.value)} />
          </Field>
          <Field label="Photo" htmlFor="pp-photo" hint="Optional · JPG or PNG, max 5 MB · shown on your health card" error={errors.photo}>
            <Input id="pp-photo" type="file" accept="image/png,image/jpeg"
              onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
          </Field>
          <p className="text-xs text-muted-foreground">
            Your date of birth, gender, blood group and medical details can only be changed by your care team.
          </p>
          <DialogFooter>
            <DialogClose asChild><Button type="button" variant="secondary" disabled={save.isPending}>Cancel</Button></DialogClose>
            <Button type="submit" loading={save.isPending}>Save changes</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function PatientProfile() {
  const { user, loading } = useAuth()
  const patient = user?.patient_profile
  const [editing, setEditing] = useState(false)

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
        description="Your details on file. You can update your name, contact details and photo."
        icon={UserCircle}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => setEditing(true)}>
              <Pencil className="size-4" /> Edit profile
            </Button>
            <Button asChild variant="secondary">
              <Link to="/change-password"><KeyRound className="size-4" /> Change password</Link>
            </Button>
          </div>
        }
      />
      <EditProfileDialog patient={patient} open={editing} onOpenChange={setEditing} />

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
          You can change your name, phone numbers, email, address and photo with <strong>Edit profile</strong>.
          To keep your medical information accurate, your date of birth, gender, blood group and medical details
          can only be changed by your care team.
        </p>
      </div>
    </div>
  )
}
