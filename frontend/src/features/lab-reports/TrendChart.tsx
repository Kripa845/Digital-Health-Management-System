import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatDate } from '@/lib/utils'
import type { DashboardTest } from '@/lib/types'

/** Small line chart of a test's history. Needs at least two points to draw. */
export function TrendChart({ test }: { test: DashboardTest }) {
  const points = test.history
  if (points.length < 2) {
    return <p className="text-[11px] text-muted-foreground">Trend appears after two reports.</p>
  }
  const first = points[0]
  const last = points[points.length - 1]
  const summary = `${test.label} trend: ${first.value} ${test.unit} on ${formatDate(first.date)} to ${last.value} ${test.unit} on ${formatDate(last.date)}`
  return (
    <figure className="h-20 w-full" role="img" aria-label={summary}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 6, right: 6, bottom: 0, left: 0 }}>
          <XAxis dataKey="date" hide />
          <YAxis hide domain={['auto', 'auto']} />
          <Tooltip
            formatter={(v: number) => [`${v} ${test.unit}`, test.label]}
            labelFormatter={(d: string) => formatDate(d)}
            contentStyle={{ fontSize: 12, background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
          />
          <Line type="monotone" dataKey="value" stroke="var(--color-primary)" strokeWidth={2}
            dot={{ r: 2.5 }} activeDot={{ r: 4 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </figure>
  )
}
