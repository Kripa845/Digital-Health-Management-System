import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'

// Non-component helpers shared by the admin pages. Kept out of
// admin-common.tsx so React fast refresh works for the components there.

// ── Shared option lists (match BACKEND_SPEC exactly) ──────────────────
export const DEPARTMENTS = [
  'General Medicine', 'Cardiology', 'Neurology', 'Dermatology', 'Pediatrics',
  'Gynecology', 'Orthopedics', 'ENT', 'Ophthalmology', 'Psychiatry', 'Oncology',
  'Urology', 'Gastroenterology', 'Nephrology', 'Endocrinology', 'Pulmonology',
  'Emergency Medicine', 'Family Medicine', 'Dentistry', 'Radiology', 'Pathology',
] as const

export const BLOOD_GROUPS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'] as const
export const GENDERS = ['Male', 'Female', 'Other'] as const
export const STATUSES = ['Active', 'Inactive'] as const
export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const

export const NEPAL_PHONE = /^(98|97)\d{8}$/
/** Letters in any script (incl. Devanagari), with single spaces, hyphens, apostrophes or dots between parts. */
export const NAME_RE = /^[\p{L}\p{M}]+(?:[ '.-][\p{L}\p{M}]+)*\.?$/u
/** NMC (Nepal Medical Council) reg. number: digits, optional "NMC"/"NMC-"/"NMC No." prefix. */
export const NMC_RE = /^(?:NMC[-\s]?(?:No\.?\s*)?)?\d{1,6}$/i

/**
 * The patient ID code the admin types: the part after "PAT-", 4 to 12 letters or
 * digits with at least 4 digits (same rule as the backend), e.g. 79028232. Lab
 * reports are matched on the digits alone.
 */
export const PATIENT_ID_CODE_RE = /^(?=(?:[A-Z]*\d){4})[A-Z0-9]{4,12}$/

/** "PAT-79028232" → "79028232": the code without the PAT prefix. */
export function patientIdCode(patientId: string): string {
  return patientId.toUpperCase().replace(/^\s*PAT[\s-]*/, '')
}

/** Tidy the code as it is typed or pasted: upper-case, drop a pasted "PAT-" and any symbols. */
export function formatPatientId(raw: string): string {
  return patientIdCode(raw).replace(/[^A-Z0-9]/g, '').slice(0, 12)
}

/** A suggested 8-digit code the admin can edit, e.g. 79028232. */
export function randomPatientId(): string {
  const digits = crypto.getRandomValues(new Uint8Array(8))
  return Array.from(digits, (d) => String(d % 10)).join('')
}

/** Light input tidy for the NMC field: uppercase, drop stray symbols. Backend stores canonical "NMC-<digits>". */
export function formatNmc(raw: string): string {
  return raw.replace(/[^A-Za-z0-9\s-]/g, '').toUpperCase().slice(0, 20)
}

/**
 * Normalize a name as the user types: keep letters (any script), spaces,
 * hyphens, apostrophes and dots, and upper-case each word's first letter
 * without touching the rest — "rojina" → "Rojina", "McDonald" stays "McDonald".
 * Preserves a single trailing space so multi-word names can be typed.
 */
export function formatName(raw: string): string {
  const trailingSpace = /\s$/.test(raw)
  const cleaned = raw
    .replace(/[^\p{L}\p{M}\s'.-]/gu, '') // letters, marks, whitespace, ' . -
    .replace(/\s+/g, ' ')                // collapse runs of whitespace
    .replace(/^\s+/, '')                 // no leading space
  const titled = cleaned
    .split(' ')
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : ''))
    .join(' ')
  return trailingSpace ? `${titled.trimEnd()} ` : titled
}

// ── Extract a readable message from a DRF error response ───────────────
export function apiError(err: unknown, fallback = 'Something went wrong. Please try again.'): string {
  const e = err as { response?: { data?: unknown }; message?: string }
  const data = e?.response?.data
  if (data == null) return e?.message || fallback
  if (typeof data === 'string') return data
  if (typeof data === 'object') {
    const obj = data as Record<string, unknown>
    if (typeof obj.detail === 'string') return obj.detail
    const parts: string[] = []
    for (const [key, value] of Object.entries(obj)) {
      const msg = Array.isArray(value) ? value.join(', ') : typeof value === 'string' ? value : JSON.stringify(value)
      parts.push(key === 'non_field_errors' ? msg : `${key.replace(/_/g, ' ')}: ${msg}`)
    }
    if (parts.length) return parts.join(' · ')
  }
  return fallback
}

// ── Debounce a value (for search inputs) ──────────────────────────────
export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

// ── Small header for a table cell group / avatar helper ───────────────
export function tableHeadClass(extra?: string) {
  return cn('px-4 py-3 text-left text-[0.7rem] font-semibold uppercase tracking-wide text-subtle-foreground', extra)
}
