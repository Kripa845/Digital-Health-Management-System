import { describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { API, server } from '@/test/server'
import { renderPage } from '@/test/render'
import { dashboard } from '@/test/fixtures'
import { HealthVitalsCard } from './HealthVitalsCard'

describe('HealthVitalsCard (dashboard)', () => {
  it('shows age, blood group and each card with value, date, status and trend', async () => {
    server.use(http.get(`${API}/dashboard/`, () => HttpResponse.json(dashboard())))
    renderPage(<HealthVitalsCard />)

    expect(await screen.findByText('34 yrs')).toBeInTheDocument()
    expect(screen.getByText('O+')).toBeInTheDocument()

    const hb = screen.getByRole('region', { name: 'Haemoglobin' })
    expect(within(hb).getByText('11.20')).toBeInTheDocument()
    expect(within(hb).getByText('Low')).toBeInTheDocument()
    expect(within(hb).getByText(/14 Sep 2026|Sep 14, 2026|2026/)).toBeInTheDocument()
    expect(within(hb).getByRole('img', { name: /Haemoglobin trend/ })).toBeInTheDocument()

    const chol = screen.getByRole('region', { name: 'Total Cholesterol' })
    expect(within(chol).getByText('High')).toBeInTheDocument()

    const sugar = screen.getByRole('region', { name: 'Blood Sugar (Random)' })
    expect(within(sugar).getByText(/Not recorded yet/)).toBeInTheDocument()

    expect(screen.getByText('Informational only, not medical advice.')).toBeInTheDocument()
  })

  it('shows an empty state when there are no results yet', async () => {
    const empty = dashboard()
    empty.tests = empty.tests.map((t) => ({ ...t, latest: null, status: null, history: [], trend: null }))
    server.use(http.get(`${API}/dashboard/`, () => HttpResponse.json(empty)))
    renderPage(<HealthVitalsCard />)
    expect(await screen.findByText(/No lab results yet/)).toBeInTheDocument()
  })

  it('shows a loading state, then an error with retry', async () => {
    let calls = 0
    server.use(http.get(`${API}/dashboard/`, () => {
      calls += 1
      return calls === 1 ? HttpResponse.json({ code: 'server_error', message: 'x' }, { status: 500 }) : HttpResponse.json(dashboard())
    }))
    renderPage(<HealthVitalsCard />)
    expect(screen.getByLabelText('Loading health vitals')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('34 yrs')).toBeInTheDocument()
  })
})
