/**
 * LabReportSummary
 * ----------------
 * Displays the three-panel processing summary:
 *   • Detected fields
 *   • Updated fields (values that changed or were new)
 *   • Unchanged fields (values that already matched)
 *   • Needs review (detected but not saved to the record)
 *
 * Also used standalone on the LabReportsList to show previously processed reports.
 */

import { CheckCircle2, RefreshCw, MinusCircle, FlaskConical, Info, TriangleAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import type { LabReport, LabReportField } from '@/lib/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function valueLabel(field: LabReportField): string {
  // Show the value in the dashboard's unit (after any conversion).
  const value = field.converted_value || field.extracted_value
  const unitText = field.converted_value ? field.converted_unit : field.unit
  const unit = unitText ? ` ${unitText}` : ''
  if (field.change_status === 'UPDATED' && field.previous_value) {
    return `${field.previous_value}${unit} → ${value}${unit}`
  }
  if (field.change_status === 'INSERTED') {
    return `${value}${unit} (new)`
  }
  return `${value}${unit}`
}

function FieldPill({
  field,
  variant,
}: {
  field: LabReportField
  variant: 'updated' | 'unchanged' | 'detected' | 'review'
}) {
  const colourMap = {
    updated: 'border-success/30 bg-success-soft/40',
    unchanged: 'border-border bg-surface-2',
    detected: 'border-info/30 bg-info-soft/30',
    review: 'border-warning/30 bg-warning-soft/40',
  }

  return (
    <div
      className={`flex flex-col gap-0.5 rounded-[var(--radius-md)] border px-3 py-2 ${colourMap[variant]}`}
    >
      <p className="text-xs font-semibold">{field.field_name}</p>
      <p className="text-xs text-muted-foreground">{valueLabel(field)}</p>
      {field.converted_value && field.converted_value !== field.extracted_value && (
        <p className="text-[10px] text-subtle-foreground">
          Converted from {field.extracted_value}{field.unit ? ` ${field.unit}` : ''}
        </p>
      )}
      {field.skip_reason && <p className="text-[10px] text-warning">{field.skip_reason}</p>}
      {field.reference_range && (
        <p className="text-[10px] text-subtle-foreground">Ref: {field.reference_range}</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Change-status badge
// ---------------------------------------------------------------------------

function StatusChip({ count, label, tone }: { count: number; label: string; tone: 'success' | 'info' | 'neutral' | 'warning' }) {
  return (
    <div className="flex items-center gap-1.5">
      <Badge variant={tone}>{count}</Badge>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  report: LabReport
  /** compact = just show counts + collapsible fields, no outer card shell */
  compact?: boolean
}

export function LabReportSummary({ report, compact = false }: Props) {
  const detected = report.detected_fields ?? report.fields ?? []
  const updated = report.updated_fields ?? detected.filter(
    (f) => f.change_status === 'UPDATED' || f.change_status === 'INSERTED',
  )
  const unchanged = report.unchanged_fields ?? detected.filter(
    (f) => f.change_status === 'UNCHANGED',
  )
  const needsReview = detected.filter((f) => f.change_status === 'SKIPPED')

  const noneDetected = detected.length === 0
  const isCompleted = report.status === 'CONFIRMED'
  const isFailed = report.status === 'FAILED'

  // Outer wrapper varies between full-card and compact inline
  const Wrapper = compact
    ? ({ children }: { children: React.ReactNode }) => <div className="space-y-4">{children}</div>
    : ({ children }: { children: React.ReactNode }) => (
        <Card>
          <CardContent className="space-y-4 p-5">{children}</CardContent>
        </Card>
      )

  if (isFailed) {
    return (
      <Wrapper>
        <div className="flex items-start gap-2 text-sm text-danger">
          <MinusCircle className="mt-0.5 size-4 shrink-0" />
          <p>Processing failed: {report.error_message || 'Unknown error'}</p>
        </div>
      </Wrapper>
    )
  }

  return (
    <Wrapper>
      {/* Header row */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <div className="flex items-center gap-2">
          <FlaskConical className="size-4 text-primary" />
          <span className="text-sm font-semibold">Processing summary</span>
        </div>
        <div className="flex flex-wrap gap-3">
          <StatusChip count={report.detected_count} label="detected" tone="info" />
          <StatusChip count={report.updated_count} label="updated" tone="success" />
          <StatusChip count={report.unchanged_count} label="unchanged" tone="neutral" />
          {needsReview.length > 0 && (
            <StatusChip count={needsReview.length} label="need review" tone="warning" />
          )}
        </div>
      </div>

      {/* No medical values detected */}
      {noneDetected && isCompleted && (
        <div className="flex items-start gap-2 rounded-[var(--radius-md)] border border-border bg-surface-2 px-3.5 py-3 text-sm text-muted-foreground">
          <Info className="mt-0.5 size-4 shrink-0" />
          <p>
            No standard clinical values were detected in this report. The original file has been
            stored and is available for download. Try a clearer scan or a machine-printed report.
          </p>
        </div>
      )}

      {/* Updated / Inserted fields */}
      {updated.length > 0 && (
        <section className="space-y-2">
          <div className="flex items-center gap-1.5">
            <RefreshCw className="size-3.5 text-success" />
            <p className="text-xs font-semibold uppercase tracking-wide text-success">Updated fields</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {updated.map((f) => (
              <FieldPill key={f.id} field={f} variant="updated" />
            ))}
          </div>
        </section>
      )}

      {/* Detected but not saved: implausible, unclear, or blood group */}
      {needsReview.length > 0 && (
        <section className="space-y-2">
          <div className="flex items-center gap-1.5">
            <TriangleAlert className="size-3.5 text-warning" />
            <p className="text-xs font-semibold uppercase tracking-wide text-warning">Needs review (not saved)</p>
          </div>
          <p className="text-xs text-muted-foreground">
            These values were read from the report but not added to the health record. The reason is shown
            under each one. Ask the care team to check and enter them if needed.
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {needsReview.map((f) => (
              <FieldPill key={f.id} field={f} variant="review" />
            ))}
          </div>
        </section>
      )}

      {/* Unchanged fields */}
      {unchanged.length > 0 && (
        <section className="space-y-2">
          <div className="flex items-center gap-1.5">
            <CheckCircle2 className="size-3.5 text-muted-foreground" />
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Unchanged fields
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {unchanged.map((f) => (
              <FieldPill key={f.id} field={f} variant="unchanged" />
            ))}
          </div>
        </section>
      )}
    </Wrapper>
  )
}
