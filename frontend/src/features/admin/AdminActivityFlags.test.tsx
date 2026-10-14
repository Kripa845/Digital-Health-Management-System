import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { API, server } from '@/test/server'
import { renderPage } from '@/test/render'
import type { ActivityFlag } from '@/lib/types'
import { AdminActivityFlags } from './AdminActivityFlags'

const flag: ActivityFlag = {
  id: 1, user: 7, username: 'pat7', full_name: 'Pat Seven', role: 'PATIENT',
  window_start: '2026-09-01T00:00:00Z', window_end: '2026-10-01T00:00:00Z',
  features: { failed_logins: 12 },
  reasons: [{
    metric: 'failed_logins',
    text: '12 failed login attempts. Most patients had none.',
    detail: 'failed_logins = 12, role median 0, robust z +5.6',
  }],
  severity: 'MEDIUM', eps: 1, status: 'NEW', reviewed_by: null, reviewed_by_username: null, note: '',
  created_at: '2026-10-01T00:00:00Z',
}

describe('AdminActivityFlags', () => {
  it('shows plain reasons with the technical detail on hover, and a severity badge', async () => {
    server.use(http.get(`${API}/activity-flags/`, () => HttpResponse.json([flag])))
    renderPage(<AdminActivityFlags />)

    const reason = await screen.findByText('12 failed login attempts. Most patients had none.')
    expect(screen.queryByText(/robust z/)).not.toBeInTheDocument()
    expect(screen.getByText('Medium')).toBeInTheDocument()
    expect(screen.getByText('NEW')).toBeInTheDocument()

    await userEvent.hover(reason)
    expect((await screen.findAllByText('failed_logins = 12, role median 0, robust z +5.6')).length).toBeGreaterThan(0)
  })
})
