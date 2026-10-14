import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Sparkles, Stethoscope, Activity, ArrowRight, TriangleAlert, Info, BrainCircuit } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/input'
import { Input } from '@/components/ui/input'
import { Field } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Progress } from '@/components/ui/misc'
import { recommendationService } from '@/lib/api'
import type { Recommendation, SmartCheckResult } from '@/lib/types'
import { cn } from '@/lib/utils'
import { AssignDoctorButton } from './AssignDoctorButton'

const PAIN_HINTS = ['No pain', 'Mild', 'Uncomfortable', 'Distressing', 'Intense', 'Severe']
const DISCLAIMER = 'Suggestion only, not a medical diagnosis.'

/** Shown when the smart check is unavailable and the keyword match is used instead. */
const UNAVAILABLE_MESSAGE = 'The smart check is not available right now. Here is a general match based on what you wrote.'

const pct = (p: number) => `${Math.round(p * 100)}%`

/** Passing ``assignTo`` (admins, with a chosen patient) adds an Assign button to each recommended doctor. */
export function SymptomChecker({ compact = false, patientId, assignTo }: {
  compact?: boolean
  patientId?: number
  assignTo?: { id: number; name: string }
}) {
  const [symptoms, setSymptoms] = useState('')
  const [pain, setPain] = useState(4)
  const [age, setAge] = useState<number | ''>(30)
  const [history, setHistory] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<Recommendation | null>(null)
  const [smart, setSmart] = useState<SmartCheckResult | null>(null)
  const [fallbackNote, setFallbackNote] = useState('')

  const painHint = PAIN_HINTS[Math.min(PAIN_HINTS.length - 1, Math.round((pain / 10) * (PAIN_HINTS.length - 1)))]

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!symptoms.trim()) return toast.error('Please describe your symptoms first.')
    if (!age || age < 1 || age > 120) return toast.error('Enter an age between 1 and 120.')
    setLoading(true); setResult(null); setSmart(null); setFallbackNote('')
    try {
      // 1. Smart check (red flags + Random Forest + TOPSIS). Follow-up questions are only asked
      //    on the full symptom checker page; here an unsure result uses the keyword match.
      //    "Not enough information" results suggest General Medicine; unclear spellings are listed.
      try {
        const smartResult = await recommendationService.smartCheck({ text: symptoms, patient_id: patientId })
        if (smartResult.status !== 'model_unavailable') {
          setSmart(smartResult)            // an emergency is never replaced by a keyword match
          if (smartResult.status === 'ok') toast.success('We found a care suggestion for you.')
          return
        }
      } catch {
        // Smart check failed (e.g. server error): use the keyword match below.
      }
      // 2. Fallback: the existing keyword-based match.
      setFallbackNote(UNAVAILABLE_MESSAGE)
      const data = await recommendationService.create({
        symptoms, pain_level: pain, age: Number(age), medical_history: history, patient_id: patientId,
      })
      setResult(data)
      toast.success('We found a care match for you.')
    } catch (err: any) {
      toast.error(err.response?.data?.symptoms?.[0] || err.response?.data?.detail || "We couldn't recognise those symptoms. Try describing them differently.")
    } finally {
      setLoading(false)
    }
  }

  const severity = result?.clinical_severity ?? 0
  const highSeverity = severity >= 70 || pain >= 8

  return (
    <div className={cn('grid gap-6', !compact && 'lg:grid-cols-[1.1fr_1fr]')}>
      <Card className={cn(compact && 'border-0 shadow-none bg-transparent')}>
        <CardContent className={cn('p-6', compact && 'p-0')}>
          <form onSubmit={submit} className="space-y-5">
            <Field label="What are you feeling?" htmlFor="symptoms" hint="e.g. “fever, cough, no shortness of breath”">
              <Textarea
                id="symptoms"
                value={symptoms}
                onChange={(e) => setSymptoms(e.target.value)}
                rows={compact ? 3 : 4}
                placeholder="Tell us what's going on…"
              />
            </Field>

            <div className="grid grid-cols-2 gap-4">
              <Field label="Age" htmlFor="age">
                <Input id="age" type="number" min={1} max={120} value={age}
                  onChange={(e) => setAge(e.target.value === '' ? '' : Number(e.target.value))} />
              </Field>
              <Field label={`Pain level`} htmlFor="pain">
                <div className="flex h-10 items-center gap-3">
                  <input id="pain" type="range" min={0} max={10} value={pain} onChange={(e) => setPain(+e.target.value)}
                    className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-surface-3 accent-primary" />
                  <span className="w-16 shrink-0 text-right text-xs font-medium text-muted-foreground tabular">{pain}/10</span>
                </div>
                <span className="text-xs text-subtle-foreground">{painHint}</span>
              </Field>
            </div>

            <Field label="Relevant medical history" htmlFor="history" hint="Optional — conditions, allergies, or past treatments.">
              <Textarea id="history" value={history} onChange={(e) => setHistory(e.target.value)} rows={2}
                placeholder="e.g. hypertension, type 2 diabetes…" />
            </Field>

            <Button type="submit" loading={loading} size="lg" className="w-full">
              {loading ? 'Finding the right care…' : <>Find the right doctor <ArrowRight className="size-4" /></>}
            </Button>
            <p className="text-center text-xs text-subtle-foreground">
              Guidance only — not a diagnosis. In an emergency, call your local emergency number.
            </p>
          </form>
        </CardContent>
      </Card>

      <div className="relative">
        <AnimatePresence mode="wait">
          {smart ? (
            <motion.div
              key="smart"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            >
              {smart.status === 'emergency' ? (
                <div role="alert" className="space-y-2 rounded-[var(--radius-md)] border border-danger/40 bg-danger-soft p-5 text-sm text-danger">
                  <p className="flex items-center gap-2 font-display text-lg font-semibold"><TriangleAlert className="size-5 shrink-0" />Seek emergency care now</p>
                  <p className="text-pretty">{smart.message}</p>
                  <ul className="list-disc space-y-0.5 pl-5">
                    {(smart.red_flags ?? []).map((f) => <li key={f.id}>{f.message}</li>)}
                  </ul>
                </div>
              ) : <SmartResultCard result={smart} assignTo={assignTo} />}
            </motion.div>
          ) : result ? (
            <motion.div
              key="result"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            >
              <Card className="overflow-hidden">
                <div className="border-b border-border bg-primary-soft/50 p-6">
                  <div className="flex items-center justify-between">
                    <Badge variant="primary"><Sparkles />Care match</Badge>
                    {result.confidence != null && (
                      <span className="text-xs font-medium text-muted-foreground">{result.confidence}% confidence</span>
                    )}
                  </div>
                  <p className="mt-3 text-xs font-medium uppercase tracking-wide text-subtle-foreground">Recommended department</p>
                  <p className="font-display text-2xl font-semibold">{result.recommended_department}</p>
                  {result.confidence != null && <Progress value={result.confidence} className="mt-3" />}
                </div>
                <CardContent className="space-y-4 p-6">
                  {fallbackNote && (
                    <div role="status" className="flex items-start gap-2.5 rounded-[var(--radius-md)] border border-info/30 bg-info-soft p-3 text-sm text-info">
                      <Info className="mt-0.5 size-4 shrink-0" />
                      <p className="text-pretty">{fallbackNote}</p>
                    </div>
                  )}
                  {highSeverity && (
                    <div className="flex items-start gap-2.5 rounded-[var(--radius-md)] border border-warning/30 bg-warning-soft p-3 text-sm text-warning">
                      <TriangleAlert className="mt-0.5 size-4 shrink-0" />
                      <p className="text-pretty">These symptoms rate high on severity. Please seek care promptly.</p>
                    </div>
                  )}
                  {result.reason && <p className="text-sm text-muted-foreground text-pretty leading-relaxed">{result.reason}</p>}

                  {result.ranked_doctors && result.ranked_doctors.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">Suggested clinicians</p>
                      {result.ranked_doctors.map((doc, i) => (
                        <div key={doc.id ?? i} className={cn(
                          'flex flex-wrap items-center gap-3 rounded-[var(--radius-md)] border p-3',
                          i === 0 ? 'border-primary/30 bg-primary-soft/30' : 'border-border',
                        )}>
                          <span className="grid size-9 shrink-0 place-items-center rounded-full bg-surface-2 text-muted-foreground">
                            <Stethoscope className="size-4" />
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-medium">Dr. {doc.first_name} {doc.last_name}</p>
                            <p className="truncate text-xs text-muted-foreground">{doc.specialization} · {doc.department}</p>
                          </div>
                          {i === 0 && <Badge variant="success">Best match</Badge>}
                          {assignTo && doc.id != null && (
                            <AssignDoctorButton doctorId={doc.id} doctorName={`${doc.first_name} ${doc.last_name}`}
                              patientId={assignTo.id} patientName={assignTo.name} />
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  <p className="text-xs text-subtle-foreground">{DISCLAIMER}</p>
                </CardContent>
              </Card>
            </motion.div>
          ) : (
            <motion.div
              key="placeholder"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex h-full min-h-[20rem] flex-col items-center justify-center gap-3 rounded-[var(--radius-lg)] border border-dashed border-border-strong bg-surface/40 p-8 text-center"
            >
              <span className="grid size-14 place-items-center rounded-full bg-primary-soft text-primary-soft-foreground">
                <Activity className="size-7" />
              </span>
              <p className="font-medium">Your care match appears here</p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}


/** Result of the smart check: likely area, possible illnesses and TOPSIS-ranked doctors. */
function SmartResultCard({ result, assignTo }: { result: SmartCheckResult; assignTo?: { id: number; name: string } }) {
  const deptPct = Math.round((result.dept_probability ?? 0) * 100)
  const sure = result.status === 'ok'
  const confirm = result.status === 'needs_confirmation'
  return (
    <Card className="overflow-hidden">
      <div className="border-b border-border bg-primary-soft/50 p-6">
        <div className="flex items-center justify-between">
          <Badge variant="primary"><BrainCircuit />Smart check</Badge>
          {sure && <span className="text-xs font-medium text-muted-foreground">{deptPct}% likely</span>}
        </div>
        {sure ? (
          <>
            <p className="mt-3 font-display text-2xl font-semibold">Likely area: {result.department} ({deptPct}%)</p>
            <Progress value={deptPct} className="mt-3" />
          </>
        ) : confirm ? (
          <p className="mt-3 font-display text-2xl font-semibold">Please check the spelling</p>
        ) : (
          <>
            <p className="mt-3 font-display text-2xl font-semibold">Not enough information: {result.department}</p>
            {result.message && <p className="mt-2 text-sm text-muted-foreground text-pretty">{result.message}</p>}
          </>
        )}
        <p className="mt-3 flex items-center gap-1.5 text-xs font-medium text-warning">
          <TriangleAlert className="size-3.5 shrink-0" />{result.disclaimer || DISCLAIMER}
        </p>
      </div>
      <CardContent className="space-y-5 p-6">
        {result.symptoms.length > 0 && (
          <p className="text-sm text-muted-foreground text-pretty">
            Symptoms recognised: <span className="font-medium text-foreground">{result.symptoms.join(', ')}</span>
          </p>
        )}
        {!!result.unrecognized?.length && (
          <p className="text-sm text-warning text-pretty">
            We didn't recognise: {result.unrecognized.map((u) => `“${u}”`).join(', ')}.
          </p>
        )}
        {confirm && (
          <ul className="space-y-1 text-sm">
            {(result.suggestions ?? []).map((sg) => (
              <li key={sg.term}>
                Did you mean <span className="font-medium">{sg.label}</span> for “{sg.term}”? Correct the word and check again.
              </li>
            ))}
          </ul>
        )}
        {result.safety_net && (
          <p className="flex items-start gap-1.5 text-sm text-warning text-pretty">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />{result.safety_net}
          </p>
        )}

        {!!result.illnesses?.length && (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">Possible illnesses</p>
            <ul className="space-y-1.5">
              {result.illnesses.map((ill) => (
                <li key={ill.name} className="flex items-center justify-between gap-3 text-sm">
                  <span className="truncate">{ill.name}</span>
                  <span className="shrink-0 font-medium tabular-nums">{pct(ill.probability)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {!confirm && <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">Suggested clinicians</p>
          {result.doctors_note && <p className="text-xs text-muted-foreground text-pretty">{result.doctors_note}</p>}
          {result.doctors?.map((doc, i) => (
            <div key={doc.id} className={cn(
              'flex flex-wrap items-center gap-3 rounded-[var(--radius-md)] border p-3',
              i === 0 ? 'border-primary/30 bg-primary-soft/30' : 'border-border',
            )}>
              <span className="grid size-9 shrink-0 place-items-center rounded-full bg-surface-2 text-muted-foreground">
                <Stethoscope className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">Dr. {doc.name}</p>
                <p className="truncate text-xs text-muted-foreground">{doc.specialization} · {doc.department}</p>
                <p className="truncate text-xs text-subtle-foreground">{doc.reason}</p>
              </div>
              {i === 0 && <Badge variant="success">Best match</Badge>}
              {assignTo && (
                <AssignDoctorButton doctorId={doc.id} doctorName={doc.name} patientId={assignTo.id} patientName={assignTo.name} />
              )}
            </div>
          ))}
        </div>}
      </CardContent>
    </Card>
  )
}
