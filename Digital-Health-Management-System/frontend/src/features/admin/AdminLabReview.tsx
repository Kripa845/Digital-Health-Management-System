import { useState } from 'react'
import { Check, Download, ShieldAlert, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Field } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { DataState, EmptyState, InfoRow, ListSkeleton, PageHeader } from '@/components/patterns'
import { apiErrorBody, labReportService } from '@/lib/api'
import { formatDate, saveBlob } from '@/lib/utils'
import type { LabReviewItem } from '@/lib/types'
import { useResolveReport, useReviewQueue } from '@/features/lab-reports/hooks'

function ReviewCard({ item }: { item: LabReviewItem }) {
  const resolve = useResolveReport()
  const [note, setNote] = useState('')
  const noteId = `review-note-${item.id}`

  function decide(decision: 'approve' | 'reject') {
    resolve.mutate({ id: item.id, decision, note }, {
      onSuccess: () => toast.success(decision === 'approve'
        ? 'Approved. The patient can now confirm the values.'
        : 'Rejected. The file was deleted and the patient was notified.'),
      onError: (err) => toast.error(apiErrorBody(err).message),
    })
  }

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="font-semibold">{item.patient_name} <span className="font-mono text-xs text-muted-foreground">{item.patient_id_code}</span></p>
            <p className="text-xs text-muted-foreground">{item.name} · uploaded {formatDate(item.uploaded_at)}{item.uploaded_by_name ? ` by ${item.uploaded_by_name}` : ''}</p>
          </div>
          <Button size="sm" variant="secondary"
            onClick={async () => {
              try { saveBlob(await labReportService.download(item.id), item.name) } catch (e) { toast.error(apiErrorBody(e).message) }
            }}>
            <Download className="size-3.5" />Original
          </Button>
        </div>

        <ul className="list-disc space-y-0.5 pl-5 text-sm text-warning">
          {(item.review_messages ?? []).map((m) => <li key={m}>{m}</li>)}
        </ul>

        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <InfoRow label="ID on report" value={item.identity.patient_id ?? 'none'} mono />
          <InfoRow label="Name on report" value={item.identity.name ?? 'none'} />
          <InfoRow label="DOB on report" value={item.identity.dob ? formatDate(item.identity.dob) : 'none'} />
        </dl>

        <div className="flex flex-wrap gap-2 text-xs">
          {(item.fields ?? []).map((f) => (
            <span key={f.id} className="rounded-[var(--radius-sm)] border border-border bg-surface-2 px-2 py-1">
              {f.field_name}: <b>{f.converted_value || f.extracted_value} {f.converted_unit}</b>
            </span>
          ))}
        </div>

        <Field label="Note to the patient (optional)" htmlFor={noteId}>
          <Input id={noteId} value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" onClick={() => decide('reject')} loading={resolve.isPending}>
            <X className="size-4" />Reject
          </Button>
          <Button onClick={() => decide('approve')} loading={resolve.isPending}>
            <Check className="size-4" />Approve for confirmation
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Approving does not change the record: the values still have to be confirmed on the patient's report.
        </p>
      </CardContent>
    </Card>
  )
}

export function AdminLabReview() {
  const { data = [], isLoading, isError, refetch } = useReviewQueue()
  return (
    <div className="space-y-6">
      <PageHeader title="Lab report review" icon={ShieldAlert}
        description="Reports whose patient ID could not be verified automatically. Check them against the patient before approving." />
      <DataState isLoading={isLoading} isError={isError} onRetry={() => refetch()} isEmpty={!data.length}
        skeleton={<ListSkeleton rows={2} />}
        empty={<EmptyState icon={ShieldAlert} title="Nothing to review" description="All uploaded reports have been verified." />}>
        <div className="space-y-4">{data.map((item) => <ReviewCard key={item.id} item={item} />)}</div>
      </DataState>
    </div>
  )
}
