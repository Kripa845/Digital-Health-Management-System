import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Radar, Siren } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { SimpleSelect } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Card, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { DataState, EmptyState, ListSkeleton } from '@/components/patterns'
import { NewAlertsBanner, useNewSuspiciousAlerts } from '@/components/suspicious-alerts'
import { suspiciousAlertService } from '@/lib/api'
import type { ActivityFlagStatus, SuspiciousAlert, SuspiciousDetection } from '@/lib/types'
import { formatDate } from '@/lib/utils'
import { apiError, tableHeadClass } from './admin-utils'

const FILTER_OPTIONS = [
  { value: 'NEW', label: 'New alerts' },
  { value: 'REVIEWED', label: 'Reviewed' },
  { value: 'DISMISSED', label: 'Dismissed' },
  { value: 'all', label: 'All alerts' },
]

const statusVariant = (s: ActivityFlagStatus) => (s === 'NEW' ? 'danger' : s === 'REVIEWED' ? 'success' : 'neutral')

function ReviewButtons({ alert }: { alert: SuspiciousAlert }) {
  const qc = useQueryClient()
  const mutation = useMutation({
    mutationFn: (status: ActivityFlagStatus) => suspiciousAlertService.setStatus(alert.id, status),
    onSuccess: (_, status) => {
      toast.success(`Alert for ${alert.username} marked ${status.toLowerCase()}.`)
      qc.invalidateQueries({ queryKey: ['admin', 'suspicious-alerts'] })
      qc.invalidateQueries({ queryKey: ['admin', 'activity-analysis'] })
    },
    onError: (err) => toast.error(apiError(err, 'Could not save the review.')),
  })
  const pending = mutation.isPending ? mutation.variables : undefined

  return (
    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="secondary" disabled={alert.status === 'REVIEWED' || mutation.isPending}
        loading={pending === 'REVIEWED'} onClick={() => mutation.mutate('REVIEWED')}>
        Mark reviewed
      </Button>
      <Button size="sm" variant="ghost" disabled={alert.status === 'DISMISSED' || mutation.isPending}
        loading={pending === 'DISMISSED'} onClick={() => mutation.mutate('DISMISSED')}>
        Dismiss
      </Button>
    </div>
  )
}

const POLL_MS = 60_000

/** Runs DBSCAN on today's activity every POLL_MS while the page is open; refreshes the alerts when it creates any. */
function useDetection() {
  const qc = useQueryClient()
  const onResult = (d: SuspiciousDetection) => {
    if (d.created > 0 || d.updated > 0) qc.invalidateQueries({ queryKey: ['admin', 'suspicious-alerts'] })
  }
  const detectQ = useQuery({
    queryKey: ['admin', 'suspicious-detection'],
    queryFn: async () => {
      const d = await suspiciousAlertService.detect()
      onResult(d)
      return d
    },
    refetchInterval: POLL_MS,
    retry: false,
  })
  const runNow = useMutation({
    mutationFn: () => suspiciousAlertService.detect(true),
    onSuccess: (d) => {
      qc.setQueryData(['admin', 'suspicious-detection'], d)
      onResult(d)
      if (!d.enough_data || d.roles.every((r) => r.skipped)) toast.info('DBSCAN could not run yet: not enough activity to learn what is normal.')
      else if (d.created === 0) toast.success('DBSCAN check finished. No new suspicious activity.')
    },
    onError: (err) => toast.error(apiError(err, 'Could not run the DBSCAN check.')),
  })
  return { detection: detectQ.data, isError: detectQ.isError, runNow }
}

function DetectionStatus({ detection, isError, onRun, running }: {
  detection?: SuspiciousDetection; isError: boolean; onRun: () => void; running: boolean
}) {
  const skipped = detection?.roles.filter((r) => r.skipped) ?? []
  const ran = detection?.roles.filter((r) => !r.skipped) ?? []
  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface-2 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-3">
        <Radar className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
        <div className="space-y-0.5">
          <p className="font-medium">
            {isError ? 'Automatic DBSCAN check failed' : !detection ? 'Running DBSCAN check…'
              : `DBSCAN checked today at ${new Date(detection.ran_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`}
          </p>
          {detection && (
            <p className="text-muted-foreground">
              {!detection.enough_data
                ? `Not enough activity yet to learn what is normal: ${detection.user_days} user-days in the last ${detection.history} days, at least ${detection.min_rows} needed.`
                : ran.length === 0
                  ? `Not enough activity per role yet (${skipped.map((r) => `${r.role.toLowerCase()} ${r.user_days}`).join(', ')} of ${detection.min_rows} user-days needed). No alerts can be raised until then.`
                  : `${detection.checked} user-days checked (${ran.map((r) => r.role.toLowerCase()).join(', ')}), ${detection.clusters} normal clusters.`
                    + (skipped.length ? ` Skipped ${skipped.map((r) => r.role.toLowerCase()).join(', ')}: too little activity.` : '')}
              {' '}Checks again every minute while this page is open.
            </p>
          )}
        </div>
      </div>
      <Button size="sm" variant="secondary" loading={running} onClick={onRun}>Run DBSCAN now</Button>
    </div>
  )
}

/** User-days whose activity was unlike recent normal days (DBSCAN). Review only: nothing here changes an account. */
export function AdminSuspiciousAlerts() {
  const [status, setStatus] = useState('NEW')
  const listQ = useQuery({
    queryKey: ['admin', 'suspicious-alerts', status],
    queryFn: () => suspiciousAlertService.list(status !== 'all' ? { status } : undefined),
    retry: false,      // a failed load shows the error state with a Retry button instead
  })
  const alerts = listQ.data ?? []

  const { detection, isError: detectError, runNow } = useDetection()

  // Toasts come from SuspiciousAlertWatcher in the admin shell, on every admin page.
  const newCount = useNewSuspiciousAlerts().data?.length ?? 0

  return (
    <div className="space-y-4">
      <DetectionStatus detection={detection} isError={detectError} onRun={() => runNow.mutate()} running={runNow.isPending} />
      <NewAlertsBanner count={newCount} onShow={status !== 'NEW' ? () => setStatus('NEW') : undefined} />
      <Card className="overflow-hidden">
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle>Suspicious activity alerts</CardTitle>
            <CardDescription>
              Days that looked unlike a user's usual activity. For review only.
            </CardDescription>
          </div>
          <div className="w-full sm:w-44">
            <SimpleSelect value={status} onValueChange={setStatus} options={FILTER_OPTIONS} />
          </div>
        </CardHeader>
        <DataState
          isLoading={listQ.isLoading}
          isError={listQ.isError}
          isEmpty={alerts.length === 0}
          onRetry={() => listQ.refetch()}
          skeleton={<ListSkeleton rows={3} />}
          empty={<EmptyState icon={Siren} title="No alerts" description="No suspicious activity matches this filter." />}
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-y border-border bg-surface-2">
                <tr>
                  <th className={tableHeadClass()}>Status</th>
                  <th className={tableHeadClass()}>User</th>
                  <th className={tableHeadClass()}>Day</th>
                  <th className={tableHeadClass()}>Reason</th>
                  <th className={tableHeadClass('w-56')}>Review</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {alerts.map((a) => (
                  <tr key={a.id} className="align-top">
                    <td className="px-4 py-3"><Badge variant={statusVariant(a.status)} dot={a.status === 'NEW'}>{a.status}</Badge></td>
                    <td className="px-4 py-3">
                      <div className="font-medium">{a.full_name || a.username}</div>
                      <div className="text-xs text-subtle-foreground">{a.username} · {a.role.toLowerCase()}</div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 tabular-nums text-muted-foreground">{formatDate(a.day)}</td>
                    <td className="max-w-md px-4 py-3">
                      <ul className="space-y-1 text-muted-foreground">
                        {a.reason.split('; ').map((r) => <li key={r}>{r}</li>)}
                      </ul>
                    </td>
                    <td className="px-4 py-3"><ReviewButtons alert={a} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DataState>
      </Card>
    </div>
  )
}
