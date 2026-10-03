import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { API, server } from '@/test/server'
import { renderPage } from '@/test/render'
import { report } from '@/test/fixtures'
import type { LabReport } from '@/lib/types'
import { LabConfirmPage } from './LabConfirmPage'

function setup(data: LabReport) {
  server.use(
    http.get(`${API}/reports/${data.id}/`, () => HttpResponse.json(data)),
    http.get(`${API}/reports/${data.id}/download/`, () => new HttpResponse(new Blob(['%PDF-1.4']))),
  )
  const user = userEvent.setup()
  renderPage(<LabConfirmPage />, {
    path: '/patient/lab-reports/:id/confirm',
    route: `/patient/lab-reports/${data.id}/confirm`,
    routes: { '/patient/dashboard': <p>Dashboard page</p>, '/patient/lab-reports': <p>History page</p> },
  })
  return user
}

describe('LabConfirmPage', () => {
  it('shows extracted values beside the report, with flagged values and reasons', async () => {
    setup(report())
    expect(await screen.findByLabelText('Haemoglobin')).toHaveValue('12.8')
    expect(screen.getByLabelText('Total Cholesterol')).toHaveValue('201.08')
    expect(screen.getByText('Converted from 5.2 mmol/L')).toBeInTheDocument()
    expect(screen.getByLabelText('Blood Sugar (Random)')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getAllByText(/Outside the expected range \(20–800 mg\/dL\)/).length).toBeGreaterThan(0)
    expect(screen.getByTitle('Uploaded report')).toBeInTheDocument()
  })

  it('sends edits and accepted flags, and nothing before Confirm', async () => {
    let body: unknown = null
    server.use(http.post(`${API}/reports/42/confirm/`, async ({ request }) => {
      body = await request.json()
      return HttpResponse.json(report({ status: 'CONFIRMED' }))
    }))
    const user = setup(report())
    const hb = await screen.findByLabelText('Haemoglobin')
    expect(body).toBeNull()
    await user.clear(hb)
    await user.type(hb, '13.1')
    await user.click(screen.getByLabelText(/save it anyway/i))
    await user.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(await screen.findByText('Dashboard page')).toBeInTheDocument()
    expect(body).toEqual({ values: { hemoglobin: '13.1' }, accept_flagged: ['blood_sugar_random'], acknowledge_older_report: false })
  })

  it('shows the server’s error next to an invalid value', async () => {
    server.use(http.post(`${API}/reports/42/confirm/`, () => HttpResponse.json(
      { code: 'invalid_values', message: 'Some values need correcting.', errors: { hemoglobin: 'Enter a number.' } },
      { status: 400 },
    )))
    const user = setup(report())
    const hb = await screen.findByLabelText('Haemoglobin')
    await user.clear(hb)
    await user.type(hb, 'abc')
    await user.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(await screen.findByText('Enter a number.')).toBeInTheDocument()
  })

  it('cancel deletes the preview and returns to the history', async () => {
    server.use(http.post(`${API}/reports/42/discard/`, () => new HttpResponse(null, { status: 204 })))
    const user = setup(report())
    await screen.findByLabelText('Haemoglobin')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(await screen.findByText('History page')).toBeInTheDocument()
  })

  it('does not offer Confirm while the report is under review', async () => {
    setup(report({ status: 'NEEDS_REVIEW' }))
    const status = await screen.findByRole('status')
    expect(within(status).getByText(/being checked by the care team/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument()
  })

  it('shows a not-found state', async () => {
    server.use(http.get(`${API}/reports/404/`, () => HttpResponse.json({ detail: 'Not found.' }, { status: 404 })))
    userEvent.setup()
    renderPage(<LabConfirmPage />, { path: '/patient/lab-reports/:id/confirm', route: '/patient/lab-reports/404/confirm' })
    await waitFor(() => expect(screen.getByText('Report not found')).toBeInTheDocument())
  })
})

describe('LabConfirmPage report date', () => {
  const older = {
    report_date: '2026-03-01', report_date_source: 'reporting', date_check_status: 'older_than_latest' as const,
    latest_report_date: '2026-09-14', date_ack_required: true,
    date_message: 'This report (1 Mar 2026) is older than your latest report (14 Sep 2026).',
  }

  it('warns about an older report and enables Confirm only after acknowledging', async () => {
    let body: any = null
    server.use(http.post(`${API}/reports/42/confirm/`, async ({ request }) => {
      body = await request.json()
      return HttpResponse.json(report({ status: 'CONFIRMED' }))
    }))
    const user = setup(report(older))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('This report (1 Mar 2026) is older than your latest report (14 Sep 2026).')
    const confirm = screen.getByRole('button', { name: 'Confirm' })
    expect(confirm).toBeDisabled()
    await user.click(screen.getByLabelText(/I understand this is an older report, upload anyway/))
    expect(confirm).toBeEnabled()
    await user.click(confirm)
    await waitFor(() => expect(body?.acknowledge_older_report).toBe(true))
  })

  it('lets the user type a missing date, then compares it again', async () => {
    let sentDate: unknown = null
    server.use(http.post(`${API}/reports/42/report-date/`, async ({ request }) => {
      sentDate = ((await request.json()) as { report_date: string }).report_date
      return HttpResponse.json(report({ ...older, report_date_source: 'user', report_date_user_entered: true }))
    }))
    const user = setup(report({
      report_date: null, report_date_source: '', date_check_status: 'date_missing',
      date_message: 'No reporting date could be read from this report. Enter the date printed on the report.',
    }))
    expect(await screen.findByText(/No reporting date could be read/)).toBeInTheDocument()
    const dateInput = screen.getByLabelText('Report date')
    await user.type(dateInput, '2026-03-01')
    await user.click(screen.getByRole('button', { name: 'Save date' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/older than your latest report/)
    expect(sentDate).toBe('2026-03-01')
    expect(screen.getByText(/Entered by you/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeDisabled()
  })

  it('shows the server message when the typed date is refused', async () => {
    server.use(http.post(`${API}/reports/42/report-date/`, () => HttpResponse.json(
      { code: 'invalid_date', message: 'The report date cannot be in the future.' }, { status: 400 })))
    const user = setup(report({ report_date: '2026-09-14', date_check_status: 'ok', report_date_source: 'reporting' }))
    const dateInput = await screen.findByLabelText('Report date')
    expect(screen.getByText(/Read from the reporting date/)).toBeInTheDocument()
    await user.clear(dateInput)
    await user.type(dateInput, '2026-09-20')
    await user.click(screen.getByRole('button', { name: 'Save date' }))
    expect(await screen.findByText('The report date cannot be in the future.')).toBeInTheDocument()
  })
})

describe('LabConfirmPage report without card values', () => {
  const noValues = {
    status: 'NO_VALUES_SAVEABLE' as const, fields: [], detected_fields: [], can_save_without_values: true,
    no_values_message: 'No health card values were found. You can save this report as a document only. Dashboard values will not change.',
    date_check_status: 'first_report' as const, report_date: '2026-09-14', report_date_source: 'reporting',
    identity_verified: true,
  }

  it('offers "Save report only" and "Cancel" instead of a values table', async () => {
    let confirmed = false
    server.use(http.post(`${API}/reports/42/confirm/`, () => {
      confirmed = true
      return HttpResponse.json(report({ ...noValues, status: 'SAVED_NO_VALUES' }))
    }))
    const user = setup(report(noValues))
    expect(await screen.findByText(/You can save this report as a document only/)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    expect(confirmed).toBe(false)                                   // never saved without the user's click
    await user.click(screen.getByRole('button', { name: 'Save report only' }))
    await waitFor(() => expect(confirmed).toBe(true))
  })

  it('says when the report will be saved as unverified', async () => {
    setup(report({ ...noValues, identity_verified: false }))
    expect(await screen.findByText(/saved as unverified/)).toBeInTheDocument()
  })
})
