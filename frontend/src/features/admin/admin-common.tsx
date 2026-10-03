import { useState } from 'react'
import { Check, Copy, KeyRound, TriangleAlert } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose,
} from '@/components/ui/dialog'

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
export function CredentialsDialog({
  creds, onClose, emailed = true,
}: { creds: GeneratedCreds | null; onClose: () => void; emailed?: boolean }) {
  return (
    <Dialog open={!!creds} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <div className="mb-1 grid size-11 place-items-center rounded-[var(--radius-md)] bg-primary-soft text-primary-soft-foreground">
            <KeyRound className="size-5.5" />
          </div>
          <DialogTitle>Account credentials generated</DialogTitle>
          <DialogDescription>
            Login details for {creds?.name}. These are shown once, so copy them now.{' '}
            {emailed
              ? 'A copy has also been emailed to the registered address.'
              : 'The welcome email could not be sent, so give these details to the user yourself.'}
          </DialogDescription>
        </DialogHeader>
        {creds && (
          <div className="space-y-2.5">
            <CredentialRow label="Username" value={creds.username} />
            {creds.password && <CredentialRow label="Temporary password" value={creds.password} />}
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
