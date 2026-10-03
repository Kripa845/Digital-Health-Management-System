import { TriangleAlert } from 'lucide-react'
import type { LabReportField } from '@/lib/types'

/** Values the server flagged (and why), plus any review messages. */
export function FlagList({ fields, messages = [] }: { fields: LabReportField[]; messages?: string[] }) {
  const flagged = fields.filter((f) => f.flag || f.change_status === 'SKIPPED')
  if (!flagged.length && !messages.length) return null
  return (
    <div role="status" className="space-y-2 rounded-[var(--radius-md)] border border-warning/30 bg-warning-soft/40 px-4 py-3">
      <p className="flex items-center gap-1.5 text-sm font-semibold text-warning">
        <TriangleAlert className="size-4" aria-hidden="true" /> Please check
      </p>
      <ul className="list-disc space-y-1 pl-5 text-sm text-foreground">
        {messages.map((m) => <li key={m}>{m}</li>)}
        {flagged.map((f) => (
          <li key={f.id}>
            <span className="font-medium">{f.field_name}:</span> {f.skip_reason || 'This value needs checking.'}
          </li>
        ))}
      </ul>
    </div>
  )
}
