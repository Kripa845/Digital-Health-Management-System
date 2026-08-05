import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ScrollText, Search } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { SimpleSelect } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { PageHeader, DataState, EmptyState, ListSkeleton } from '@/components/patterns'
import { auditService } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'
import { useDebounced, tableHeadClass } from './admin-common'

const ACTION_OPTIONS = [
  { value: 'all', label: 'All actions' },
  ...[
    'LOGIN', 'CREATE_PATIENT', 'UPDATE_PATIENT', 'DELETE_PATIENT',
    'CREATE_DOCTOR', 'UPDATE_DOCTOR', 'DELETE_DOCTOR', 'RESET_PASSWORD',
    'UPLOAD_DOCUMENT', 'DELETE_DOCUMENT', 'CREATE_ASSIGNMENT', 'DELETE_ASSIGNMENT',
  ].map((a) => ({ value: a, label: a.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()) })),
]

function actionVariant(action: string): 'danger' | 'success' | 'info' | 'neutral' {
  if (action.startsWith('DELETE')) return 'danger'
  if (action.startsWith('CREATE')) return 'success'
  if (action.startsWith('UPDATE') || action.startsWith('UPLOAD') || action.startsWith('RESET')) return 'info'
  return 'neutral'
}

export function AdminAudit() {
  const [search, setSearch] = useState('')
  const [action, setAction] = useState('all')
  const debouncedSearch = useDebounced(search)

  const params = useMemo(() => ({
    search: debouncedSearch || undefined,
    action: action !== 'all' ? action : undefined,
  }), [debouncedSearch, action])

  const listQ = useQuery({
    queryKey: ['admin', 'audit', params],
    queryFn: () => auditService.list(params),
  })
  const logs = listQ.data ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit log"
        description="An append-only record of every sensitive action across the system."
        icon={ScrollText}
      />

      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" />
          <Input
            className="pl-9"
            placeholder="Search descriptions, users, IP address…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="w-full sm:w-56">
          <SimpleSelect value={action} onValueChange={setAction} options={ACTION_OPTIONS} placeholder="All actions" />
        </div>
      </div>

      <DataState
        isLoading={listQ.isLoading}
        isError={listQ.isError}
        isEmpty={logs.length === 0}
        onRetry={() => listQ.refetch()}
        skeleton={<ListSkeleton rows={8} />}
        empty={<EmptyState icon={ScrollText} title="No audit entries" description="No activity matches the current filters." />}
      >
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-border bg-surface-2">
                <tr>
                  <th className={tableHeadClass()}>Timestamp</th>
                  <th className={tableHeadClass()}>User</th>
                  <th className={tableHeadClass()}>Action</th>
                  <th className={tableHeadClass()}>Description</th>
                  <th className={tableHeadClass()}>IP address</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {logs.map((log) => (
                  <tr key={log.id} className="transition-colors hover:bg-surface-2/60">
                    <td className="whitespace-nowrap px-4 py-3 tabular-nums text-muted-foreground">{formatDateTime(log.timestamp)}</td>
                    <td className="px-4 py-3 font-medium">{log.user_name || 'System'}</td>
                    <td className="px-4 py-3"><Badge variant={actionVariant(log.action)}>{log.action}</Badge></td>
                    <td className="max-w-md px-4 py-3 text-muted-foreground">{log.description}</td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-subtle-foreground">{log.ip_address || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </DataState>
    </div>
  )
}
