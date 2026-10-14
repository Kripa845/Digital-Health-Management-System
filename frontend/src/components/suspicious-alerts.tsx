import { useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { suspiciousAlertService } from '@/lib/api'
import { formatDate } from '@/lib/utils'

export const SUSPICIOUS_ALERTS_PATH = '/admin/suspicious-alerts'
const POLL_MS = 30_000

/** NEW suspicious alerts (DBSCAN or the failed-login rule), polled. Same key as the alerts page's "New" filter. */
export function useNewSuspiciousAlerts(enabled = true) {
  return useQuery({
    queryKey: ['admin', 'suspicious-alerts', 'NEW'],
    queryFn: () => suspiciousAlertService.list({ status: 'NEW' }),
    refetchInterval: POLL_MS,
    retry: false,
    enabled,
  })
}

// Module level so a remounted shell doesn't toast the same alerts again.
let seen: Set<number> | null = null

/** Mounted once in the admin shell: toasts on any admin page when suspicious activity is detected. */
export function SuspiciousAlertWatcher() {
  const { data } = useNewSuspiciousAlerts()
  const navigate = useNavigate()
  const qc = useQueryClient()

  useEffect(() => {
    if (!data) return
    const view = { label: 'View', onClick: () => navigate(SUSPICIOUS_ALERTS_PATH) }
    if (seen === null) {
      // First load after login: one summary toast rather than one per alert.
      if (data.length > 0) {
        toast.warning(`${data.length} suspicious activity alert${data.length === 1 ? '' : 's'} awaiting review.`,
          { action: view, duration: 10_000 })
      }
    } else {
      const fresh = data.filter((a) => !seen!.has(a.id))
      if (fresh.length > 0) {
        const a = fresh[0]
        toast.error(fresh.length === 1
          ? `Suspicious activity: ${a.full_name || a.username} on ${formatDate(a.day)}`
          : `${fresh.length} new suspicious activity alerts`,
        { description: fresh.length === 1 ? a.reason : undefined, action: view, duration: 15_000 })
        qc.invalidateQueries({ queryKey: ['notifications'] })     // the bell has a matching notification
        qc.invalidateQueries({ queryKey: ['admin', 'activity-analysis'] })   // its Suspicious alerts section
      }
    }
    seen = new Set(data.map((a) => a.id))
  }, [data, navigate, qc])

  return null
}

export function NewAlertsBanner({ count, onShow, showLink }: { count: number; onShow?: () => void; showLink?: boolean }) {
  if (count === 0) return null
  return (
    <div role="alert" className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-danger/30 bg-danger-soft/40 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden="true" />
        <div className="space-y-0.5 text-sm">
          <p className="font-semibold text-danger">
            {count} new suspicious activity alert{count === 1 ? '' : 's'}
          </p>
          <p className="text-muted-foreground">Activity unlike a user's normal days, or repeated failed logins. Review them on Suspicious Alerts.</p>
        </div>
      </div>
      {onShow && <Button size="sm" variant="secondary" onClick={onShow}>Show new alerts</Button>}
      {showLink && <Button asChild size="sm" variant="secondary"><Link to={SUSPICIOUS_ALERTS_PATH}>Review alerts</Link></Button>}
    </div>
  )
}
