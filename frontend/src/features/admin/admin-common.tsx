import { useEffect, useState } from 'react'
import { Check, Copy, KeyRound, TriangleAlert } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

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
export const NAME_RE = /^[A-Za-z]+(?: [A-Za-z]+)*$/
/** NMC (Nepal Medical Council) reg. number: digits, optional "NMC"/"NMC-"/"NMC No." prefix. */
export const NMC_RE = /^(?:NMC[-\s]?(?:No\.?\s*)?)?\d{1,6}$/i

/** Light input tidy for the NMC field: uppercase, drop stray symbols. Backend stores canonical "NMC-<digits>". */
export function formatNmc(raw: string): string {
  return raw.replace(/[^A-Za-z0-9\s-]/g, '').toUpperCase().slice(0, 20)
}

/**
 * Normalize a name as the user types: keep only letters and single spaces,
 * and Title-Case each word — "rojina" → "Rojina", "MARY jane" → "Mary Jane".
 * Preserves a single trailing space so multi-word names can be typed.
 */
export function formatName(raw: string): string {
  const trailingSpace = /\s$/.test(raw)
  const cleaned = raw
    .replace(/[^A-Za-z\s]/g, '')     // letters + whitespace only
    .replace(/\s+/g, ' ')            // collapse runs of whitespace
    .replace(/^\s+/, '')             // no leading space
  const titled = cleaned
    .split(' ')
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1).toLowerCase() : ''))
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

// ── Copy-to-clipboard button ──────────────────────────────────────────
export function CopyButton({ value, className }: { value: string; className?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label="Copy"
      className={className}
      onClick={() => {
        navigator.clipboard.writeText(value).then(() => {
          setCopied(true)
          toast.success('Copied to clipboard')
          setTimeout(() => setCopied(false), 1500)
        }).catch(() => toast.error('Could not copy'))
      }}
    >
      {copied ? <Check className="text-success" /> : <Copy />}
    </Button>
  )
}

// ── A single labelled, copyable credential row ────────────────────────
export function CredentialRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-[var(--radius-md)] border border-border bg-surface-2 px-3.5 py-2.5">
      <div className="min-w-0">
        <p className="text-[0.68rem] font-semibold uppercase tracking-wide text-subtle-foreground">{label}</p>
        <code className="block select-all truncate font-mono text-sm font-semibold text-foreground">{value}</code>
      </div>
      <CopyButton value={value} className="shrink-0" />
    </div>
  )
}

export interface GeneratedCreds { name: string; username: string; password: string }

// ── One-time credentials reveal dialog (shown after create) ───────────
export function CredentialsDialog({ creds, onClose }: { creds: GeneratedCreds | null; onClose: () => void }) {
  return (
    <Dialog open={!!creds} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <div className="mb-1 grid size-11 place-items-center rounded-[var(--radius-md)] bg-primary-soft text-primary-soft-foreground">
            <KeyRound className="size-5.5" />
          </div>
          <DialogTitle>Account credentials generated</DialogTitle>
          <DialogDescription>
            Login details for {creds?.name}. These are shown once — copy them now. A copy has also been emailed to the
            registered address.
          </DialogDescription>
        </DialogHeader>
        {creds && (
          <div className="space-y-2.5">
            <CredentialRow label="Username" value={creds.username} />
            <CredentialRow label="Temporary password" value={creds.password} />
          </div>
        )}
        <div className="flex items-start gap-2.5 rounded-[var(--radius-md)] bg-warning-soft px-3.5 py-2.5 text-warning">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" />
          <p className="text-xs leading-relaxed">
            The user must change this password on first sign-in. You won't be able to view it again.
          </p>
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button className="w-full sm:w-auto">Done</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Confidence badge for recommendations ──────────────────────────────
export function ConfidenceBadge({ value }: { value?: number | null }) {
  if (value == null) return <Badge variant="neutral">—</Badge>
  const variant = value >= 75 ? 'success' : value >= 50 ? 'info' : 'warning'
  return <Badge variant={variant}>{value}% confidence</Badge>
}

// ── Small header for a table cell group / avatar helper ───────────────
export function tableHeadClass(extra?: string) {
  return cn('px-4 py-3 text-left text-[0.7rem] font-semibold uppercase tracking-wide text-subtle-foreground', extra)
}
