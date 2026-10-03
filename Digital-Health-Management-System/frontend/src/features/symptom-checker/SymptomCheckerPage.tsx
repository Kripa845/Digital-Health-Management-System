/**
 * SymptomCheckerPage
 * ------------------
 * The smart symptom check on its own page, shown as its three steps:
 *   1. negation detection  → the symptoms recognised (negated ones are left out)
 *   2. Naive Bayes         → likely illnesses and the likely area (department)
 *   3. TOPSIS              → doctors of that department ranked by free hours and caseload
 * When the model has too little information or is not confident, the page says
 * so and shows the keyword checker's match instead. Every result is a suggestion,
 * never a diagnosis.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BrainCircuit, ListChecks, Activity, Stethoscope, TriangleAlert, Info, ArrowRight, Sparkles,
  UserRound, UserPlus, CheckCircle2,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/input'
import { SimpleSelect } from '@/components/ui/select'
import { Field } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Progress } from '@/components/ui/misc'
import { PageHeader } from '@/components/patterns'
import { assignmentService, patientService, recommendationService } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { Patient, Recommendation, SmartCheckResult, SmartCheckStatus } from '@/lib/types'
import { cn } from '@/lib/utils'
import { apiError } from '@/features/admin/admin-utils'

const DISCLAIMER = 'Suggestion only, not a medical diagnosis.'
const MAX_LENGTH = 2000

const EXAMPLES = [
  'itching, skin rash and nodal skin eruptions',
  'no fever, but chest pain, breathlessness and sweating',
  'high fever, chills, sweating, headache and vomiting',
]

const NOT_OK_MESSAGES: Record<Exclude<SmartCheckStatus, 'ok'>, string> = {
  not_enough_info: 'Not enough information. Please add more symptoms (at least two) so the model can suggest a likely area.',
  low_confidence: 'These symptoms could point to several areas, so the model is not confident. Adding more symptoms will help.',
  model_unavailable: 'The smart check is not available right now.',
}

const pct = (p: number) => `${Math.round(p * 100)}%`
const NO_PATIENT = 'none'

type Outcome = { smart: SmartCheckResult | null; fallback: Recommendation | null; failed: boolean }

export function SymptomCheckerPage() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const isAdmin = user?.role === 'ADMIN'
  const [text, setText] = useState('')
  // Admins choose an existing patient (or none, for a guest check); patients check for themselves.
  const [chosen, setChosen] = useState<Patient | null>(null)
  const patientId = isAdmin ? chosen?.id : user?.patient_profile?.id
  const patientAge = isAdmin ? chosen?.age : user?.patient_profile?.age

  const check = useMutation({
    mutationFn: async (input: string): Promise<Outcome> => {
      let smart: SmartCheckResult | null = null
      let failed = false
      try {
        smart = await recommendationService.smartCheck({ text: input, patient_id: patientId })
      } catch {
        failed = true
      }
      if (smart?.status === 'ok') return { smart, fallback: null, failed }
      // Not confident (or the smart check failed): the keyword checker's match.
      let fallback: Recommendation | null = null
      try {
        fallback = await recommendationService.create({
          symptoms: input, pain_level: 5, patient_id: patientId, age: patientAge ?? undefined,
        })
      } catch {
        fallback = null
      }
      return { smart, fallback, failed }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['patient', 'recommendations'] })
      qc.invalidateQueries({ queryKey: ['admin', 'recommendations'] })
    },
  })

  function choosePatient(p: Patient | null) {
    setChosen(p)
    check.reset()          // a result belongs to the patient it was checked for
  }

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!text.trim()) return toast.error('Please describe your symptoms first.')
    check.mutate(text)
  }

  const outcome = check.data
  const smart = outcome?.smart

  return (
    <div className="space-y-6">
      <PageHeader
        title="Symptom checker"
        description="Describe your symptoms in your own words. The checker finds the symptoms you have (ignoring the ones you say you don't), estimates likely illnesses with a Naive Bayes model, and ranks doctors in the likely area with TOPSIS."
        icon={BrainCircuit}
      />

      <div className="flex items-start gap-2.5 rounded-[var(--radius-md)] border border-warning/30 bg-warning-soft p-3 text-sm text-warning">
        <TriangleAlert className="mt-0.5 size-4 shrink-0" />
        <p className="text-pretty"><span className="font-semibold">{DISCLAIMER}</span> In an emergency, call your local emergency number.</p>
      </div>

      {isAdmin
        ? <PatientSection chosen={chosen} onChoose={choosePatient} />
        : user?.patient_profile && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <UserRound className="size-4" />Checking symptoms for <span className="font-medium text-foreground">
              you ({user.patient_profile.first_name} {user.patient_profile.last_name}, {user.patient_profile.patient_id})</span>
          </p>
        )}

      <Card>
        <CardContent className="p-6">
          <form onSubmit={submit} className="space-y-4">
            <Field label={isAdmin && chosen ? `Symptoms of ${chosen.first_name} ${chosen.last_name}` : 'What are you feeling?'}
              htmlFor="smart-symptoms"
              hint='List the symptoms. You can also say what is absent, e.g. "no fever, but cough and headache".'>
              <Textarea id="smart-symptoms" rows={4} maxLength={MAX_LENGTH} value={text}
                onChange={(e) => setText(e.target.value)} placeholder="e.g. itching, skin rash and nodal skin eruptions" />
            </Field>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-subtle-foreground">Try an example:</span>
              {EXAMPLES.map((ex) => (
                <button key={ex} type="button" onClick={() => setText(ex)}
                  className="rounded-full border border-border bg-surface-2 px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60">
                  {ex}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="text-xs text-subtle-foreground tabular-nums">{text.length} / {MAX_LENGTH}</span>
              <Button type="submit" loading={check.isPending}>
                {check.isPending ? 'Checking…' : <>Check symptoms <ArrowRight className="size-4" /></>}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <AnimatePresence mode="wait">
        {outcome ? (
          <motion.div key={check.submittedAt} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }} transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }} className="space-y-4">
            {smart?.status === 'ok'
              ? <SmartSteps result={smart} assignTo={isAdmin ? smart.patient ?? null : null} />
              : <NotConfident outcome={outcome} />}
          </motion.div>
        ) : (
          <motion.div key="how" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <HowItWorks />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/* ── Results ───────────────────────────────────────────────────────────── */

function Step({ n, title, method, icon: Icon, children }: {
  n: number; title: string; method: string; icon: typeof Activity; children: React.ReactNode
}) {
  return (
    <Card aria-label={`Step ${n}: ${title}`} role="region">
      <CardContent className="space-y-4 p-6">
        <div className="flex items-start gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-full bg-primary-soft text-primary-soft-foreground">
            <Icon className="size-4" />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">Step {n} · {method}</p>
            <h2 className="font-display text-lg font-semibold">{title}</h2>
          </div>
        </div>
        {children}
      </CardContent>
    </Card>
  )
}

function SymptomChips({ symptoms }: { symptoms: string[] }) {
  if (!symptoms.length) return <p className="text-sm text-muted-foreground">No known symptoms were recognised.</p>
  return (
    <div className="flex flex-wrap gap-2">
      {symptoms.map((s) => <Badge key={s} variant="primary">{s}</Badge>)}
    </div>
  )
}

type CheckedPatient = NonNullable<SmartCheckResult['patient']>

function SmartSteps({ result, assignTo }: { result: SmartCheckResult; assignTo: CheckedPatient | null }) {
  const deptPct = Math.round((result.dept_probability ?? 0) * 100)
  const doctors = result.doctors ?? []
  return (
    <>
      <Step n={1} title="Symptoms recognised" method="Negation detection" icon={ListChecks}>
        <SymptomChips symptoms={result.symptoms} />
        <p className="text-xs text-subtle-foreground">Symptoms you said you don't have ("no", "not", "without"…) are left out.</p>
      </Step>

      <Step n={2} title={`Likely area: ${result.department} (${deptPct}%)`} method="Naive Bayes" icon={Activity}>
        <Progress value={deptPct} />
        <div className="space-y-2.5">
          <p className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">Possible illnesses</p>
          <ul className="space-y-2.5">
            {(result.illnesses ?? []).map((ill) => (
              <li key={ill.name} className="space-y-1">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="truncate">{ill.name}</span>
                  <span className="shrink-0 font-medium tabular-nums">{pct(ill.probability)}</span>
                </div>
                <Progress value={Math.round(ill.probability * 100)} className="h-1.5" />
              </li>
            ))}
          </ul>
          <p className="text-xs text-subtle-foreground">
            The likely area adds up the probabilities of all illnesses seen by the same department.
          </p>
        </div>
      </Step>

      <Step n={3} title="Suggested doctors" method="TOPSIS ranking" icon={Stethoscope}>
        {result.doctors_note && (
          <div role="status" className="flex items-start gap-2.5 rounded-[var(--radius-md)] border border-info/30 bg-info-soft p-3 text-sm text-info">
            <Info className="mt-0.5 size-4 shrink-0" /><p className="text-pretty">{result.doctors_note}</p>
          </div>
        )}
        {doctors.length > 0 && (
          <div className="overflow-x-auto rounded-[var(--radius-md)] border border-border">
            <table className="w-full text-sm">
              <thead className="bg-surface-2 text-left text-xs uppercase tracking-wide text-subtle-foreground">
                <tr>
                  <th className="px-3 py-2 font-semibold">Doctor</th>
                  <th className="px-3 py-2 text-right font-semibold">Free hours this week</th>
                  <th className="px-3 py-2 text-right font-semibold">Current patients</th>
                  <th className="px-3 py-2 text-right font-semibold">TOPSIS score</th>
                  {assignTo && <th className="px-3 py-2 text-right font-semibold"><span className="sr-only">Assign</span></th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {doctors.map((doc, i) => (
                  <tr key={doc.id} className={cn(i === 0 && 'bg-primary-soft/30')}>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">Dr. {doc.name}</span>
                        {i === 0 && <Badge variant="success">Best match</Badge>}
                      </div>
                      <p className="text-xs text-muted-foreground">{doc.specialization} · {doc.department}</p>
                      <p className="text-xs text-subtle-foreground">{doc.reason}</p>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{doc.free_hours}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{doc.caseload}</td>
                    <td className="px-3 py-2.5 text-right font-medium tabular-nums">{doc.score.toFixed(2)}</td>
                    {assignTo && (
                      <td className="px-3 py-2.5 text-right">
                        <AssignButton doctorId={doc.id} doctorName={doc.name} patient={assignTo} />
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-subtle-foreground">
          TOPSIS scores each doctor from 0 to 1 by closeness to the ideal: the most free hours this week and the fewest current patients.
        </p>
      </Step>

      {result.patient && (
        <p className="text-center text-xs text-muted-foreground">
          Saved to the symptom history of {result.patient.name} ({result.patient.patient_id}).
          {assignTo && ' Assigning a doctor also gives them access to this patient\'s record.'}
        </p>
      )}
      <p className="text-center text-xs font-medium text-warning">{result.disclaimer || DISCLAIMER}</p>
    </>
  )
}

/* ── Assigning a recommended doctor (admins) ──────────────────────────── */

function usePatientAssignments(patientId: number) {
  return useQuery({
    queryKey: ['admin', 'assignments', { patient: patientId }],
    queryFn: () => assignmentService.list({ patient: patientId }),
  })
}

function AssignButton({ doctorId, doctorName, patient }: { doctorId: number; doctorName: string; patient: CheckedPatient }) {
  const qc = useQueryClient()
  const assignments = usePatientAssignments(patient.id)
  const existing = (assignments.data ?? []).find((a) => a.doctor === doctorId)
  const assign = useMutation({
    mutationFn: () => assignmentService.create(doctorId, patient.id),
    onSuccess: () => {
      toast.success(`${patient.name} is now assigned to Dr. ${doctorName}.`)
      qc.invalidateQueries({ queryKey: ['admin', 'assignments'] })
      qc.invalidateQueries({ queryKey: ['admin', 'access-requests'] })
    },
    onError: (err) => toast.error(apiError(err, 'Could not assign the patient.')),
  })

  if (assignments.isLoading) return <span className="text-xs text-muted-foreground">…</span>
  if (existing) {
    return existing.status === 'Active'
      ? <Badge variant="success"><CheckCircle2 />Assigned</Badge>
      : <Badge variant="neutral" title="This assignment is inactive. Reactivate it from the doctor's page.">Inactive assignment</Badge>
  }
  return (
    <Button type="button" size="sm" variant="secondary" loading={assign.isPending}
      onClick={() => assign.mutate()} aria-label={`Assign ${patient.name} to Dr. ${doctorName}`}>
      {!assign.isPending && <UserPlus className="size-4" />}Assign
    </Button>
  )
}

/* ── Patient section (admins) ──────────────────────────────────────────── */

function PatientSection({ chosen, onChoose }: { chosen: Patient | null; onChoose: (p: Patient | null) => void }) {
  const patientsQ = useQuery({
    queryKey: ['admin', 'patients', 'symptom-checker'],
    queryFn: () => patientService.list(),
  })
  const patients = [...(patientsQ.data ?? [])].sort((a, b) =>
    `${a.first_name} ${a.last_name}`.localeCompare(`${b.first_name} ${b.last_name}`))
  const options = [
    { value: NO_PATIENT, label: 'No patient (check not linked to a patient)' },
    ...patients.map((p) => ({ value: String(p.id), label: `${p.first_name} ${p.last_name} · ${p.patient_id}` })),
  ]

  function select(value: string) {
    onChoose(value === NO_PATIENT ? null : patients.find((p) => String(p.id) === value) ?? null)
  }

  return (
    <Card>
      <CardContent className="space-y-4 p-6">
        <div className="flex items-start gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-full bg-primary-soft text-primary-soft-foreground">
            <UserRound className="size-4" />
          </span>
          <div className="min-w-0">
            <h2 className="font-display text-lg font-semibold">Patient</h2>
            <p className="text-sm text-muted-foreground">
              Choose the patient whose symptoms you are checking. The result is saved to their symptom history.
            </p>
          </div>
        </div>

        <Field label="Patient" htmlFor="patient-select">
          {patientsQ.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading patients…</p>
          ) : patientsQ.isError ? (
            <p className="text-sm text-danger">Could not load the patient list. Refresh the page to try again.</p>
          ) : (
            <SimpleSelect id="patient-select" value={chosen ? String(chosen.id) : NO_PATIENT}
              onValueChange={select} options={options} placeholder="Choose a patient" />
          )}
        </Field>
        {!patientsQ.isLoading && patients.length === 0 && !patientsQ.isError && (
          <p className="text-sm text-muted-foreground">No patients are registered yet.</p>
        )}

        {chosen && (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-[var(--radius-md)] border border-primary/30 bg-primary-soft/30 p-4 text-sm sm:grid-cols-3">
            <div className="col-span-2 sm:col-span-3">
              <dt className="sr-only">Name</dt>
              <dd className="font-medium">{chosen.first_name} {chosen.middle_name ? `${chosen.middle_name} ` : ''}{chosen.last_name}
                <span className="ml-2 font-mono text-xs text-muted-foreground">{chosen.patient_id}</span></dd>
            </div>
            <PatientFact label="Age" value={chosen.age != null ? `${chosen.age} yrs` : '—'} />
            <PatientFact label="Gender" value={chosen.gender} />
            <PatientFact label="Blood group" value={chosen.blood_group} />
            <PatientFact label="Allergies" value={chosen.allergies || 'None recorded'} wide />
            <PatientFact label="Current medication" value={chosen.current_medication || 'None recorded'} wide />
          </dl>
        )}
      </CardContent>
    </Card>
  )
}

function PatientFact({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={cn('min-w-0', wide && 'col-span-2 sm:col-span-3')}>
      <dt className="text-xs uppercase tracking-wide text-subtle-foreground">{label}</dt>
      <dd className="truncate">{value}</dd>
    </div>
  )
}

function NotConfident({ outcome }: { outcome: Outcome }) {
  const status: Exclude<SmartCheckStatus, 'ok'> =
    outcome.failed || !outcome.smart ? 'model_unavailable' : (outcome.smart.status as Exclude<SmartCheckStatus, 'ok'>)
  const fb = outcome.fallback
  return (
    <>
      {outcome.smart && (
        <Step n={1} title="Symptoms recognised" method="Negation detection" icon={ListChecks}>
          <SymptomChips symptoms={outcome.smart.symptoms} />
        </Step>
      )}
      <div role="status" className="flex items-start gap-2.5 rounded-[var(--radius-md)] border border-info/30 bg-info-soft p-4 text-sm text-info">
        <Info className="mt-0.5 size-4 shrink-0" />
        <p className="text-pretty">{NOT_OK_MESSAGES[status]}{fb ? ' Below is a general match from the keyword checker.' : ''}</p>
      </div>
      {fb && (
        <Card>
          <CardContent className="space-y-3 p-6">
            <div className="flex items-center justify-between gap-3">
              <Badge variant="neutral"><Sparkles />Keyword match</Badge>
              {fb.confidence != null && <span className="text-xs text-muted-foreground">{fb.confidence}% confidence</span>}
            </div>
            <p className="font-display text-xl font-semibold">{fb.recommended_department}</p>
            {fb.reason && <p className="text-sm text-muted-foreground text-pretty">{fb.reason}</p>}
            {!!fb.ranked_doctors?.length && (
              <ul className="space-y-1.5 text-sm">
                {fb.ranked_doctors.map((doc, i) => (
                  <li key={doc.id ?? i}>Dr. {doc.first_name} {doc.last_name} <span className="text-muted-foreground">· {doc.specialization}</span></li>
                ))}
              </ul>
            )}
            <p className="text-xs text-subtle-foreground">{DISCLAIMER}</p>
          </CardContent>
        </Card>
      )}
    </>
  )
}

function HowItWorks() {
  const steps = [
    { icon: ListChecks, title: 'Negation detection', body: 'Finds the symptoms you mention and leaves out the ones you say you don\'t have, such as "no fever".' },
    { icon: Activity, title: 'Naive Bayes', body: 'Estimates the most likely illnesses from your symptoms and adds them up into a likely area of care.' },
    { icon: Stethoscope, title: 'TOPSIS', body: 'Ranks the doctors in that area by free hours this week and current number of patients.' },
  ]
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {steps.map((s, i) => (
        <div key={s.title} className="rounded-[var(--radius-lg)] border border-dashed border-border-strong bg-surface/40 p-5">
          <span className="grid size-9 place-items-center rounded-full bg-primary-soft text-primary-soft-foreground"><s.icon className="size-4" /></span>
          <p className="mt-3 text-xs font-semibold uppercase tracking-wide text-subtle-foreground">Step {i + 1}</p>
          <p className="font-medium">{s.title}</p>
          <p className="mt-1 text-sm text-muted-foreground text-pretty">{s.body}</p>
        </div>
      ))}
    </div>
  )
}
