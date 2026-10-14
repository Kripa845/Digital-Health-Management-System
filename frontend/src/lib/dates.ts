/**
 * Calendar dates as plain "YYYY-MM-DD" strings.
 *
 * Appointment dates are Asia/Kathmandu calendar days chosen by the server. They
 * never go through `toISOString()` (UTC), which moves the day for anyone whose
 * clock is not on UTC; arithmetic is done on UTC midnights so the browser's
 * own time zone cannot shift a day either.
 */

export const CLINIC_TIME_ZONE = 'Asia/Kathmandu'

const pad = (n: number) => String(n).padStart(2, '0')

function toUTC(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d))
}

function fromUTC(date: Date): string {
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`
}

export function isISODate(value: unknown): value is string {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
}

/** Today's date in Kathmandu, whatever the browser's time zone. */
export function todayInClinic(now: Date = new Date()): string {
  // en-CA formats as YYYY-MM-DD.
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: CLINIC_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(now)
}

export function addDays(iso: string, days: number): string {
  const d = toUTC(iso)
  d.setUTCDate(d.getUTCDate() + days)
  return fromUTC(d)
}

/** "YYYY-MM" of a date. */
export function monthOf(iso: string): string {
  return iso.slice(0, 7)
}

export function addMonths(month: string, months: number): string {
  const d = toUTC(`${month}-01`)
  d.setUTCMonth(d.getUTCMonth() + months)
  return fromUTC(d).slice(0, 7)
}

/** The cells of a month grid starting on Sunday: null for the leading blanks. */
export function monthGrid(month: string): (string | null)[] {
  const first = toUTC(`${month}-01`)
  const days = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate()
  const cells: (string | null)[] = Array(first.getUTCDay()).fill(null)
  for (let day = 1; day <= days; day++) cells.push(`${month}-${pad(day)}`)
  return cells
}

/** Format a "YYYY-MM-DD" calendar date without shifting it to another day. */
export function formatISODate(iso: string, opts: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'short', day: 'numeric' }) {
  return toUTC(iso).toLocaleDateString(undefined, { ...opts, timeZone: 'UTC' })
}

export function formatMonth(month: string) {
  return formatISODate(`${month}-01`, { month: 'long', year: 'numeric' })
}
