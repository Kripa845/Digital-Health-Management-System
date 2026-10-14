import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { API, server } from '@/test/server'
import { renderPage } from '@/test/render'
import type { ActivityAnalysis, ActivityAnalysisUser } from '@/lib/types'
import { AdminActivityAnalysis } from './AdminActivityAnalysis'
import {
  activityTotals, beyondEps, featureSpread, isLowActivity, kdistPoints, plainReason, quantile, reasonCounts, sortUsers,
  compareToTypical, times, topFeature, unusualUsers, zBars, zDomain,
} from './activity-analysis-utils'

const FEATURES = [
  'total_actions', 'distinct_patients', 'failed_logins', 'off_hours_actions',
  'active_days', 'access_requests', 'access_denied',
]
const zero = () => Object.fromEntries(FEATURES.map((f) => [f, 0]))

function user(id: number, kind: ActivityAnalysisUser['kind'], patients: number, z: number, kdist: number): ActivityAnalysisUser {
  return {
    user_id: id, username: `doc${id}`,
    raw: { ...zero(), total_actions: 40, distinct_patients: patients, active_days: 20 },
    log: { ...zero(), distinct_patients: Math.log1p(patients) },
    scaled: { ...zero(), distinct_patients: z / 4 },
    z: { ...zero(), distinct_patients: z },
    cluster: kind === 'noise' ? -1 : 0, kind, kdist, x: id, y: 0,
    reasons: kind === 'noise'
      ? [{ feature: 'distinct_patients', value: patients, median: 6, z, text: `distinct_patients = ${patients} is far above the role median of 6 (robust z +${z})` }]
      : [],
  }
}

const users = [
  ...Array.from({ length: 11 }, (_, i) => user(i + 1, i < 9 ? 'core' : 'border', 6, 0, 0.5 + i / 20)),
  user(99, 'noise', 60, 16.2, 3.4),
]

const analysis: ActivityAnalysis = {
  role: 'DOCTOR', demo: false, auto: true, days: 30, window_start: '2026-09-06T00:00:00+05:45', window_end: '2026-10-06T00:00:00+05:45',
  n_users: 12, min_users: 10, eps: 1, min_samples: 5, k: 4, features: FEATURES, skipped: false, message: '',
  scaling: Object.fromEntries(FEATURES.map((f) => [f, { mean: 1, sd: 0.5 }])),
  kdist_sorted: users.map((u) => u.kdist!).sort((a, b) => a - b), suggested_eps: 1.1,
  suggested: { min_samples: 4, eps: 2.3 },
  explained_variance: [0.6, 0.2], n_clusters: 1, counts: { core: 9, border: 2, noise: 1 }, users,
}

/** An outlier with almost no activity: never shown as unusual. */
const quietOutlier: ActivityAnalysisUser = {
  ...user(98, 'noise', 1, 4, 3),
  raw: { ...zero(), total_actions: 1, distinct_patients: 1, failed_logins: 1, active_days: 1 },
}

const tooFew: ActivityAnalysis = {
  ...analysis, n_users: 3, min_users: 6, skipped: true, n_clusters: 0, counts: { core: 0, border: 0, noise: 0 },
  users: users.slice(0, 3).map((u) => ({ ...u, kind: null, cluster: null, reasons: [] })),
}

describe('activity analysis helpers', () => {
  it('puts outliers first and finds the most unusual feature', () => {
    expect(sortUsers(users)[0].user_id).toBe(99)
    expect(sortUsers(users).at(-1)!.kind).toBe('core')
    expect(topFeature(users.at(-1)!, FEATURES)).toBe('distinct_patients')
  })

  it('builds z bars with a symmetric domain that always shows the threshold', () => {
    const bars = zBars(users.at(-1)!, FEATURES)
    expect(bars.find((b) => b.feature === 'distinct_patients')).toMatchObject({ z: 16.2, out: true, value: 60 })
    expect(bars.filter((b) => b.out)).toHaveLength(1)
    expect(zDomain(users.at(-1)!, FEATURES)).toEqual([-17, 17])
    expect(zDomain(users[0], FEATURES)).toEqual([-5, 5])
  })

  it('counts users beyond eps on the k-distance curve', () => {
    expect(kdistPoints(analysis)[0]).toEqual({ rank: 1, distance: 0.5 })
    expect(beyondEps(analysis)).toBe(1)
  })

  it('writes reasons in plain language', () => {
    const [reason] = users.at(-1)!.reasons
    expect(plainReason(reason, 'DOCTOR', 30)).toBe('Opened 60 patient records in 30 days; other doctors opened about 6.')
    expect(plainReason({ ...reason, feature: 'failed_logins', value: 14, median: 0 }, 'PATIENT', 7))
      .toBe('Had 14 failed sign-in attempts in 7 days; most other patients had none.')
  })

  it('leaves very quiet outliers out of the unusual users', () => {
    expect(isLowActivity(quietOutlier)).toBe(true)
    // Failed sign-ins count as activity, so a password-guessing burst is still shown.
    expect(isLowActivity({ ...quietOutlier, raw: { ...quietOutlier.raw, failed_logins: 20 } })).toBe(false)
    expect(unusualUsers({ ...analysis, users: [...users, quietOutlier] }).map((u) => u.user_id)).toEqual([99])
  })
})

describe('analysis summary helpers', () => {
  it('interpolates quantiles', () => {
    expect(quantile([], 0.5)).toBe(0)
    expect(quantile([4, 1, 3, 2], 0.5)).toBe(2.5)
    expect(quantile([1, 2, 3, 4, 5], 0.9)).toBeCloseTo(4.6)
  })

  it('totals the role and leaves rates empty when there is nothing to divide by', () => {
    const t = activityTotals(analysis)
    expect(t).toMatchObject({ actions: 480, medianActions: 40, medianActiveDays: 20, failedLogins: 0, usersWithFailedLogins: 0 })
    expect(t.offHoursShare).toBe(0)
    expect(t.deniedShare).toBeNull()
  })

  it('compares unusual users with the typical value of each feature', () => {
    const unusual = unusualUsers(analysis)
    const patients = featureSpread(analysis, unusual).find((s) => s.feature === 'distinct_patients')!
    expect(patients).toMatchObject({ median: 6, max: 60, unusualMedian: 60, ratio: 10 })
    expect(featureSpread(analysis, []).every((s) => s.unusualMedian === null && s.ratio === null)).toBe(true)
    expect(reasonCounts(analysis, unusual)).toEqual([{ feature: 'distinct_patients', label: 'Patients opened', count: 1 }])
    expect([times(10), times(2.46), times(1)]).toEqual(['10×', '2.5×', '1×'])
    expect([compareToTypical(60, 6), compareToTypical(2, 8), compareToTypical(3, 3), compareToTypical(2, 0), compareToTypical(null, 3)])
      .toEqual(['10× more', '4× less', 'About the same', 'More (most had none)', '—'])
  })
})

describe('AdminActivityAnalysis page', () => {
  /** Answer each preview with respond(query); record the previews and the last save. */
  function serve(respond: (q: Record<string, string>) => ActivityAnalysis = () => analysis) {
    let saved: unknown = null
    const requested: Record<string, string>[] = []
    server.use(
      http.get(`${API}/activity-settings/`, () =>
        HttpResponse.json({ activity_window_days: 30, dbscan_eps: 1, dbscan_min_samples: 5, updated_at: '' })),
      http.get(`${API}/activity-analysis/`, ({ request }) => {
        const q = Object.fromEntries(new URL(request.url).searchParams)
        requested.push(q)
        return HttpResponse.json(respond(q))
      }),
      http.post(`${API}/activity-analysis/`, async ({ request }) => {
        saved = await request.json()
        return HttpResponse.json({ role: 'DOCTOR', n_users: 12, flagged: 1, created: 1, updated: 0 })
      }),
    )
    return Object.assign(() => saved, { requested })
  }

  it('runs automatically and explains the result in plain language', async () => {
    const saved = serve()
    renderPage(<AdminActivityAnalysis />)
    expect(await screen.findByText('1 of 12 doctors has unusual activity.')).toBeInTheDocument()
    expect(saved.requested[0]).toMatchObject({ role: 'DOCTOR', days: '30', auto: 'true', demo: 'false' })
    expect(saved.requested[0]).not.toHaveProperty('eps')
    expect(screen.getByText('Unusual users')).toBeInTheDocument()
    expect(screen.getByText('Opened 60 patient records in 30 days; other doctors opened about 6.')).toBeInTheDocument()
    expect(screen.getByText(/for review only. No account is blocked/)).toBeInTheDocument()
    for (const word of [/DBSCAN/, /\beps\b/, /min_samples/, /PCA/, /z-score/]) expect(screen.queryByText(word)).toBeNull()
    expect(screen.queryByLabelText('eps')).toBeNull()                       // advanced settings start closed
  })

  it('summarises the run with calculated numbers', async () => {
    serve()
    renderPage(<AdminActivityAnalysis />)
    expect(await screen.findByText('Summary of the results')).toBeInTheDocument()
    expect(screen.getByText('1 to review, 0 had too little activity to judge')).toBeInTheDocument()
    expect(screen.getByText('11 of 12 people behave like others in a group')).toBeInTheDocument()
    expect(screen.getByText('Actions by a typical doctor')).toBeInTheDocument()
    expect(screen.getByText('480')).toBeInTheDocument()
    expect(screen.getByText('Why people stood out')).toBeInTheDocument()
    expect(screen.getByText('10× more')).toBeInTheDocument()
    for (const word of [/median/i, /outlier/i, /cluster/i, /eps/]) expect(screen.queryByText(word)).toBeNull()
  })

  it('sends one user for review with the parameters used', async () => {
    const saved = serve()
    const ue = userEvent.setup()
    renderPage(<AdminActivityAnalysis />)
    await ue.click(await screen.findByRole('button', { name: /^Send for review/ }))
    await waitFor(() => expect(saved()).toEqual({ role: 'DOCTOR', days: 30, eps: 1, min_samples: 5, user_ids: [99] }))
    expect(await screen.findByRole('button', { name: /Sent for review/ })).toBeDisabled()
  })

  it('shows the technical details once "how the results were worked out" is opened', async () => {
    serve()
    const ue = userEvent.setup()
    renderPage(<AdminActivityAnalysis />)
    await screen.findByText('Unusual users')
    expect(screen.queryByText('Everyone checked')).toBeNull()
    await ue.click(screen.getByRole('button', { name: /How the results were worked out/ }))
    expect(screen.queryByText('Step by step')).toBeNull()
    expect(screen.getByText('Everyone checked')).toBeInTheDocument()
  })

  it('uses typed eps and min_samples only after they are edited', async () => {
    const saved = serve()
    const ue = userEvent.setup()
    renderPage(<AdminActivityAnalysis />)
    await screen.findByText('Unusual users')
    await ue.click(screen.getByRole('button', { name: /Advanced settings/ }))
    expect(await screen.findByDisplayValue('1')).toBe(screen.getByLabelText('eps'))   // from Admin Settings
    const eps = screen.getByLabelText('eps')
    await ue.clear(eps)
    await ue.type(eps, '2')
    expect(screen.getByText(/Press Analyse to update/)).toBeInTheDocument()
    await ue.click(screen.getByRole('button', { name: /Analyse/ }))
    await waitFor(() => expect(saved.requested.at(-1)).toMatchObject({ auto: 'false', eps: '2', min_samples: '5' }))
    await ue.click(screen.getByRole('switch'))
    await waitFor(() => expect(saved.requested.at(-1)).toMatchObject({ demo: 'true', eps: '2' }))
  })

  it('offers a longer period when too few users were active', async () => {
    const saved = serve((q) => (q.days === '90' ? analysis : tooFew))
    const ue = userEvent.setup()
    renderPage(<AdminActivityAnalysis />)
    expect(await screen.findByText(
      'Only 3 doctors were active in the last 30 days. We need at least 6 to compare fairly.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /How the results were worked out/ })).toBeNull()
    expect(screen.queryByText(/Not run/)).toBeNull()
    await ue.click(screen.getByRole('button', { name: 'Try last 90 days' }))
    expect(await screen.findByText('1 of 12 doctors has unusual activity.')).toBeInTheDocument()
    expect(saved.requested.at(-1)).toMatchObject({ days: '90', auto: 'true' })
  })

  it('says there is not enough activity yet when even 90 days is too few', async () => {
    serve(() => tooFew)
    renderPage(<AdminActivityAnalysis />)
    expect(await screen.findByText('Not enough activity yet')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Try last 90 days/ })).toBeNull()
    expect(screen.queryByText(/No account is blocked/)).toBeNull()
  })

  it('shows a green banner when the only outlier has very little activity', async () => {
    serve(() => ({ ...analysis, users: [...users.slice(0, 11), quietOutlier] }))
    renderPage(<AdminActivityAnalysis />)
    expect(await screen.findByText('No unusual activity found among 12 doctors.')).toBeInTheDocument()
    expect(screen.getByText('1 person with very little activity was left out.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Send for review/ })).toBeNull()
  })
})
