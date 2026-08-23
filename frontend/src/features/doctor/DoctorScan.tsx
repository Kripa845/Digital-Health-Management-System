import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Html5Qrcode } from 'html5-qrcode'
import {
  ScanLine, Camera, CameraOff, KeyRound, ShieldCheck, Lock, ArrowRight, Loader2, AlertCircle,
} from 'lucide-react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Field } from '@/components/ui/label'
import { PageHeader, InfoRow, SectionTitle } from '@/components/patterns'
import { patientService, accessRequestService } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import type { Patient } from '@/lib/types'

const UUID_RE = /([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/
const READER_ID = 'doctor-qr-reader'

interface GeneralPatient {
  id: number
  uuid: string
  patient_id: string
  first_name: string
  middle_name?: string | null
  last_name: string
  age?: number
  gender: string
  blood_group: string
  phone: string
  emergency_contact: string
  status: string
}

type ScanResult =
  | { access: 'FULL'; patient: Patient }
  | { access: 'PENDING'; patient: GeneralPatient; message: string }
  | { access: 'DECLINED'; patient: GeneralPatient; message: string }
  | { access: 'GENERAL'; patient: GeneralPatient; message?: string }

function extractUuid(text: string): string | null {
  const m = text.match(UUID_RE)
  return m ? m[1] : null
}

export function DoctorScan() {
  const [manual, setManual] = useState('')
  const [reason, setReason] = useState('')
  const [result, setResult] = useState<ScanResult | null>(null)
  const [scanning, setScanning] = useState(false)
  const [cameraError, setCameraError] = useState<string | null>(null)

  const scannerRef = useRef<Html5Qrcode | null>(null)
  const firedRef = useRef(false)

  const scan = useMutation({
    mutationFn: (uuid: string) => patientService.scan(uuid) as Promise<ScanResult>,
    onSuccess: (data) => {
      setResult(data)
      if (data.access === 'FULL') toast.success('Access granted — you are assigned to this patient.')
      else if (data.access === 'PENDING') toast.info('Access request sent to the admin team.')
      else if (data.access === 'DECLINED') toast.error('Your access request was declined.')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Could not resolve the scanned card.'),
  })

  const requestAccess = useMutation({
    mutationFn: ({ patientId, reason }: { patientId: number; reason: string }) =>
      accessRequestService.create(patientId, reason || undefined),
    onSuccess: () => {
      toast.success('Access request sent to the admin team.')
      setResult((prev) => {
        if (!prev) return prev
        if (prev.access === 'GENERAL' || prev.access === 'DECLINED') {
          return { ...prev, access: 'PENDING', message: 'Your access request is awaiting admin approval.' }
        }
        return prev
      })
      setReason('')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Could not send the access request.'),
  })

  async function stopCamera() {
    const s = scannerRef.current
    scannerRef.current = null
    if (s) {
      try { await s.stop() } catch { /* already stopped */ }
      try { s.clear() } catch { /* noop */ }
    }
    setScanning(false)
  }

  async function startCamera() {
    setCameraError(null)
    setResult(null)
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setCameraError('Camera is not available in this browser. Please enter the card ID manually below.')
      return
    }
    firedRef.current = false
    setScanning(true)
    try {
      const scanner = new Html5Qrcode(READER_ID)
      scannerRef.current = scanner
      await scanner.start(
        { facingMode: 'environment' },
        { fps: 10, qrbox: 230 },
        (decoded) => {
          if (firedRef.current) return
          firedRef.current = true
          const uuid = extractUuid(decoded) ?? decoded.trim()
          void stopCamera().then(() => scan.mutate(uuid))
        },
        () => { /* per-frame decode failures are expected */ },
      )
    } catch (err: any) {
      scannerRef.current = null
      setScanning(false)
      setCameraError(
        typeof err === 'string'
          ? err
          : 'Unable to access the camera. Grant camera permission (HTTPS or localhost) or enter the card ID manually.',
      )
    }
  }

  function submitManual(e: React.FormEvent) {
    e.preventDefault()
    const uuid = extractUuid(manual) ?? manual.trim()
    if (!uuid) return toast.error('Enter a patient card UUID or public-profile link.')
    setResult(null)
    scan.mutate(uuid)
  }

  useEffect(() => {
    return () => { void stopCamera() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="space-y-8">
      <PageHeader
        title="Scan a patient card"
        description="Scan a Mero Care QR card or enter its ID. Assigned patients open in full; otherwise you'll see a general profile and can request access."
        icon={ScanLine}
      />

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Scanner + manual entry */}
        <Card>
          <CardContent className="space-y-5 p-5 sm:p-6">
            <SectionTitle>Camera scan</SectionTitle>
            <div className="overflow-hidden rounded-[var(--radius-lg)] border border-dashed border-border-strong bg-surface-2/40">
              <div id={READER_ID} className="mx-auto w-full max-w-xs [&_video]:rounded-[var(--radius-md)]" />
              {!scanning && (
                <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
                  <span className="grid size-12 place-items-center rounded-full bg-primary-soft text-primary-soft-foreground">
                    <Camera className="size-6" />
                  </span>
                  <p className="text-sm text-muted-foreground">Camera is off. Start it to scan a QR card.</p>
                </div>
              )}
            </div>

            {cameraError && (
              <div className="flex items-start gap-2.5 rounded-[var(--radius-md)] border border-warning/30 bg-warning-soft p-3 text-sm text-warning">
                <CameraOff className="mt-0.5 size-4 shrink-0" />
                <p className="text-pretty">{cameraError}</p>
              </div>
            )}

            <div className="flex gap-2">
              {scanning ? (
                <Button variant="secondary" className="w-full" onClick={() => void stopCamera()}>
                  <CameraOff className="size-4" /> Stop camera
                </Button>
              ) : (
                <Button className="w-full" onClick={() => void startCamera()}>
                  <Camera className="size-4" /> Start camera
                </Button>
              )}
            </div>

            <div className="relative py-1 text-center">
              <span className="relative z-10 bg-surface px-3 text-xs uppercase tracking-wide text-subtle-foreground">or enter manually</span>
              <span className="absolute inset-x-0 top-1/2 h-px bg-border" />
            </div>

            <form onSubmit={submitManual} className="space-y-3">
              <Field label="Card ID or public-profile link" htmlFor="manual-uuid"
                hint="Paste the patient's UUID or a /public-profile/{uuid} URL.">
                <Input id="manual-uuid" value={manual} onChange={(e) => setManual(e.target.value)}
                  placeholder="e.g. 3f9a…-…-…-…-…" autoComplete="off" />
              </Field>
              <Button type="submit" variant="soft" className="w-full" loading={scan.isPending}>
                <KeyRound className="size-4" /> Look up patient
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Result */}
        <Card>
          <CardContent className="space-y-4 p-5 sm:p-6">
            <SectionTitle>Result</SectionTitle>
            {scan.isPending ? (
              <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted-foreground">
                <Loader2 className="size-6 animate-spin" />
                <p className="text-sm">Resolving card…</p>
              </div>
            ) : !result ? (
              <div className="flex flex-col items-center justify-center gap-3 rounded-[var(--radius-lg)] border border-dashed border-border-strong bg-surface/50 px-6 py-16 text-center">
                <span className="grid size-14 place-items-center rounded-full bg-surface-2 text-muted-foreground">
                  <ScanLine className="size-7" />
                </span>
                <p className="font-medium">Scan results appear here</p>
                <p className="max-w-xs text-sm text-muted-foreground text-pretty">
                  Scan or look up a card to see the patient's profile.
                </p>
              </div>
            ) : result.access === 'FULL' ? (
              <FullResult patient={result.patient} />
            ) : (
              <GeneralResult
                result={result}
                reason={reason}
                setReason={setReason}
                onRequest={() => requestAccess.mutate({ patientId: result.patient.id, reason })}
                requesting={requestAccess.isPending}
              />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function FullResult({ patient: p }: { patient: Patient }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2.5 rounded-[var(--radius-md)] border border-success/30 bg-success-soft p-3 text-sm text-success">
        <ShieldCheck className="size-4 shrink-0" />
        <p>Full access — you are assigned to this patient.</p>
      </div>
      <div>
        <p className="text-lg font-semibold">{p.first_name} {p.middle_name ? `${p.middle_name} ` : ''}{p.last_name}</p>
        <p className="text-xs text-muted-foreground font-mono">{p.patient_id}</p>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-4">
        <InfoRow label="Age" value={p.age != null ? `${p.age} yrs` : '—'} />
        <InfoRow label="Gender" value={p.gender} />
        <InfoRow label="Blood group" value={p.blood_group} />
        <InfoRow label="Date of birth" value={formatDate(p.dob)} />
        <InfoRow label="Phone" value={p.phone} mono />
        <InfoRow label="Emergency" value={p.emergency_contact} mono />
        <InfoRow label="Allergies" value={p.allergies || 'None recorded'} />
        <InfoRow label="Current medication" value={p.current_medication || 'None recorded'} />
      </dl>
      <Button asChild variant="secondary" className="w-full">
        <Link to="/doctor/patients">Open full record <ArrowRight className="size-4" /></Link>
      </Button>
    </div>
  )
}

function GeneralResult({
  result, reason, setReason, onRequest, requesting,
}: {
  result: Extract<ScanResult, { access: 'GENERAL' | 'PENDING' | 'DECLINED' }>
  reason: string
  setReason: (v: string) => void
  onRequest: () => void
  requesting: boolean
}) {
  const p = result.patient
  const isPending = result.access === 'PENDING'
  const isDeclined = result.access === 'DECLINED'

  return (
    <div className="space-y-4">
      <div className={`flex items-center gap-2.5 rounded-[var(--radius-md)] border p-3 text-sm ${
        isPending ? 'border-info/30 bg-info-soft text-info' :
        isDeclined ? 'border-danger/30 bg-danger-soft text-danger' :
        'border-warning/30 bg-warning-soft text-warning'
      }`}>
        {isPending ? <ShieldCheck className="size-4 shrink-0" /> :
         isDeclined ? <AlertCircle className="size-4 shrink-0" /> :
         <Lock className="size-4 shrink-0" />}
        <p className="text-pretty">{result.message || 'General profile only — medical records are hidden.'}</p>
      </div>
      <div className="text-center">
        <p className="text-lg font-semibold">{p.first_name} {p.middle_name ? `${p.middle_name} ` : ''}{p.last_name}</p>
        <p className="text-xs text-muted-foreground font-mono">{p.patient_id}</p>
      </div>
      <dl className="grid grid-cols-3 gap-x-4 gap-y-4">
        <InfoRow label="Age" value={p.age != null ? `${p.age} yrs` : '—'} />
        <InfoRow label="Gender" value={p.gender} />
        <InfoRow label="Blood" value={p.blood_group} />
      </dl>
      <InfoRow label="Emergency contact" value={p.emergency_contact} mono />

      {isPending && (
        <div className="rounded-[var(--radius-md)] border border-border bg-surface-2/50 p-3 text-center text-sm text-muted-foreground">
          Your access request is awaiting admin approval.
        </div>
      )}

      {!isPending && (
        <div className="space-y-3">
          <Field label="Reason for access" htmlFor="access-reason" hint="Optional — helps the admin review your request.">
            <Textarea id="access-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Patient presented at emergency and needs record review." />
          </Field>
          <Button className="w-full" onClick={onRequest} loading={requesting}>
            <ShieldCheck className="size-4" /> Request access
          </Button>
        </div>
      )}
    </div>
  )
}
