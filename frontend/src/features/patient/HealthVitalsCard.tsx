/**
 * HealthVitalsCard
 * ─────────────────
 * Displays ALL patient vitals on the dashboard — always visible, regardless of
 * whether values have been recorded yet.  Empty fields show a "—" placeholder
 * with a subtle "Upload a lab report to fill this in" prompt.
 *
 * Values are auto-updated whenever a lab report is processed via OCR / CDSA.
 */

import { Link } from 'react-router-dom'
import {
  Activity, Droplets, FlaskConical, Heart, Scale, Ruler,
  ChevronRight, RefreshCw, TrendingUp,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import type { Patient } from '@/lib/types'

// ─── value helpers ───────────────────────────────────────────────────────────

function numVal(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return isNaN(n) ? null : n
}

function fmt(v: string | number | null | undefined, decimals = 1): string {
  const n = numVal(v)
  if (n === null) return '—'
  return n % 1 === 0 ? String(n) : n.toFixed(decimals)
}

// ─── status types + helpers ───────────────────────────────────────────────────

type VitalStatus = 'normal' | 'warning' | 'critical' | 'unknown'

function bpStatus(bp: string | null | undefined): VitalStatus {
  if (!bp) return 'unknown'
  const m = bp.match(/^(\d+)\/(\d+)$/)
  if (!m) return 'unknown'
  const sys = Number(m[1]), dia = Number(m[2])
  if (sys >= 180 || dia >= 120) return 'critical'
  if (sys >= 130 || dia >= 80)  return 'warning'
  return 'normal'
}

function bsStatus(v: number | null): VitalStatus {
  if (v === null) return 'unknown'
  if (v >= 200) return 'critical'
  if (v >= 126) return 'warning'
  return 'normal'
}

function hbStatus(v: number | null, gender?: string): VitalStatus {
  if (v === null) return 'unknown'
  const low = gender === 'Female' ? 12 : 13.5
  if (v < low - 2) return 'critical'
  if (v < low)     return 'warning'
  return 'normal'
}

function cholStatus(v: number | null): VitalStatus {
  if (v === null) return 'unknown'
  if (v >= 240) return 'critical'
  if (v >= 200) return 'warning'
  return 'normal'
}

function bmiStatus(v: number | null): VitalStatus {
  if (v === null) return 'unknown'
  if (v >= 35) return 'critical'
  if (v < 18.5 || v >= 30) return 'warning'
  return 'normal'
}

const STATUS_DOT: Record<VitalStatus, string> = {
  normal:   'bg-success',
  warning:  'bg-warning',
  critical: 'bg-danger',
  unknown:  'bg-muted',
}

const STATUS_TEXT: Record<VitalStatus, string> = {
  normal:   'text-success',
  warning:  'text-warning',
  critical: 'text-danger',
  unknown:  'text-muted-foreground',
}

const STATUS_LABEL: Record<VitalStatus, string> = {
  normal:   'Normal',
  warning:  'Borderline',
  critical: 'High',
  unknown:  '',
}

// ─── single vital tile ────────────────────────────────────────────────────────

interface TileProps {
  icon: React.ElementType
  label: string
  value: string          // '—' when unknown
  unit?: string
  status: VitalStatus
  accent?: string        // tailwind text-colour for the icon bg
}

function VitalTile({ icon: Icon, label, value, unit, status, accent = 'text-primary' }: TileProps) {
  const hasValue = value !== '—'

  return (
    <div className="relative flex items-start gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-3.5 py-3 transition-colors hover:bg-surface-2">
      {/* accent bar on left edge */}
      <span className={`absolute inset-y-0 left-0 w-0.5 rounded-l-[var(--radius-md)] ${
        status === 'normal'   ? 'bg-success/60'
        : status === 'warning'  ? 'bg-warning/60'
        : status === 'critical' ? 'bg-danger/60'
        : 'bg-transparent'
      }`} />

      {/* icon */}
      <span className={`mt-0.5 grid size-8 shrink-0 place-items-center rounded-[var(--radius-sm)] bg-surface-2 ${accent}`}>
        <Icon className="size-4" />
      </span>

      {/* label + value */}
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-medium uppercase tracking-wide text-subtle-foreground leading-none mb-1">
          {label}
        </p>
        <div className="flex items-baseline gap-1">
          <span className={`text-xl font-bold leading-tight tabular-nums ${
            hasValue ? 'text-foreground' : 'text-muted-foreground/40'
          }`}>
            {value}
          </span>
          {unit && hasValue && (
            <span className="text-xs text-muted-foreground">{unit}</span>
          )}
        </div>
      </div>

      {/* status badge */}
      {hasValue ? (
        <div className="flex shrink-0 flex-col items-end gap-1 pt-0.5">
          <span className={`size-2 rounded-full ${STATUS_DOT[status]}`} />
          {STATUS_LABEL[status] && (
            <span className={`text-[10px] font-medium ${STATUS_TEXT[status]}`}>
              {STATUS_LABEL[status]}
            </span>
          )}
        </div>
      ) : (
        <span className="shrink-0 text-[10px] text-muted-foreground/50 pt-1">Not recorded</span>
      )}
    </div>
  )
}

// ─── section group ────────────────────────────────────────────────────────────

function VitalGroup({
  title,
  children,
  cols = 2,
}: {
  title: string
  children: React.ReactNode
  cols?: 2 | 3 | 4
}) {
  const colClass = cols === 3 ? 'sm:grid-cols-3' : cols === 4 ? 'sm:grid-cols-2 lg:grid-cols-4' : 'sm:grid-cols-2'
  return (
    <div>
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-subtle-foreground">
        {title}
      </p>
      <div className={`grid gap-2 ${colClass}`}>{children}</div>
    </div>
  )
}

// ─── main export ──────────────────────────────────────────────────────────────

interface Props {
  patient: Patient
}

export function HealthVitalsCard({ patient }: Props) {
  const hVal   = numVal(patient.height)
  const wVal   = numVal(patient.weight)
  const bmi    = hVal && wVal ? wVal / Math.pow(hVal / 100, 2) : null

  const hbVal  = numVal(patient.hemoglobin)
  const bsfVal = numVal(patient.blood_sugar_fasting)
  const bsrVal = numVal(patient.blood_sugar_random)
  const cholVal= numVal(patient.cholesterol_total)
  const hdlVal = numVal(patient.cholesterol_hdl)
  const ldlVal = numVal(patient.cholesterol_ldl)
  const tgVal  = numVal(patient.triglycerides)

  // How many clinical vitals (beyond height/weight) are populated
  const clinicalCount = [
    patient.blood_pressure, patient.hemoglobin,
    patient.blood_sugar_fasting, patient.blood_sugar_random,
    patient.cholesterol_total, patient.cholesterol_hdl,
    patient.cholesterol_ldl, patient.triglycerides,
  ].filter((v) => v !== null && v !== undefined && v !== '').length

  return (
    <Card className="overflow-hidden">

      {/* ── Header ── */}
      <div className="flex items-center justify-between border-b border-border bg-surface-2/40 px-5 py-3.5">
        <div className="flex items-center gap-2.5">
          <span className="grid size-7 place-items-center rounded-[var(--radius-sm)] bg-primary-soft text-primary">
            <Activity className="size-4" />
          </span>
          <span className="text-sm font-semibold">Health vitals</span>
          {clinicalCount > 0 ? (
            <Badge variant="success" className="gap-1 text-[10px]">
              <RefreshCw className="size-2.5" />
              {clinicalCount} value{clinicalCount > 1 ? 's' : ''} from lab reports
            </Badge>
          ) : (
            <Badge variant="neutral" className="text-[10px]">
              No lab report processed yet
            </Badge>
          )}
        </div>

        <Link
          to="/patient/reports"
          className="flex items-center gap-1 rounded-[var(--radius-sm)] px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary-soft/40"
        >
          <FlaskConical className="size-3" />
          Upload lab report
          <ChevronRight className="size-3" />
        </Link>
      </div>

      <CardContent className="space-y-5 p-5">

        {/* ── Physical measurements (always shown — populated at registration) ── */}
        <VitalGroup title="Physical measurements" cols={3}>
          <VitalTile
            icon={Ruler}
            label="Height"
            value={fmt(patient.height, 0)}
            unit="cm"
            status={hVal ? 'normal' : 'unknown'}
            accent="text-info"
          />
          <VitalTile
            icon={Scale}
            label="Weight"
            value={fmt(patient.weight, 1)}
            unit="kg"
            status={wVal ? 'normal' : 'unknown'}
            accent="text-info"
          />
          <VitalTile
            icon={TrendingUp}
            label="BMI"
            value={bmi ? bmi.toFixed(1) : '—'}
            unit="kg/m²"
            status={bmiStatus(bmi)}
            accent="text-info"
          />
        </VitalGroup>

        {/* ── Cardiovascular (always shown) ── */}
        <VitalGroup title="Cardiovascular" cols={2}>
          <VitalTile
            icon={Heart}
            label="Blood Pressure"
            value={patient.blood_pressure || '—'}
            unit={patient.blood_pressure ? 'mmHg' : undefined}
            status={bpStatus(patient.blood_pressure)}
            accent="text-danger"
          />
          <VitalTile
            icon={Droplets}
            label="Hemoglobin"
            value={fmt(patient.hemoglobin, 1)}
            unit="g/dL"
            status={hbStatus(hbVal, patient.gender)}
            accent="text-danger"
          />
        </VitalGroup>

        {/* ── Blood glucose (always shown) ── */}
        <VitalGroup title="Blood glucose" cols={2}>
          <VitalTile
            icon={Droplets}
            label="Blood Sugar (Fasting)"
            value={fmt(patient.blood_sugar_fasting, 0)}
            unit="mg/dL"
            status={bsStatus(bsfVal)}
            accent="text-warning"
          />
          <VitalTile
            icon={Droplets}
            label="Blood Sugar (Random)"
            value={fmt(patient.blood_sugar_random, 0)}
            unit="mg/dL"
            status={bsStatus(bsrVal)}
            accent="text-warning"
          />
        </VitalGroup>

        {/* ── Lipid panel (always shown) ── */}
        <VitalGroup title="Cholesterol &amp; lipids" cols={4}>
          <VitalTile
            icon={Activity}
            label="Total Cholesterol"
            value={fmt(patient.cholesterol_total, 0)}
            unit="mg/dL"
            status={cholStatus(cholVal)}
            accent="text-primary"
          />
          <VitalTile
            icon={Activity}
            label="HDL"
            value={fmt(patient.cholesterol_hdl, 0)}
            unit="mg/dL"
            status={hdlVal !== null ? (hdlVal >= 40 ? 'normal' : 'warning') : 'unknown'}
            accent="text-success"
          />
          <VitalTile
            icon={Activity}
            label="LDL"
            value={fmt(patient.cholesterol_ldl, 0)}
            unit="mg/dL"
            status={
              ldlVal !== null
                ? ldlVal < 100 ? 'normal' : ldlVal < 160 ? 'warning' : 'critical'
                : 'unknown'
            }
            accent="text-warning"
          />
          <VitalTile
            icon={Activity}
            label="Triglycerides"
            value={fmt(patient.triglycerides, 0)}
            unit="mg/dL"
            status={
              tgVal !== null
                ? tgVal < 150 ? 'normal' : tgVal < 200 ? 'warning' : 'critical'
                : 'unknown'
            }
            accent="text-warning"
          />
        </VitalGroup>

        {/* ── Footer ── */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>Blood group:</span>
            <span className="font-semibold text-foreground">{patient.blood_group || '—'}</span>
          </div>

          {clinicalCount === 0 ? (
            <Link
              to="/patient/reports"
              className="inline-flex items-center gap-1.5 rounded-[var(--radius-md)] border border-primary/30 bg-primary-soft/40 px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary-soft/70"
            >
              <FlaskConical className="size-3" />
              Upload a lab report to fill in your vitals
            </Link>
          ) : (
            <span className="text-[11px] italic text-muted-foreground">
              Values reflect your most recent lab report
            </span>
          )}
        </div>

      </CardContent>
    </Card>
  )
}
