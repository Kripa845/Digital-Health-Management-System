import type { ActivityAnalysis, ActivityAnalysisUser, ActivityFlagReason, ActivityPointKind } from '@/lib/types'

/** Same threshold the backend uses to name a feature as a reason. */
export const Z_THRESHOLD = 3.5

export const FEATURE_LABELS: Record<string, string> = {
  total_actions: 'Actions',
  distinct_patients: 'Patients opened',
  failed_logins: 'Wrong-password sign-ins',
  off_hours_actions: 'Late-night actions',
  active_days: 'Days active',
  access_requests: 'Record requests',
  access_denied: 'Requests declined',
}

export const featureLabel = (f: string) => FEATURE_LABELS[f] ?? f

export const KIND_LABELS: Record<ActivityPointKind, string> = {
  core: 'Typical',
  border: 'Close to typical',
  noise: 'Stands out',
}

export function kindLabel(kind: ActivityPointKind | null) {
  return kind ? KIND_LABELS[kind] : 'Not checked'
}

const KIND_ORDER: Record<string, number> = { noise: 0, border: 1, core: 2 }

/** Outliers first, then border, then core points; within a group the most isolated (largest k-distance) first. */
export function sortUsers(users: ActivityAnalysisUser[]): ActivityAnalysisUser[] {
  return [...users].sort((a, b) =>
    (KIND_ORDER[a.kind ?? 'core'] - KIND_ORDER[b.kind ?? 'core']) || ((b.kdist ?? 0) - (a.kdist ?? 0)))
}

/** The feature that sets this user apart most (largest |robust z|). */
export function topFeature(user: ActivityAnalysisUser, features: string[]): string {
  return features.reduce((best, f) => (Math.abs(user.z[f]) > Math.abs(user.z[best]) ? f : best), features[0])
}

/** Rows for the robust-z bar chart of one user, in feature order. */
export function zBars(user: ActivityAnalysisUser, features: string[]) {
  return features.map((f) => ({
    feature: f,
    label: featureLabel(f),
    z: user.z[f],
    value: user.raw[f],
    out: Math.abs(user.z[f]) >= Z_THRESHOLD,
  }))
}

/** Symmetric axis limit for z bars so 0 sits in the middle and the threshold lines always show. */
export function zDomain(user: ActivityAnalysisUser, features: string[]): [number, number] {
  const max = Math.max(Z_THRESHOLD + 1, ...features.map((f) => Math.abs(user.z[f])))
  const lim = Math.ceil(max)
  return [-lim, lim]
}

/** Points on the sorted k-distance curve, 1-based rank on x. */
export function kdistPoints(a: ActivityAnalysis) {
  return a.kdist_sorted.map((d, i) => ({ rank: i + 1, distance: d }))
}

/** How many users have their k-th neighbour beyond eps (cannot be core points). */
export function beyondEps(a: ActivityAnalysis) {
  return a.kdist_sorted.filter((d) => d > a.eps).length
}

export const pct = (x: number) => `${Math.round(100 * x)}%`
export const signed = (x: number, digits = 2) => `${x >= 0 ? '+' : '−'}${Math.abs(x).toFixed(digits)}`

// ── Plain-language view ───────────────────────────────────────────────

/**
 * Users this quiet are never shown as unusual: a handful of actions makes almost
 * anyone look different. A user is "low activity" when below BOTH limits
 * (failed sign-ins count as actions, so a password-guessing burst is still shown).
 * They stay in the technical table.
 */
export const MIN_ACTIVITY = { actions: 3, accessRequests: 3 }

export function isLowActivity(u: ActivityAnalysisUser) {
  return u.raw.total_actions + u.raw.failed_logins < MIN_ACTIVITY.actions
    && u.raw.access_requests < MIN_ACTIVITY.accessRequests
}

/** Outliers worth an admin's attention: DBSCAN noise points that are not low activity, most isolated first. */
export function unusualUsers(a: ActivityAnalysis) {
  return sortUsers(a.users).filter((u) => u.kind === 'noise' && !isLowActivity(u))
}

const ROLE_NOUNS: Record<ActivityAnalysis['role'], [string, string]> = {
  DOCTOR: ['doctor', 'doctors'],
  PATIENT: ['patient', 'patients'],
  ADMIN: ['administrator', 'administrators'],
}

/** "1 doctor", "12 doctors"; without n, just the plural noun. */
export function roleNoun(role: ActivityAnalysis['role'], n?: number) {
  const [one, many] = ROLE_NOUNS[role]
  return n == null ? many : `${n} ${n === 1 ? one : many}`
}

const plural = (n: number, word: string, words = `${word}s`) => `${n} ${n === 1 ? word : words}`

/** What this user did, and what the others typically did, for one feature. */
const PLAIN: Record<string, { did: (n: number, days: number) => string; others: (m: number) => string }> = {
  total_actions: { did: (n, d) => `did ${plural(n, 'action')} in ${d} days`, others: (m) => `did about ${m}` },
  distinct_patients: {
    did: (n, d) => `opened ${plural(n, 'patient record')} in ${d} days`, others: (m) => `opened about ${m}`,
  },
  failed_logins: {
    did: (n, d) => `had ${plural(n, 'failed sign-in attempt')} in ${d} days`, others: (m) => `had about ${m}`,
  },
  off_hours_actions: {
    did: (n, d) => `did ${plural(n, 'action')} late at night (10 pm – 6 am) in ${d} days`, others: (m) => `did about ${m}`,
  },
  active_days: {
    did: (n, d) => `was active on ${n} of the last ${d} days`, others: (m) => `were active on about ${m}`,
  },
  access_requests: {
    did: (n, d) => `asked for access to patient records ${plural(n, 'time')} in ${d} days`,
    others: (m) => `asked about ${plural(m, 'time')}`,
  },
  access_denied: {
    did: (n, d) => `had ${plural(n, 'access request')} declined in ${d} days`, others: (m) => `had about ${m}`,
  },
}

/** "Opened 95 patient records in 30 days; other doctors opened about 9." */
export function plainReason(r: ActivityFlagReason, role: ActivityAnalysis['role'], days: number) {
  const p = PLAIN[r.feature]
  if (!p) return r.text
  const median = Math.round(r.median)
  const others = median === 0 ? `most other ${roleNoun(role)} had none` : `other ${roleNoun(role)} ${p.others(median)}`
  const did = p.did(r.value, days)
  return `${did[0].toUpperCase()}${did.slice(1)}; ${others}.`
}

// ── Summary of the run ────────────────────────────────────────────────

/** Value at quantile q (0–1) by linear interpolation; 0 for an empty list. */
export function quantile(values: number[], q: number) {
  if (values.length === 0) return 0
  const s = [...values].sort((a, b) => a - b)
  const pos = (s.length - 1) * q
  const lo = Math.floor(pos)
  const hi = Math.ceil(pos)
  return s[lo] + (s[hi] - s[lo]) * (pos - lo)
}

const sum = (users: ActivityAnalysisUser[], f: string) => users.reduce((t, u) => t + (u.raw[f] ?? 0), 0)

/** share of part in whole, or null when whole is 0 (nothing to compare). */
const share = (part: number, whole: number) => (whole > 0 ? part / whole : null)

/** Role-wide totals and rates computed from every user's raw counts. */
export function activityTotals(a: ActivityAnalysis) {
  const u = a.users
  const actions = sum(u, 'total_actions')
  const requests = sum(u, 'access_requests')
  return {
    actions,
    offHoursShare: share(sum(u, 'off_hours_actions'), actions),
    requests,
    deniedShare: share(sum(u, 'access_denied'), requests),
    failedLogins: sum(u, 'failed_logins'),
    usersWithFailedLogins: u.filter((x) => x.raw.failed_logins > 0).length,
    medianActions: quantile(u.map((x) => x.raw.total_actions), 0.5),
    medianActiveDays: quantile(u.map((x) => x.raw.active_days), 0.5),
  }
}

/** Per feature: how the whole role is spread, and the median of the unusual users (null when there are none). */
export function featureSpread(a: ActivityAnalysis, unusual: ActivityAnalysisUser[]) {
  return a.features.map((f) => {
    const all = a.users.map((u) => u.raw[f])
    const typical = quantile(all, 0.5)
    const unusualMedian = unusual.length ? quantile(unusual.map((u) => u.raw[f]), 0.5) : null
    return {
      feature: f,
      label: featureLabel(f),
      median: typical,
      p90: quantile(all, 0.9),
      max: Math.max(0, ...all),
      unusualMedian,
      /** How many times the typical value; null when the typical value is 0. */
      ratio: unusualMedian != null && typical > 0 ? unusualMedian / typical : null,
    }
  })
}

/** How many of the given users have each feature named as a reason, most common first; features never named are left out. */
export function reasonCounts(a: ActivityAnalysis, users: ActivityAnalysisUser[]) {
  return a.features
    .map((f) => ({ feature: f, label: featureLabel(f), count: users.filter((u) => u.reasons.some((r) => r.feature === f)).length }))
    .filter((r) => r.count > 0)
    .sort((x, y) => y.count - x.count)
}

/** 1.0 → "1×", 12.34 → "12×", 2.46 → "2.5×". */
export const times = (x: number) => `${x >= 10 ? Math.round(x) : Number(x.toFixed(1))}×`

/** "10× more", "2× less", "About the same", from the unusual value and the typical value. */
export function compareToTypical(unusual: number | null, typical: number) {
  if (unusual == null) return '—'
  if (typical === 0) return unusual > 0 ? 'More (most had none)' : 'Same'
  const r = unusual / typical
  if (r >= 1.1) return `${times(r)} more`
  if (r <= 0.9) return unusual === 0 ? 'None' : `${times(1 / r)} less`
  return 'About the same'
}

/** Counts keep up to one decimal (medians can fall between two users). */
export const num = (x: number) => (Number.isInteger(x) ? String(x) : x.toFixed(1))
