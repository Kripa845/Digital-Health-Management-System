import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { addDays, addMonths, formatISODate, formatMonth, monthGrid, monthOf } from '@/lib/dates'
import { cn } from '@/lib/utils'

const WEEKDAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']

/**
 * A month calendar in which only `available` dates ("YYYY-MM-DD") can be
 * picked. Navigation is limited to the months between `today` and
 * `today + days - 1`.
 */
export function AvailableDatePicker({
  today, days, available, value, onChange, id,
}: {
  today: string
  days: number
  available: string[]
  value: string
  onChange: (date: string) => void
  id?: string
}) {
  const last = addDays(today, days - 1)
  const firstMonth = monthOf(today)
  const lastMonth = monthOf(last)
  const [month, setMonth] = useState(() => monthOf(value || available[0] || today))
  const open = useMemo(() => new Set(available), [available])

  // Follow the first available date when the doctor (and so the list) changes.
  useEffect(() => {
    if (!value) setMonth(monthOf(available[0] || today))
  }, [available, today, value])

  return (
    <div id={id} className="rounded-[var(--radius-md)] border border-border p-3">
      <div className="mb-2 flex items-center justify-between">
        <Button
          type="button" variant="ghost" size="icon-sm" aria-label="Previous month"
          disabled={month <= firstMonth} onClick={() => setMonth(addMonths(month, -1))}
        >
          <ChevronLeft />
        </Button>
        <p className="text-sm font-semibold" aria-live="polite">{formatMonth(month)}</p>
        <Button
          type="button" variant="ghost" size="icon-sm" aria-label="Next month"
          disabled={month >= lastMonth} onClick={() => setMonth(addMonths(month, 1))}
        >
          <ChevronRight />
        </Button>
      </div>
      <div className="grid grid-cols-7 gap-1 text-center text-xs" role="group" aria-label={`Dates in ${formatMonth(month)}`}>
        {WEEKDAYS.map((d) => <span key={d} className="py-1 font-medium text-muted-foreground" aria-hidden>{d}</span>)}
        {monthGrid(month).map((date, i) => {
          if (!date) return <span key={`blank-${i}`} />
          const enabled = open.has(date)
          const selected = date === value
          return (
            <button
              key={date}
              type="button"
              disabled={!enabled}
              aria-pressed={selected}
              aria-label={formatISODate(date, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
                + (enabled ? '' : ', unavailable')}
              onClick={() => onChange(date)}
              className={cn(
                'h-9 rounded-[var(--radius-sm)] text-sm transition-colors',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60',
                enabled ? 'cursor-pointer font-semibold hover:bg-primary-soft' : 'cursor-not-allowed text-muted-foreground/50',
                selected && 'bg-primary text-primary-foreground hover:bg-primary',
                date === today && !selected && 'ring-1 ring-border-strong',
              )}
            >
              {Number(date.slice(8))}
            </button>
          )
        })}
      </div>
    </div>
  )
}
