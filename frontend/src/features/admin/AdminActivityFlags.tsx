import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ShieldAlert, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/input'
import { SimpleSelect } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Tooltip } from '@/components/ui/misc'
import { Card, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { DataState, EmptyState, ListSkeleton } from '@/components/patterns'
import { activityFlagService } from '@/lib/api'
import type { ActivityFlag, ActivityFlagSeverity, ActivityFlagStatus } from '@/lib/types'
import { formatDateTime } from '@/lib/utils'
import { apiError, tableHeadClass } from './admin-utils'

const STATUS_OPTIONS: { value: ActivityFlagStatus; label: string }[] = [
  { value: 'NEW', label: 'New' },
  { value: 'REVIEWED', label: 'Reviewed' },
  { value: 'DISMISSED', label: 'Dismissed' },
]
const FILTER_OPTIONS = [{ value: 'all', label: 'All flags' }, ...STATUS_OPTIONS]

const statusVariant = (s: ActivityFlagStatus) => (s === 'NEW' ? 'warning' : s === 'REVIEWED' ? 'success' : 'neutral')

// Low stays gray so High stands out.
const SEVERITY: Record<ActivityFlagSeverity, { label: string; variant: 'danger' | 'warning' | 'neutral' }> = {
  HIGH: { label: 'High', variant: 'danger' },
  MEDIUM: { label: 'Medium', variant: 'warning' },
  LOW: { label: 'Low', variant: 'neutral' },
}

function ReviewControl({ flag }: { flag: ActivityFlag }) {
  const qc = useQueryClient()
  const [note, setNote] = useState(flag.note)

  const mutation = useMutation({
    mutationFn: (status: ActivityFlagStatus) => activityFlagService.review(flag.id, { status, note: note.trim() }),
    onSuccess: (saved) => {
      toast.success(
        `Flag for ${flag.username} ${saved.status === 'DISMISSED' ? 'dismissed' : 'marked as reviewed'}`,
        { description: 'It has been recorded in the audit log below.' },
      )
      // Drop the flag right away from any list whose filter it no longer matches.
      for (const [key, data] of qc.getQueriesData<ActivityFlag[]>({ queryKey: ['admin', 'activity-flags'] })) {
        const filter = key[2]
        if (!data || filter === 'all' || filter === saved.status) continue
        qc.setQueryData<ActivityFlag[]>(key, data.filter((f) => f.id !== flag.id))
      }
      qc.invalidateQueries({ queryKey: ['admin', 'activity-flags'] })
      qc.invalidateQueries({ queryKey: ['admin', 'audit'] })
    },
    onError: (err) => toast.error(apiError(err, 'Could not save the review.')),
  })
  const pendingStatus = mutation.isPending ? mutation.variables : undefined

  if (flag.status !== 'NEW') {
    return (
      <div className="space-y-2">
        <p className={flag.note ? 'whitespace-pre-wrap text-foreground' : 'italic text-subtle-foreground'}>
          {flag.note || 'No note added.'}
        </p>
        {flag.reviewed_by_username && (
          <p className="text-xs text-subtle-foreground">
            {flag.status === 'DISMISSED' ? 'Dismissed' : 'Reviewed'} by {flag.reviewed_by_username}
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <Textarea
        rows={2}
        placeholder="Add a review note (optional)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        aria-label={`Note for ${flag.username}`}
      />
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          loading={pendingStatus === 'REVIEWED'}
          disabled={mutation.isPending}
          onClick={() => mutation.mutate('REVIEWED')}
        >
          {pendingStatus !== 'REVIEWED' && <Check />} Mark reviewed
        </Button>
        <Button
          size="sm"
          variant="ghost"
          loading={pendingStatus === 'DISMISSED'}
          disabled={mutation.isPending}
          onClick={() => mutation.mutate('DISMISSED')}
        >
          {pendingStatus !== 'DISMISSED' && <X />} Dismiss
        </Button>
      </div>
    </div>
  )
}

/** Users whose activity stood out from their role (DBSCAN). Review only: nothing here changes an account. */
export function AdminActivityFlags() {
  const [status, setStatus] = useState('NEW')
  const listQ = useQuery({
    queryKey: ['admin', 'activity-flags', status],
    queryFn: () => activityFlagService.list(status !== 'all' ? { status } : undefined),
  })
  const flags = listQ.data ?? []

  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <CardTitle>Unusual activity</CardTitle>
          <CardDescription>
            Users whose activity stood out from others in the same role. For review only.
          </CardDescription>
        </div>
        <div className="w-full sm:w-44">
          <SimpleSelect value={status} onValueChange={setStatus} options={FILTER_OPTIONS} />
        </div>
      </CardHeader>
      <DataState
        isLoading={listQ.isLoading}
        isError={listQ.isError}
        isEmpty={flags.length === 0}
        onRetry={() => listQ.refetch()}
        skeleton={<ListSkeleton rows={3} />}
        empty={<EmptyState icon={ShieldAlert} title="No flags" description="No unusual activity matches this filter." />}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-y border-border bg-surface-2">
              <tr>
                <th className={tableHeadClass()}>User</th>
                <th className={tableHeadClass()}>Window</th>
                <th className={tableHeadClass()}>Reasons</th>
                <th className={tableHeadClass()}>Status</th>
                <th className={tableHeadClass('w-72')}>Review</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {flags.map((f) => (
                <tr key={f.id} className="align-top">
                  <td className="px-4 py-3">
                    <div className="font-medium">{f.full_name || f.username}</div>
                    <div className="text-xs text-subtle-foreground">{f.username} · {f.role.toLowerCase()}</div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 tabular-nums text-muted-foreground">
                    {formatDateTime(f.window_start)}<br />to {formatDateTime(f.window_end)}
                  </td>
                  <td className="max-w-md px-4 py-3">
                    <ul className="space-y-1 text-muted-foreground">
                      {f.reasons.map((r) => (
                        <Tooltip key={r.metric} content={r.detail}>
                          <li tabIndex={0} className="cursor-help">{r.text}</li>
                        </Tooltip>
                      ))}
                    </ul>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      <Badge variant={statusVariant(f.status)}>{f.status}</Badge>
                      <Badge variant={SEVERITY[f.severity].variant} title="How far the strongest reason is from typical">
                        {SEVERITY[f.severity].label}
                      </Badge>
                    </div>
                  </td>
                  <td className="px-4 py-3"><ReviewControl key={`${f.id}-${f.status}-${f.note}`} flag={f} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DataState>
    </Card>
  )
}
