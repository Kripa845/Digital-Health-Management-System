/**
 * SymptomCheckerPage
 * ------------------
 * The smart symptom check on its own page, shown as its three steps:
 *   1. negation detection  → the symptoms recognised (negated ones are left out), with
 *                            synonyms / typos mapped to known symptoms and unknown words listed
 *   2. Random Forest       → likely illnesses and the likely area (department)
 *   3. TOPSIS              → doctors of that department ranked by free hours, caseload and experience
 * Red-flag symptoms stop the check with an emergency message (no model, no fallback).
 * Words only close to a symptom ("feverr") are asked first: "Did you mean fever?"; nothing
 * unconfirmed reaches the model. When the model has too little information or is not
 * confident, it may ask one yes/no follow-up question at a time; otherwise (or when
 * skipped) the page says "not enough information" and suggests General Medicine doctors.
 * The keyword checker is only used when the smart check is unavailable. Symptoms and illnesses come from DDXPlus, a
 * synthetic dataset. Every result is a suggestion, never a diagnosis.
 */

import { createContext, useContext, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BrainCircuit, ListChecks, Activity, Stethoscope, TriangleAlert, Info, ArrowRight, Sparkles,
  UserRound, HelpCircle,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/input'
import { SimpleSelect } from '@/components/ui/select'
import { Field } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Progress } from '@/components/ui/misc'
import { PageHeader } from '@/components/patterns'
import { patientService, recommendationService } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type {
  Patient, Recommendation, SmartCheckDoctor, SmartCheckQuestion, SmartCheckResult, SmartCheckStatus, SmartCheckSuggestion,
} from '@/lib/types'
import { cn } from '@/lib/utils'
import { AssignDoctorAction } from '@/features/shared/AssignDoctorButton'

const DISCLAIMER = 'Suggestion only, not a medical diagnosis.'
const MAX_LENGTH = 2000
const COUNTER_WARN_AT = 100     // show the character counter only this close to the limit
const MAX_ILLNESSES = 3
const MIN_ILLNESS_PROBABILITY = 0.05

const EXAMPLES = [
  'fever, cough and sore throat',
  'no fever, but heartburn, worse after eating and worse lying down',
  'chest pain, fever, coloured sputum and cough',
]

type NotOkStatus = Exclude<SmartCheckStatus, 'ok' | 'emergency'>

const NOT_OK_MESSAGES: Record<NotOkStatus, string> = {
  needs_confirmation: 'Some words were not clear. Please confirm what you meant.',
  not_enough_info: 'Not enough information. Please add more symptoms (at least two) so the model can suggest a likely area.',
  low_confidence: 'These symptoms could point to several areas, so the model is not confident. Adding more symptoms will help.',
  model_unavailable: 'The smart check is not available right now.',
}

const pct = (p: number) => `${Math.round(p * 100)}%`
const NO_PATIENT = 'none'

type Outcome = { smart: SmartCheckResult | null; fallback: Recommendation | null; failed: boolean; skipped?: boolean }
type CheckInput = { text: string; answers: Record<string, boolean>; dismissed: string[]; skipQuestions?: boolean }

export function SymptomCheckerPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Symptom checker"
        description="Describe your symptoms to see likely conditions and suggested doctors."
        icon={BrainCircuit}
      />
      <SymptomCheckerPanel />
    </div>
  )
}

/** The checker itself. ``guest`` (the public landing page) ignores any signed-in user: nothing is saved to a patient. */
export function SymptomCheckerPanel({ guest = false }: { guest?: boolean }) {
  const { user: authUser } = useAuth()
  const user = guest ? null : authUser
  const qc = useQueryClient()
  const isAdmin = user?.role === 'ADMIN'
  const [text, setText] = useState('')
  // Replies to the follow-up questions of the current check ({ symptom: yes? }).
  const [answers, setAnswers] = useState<Record<string, boolean>>({})
  // "Did you mean ...?" suggestions the user said were not meant (their terms).
  const [dismissed, setDismissed] = useState<string[]>([])
  // Admins choose an existing patient (or none, for a guest check); patients check for themselves.
  const [chosen, setChosen] = useState<Patient | null>(null)
  const patientId = isAdmin ? chosen?.id : user?.patient_profile?.id
  const patientAge = isAdmin ? chosen?.age : user?.patient_profile?.age
  // The patient a recommended doctor is assigned to (admins); with none chosen, Assign asks for one.
  const assignPatient = chosen ? { id: chosen.id, name: `${chosen.first_name} ${chosen.last_name}` } : null

  const check = useMutation({
    mutationFn: async ({ text: input, answers: given, dismissed: notMeant, skipQuestions }: CheckInput): Promise<Outcome> => {
      let smart: SmartCheckResult | null = null
      let failed = false
      try {
        smart = await recommendationService.smartCheck({ text: input, patient_id: patientId, answers: given, dismissed: notMeant })
      } catch {
        failed = true
      }
      // A result, an emergency (never replaced by a keyword match), words to confirm, a follow-up
      // question to ask first, or "not enough information" with General Medicine doctors.
      if (smart && smart.status !== 'model_unavailable') return { smart, fallback: null, failed, skipped: skipQuestions }
      // The smart check failed or is unavailable: the keyword checker's match.
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
    setAnswers({})
    setDismissed([])
    check.mutate({ text, answers: {}, dismissed: [] })
  }

  function answer(symptom: string, yes: boolean) {
    const next = { ...answers, [symptom]: yes }
    setAnswers(next)
    check.mutate({ text, answers: next, dismissed })
  }

  /** "Did you mean ...?": yes confirms the symptom, no drops the word. */
  function confirm(s: SmartCheckSuggestion, yes: boolean) {
    if (yes) return answer(s.symptom, true)
    const next = [...dismissed, s.term]
    setDismissed(next)
    check.mutate({ text, answers, dismissed: next })
  }

  const outcome = check.data
  const smart = outcome?.smart
  const question = (smart?.status === 'not_enough_info' || smart?.status === 'low_confidence') && !outcome?.skipped
    ? smart?.question : null

  return (
    <ShowMethodContext.Provider value={isAdmin}>
      <div className="grid items-start gap-6 xl:grid-cols-[400px_minmax(0,1fr)]">
        {/* Left: who and what */}
        <div className="space-y-6 xl:sticky xl:top-6">
          {isAdmin && <PatientSection chosen={chosen} onChoose={choosePatient} />}

          <Section icon={<Stethoscope className="size-4" />} title="Symptoms">
            {!isAdmin && user?.patient_profile && (
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
                <UserRound className="size-4 shrink-0" />
                <span>Checking for</span>
                <span className="min-w-0 wrap-break-word font-medium text-foreground">
                  you ({user.patient_profile.first_name} {user.patient_profile.last_name}, {user.patient_profile.patient_id})
                </span>
              </div>
            )}
            <form onSubmit={submit} className="space-y-5">
              <div className="space-y-3">
                <Field className="gap-2" htmlFor="smart-symptoms"
                  label={isAdmin && chosen ? `Symptoms of ${chosen.first_name} ${chosen.last_name}` : 'What are you feeling?'}>
                  <Textarea id="smart-symptoms" rows={4} maxLength={MAX_LENGTH} value={text}
                    onChange={(e) => setText(e.target.value)} placeholder="Type your symptoms…" />
                </Field>
                <div className="space-y-2">
                  <p className="text-xs font-medium text-subtle-foreground">Examples</p>
                  <div className="flex flex-wrap gap-2">
                    {EXAMPLES.map((ex) => (
                      <button key={ex} type="button" onClick={() => setText(ex)}
                        className="rounded-full border border-border bg-surface-2 px-3 py-1 text-left text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60">
                        {ex}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="flex items-center justify-end gap-3 border-t border-border pt-5">
                {text.length >= MAX_LENGTH - COUNTER_WARN_AT && (
                  <span className="mr-auto text-xs text-warning tabular-nums">{text.length} / {MAX_LENGTH}</span>
                )}
                <Button type="submit" loading={check.isPending}>
                  {check.isPending ? 'Checking…' : <>Check symptoms <ArrowRight className="size-4" /></>}
                </Button>
              </div>
            </form>
            <Notice tone="warning">
              <span>{DISCLAIMER}</span> In an emergency, call your local emergency number.
            </Notice>
          </Section>
        </div>

        {/* Right: results */}
        <AnimatePresence mode="wait">
          {outcome ? (
            <motion.div key={check.submittedAt} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }} transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }} className="min-w-0 space-y-6">
              {smart?.status === 'ok'
                ? <SmartSteps result={smart} canAssign={isAdmin} patient={assignPatient} />
                : smart?.status === 'emergency'
                  ? <Emergency result={smart} />
                  : smart?.status === 'needs_confirmation'
                    ? <ConfirmTerms result={smart} busy={check.isPending} onConfirm={confirm} />
                  : smart && question
                    ? <FollowUp result={smart} question={question} asked={Object.keys(answers).length}
                        busy={check.isPending} onAnswer={answer}
                        onSkip={() => check.mutate({ text, answers, dismissed, skipQuestions: true })} />
                    : <NotConfident outcome={outcome} canAssign={isAdmin} patient={assignPatient} />}
            </motion.div>
          ) : (
            <motion.div key="how" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="min-w-0">
              <HowItWorks />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </ShowMethodContext.Provider>
  )
}

/* ── Building blocks ───────────────────────────────────────────────────── */

/** A card with a one-line header (icon, title, optional tag) and a body. */
function Section({ icon, title, tag, label, children }: {
  icon: React.ReactNode; title: React.ReactNode; tag?: React.ReactNode; label?: string; children: React.ReactNode
}) {
  return (
    <Card aria-label={label} role={label ? 'region' : undefined}>
      <div className="flex items-center gap-3 border-b border-border px-6 py-4">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-primary-soft text-sm font-semibold text-primary-soft-foreground">
          {icon}
        </span>
        <h2 className="min-w-0 flex-1 font-display text-base font-semibold text-pretty">{title}</h2>
        {tag}
      </div>
      {/* Not CardContent: its built-in pt-0 would put the body right on the divider. */}
      <div className="space-y-5 p-6">{children}</div>
    </Card>
  )
}

/** Whether the technical method names are shown in step headers (admins only). */
const ShowMethodContext = createContext(false)

function Step({ n, title, method, icon: Icon, children }: {
  n: number; title: string; method: string; icon: typeof Activity; children: React.ReactNode
}) {
  const showMethod = useContext(ShowMethodContext)
  return (
    <Section label={`Step ${n}: ${title}`} icon={n} title={title}
      tag={showMethod && <Badge variant="neutral" className="hidden shrink-0 sm:inline-flex"><Icon />{method}</Badge>}>
      {children}
    </Section>
  )
}

const NOTICE_TONE = {
  warning: 'border-warning/30 bg-warning-soft text-warning',
  info: 'border-info/30 bg-info-soft text-info',
  danger: 'border-danger/40 bg-danger-soft text-danger',
} as const

function Notice({ tone, role, children }: { tone: keyof typeof NOTICE_TONE; role?: string; children: React.ReactNode }) {
  const Icon = tone === 'info' ? Info : TriangleAlert
  return (
    <div role={role} className={cn('flex items-start gap-3 rounded-[var(--radius-md)] border p-4 text-sm', NOTICE_TONE[tone])}>
      <Icon className="mt-0.5 size-4 shrink-0" />
      <p className="leading-relaxed text-pretty">{children}</p>
    </div>
  )
}

function SubHeading({ children }: { children: React.ReactNode }) {
  return <p className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">{children}</p>
}

/* ── Results ───────────────────────────────────────────────────────────── */

const METHOD_LABEL = { exact: 'exact', synonym: 'synonym', lemma: 'word form', fuzzy: 'spelling' } as const

/** How the words were understood: synonym / typo mappings, negated symptoms and unknown words. */
function TermsUnderstood({ result }: { result: SmartCheckResult }) {
  const mapped = (result.matched ?? []).filter((m) => m.method !== 'exact')
  const negated = result.negated ?? []
  const unrecognized = result.unrecognized ?? []
  return (
    <>
      {mapped.length > 0 && (
        <ul aria-label="How your words were understood" className="space-y-2 text-sm leading-relaxed text-muted-foreground">
          {mapped.map((m) => (
            <li key={`${m.term}-${m.symptom}`}>
              “{m.term}” → <span className="font-medium text-foreground">{m.symptom}</span>{' '}
              <span className="text-xs text-subtle-foreground">
                ({METHOD_LABEL[m.method]}{m.score != null ? `, ${Math.round(m.score)}% similar` : ''})
              </span>
            </li>
          ))}
        </ul>
      )}
      {negated.length > 0 && (
        <p className="text-sm leading-relaxed text-muted-foreground">You said you don't have: {negated.join(', ')}</p>
      )}
      {unrecognized.length > 0 && (
        <Notice tone="warning" role="note">
          We didn't recognise: {unrecognized.map((u) => `“${u}”`).join(', ')}. Try a simpler word.
        </Notice>
      )}
    </>
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

function SymptomsStep({ result }: { result: SmartCheckResult }) {
  return (
    <Step n={1} title="Symptoms recognised" method="Negation detection" icon={ListChecks}>
      <SymptomChips symptoms={result.symptoms} />
      <TermsUnderstood result={result} />
    </Step>
  )
}

type AssignPatient = { id: number; name: string } | null

function SmartSteps({ result, canAssign, patient }: { result: SmartCheckResult; canAssign: boolean; patient: AssignPatient }) {
  const deptPct = Math.round((result.dept_probability ?? 0) * 100)
  const doctors = result.doctors ?? []
  return (
    <>
      <SymptomsStep result={result} />

      <Step n={2} title={`Likely area: ${result.department} (${deptPct}%)`} method="Random Forest" icon={Activity}>
        <Progress value={deptPct} />
        <div className="space-y-3">
          <SubHeading>Possible illnesses</SubHeading>
          <ul className="space-y-4">
            {(result.illnesses ?? []).filter((ill) => ill.probability > MIN_ILLNESS_PROBABILITY).slice(0, MAX_ILLNESSES).map((ill) => (
              <li key={ill.name} className="space-y-1.5">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="truncate">{ill.name}</span>
                  <span className="shrink-0 font-medium tabular-nums">{pct(ill.probability)}</span>
                </div>
                <Progress value={Math.round(ill.probability * 100)} className="h-1.5" />
              </li>
            ))}
          </ul>
        </div>
      </Step>

      <Step n={3} title="Suggested doctors" method="TOPSIS ranking" icon={Stethoscope}>
        {result.doctors_note && <Notice tone="info" role="status">{result.doctors_note}</Notice>}
        {doctors.length > 0 && (
          <div className="overflow-x-auto rounded-[var(--radius-md)] border border-border">
            <table className="w-full text-sm">
              <thead className="bg-surface-2 text-left text-xs uppercase tracking-wide text-subtle-foreground">
                <tr>
                  <th className="px-3 py-2 font-semibold">Doctor</th>
                  <th className="px-3 py-2 text-right font-semibold">Free hours</th>
                  <th className="px-3 py-2 text-right font-semibold">Patients</th>
                  <th className="px-3 py-2 text-right font-semibold">Experience (years)</th>
                  <th className="px-3 py-2 text-right font-semibold">Score</th>
                  {canAssign && <th className="px-3 py-2 text-right font-semibold">Assign</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {doctors.map((doc, i) => (
                  <tr key={doc.id} className={cn(i === 0 && 'bg-primary-soft/30')}>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">Dr. {doc.name}</span>
                        {i === 0 && <Badge variant="success">Best match</Badge>}
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{doc.specialization} · {doc.department}</p>
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums">{doc.free_hours}</td>
                    <td className="px-3 py-3 text-right tabular-nums">{doc.caseload}</td>
                    <td className="px-3 py-3 text-right tabular-nums">{doc.experience_years ?? 0}</td>
                    <td className="px-3 py-3 text-right font-medium tabular-nums">{doc.score.toFixed(2)}</td>
                    {canAssign && (
                      <td className="px-3 py-3 text-right">
                        <AssignDoctorAction doctorId={doc.id} doctorName={doc.name} patient={patient} />
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Step>

      {result.patient && (
        <p className="text-center text-xs text-muted-foreground">
          Saved to the symptom history of {result.patient.name} ({result.patient.patient_id}).
        </p>
      )}
    </>
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
    <Section icon={<UserRound className="size-4" />} title="Patient">
      <Field label="Patient" htmlFor="patient-select">
        {patientsQ.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading patients…</p>
        ) : patientsQ.isError ? (
          <p className="text-sm text-danger">Could not load the patient list.</p>
        ) : (
          <SimpleSelect id="patient-select" value={chosen ? String(chosen.id) : NO_PATIENT}
            onValueChange={select} options={options} placeholder="Choose a patient" />
        )}
      </Field>
      {!patientsQ.isLoading && patients.length === 0 && !patientsQ.isError && (
        <p className="text-sm text-muted-foreground">No patients are registered yet.</p>
      )}

      {chosen && (
        <dl className="grid grid-cols-3 gap-x-4 gap-y-4 rounded-[var(--radius-md)] border border-border bg-surface-2 p-4 text-sm">
          <div className="col-span-3">
            <dt className="sr-only">Name</dt>
            <dd className="font-medium">{chosen.first_name} {chosen.middle_name ? `${chosen.middle_name} ` : ''}{chosen.last_name}
              <span className="ml-2 font-mono text-xs text-muted-foreground">{chosen.patient_id}</span></dd>
          </div>
          <PatientFact label="Age" value={chosen.age != null ? `${chosen.age} yrs` : '—'} />
          <PatientFact label="Gender" value={chosen.gender} />
          <PatientFact label="Blood" value={chosen.blood_group} />
          <PatientFact label="Allergies" value={chosen.allergies || 'None recorded'} wide />
          <PatientFact label="Medication" value={chosen.current_medication || 'None recorded'} wide />
        </dl>
      )}
    </Section>
  )
}

function PatientFact({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={cn('min-w-0', wide && 'col-span-3')}>
      <dt className="text-xs uppercase tracking-wide text-subtle-foreground">{label}</dt>
      <dd className="truncate">{value}</dd>
    </div>
  )
}

/* ── Other outcomes ────────────────────────────────────────────────────── */

/** A red-flag rule matched: go to emergency care. The model was not run; no keyword fallback. */
function Emergency({ result }: { result: SmartCheckResult }) {
  return (
    <>
      <div role="alert" className="space-y-3 rounded-[var(--radius-md)] border border-danger/40 bg-danger-soft p-5 text-sm leading-relaxed text-danger">
        <p className="flex items-center gap-2 font-display text-lg font-semibold"><TriangleAlert className="size-5 shrink-0" />Seek emergency care now</p>
        <p className="text-pretty">{result.message}</p>
        <ul className="list-disc space-y-1 pl-5">
          {(result.red_flags ?? []).map((f) => <li key={f.id}>{f.message}</li>)}
        </ul>
      </div>
      <SymptomsStep result={result} />
    </>
  )
}

/** The model is unsure: one yes/no question chosen by information gain. */
function FollowUp({ result, question, asked, busy, onAnswer, onSkip }: {
  result: SmartCheckResult; question: SmartCheckQuestion; asked: number; busy: boolean
  onAnswer: (symptom: string, yes: boolean) => void; onSkip: () => void
}) {
  return (
    <>
      <SymptomsStep result={result} />
      <Section label="Follow-up question" icon={<HelpCircle className="size-4" />} title={question.text}
        tag={<Badge variant="info" className="shrink-0">Question {asked + 1}</Badge>}>
        <div className="flex flex-wrap gap-2">
          <Button type="button" disabled={busy} onClick={() => onAnswer(question.symptom, true)}>Yes</Button>
          <Button type="button" variant="outline" disabled={busy} onClick={() => onAnswer(question.symptom, false)}>No</Button>
          <Button type="button" variant="ghost" disabled={busy} onClick={onSkip} className="ml-auto">Skip questions</Button>
        </div>
      </Section>
    </>
  )
}

/** "Did you mean ...?": words only close to a known symptom. Nothing unconfirmed reaches the model. */
function ConfirmTerms({ result, busy, onConfirm }: {
  result: SmartCheckResult; busy: boolean; onConfirm: (s: SmartCheckSuggestion, yes: boolean) => void
}) {
  return (
    <>
      <SymptomsStep result={result} />
      <Section label="Did you mean" icon={<HelpCircle className="size-4" />} title="Did you mean…?">
        <ul className="divide-y divide-border">
          {(result.suggestions ?? []).map((s) => (
            <li key={s.term} className="flex flex-wrap items-center justify-between gap-2 py-3 first:pt-0 last:pb-0">
              <span className="text-sm">
                “{s.term}” → <span className="font-medium">{s.label}</span>{' '}
                <span className="text-xs text-subtle-foreground">({Math.round(s.score)}% similar)</span>
              </span>
              <span className="flex gap-2">
                <Button type="button" size="sm" disabled={busy} onClick={() => onConfirm(s, true)}>Yes</Button>
                <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => onConfirm(s, false)}>No</Button>
              </span>
            </li>
          ))}
        </ul>
      </Section>
    </>
  )
}

function NotConfident({ outcome, canAssign, patient }: { outcome: Outcome; canAssign: boolean; patient: AssignPatient }) {
  const status: NotOkStatus =
    outcome.failed || !outcome.smart ? 'model_unavailable' : (outcome.smart.status as NotOkStatus)
  const smart = outcome.smart
  const fb = outcome.fallback
  const doctors: SmartCheckDoctor[] = smart?.doctors ?? []
  return (
    <>
      {smart && <SymptomsStep result={smart} />}
      <Notice tone="info" role="status">
        {smart?.message ?? NOT_OK_MESSAGES[status]}{fb ? ' Below is a general match from the keyword checker.' : ''}
      </Notice>
      {smart?.safety_net && <Notice tone="warning" role="note">{smart.safety_net}</Notice>}
      {smart?.department && (
        <Section icon={<Stethoscope className="size-4" />} title="First point of contact">
          <p className="font-display text-xl font-semibold">{smart.department}</p>
          {doctors.length > 0 && <DoctorList doctors={doctors.map((d) => ({ id: d.id, name: d.name, specialization: d.specialization }))}
            canAssign={canAssign} patient={patient} />}
        </Section>
      )}
      {fb && (
        <Section icon={<Sparkles className="size-4" />} title="Keyword match"
          tag={fb.confidence != null && <span className="text-xs text-muted-foreground">{fb.confidence}% confidence</span>}>
          <p className="font-display text-xl font-semibold">{fb.recommended_department}</p>
          {fb.reason && <p className="text-sm leading-relaxed text-muted-foreground text-pretty">{fb.reason}</p>}
          {!!fb.ranked_doctors?.length && (
            <DoctorList doctors={fb.ranked_doctors.map((d) => ({ id: d.id, name: `${d.first_name} ${d.last_name}`, specialization: d.specialization }))}
              canAssign={canAssign} patient={patient} />
          )}
        </Section>
      )}
    </>
  )
}

function DoctorList({ doctors, canAssign, patient }: {
  doctors: { id?: number | null; name: string; specialization?: string }[]; canAssign: boolean; patient: AssignPatient
}) {
  return (
    <ul className="divide-y divide-border rounded-[var(--radius-md)] border border-border text-sm">
      {doctors.map((doc, i) => (
        <li key={doc.id ?? i} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
          <span>Dr. {doc.name} <span className="text-muted-foreground">· {doc.specialization}</span></span>
          {canAssign && doc.id != null && <AssignDoctorAction doctorId={doc.id} doctorName={doc.name} patient={patient} />}
        </li>
      ))}
    </ul>
  )
}

function HowItWorks() {
  const steps = [
    { icon: ListChecks, title: 'Negation detection', body: 'Finds your symptoms and skips the ones you rule out, like "no fever".' },
    { icon: Activity, title: 'Random Forest', body: 'Estimates likely illnesses and the area of care.' },
    { icon: Stethoscope, title: 'TOPSIS', body: 'Ranks available doctors in that area.' },
  ]
  return (
    <Section icon={<BrainCircuit className="size-4" />} title="How it works">
      <ol className="space-y-5">
        {steps.map((s, i) => (
          <li key={s.title} className="flex gap-3">
            <span className="grid size-7 shrink-0 place-items-center rounded-full border border-border bg-surface-2 text-xs font-semibold text-muted-foreground">
              {i + 1}
            </span>
            <div className="min-w-0">
              <p className="flex items-center gap-1.5 font-medium"><s.icon className="size-4 text-primary" />{s.title}</p>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground text-pretty">{s.body}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="border-t border-border pt-5 text-xs leading-relaxed text-subtle-foreground">Results will appear here after you check your symptoms.</p>
    </Section>
  )
}
