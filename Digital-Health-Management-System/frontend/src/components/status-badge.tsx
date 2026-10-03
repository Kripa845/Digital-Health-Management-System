import { Badge, type BadgeProps } from '@/components/ui/badge'
import { CheckCircle2, Clock, XCircle, Ban, CircleCheck, CircleDot } from 'lucide-react'
import type { AppointmentStatus, ActiveStatus } from '@/lib/types'

const APPT: Record<AppointmentStatus, { variant: BadgeProps['variant']; label: string; Icon: typeof Clock }> = {
  PENDING: { variant: 'warning', label: 'Pending', Icon: Clock },
  ACCEPTED: { variant: 'info', label: 'Accepted', Icon: CircleCheck },
  COMPLETED: { variant: 'success', label: 'Completed', Icon: CheckCircle2 },
  DECLINED: { variant: 'danger', label: 'Declined', Icon: XCircle },
  CANCELLED: { variant: 'neutral', label: 'Cancelled', Icon: Ban },
}

export function AppointmentStatusBadge({ status }: { status: AppointmentStatus }) {
  const c = APPT[status] ?? APPT.PENDING
  return <Badge variant={c.variant}><c.Icon />{c.label}</Badge>
}

export function ActiveStatusBadge({ status }: { status: ActiveStatus }) {
  return status === 'Active'
    ? <Badge variant="success"><CircleDot />Active</Badge>
    : <Badge variant="neutral"><CircleDot />Inactive</Badge>
}

const ACCESS: Record<string, BadgeProps['variant']> = {
  PENDING: 'warning', APPROVED: 'success', DECLINED: 'danger',
}
export function AccessStatusBadge({ status }: { status: string }) {
  return <Badge variant={ACCESS[status] ?? 'neutral'}>{status[0] + status.slice(1).toLowerCase()}</Badge>
}
