import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ShieldCheck, Droplet, AlertCircle, Lock } from 'lucide-react'
import { Wordmark } from '@/components/brand'
import { ThemeToggle } from '@/components/theme-toggle'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { InfoRow } from '@/components/patterns'
import { UserAvatar } from '@/components/ui/avatar'
import { Skeleton } from '@/components/ui/misc'
import { patientService } from '@/lib/api'
import type { Patient } from '@/lib/types'

export function PublicProfilePage() {
  const { uuid } = useParams<{ uuid: string }>()
  const [patient, setPatient] = useState<Patient | null>(null)
  const [state, setState] = useState<'loading' | 'ok' | 'error'>('loading')

  useEffect(() => {
    if (!uuid) return
    patientService.publicProfile(uuid)
      .then((p) => { setPatient(p); setState('ok') })
      .catch(() => setState('error'))
  }, [uuid])

  const name = patient ? [patient.first_name, patient.middle_name, patient.last_name].filter(Boolean).join(' ') : ''

  return (
    <div className="min-h-dvh bg-background">
      <header className="border-b border-border glass">
        <div className="mx-auto flex h-16 max-w-2xl items-center justify-between px-4">
          <Link to="/"><Wordmark /></Link>
          <ThemeToggle />
        </div>
      </header>

      <main className="mx-auto max-w-2xl px-4 py-10">
        <div className="mb-6 flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <ShieldCheck className="size-4 text-primary" />
          Verified emergency identity card
        </div>

        {state === 'loading' && (
          <Card><CardContent className="space-y-4 p-6">
            <div className="flex items-center gap-4"><Skeleton className="size-16 rounded-full" /><div className="space-y-2"><Skeleton className="h-5 w-40" /><Skeleton className="h-4 w-24" /></div></div>
            <Skeleton className="h-24 w-full" />
          </CardContent></Card>
        )}

        {state === 'error' && (
          <Card><CardContent className="flex flex-col items-center gap-3 py-14 text-center">
            <span className="grid size-14 place-items-center rounded-full bg-danger-soft text-danger"><AlertCircle className="size-7" /></span>
            <div><p className="font-medium">Card not found</p><p className="text-sm text-muted-foreground">This health card link is invalid or has expired.</p></div>
          </CardContent></Card>
        )}

        {state === 'ok' && patient && (
          <Card className="overflow-hidden">
            <div className="border-b border-border bg-primary-soft/40 p-6">
              <div className="flex items-center gap-4">
                <UserAvatar name={name} src={patient.photo} className="size-16 ring-2 ring-surface" />
                <div className="min-w-0">
                  <p className="font-display text-xl font-semibold truncate">{name}</p>
                  <p className="font-mono text-sm text-muted-foreground">{patient.patient_id}</p>
                </div>
                <div className="ml-auto">
                  {patient.status === 'Active' ? <Badge variant="success">Active</Badge> : <Badge variant="neutral">Inactive</Badge>}
                </div>
              </div>
            </div>
            <CardContent className="p-6">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3">
                <InfoRow label="Blood group" value={<span className="inline-flex items-center gap-1.5"><Droplet className="size-4 text-danger" />{patient.blood_group}</span>} />
                <InfoRow label="Age" value={patient.age != null ? `${patient.age} yrs` : '—'} />
                <InfoRow label="Gender" value={patient.gender} />
                <InfoRow label="Emergency" value={patient.emergency_contact} mono />
              </dl>
              {patient.address && (
                <div className="mt-5 border-t border-border pt-5">
                  <InfoRow label="Address" value={patient.address} />
                </div>
              )}
            </CardContent>
            <div className="flex items-center gap-2 border-t border-border bg-surface-2/50 px-6 py-4 text-xs text-muted-foreground">
              <Lock className="size-3.5 shrink-0" />
              <p className="text-pretty">Medical records, medications and reports are private. Only assigned clinicians can access them after signing in.</p>
            </div>
          </Card>
        )}
      </main>
    </div>
  )
}
