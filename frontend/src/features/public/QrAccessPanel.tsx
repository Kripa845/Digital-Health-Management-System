import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { Clock, FileLock2, HeartPulse, Pill, Phone, FlaskConical, XCircle, Loader2, CheckCircle2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input, Textarea } from '@/components/ui/input'
import { Field } from '@/components/ui/label'
import { InfoRow } from '@/components/patterns'
import { qrAccessService } from '@/lib/api'
import type { QrAccessRequestInput, QrExtendedRecord } from '@/lib/types'
import { formatDateTime } from '@/lib/utils'

/**
 * Below the public card: ask an admin for the rest of the record. The request's token
 * is kept in this browser only, so an approval shows the information on this phone
 * and nowhere else. Storage may be unavailable (private mode): then it lasts this visit.
 */
const storageKey = (uuid: string) => `qr-access:${uuid}`

function readToken(uuid: string) {
  try { return localStorage.getItem(storageKey(uuid)) } catch { return null }
}
function writeToken(uuid: string, token: string | null) {
  try {
    if (token) localStorage.setItem(storageKey(uuid), token)
    else localStorage.removeItem(storageKey(uuid))
  } catch { /* storage blocked: keep it in memory only */ }
}

const EMPTY: QrAccessRequestInput = { requester_name: '', requester_phone: '', reason: '' }

export function QrAccessPanel({ uuid }: { uuid: string }) {
  const [token, setTokenState] = useState<string | null>(() => readToken(uuid))
  const [formOpen, setFormOpen] = useState(false)
  const setToken = (t: string | null) => { writeToken(uuid, t); setTokenState(t) }

  const statusQ = useQuery({
    queryKey: ['qr-access', uuid, token],
    queryFn: () => qrAccessService.status(uuid, token!),
    enabled: !!token,
    retry: (count, err) => !(isAxiosError(err) && err.response?.status === 404) && count < 2,
    // Ask again every few seconds while the admin decides.
    refetchInterval: (q) => (q.state.data?.status === 'PENDING' ? 5000 : false),
  })

  // A token the server no longer knows (e.g. the card was replaced): start over.
  const unknownToken = !!token && isAxiosError(statusQ.error) && statusQ.error.response?.status === 404
  useEffect(() => {
    if (unknownToken) { writeToken(uuid, null); setTokenState(null) }
  }, [unknownToken, uuid])

  if (!token) {
    return formOpen
      ? <RequestForm uuid={uuid} onCancel={() => setFormOpen(false)} onSent={(t) => { setToken(t); setFormOpen(false) }} />
      : (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-6 text-center">
            <FileLock2 className="size-6 text-primary" />
            <div>
              <p className="font-medium">Need more medical information?</p>
              <p className="text-sm text-muted-foreground text-pretty">
                Allergies, medication, lab results and contact details are shown only after an administrator approves your request.
              </p>
            </div>
            <Button onClick={() => setFormOpen(true)}>Request more information</Button>
          </CardContent>
        </Card>
      )
  }

  const state = statusQ.data
  if (!state) {
    return (
      <Card><CardContent className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />Checking your request…
      </CardContent></Card>
    )
  }

  if (state.status === 'PENDING') {
    return (
      <Card><CardContent className="flex flex-col items-center gap-3 py-6 text-center">
        <Clock className="size-6 text-warning" />
        <div>
          <p className="font-medium">Waiting for an administrator</p>
          <p className="text-sm text-muted-foreground text-pretty">
            Your request was sent {formatDateTime(state.created_at)}. Keep this page open — it updates by itself once it is approved or declined.
          </p>
        </div>
        <Badge variant="warning">Pending</Badge>
      </CardContent></Card>
    )
  }

  if (state.status === 'APPROVED' && state.record) {
    return <ExtendedRecord record={state.record} expiresAt={state.expires_at} />
  }

  const declined = state.status === 'DECLINED'
  return (
    <Card><CardContent className="flex flex-col items-center gap-3 py-6 text-center">
      <XCircle className="size-6 text-muted-foreground" />
      <div>
        <p className="font-medium">{declined ? 'Request declined' : 'Access has ended'}</p>
        <p className="text-sm text-muted-foreground text-pretty">
          {declined
            ? 'An administrator declined this request. Only the information above can be shown.'
            : 'The time allowed for viewing this information is over.'}
        </p>
      </div>
      <Button variant="secondary" onClick={() => { setToken(null); setFormOpen(true) }}>Request again</Button>
    </CardContent></Card>
  )
}

function RequestForm({ uuid, onSent, onCancel }: { uuid: string; onSent: (token: string) => void; onCancel: () => void }) {
  const [form, setForm] = useState<QrAccessRequestInput>(EMPTY)
  const [errors, setErrors] = useState<Partial<Record<keyof QrAccessRequestInput | 'detail', string>>>({})
  const set = (k: keyof QrAccessRequestInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  const send = useMutation({
    mutationFn: () => qrAccessService.request(uuid, form),
    onSuccess: (s) => onSent(s.token),
    onError: (err) => {
      const data = isAxiosError(err) ? err.response?.data : null
      const code = isAxiosError(err) ? err.response?.status : undefined
      if (code === 429) return setErrors({ detail: 'Too many requests from this network. Please try again later.' })
      const pick = (v: unknown) => (Array.isArray(v) ? v.join(' ') : typeof v === 'string' ? v : undefined)
      setErrors({
        requester_name: pick(data?.requester_name),
        requester_phone: pick(data?.requester_phone),
        reason: pick(data?.reason),
        detail: pick(data?.detail) ?? (data ? undefined : 'Could not send the request. Check your connection and try again.'),
      })
    },
  })

  return (
    <Card>
      <CardContent className="space-y-4 p-6">
        <div>
          <p className="font-medium">Request more information</p>
          <p className="text-sm text-muted-foreground text-pretty">
            An administrator checks who you are before approving. If approved, this phone can see the information for 24 hours.
          </p>
        </div>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); setErrors({}); send.mutate() }}>
          <Field label="Your full name" htmlFor="qr-name" required error={errors.requester_name}>
            <Input id="qr-name" autoComplete="name" value={form.requester_name} onChange={set('requester_name')} />
          </Field>
          <Field label="Your mobile number" htmlFor="qr-phone" required error={errors.requester_phone} hint="98XXXXXXXX or 97XXXXXXXX — the administrator may call you.">
            <Input id="qr-phone" type="tel" inputMode="numeric" autoComplete="tel" value={form.requester_phone} onChange={set('requester_phone')} />
          </Field>
          <Field label="Why do you need it?" htmlFor="qr-reason" required error={errors.reason} hint="e.g. I am a paramedic; the patient is unconscious and needs treatment.">
            <Textarea id="qr-reason" rows={3} maxLength={500} value={form.reason} onChange={set('reason')} />
          </Field>
          {errors.detail && <p className="text-sm text-danger">{errors.detail}</p>}
          <div className="flex gap-2">
            <Button type="button" variant="secondary" className="flex-1" onClick={onCancel}>Cancel</Button>
            <Button type="submit" className="flex-1" loading={send.isPending}>Send request</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

const LAB_STATUS: Record<string, 'success' | 'warning' | 'danger' | 'neutral'> = {
  Normal: 'success', Low: 'warning', High: 'danger',
}

function withUnit(value: string | number | null | undefined, unit: string) {
  return value == null || value === '' ? undefined : `${value} ${unit}`.trim()
}

function ExtendedRecord({ record, expiresAt }: { record: QrExtendedRecord; expiresAt: string | null }) {
  const { medical, body, contact, lab_results } = record
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-center gap-2 text-sm text-success">
        <CheckCircle2 className="size-4" />
        Approved — visible on this phone until {formatDateTime(expiresAt)}
      </div>

      <Section icon={Pill} title="Allergies & medication">
        <dl className="grid gap-4">
          <InfoRow label="Allergies" value={medical.allergies || 'None recorded'} />
          <InfoRow label="Current medication" value={medical.current_medication || 'None recorded'} />
          {medical.prescription && <InfoRow label="Prescription notes" value={medical.prescription} />}
        </dl>
      </Section>

      <Section icon={HeartPulse} title="Vitals & body">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3">
          <InfoRow label="Height" value={withUnit(body.height, 'cm')} />
          <InfoRow label="Weight" value={withUnit(body.weight, 'kg')} />
          <InfoRow label="BMI" value={body.bmi != null ? `${body.bmi}${body.bmi_status ? ` (${body.bmi_status})` : ''}` : undefined} />
          <InfoRow label="Blood pressure" value={withUnit(body.blood_pressure, 'mmHg')} />
          <InfoRow label="Heart rate" value={withUnit(body.heart_rate, 'bpm')} />
          <InfoRow label="SpO₂" value={withUnit(body.spo2, '%')} />
          <InfoRow label="Temperature" value={withUnit(body.temperature, '°')} />
        </dl>
      </Section>

      <Section icon={FlaskConical} title="Lab results">
        {lab_results.length === 0 ? (
          <p className="text-sm text-muted-foreground">No lab results recorded.</p>
        ) : (
          <ul className="divide-y divide-border">
            {lab_results.map((t) => (
              <li key={t.test} className="flex items-start justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{t.label}</p>
                  <p className="text-xs text-muted-foreground">
                    {t.reference ? `Normal: ${t.reference}` : ''}
                    {t.latest?.date ? `${t.reference ? ' · ' : ''}${t.latest.date}` : ''}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className="font-mono text-sm">{withUnit(t.latest?.value, t.unit)}</span>
                  {t.status && <Badge variant={LAB_STATUS[t.status] ?? 'neutral'}>{t.status}</Badge>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section icon={Phone} title="Contact details">
        <dl className="grid gap-4 sm:grid-cols-2">
          <InfoRow label="Patient's phone" value={contact.phone} mono />
          {contact.email && <InfoRow label="Email" value={contact.email} />}
          <InfoRow label="Address" value={contact.address} />
        </dl>
      </Section>
    </div>
  )
}

function Section({ icon: Icon, title, children }: { icon: typeof Pill; title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="space-y-4 p-6">
        <p className="flex items-center gap-2 font-medium"><Icon className="size-4 text-primary" />{title}</p>
        {children}
      </CardContent>
    </Card>
  )
}
