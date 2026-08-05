import { useEffect, useState } from 'react'
import {
  UserCircle, Mail, CalendarClock, Pencil, X, Save,
} from 'lucide-react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Field } from '@/components/ui/label'
import { SimpleSelect } from '@/components/ui/select'
import { Switch, Separator } from '@/components/ui/misc'
import { UserAvatar } from '@/components/ui/avatar'
import { PageHeader, InfoRow, SectionTitle, StatCardSkeleton } from '@/components/patterns'
import { ActiveStatusBadge } from '@/components/status-badge'
import { useAuth } from '@/lib/auth'
import { doctorService } from '@/lib/api'
import { cn, formatDate } from '@/lib/utils'
import type { Doctor, Gender } from '@/lib/types'

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const
const GENDERS: Gender[] = ['Male', 'Female', 'Other']

type DaySchedule = { open: boolean; start: string; end: string }
type ScheduleForm = Record<string, DaySchedule>

interface ProfileForm {
  first_name: string
  last_name: string
  specialization: string
  phone: string
  email: string
  dob: string
  gender: string
  schedule: ScheduleForm
}

/** Coerce a stored time token ("9:00 AM", "09:00") into 24h "HH:MM". */
function to24h(raw?: string): string | null {
  if (!raw) return null
  const m = raw.trim().match(/(\d{1,2}):(\d{2})\s*(AM|PM)?/i)
  if (!m) return null
  let h = parseInt(m[1], 10)
  const min = m[2]
  const period = m[3]?.toUpperCase()
  if (period === 'PM' && h < 12) h += 12
  if (period === 'AM' && h === 12) h = 0
  return `${String(h).padStart(2, '0')}:${min}`
}

function parseDay(value?: string): DaySchedule {
  const v = (value || '').trim()
  if (!v || v.toLowerCase() === 'closed') return { open: false, start: '09:00', end: '17:00' }
  const parts = v.split('-').map((s) => s.trim())
  const start = to24h(parts[0]) || '09:00'
  const end = to24h(parts[1]) || '17:00'
  return { open: true, start, end }
}

function buildForm(doc?: Doctor | null): ProfileForm {
  const sched = doc?.availability_schedule || {}
  const schedule: ScheduleForm = {}
  DAYS.forEach((d) => { schedule[d] = parseDay(sched[d]) })
  return {
    first_name: doc?.first_name || '',
    last_name: doc?.last_name || '',
    specialization: doc?.specialization || '',
    phone: doc?.phone || '',
    email: doc?.email || '',
    dob: doc?.dob || '',
    gender: doc?.gender || '',
    schedule,
  }
}

function serializeSchedule(schedule: ScheduleForm): Record<string, string> {
  const out: Record<string, string> = {}
  DAYS.forEach((d) => {
    const s = schedule[d]
    out[d] = s.open ? `${s.start}-${s.end}` : 'closed'
  })
  return out
}

export function DoctorProfile() {
  const { user, loading, refresh } = useAuth()
  const doc = user?.doctor_profile
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<ProfileForm>(() => buildForm(doc))

  useEffect(() => {
    if (!editing) setForm(buildForm(doc))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc?.id, doc?.registration_date, editing])

  const save = useMutation({
    mutationFn: async () => {
      if (!doc) throw new Error('No profile loaded')
      const fd = new FormData()
      fd.append('first_name', form.first_name.trim())
      fd.append('last_name', form.last_name.trim())
      fd.append('specialization', form.specialization.trim())
      fd.append('phone', form.phone.trim())
      fd.append('email', form.email.trim())
      if (form.dob) fd.append('dob', form.dob)
      if (form.gender) fd.append('gender', form.gender)
      fd.append('availability_schedule', JSON.stringify(serializeSchedule(form.schedule)))
      return doctorService.update(doc.id, fd)
    },
    onSuccess: async () => {
      toast.success('Profile updated.')
      setEditing(false)
      await refresh()
    },
    onError: (err: any) => {
      const data = err.response?.data
      const first = data && typeof data === 'object' ? Object.values(data)[0] : null
      toast.error((Array.isArray(first) ? first[0] : first) || data?.detail || 'Could not save your profile.')
    },
  })

  if (loading) {
    return (
      <div className="space-y-6">
        <StatCardSkeleton />
        <StatCardSkeleton />
      </div>
    )
  }

  if (!doc) {
    return (
      <div className="space-y-8">
        <PageHeader title="My profile" icon={UserCircle} />
        <Card><CardContent className="p-6 text-sm text-muted-foreground">No doctor profile is linked to this account.</CardContent></Card>
      </div>
    )
  }

  const fullName = `Dr. ${form.first_name || doc.first_name || ''} ${form.last_name || doc.last_name || ''}`.trim()

  function setSchedule(day: string, patch: Partial<DaySchedule>) {
    setForm((f) => ({ ...f, schedule: { ...f.schedule, [day]: { ...f.schedule[day], ...patch } } }))
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="My profile"
        description="View and update your clinician details and weekly availability."
        icon={UserCircle}
        actions={
          editing ? (
            <>
              <Button variant="ghost" onClick={() => { setEditing(false); setForm(buildForm(doc)) }} disabled={save.isPending}>
                <X className="size-4" /> Cancel
              </Button>
              <Button onClick={() => save.mutate()} loading={save.isPending}>
                <Save className="size-4" /> Save changes
              </Button>
            </>
          ) : (
            <Button variant="secondary" onClick={() => setEditing(true)}>
              <Pencil className="size-4" /> Edit profile
            </Button>
          )
        }
      />

      {/* Identity header */}
      <Card>
        <CardContent className="flex flex-col items-center gap-4 p-6 sm:flex-row sm:items-center">
          <UserAvatar name={fullName} src={doc.photo || undefined} className="size-20 text-xl" />
          <div className="space-y-1 text-center sm:text-left">
            <h2 className="font-display text-xl font-semibold">{fullName}</h2>
            <p className="text-sm text-muted-foreground">{doc.specialization} · {doc.department}</p>
            <div className="flex items-center justify-center gap-2 sm:justify-start">
              <span className="font-mono text-xs text-subtle-foreground">{doc.doctor_id}</span>
              <ActiveStatusBadge status={doc.status} />
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Clinical (mostly read-only) */}
        <Card>
          <CardContent className="space-y-5 p-5 sm:p-6">
            <SectionTitle>Clinical details</SectionTitle>
            {editing ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="First name" htmlFor="first_name">
                  <Input id="first_name" value={form.first_name} onChange={(e) => setForm((f) => ({ ...f, first_name: e.target.value }))} />
                </Field>
                <Field label="Last name" htmlFor="last_name">
                  <Input id="last_name" value={form.last_name} onChange={(e) => setForm((f) => ({ ...f, last_name: e.target.value }))} />
                </Field>
                <Field label="Specialization" htmlFor="specialization" className="sm:col-span-2">
                  <Input id="specialization" value={form.specialization} onChange={(e) => setForm((f) => ({ ...f, specialization: e.target.value }))} />
                </Field>
                <Field label="Date of birth" htmlFor="dob">
                  <Input id="dob" type="date" value={form.dob} onChange={(e) => setForm((f) => ({ ...f, dob: e.target.value }))} />
                </Field>
                <Field label="Gender" htmlFor="gender">
                  <SimpleSelect id="gender" value={form.gender} onValueChange={(v) => setForm((f) => ({ ...f, gender: v }))}
                    options={GENDERS} placeholder="Select gender" />
                </Field>
              </div>
            ) : (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-4">
                <InfoRow label="Specialization" value={doc.specialization} />
                <InfoRow label="Gender" value={doc.gender} />
                <InfoRow label="Date of birth" value={formatDate(doc.dob)} />
                <InfoRow label="Age" value={doc.age != null ? `${doc.age} yrs` : '—'} />
              </dl>
            )}

            <Separator />
            <p className="text-xs text-subtle-foreground">Managed by administration</p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-4">
              <InfoRow label="Doctor ID" value={doc.doctor_id} mono />
              <InfoRow label="License number" value={doc.license_number} mono />
              <InfoRow label="Department" value={doc.department} />
              <InfoRow label="Status" value={doc.status} />
            </dl>
          </CardContent>
        </Card>

        {/* Contact */}
        <Card>
          <CardContent className="space-y-5 p-5 sm:p-6">
            <SectionTitle>Contact</SectionTitle>
            {editing ? (
              <div className="grid gap-4">
                <Field label="Email" htmlFor="email">
                  <Input id="email" type="email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
                </Field>
                <Field label="Phone" htmlFor="phone" hint="Nepal mobile format, e.g. 98XXXXXXXX.">
                  <Input id="phone" value={form.phone} onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))} />
                </Field>
              </div>
            ) : (
              <dl className="grid gap-4">
                <InfoRow label="Email" value={doc.email} mono />
                <InfoRow label="Phone" value={doc.phone} mono />
              </dl>
            )}
            <div className="flex items-center gap-2 rounded-[var(--radius-md)] bg-surface-2/60 p-3 text-xs text-muted-foreground">
              <Mail className="size-4 shrink-0" />
              Keep your contact details current so patients and admins can reach you.
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Availability */}
      <Card>
        <CardContent className="space-y-4 p-5 sm:p-6">
          <SectionTitle>
            <span className="inline-flex items-center gap-2"><CalendarClock className="size-4" /> Weekly availability</span>
          </SectionTitle>

          {editing ? (
            <div className="divide-y divide-border rounded-[var(--radius-md)] border border-border">
              {DAYS.map((day) => {
                const d = form.schedule[day]
                return (
                  <div key={day} className="flex flex-wrap items-center gap-3 px-4 py-3">
                    <span className="w-24 shrink-0 text-sm font-medium">{day}</span>
                    <label className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Switch checked={d.open} onCheckedChange={(v) => setSchedule(day, { open: v })} />
                      {d.open ? 'Open' : 'Closed'}
                    </label>
                    {d.open ? (
                      <div className="flex items-center gap-2">
                        <Input type="time" value={d.start} onChange={(e) => setSchedule(day, { start: e.target.value })}
                          className="h-9 w-32" />
                        <span className="text-xs text-muted-foreground">to</span>
                        <Input type="time" value={d.end} onChange={(e) => setSchedule(day, { end: e.target.value })}
                          className="h-9 w-32" />
                      </div>
                    ) : (
                      <span className="text-xs italic text-subtle-foreground">Not available</span>
                    )}
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              {DAYS.map((day) => {
                const d = parseDay(doc.availability_schedule?.[day])
                return (
                  <div key={day} className="flex items-center justify-between rounded-[var(--radius-md)] border border-border bg-surface px-4 py-2.5">
                    <span className="text-sm font-medium">{day}</span>
                    <span className={cn('text-sm', d.open ? 'font-medium' : 'text-subtle-foreground')}>
                      {d.open ? `${d.start} – ${d.end}` : 'Closed'}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
