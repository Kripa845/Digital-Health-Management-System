/**
 * LabReportPreview
 * ----------------
 * The confirm step for a report awaiting confirmation: current value → value
 * from the report for each test, editable, with flagged values highlighted and
 * the server's reason shown. Nothing is saved until "Confirm". All checks
 * (units, ranges, update rules) run on the server, which re-validates any edit.
 * The report date can be corrected; a report older than the patient's latest
 * confirmed one must be acknowledged before it can be confirmed. A report with
 * no health card values can only be saved as a document ("Save report only").
 * Values the server marks as needing confirmation (low OCR confidence, far outside
 * the range printed on the report, a likely lost decimal point) must be ticked as
 * checked against the scan (or corrected); otherwise they are not saved.
 * Two kinds of flag are kept apart: "possibly misread" (needs confirmation, amber) and
 * the clinical Low/High against the range printed on the value's own row (informational).
 * A range that could not be read is shown as "Range not read", never a default range.
 * Rows whose test name was not recognised are listed and are never saved.
 */
import { useMemo, useState } from 'react'
import {
  CalendarDays, CheckCircle2, Eye, EyeOff, FileText, Info, ShieldCheck, Trash2, TriangleAlert,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { apiErrorBody } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import type { LabReport, LabReportField } from '@/lib/types'
import { FlagList } from './FlagList'
import { ReportScan } from './ReportScan'
import { useConfirmReport, useDiscardReport, useSetReportDate } from './hooks'

const PLAN: Record<LabReportField['change_status'], { label: string; variant: 'success' | 'info' | 'neutral' | 'warning' }> = {
  INSERTED: { label: 'Will be added', variant: 'success' },
  UPDATED: { label: 'Will be updated', variant: 'info' },
  UNCHANGED: { label: 'Same as now', variant: 'neutral' },
  HISTORY: { label: 'History only', variant: 'neutral' },
  SKIPPED: { label: "Won't be saved", variant: 'warning' },
}

function shown(f: LabReportField) {
  return f.converted_value || f.extracted_value
}

const CLINICAL: Record<'low' | 'high', string> = { low: 'Below report range', high: 'Above report range' }

/** Tests with a numeric reference range (blood group and blood pressure have none on the row). */
function hasRange(f: LabReportField) {
  return f.patient_field !== 'blood_group' && f.patient_field !== 'blood_pressure'
}

interface Props {
  report: LabReport
  /** Kept for older callers; data refresh is handled by the hooks. */
  patientId?: number
  queryScope?: string
  onConfirmed?: (report: LabReport) => void
  onDiscarded?: () => void
  /** Offer a "Show scan" toggle; off where the scan is already shown beside the preview. */
  showScan?: boolean
}

const NO_VALUES_TEXT = 'No health card values were found. You can save this report as a document only. Dashboard values will not change.'

const DATE_SOURCE: Record<string, string> = {
  reporting: 'Read from the reporting date on the report.',
  collection: 'No reporting date was printed, so the sample collection date is used.',
  user: 'Entered by you.',
}

/** Needs a tick before it is saved: out of range (accept) or marked for confirmation. */
function needsTick(f: LabReportField) {
  return f.flag === 'out_of_range' || (!!f.needs_confirmation && f.change_status !== 'SKIPPED')
}

export function LabReportPreview({ report: initial, onConfirmed, onDiscarded, showScan = true }: Props) {
  // The report as last returned by the server (a date change re-plans the preview).
  const [updated, setUpdated] = useState<LabReport | null>(null)
  const report = updated && updated.id === initial.id ? updated : initial
  const fields = useMemo(() => report.fields ?? report.detected_fields ?? [], [report])
  const [values, setValues] = useState<Record<string, string>>(
    () => Object.fromEntries(fields.map((f) => [f.patient_field, shown(f)])),
  )
  // Ticked values: out-of-range values accepted and/or values confirmed against the scan.
  const [accepted, setAccepted] = useState<Set<string>>(new Set())
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [scanOpen, setScanOpen] = useState(false)
  const confirm = useConfirmReport()
  const discard = useDiscardReport()
  const setDate = useSetReportDate()
  const busy = confirm.isPending || discard.isPending || setDate.isPending

  const [dateInput, setDateInput] = useState(report.report_date ?? '')
  const [dateError, setDateError] = useState('')
  const [acknowledged, setAcknowledged] = useState(false)
  const noValues = report.status === 'NO_VALUES_SAVEABLE'
  const olderWarning = report.date_check_status === 'older_than_latest' && !!report.date_ack_required
  const dateChanged = !!dateInput && dateInput !== (report.report_date ?? '')
  const unconfirmed = fields.filter((f) => f.needs_confirmation && f.change_status !== 'SKIPPED' && !accepted.has(f.patient_field))
  const unmatched = report.extracted?.unmatched_rows ?? []

  function tick(field: string, on: boolean) {
    setAccepted((s) => {
      const next = new Set(s)
      if (on) next.add(field)
      else next.delete(field)
      return next
    })
  }

  function saveDate() {
    setDateError('')
    setDate.mutate({ id: report.id, reportDate: dateInput }, {
      onSuccess: (data) => {
        setUpdated(data)
        setAcknowledged(false)                       // a new date needs a new acknowledgement
        toast.success('Report date saved.')
      },
      onError: (err) => setDateError(apiErrorBody(err).message),
    })
  }

  function submit() {
    // Send only what the user changed; the server re-checks everything.
    const edits: Record<string, string> = {}
    for (const f of fields) {
      const v = (values[f.patient_field] ?? '').trim()
      if (v && v !== shown(f)) edits[f.patient_field] = v
    }
    setErrors({})
    const ticked = fields.filter((f) => accepted.has(f.patient_field))
    confirm.mutate({ id: report.id, payload: {
      values: edits,
      accept_flagged: ticked.filter((f) => f.flag === 'out_of_range').map((f) => f.patient_field),
      confirmed: ticked.filter((f) => f.needs_confirmation).map((f) => f.patient_field),
      acknowledge_older_report: olderWarning && acknowledged,
    } }, {
      onSuccess: (data) => {
        toast.success(noValues ? 'Report saved as a document. Health cards did not change.'
          : data.updated_count ? 'Health record updated.' : 'Report saved to your history.')
        onConfirmed?.(data)
      },
      onError: (err) => {
        const body = apiErrorBody(err)
        if (body.errors) {
          setErrors(Object.fromEntries(Object.entries(body.errors).map(([k, v]) => [k, Array.isArray(v) ? v[0] : String(v)])))
        }
        toast.error(body.message)
      },
    })
  }

  function cancel() {
    discard.mutate(report.id, {
      onSuccess: () => { toast.success('Report cancelled. Nothing was changed.'); onDiscarded?.() },
      onError: (err) => toast.error(apiErrorBody(err).message),
    })
  }

  return (
    <div className="space-y-4">
      {noValues && (
        <div role="status" className="flex items-start gap-3 rounded-[var(--radius-md)] border border-info/30 bg-info-soft px-4 py-3 text-info">
          <Info className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
          <div className="text-sm">
            <p className="font-semibold">{report.no_values_message || NO_VALUES_TEXT}</p>
            {!report.identity_verified && (
              <p className="mt-1 text-xs">The patient could not be identified, so it will be saved as unverified.</p>
            )}
          </div>
        </div>
      )}

      {!noValues && (
      <div className="flex items-start gap-3 rounded-[var(--radius-md)] border border-success/30 bg-success-soft/40 px-4 py-3">
        <ShieldCheck className="mt-0.5 size-5 shrink-0 text-success" aria-hidden="true" />
        <div className="text-sm">
          <p className="font-semibold text-success">Patient ID verified for {report.patient_name ?? 'this patient'}</p>
          <p className="text-xs text-muted-foreground">
            Check the date and values. Nothing is saved until you confirm.
          </p>
        </div>
      </div>
      )}

      <div className="flex flex-col gap-2 rounded-[var(--radius-md)] border border-border p-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-1">
          <label htmlFor={`report-date-${report.id}`} className="flex items-center gap-1.5 text-sm font-medium">
            <CalendarDays className="size-4 text-muted-foreground" aria-hidden="true" />Report date
          </label>
          <div className="flex items-center gap-2">
            <Input id={`report-date-${report.id}`} type="date" value={dateInput} max={new Date().toISOString().slice(0, 10)}
              onChange={(e) => setDateInput(e.target.value)} disabled={busy} className="h-8 w-44"
              aria-describedby={`report-date-${report.id}-help`} aria-invalid={!!dateError} />
            {dateChanged && (
              <Button size="sm" variant="secondary" onClick={saveDate} loading={setDate.isPending} disabled={busy}>
                Save date
              </Button>
            )}
          </div>
          <div id={`report-date-${report.id}-help`} className="text-xs">
            {dateError
              ? <p className="text-danger">{dateError}</p>
              : report.date_check_status === 'date_missing'
                ? <p className="text-warning">{report.date_message || 'No reporting date could be read. Enter the date printed on the report.'}</p>
                : <p className="text-muted-foreground">{DATE_SOURCE[report.report_date_source ?? ''] ?? ''}
                    {report.latest_report_date ? ` Latest confirmed report: ${formatDate(report.latest_report_date)}.` : ''}</p>}
          </div>
        </div>
      </div>

      {olderWarning && (
        <div role="alert" className="space-y-2 rounded-[var(--radius-md)] border border-warning/40 bg-warning-soft p-3 text-sm text-warning">
          <p className="flex items-start gap-2 font-medium">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />{report.date_message}
          </p>
          <p className="text-xs">Its values only go to the history.</p>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={acknowledged} disabled={busy} onChange={(e) => setAcknowledged(e.target.checked)} />
            I understand this is an older report, upload anyway
          </label>
        </div>
      )}

      {showScan && (
        <div className="space-y-2">
          <Button variant="secondary" size="sm" onClick={() => setScanOpen((o) => !o)} aria-expanded={scanOpen}>
            {scanOpen ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            {scanOpen ? 'Hide scan' : 'Show scan'}
          </Button>
          {scanOpen && <ReportScan id={report.id} type={report.file_type} />}
        </div>
      )}

      {!noValues && <FlagList fields={fields} />}

      {!noValues && (
      <div className="overflow-x-auto rounded-[var(--radius-md)] border border-border">
        <table className="w-full text-sm">
          <caption className="sr-only">Values read from the report</caption>
          <thead className="bg-surface-2 text-left text-[0.7rem] uppercase tracking-wide text-subtle-foreground">
            <tr>
              <th scope="col" className="px-3 py-2 font-semibold">Test</th>
              <th scope="col" className="px-3 py-2 font-semibold">Now</th>
              <th scope="col" className="px-3 py-2 font-semibold">From report</th>
              <th scope="col" className="px-3 py-2 font-semibold">Result</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((f) => {
              const id = `lab-value-${f.patient_field}`
              const waiting = !!f.needs_confirmation && f.change_status !== 'SKIPPED' && !accepted.has(f.patient_field)
              const plan = waiting ? { label: 'Needs confirmation', variant: 'warning' as const } : PLAN[f.change_status]
              const flagged = !!f.flag || waiting
              const converted = f.converted_value && f.converted_value !== f.extracted_value
              return (
                <tr key={f.id} className={`border-t border-border align-top ${flagged ? 'bg-warning-soft/30' : ''}`}>
                  <th scope="row" className="px-3 py-2.5 text-left font-medium">
                    <label htmlFor={id}>{f.field_name}</label>
                  </th>
                  <td className="px-3 py-2.5 font-mono tabular-nums text-muted-foreground">{f.previous_value || '—'}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-1.5">
                      <Input
                        id={id}
                        value={values[f.patient_field] ?? ''}
                        onChange={(e) => {
                          setValues((s) => ({ ...s, [f.patient_field]: e.target.value }))
                          // A correction made while looking at the scan counts as confirmed.
                          if (f.needs_confirmation) tick(f.patient_field, true)
                        }}
                        disabled={busy}
                        inputMode={f.patient_field === 'blood_group' || f.patient_field === 'blood_pressure' ? 'text' : 'decimal'}
                        aria-invalid={!!errors[f.patient_field] || flagged}
                        aria-describedby={`${id}-help`}
                        className="h-8 w-28 font-mono tabular-nums"
                      />
                      <span className="text-xs text-muted-foreground">{f.converted_unit}</span>
                      {(f.reference_flag === 'low' || f.reference_flag === 'high') && (
                        <Badge variant="info">{CLINICAL[f.reference_flag]}</Badge>
                      )}
                    </div>
                    <div id={`${id}-help`} className="mt-1 space-y-0.5 text-xs">
                      {converted && !f.suggested_value && <p className="text-muted-foreground">Converted from {f.extracted_value} {f.unit}</p>}
                      {f.suggested_value && <p className="text-muted-foreground">Read on the report as {f.extracted_value} {f.unit}</p>}
                      {f.reference_range
                        ? <p className="text-muted-foreground">Range on the report: {f.reference_range}</p>
                        : hasRange(f) && <p className="text-muted-foreground">Range not read</p>}
                      {f.ocr_confidence != null && f.ocr_confidence < 100 && (
                        <p className="text-muted-foreground">Read with {Math.round(f.ocr_confidence)}% confidence</p>
                      )}
                      {errors[f.patient_field] && <p className="text-danger">{errors[f.patient_field]}</p>}
                      {f.skip_reason && !errors[f.patient_field] && <p className="text-warning">{f.skip_reason}</p>}
                      {f.needs_confirmation && f.change_status !== 'SKIPPED' && !errors[f.patient_field] &&
                        !!f.confirmation_reasons?.length && (
                          <div className="text-warning">
                            <p className="font-semibold">Possibly misread:</p>
                            {f.confirmation_reasons.map((r) => <p key={r.code}>{r.message}</p>)}
                          </div>
                        )}
                    </div>
                    {needsTick(f) && (
                      <label className="mt-1.5 flex items-center gap-1.5 text-xs">
                        <input
                          type="checkbox"
                          checked={accepted.has(f.patient_field)}
                          disabled={busy}
                          onChange={(e) => tick(f.patient_field, e.target.checked)}
                        />
                        {f.needs_confirmation ? 'I checked this value against the scan' : 'This value is correct, save it anyway'}
                      </label>
                    )}
                  </td>
                  <td className="px-3 py-2.5"><Badge variant={plan.variant}>{plan.label}</Badge></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      )}

      {unmatched.length > 0 && (
        <div className="space-y-1.5 rounded-[var(--radius-md)] border border-border p-3 text-sm">
          <p className="font-semibold">Not recognised (won't be saved)</p>
          <ul className="list-disc space-y-0.5 pl-5 text-xs">
            {unmatched.map((u, i) => (
              <li key={`${u.name}-${i}`}>
                <span className="font-medium">{u.name}</span>: {u.value} {u.unit}
                {u.range ? ` (range ${u.range})` : ''} — {u.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {!noValues && unconfirmed.length > 0 && (
        <p role="note" className="flex items-start gap-2 text-sm text-warning">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {unconfirmed.length === 1 ? '1 value needs' : `${unconfirmed.length} values need`} checking against the scan.
          Values you do not confirm or correct will not be saved.
        </p>
      )}

      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="secondary" onClick={cancel} loading={discard.isPending} disabled={busy}>
          {!discard.isPending && <Trash2 className="size-4" />}
          Cancel
        </Button>
        <Button onClick={submit} loading={confirm.isPending} disabled={busy || (olderWarning && !acknowledged)}>
          {!confirm.isPending && (noValues ? <FileText className="size-4" /> : <CheckCircle2 className="size-4" />)}
          {noValues ? 'Save report only' : 'Confirm'}
        </Button>
      </div>
    </div>
  )
}
