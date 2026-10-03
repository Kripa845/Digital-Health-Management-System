import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { API, server } from '@/test/server'
import { renderPage } from '@/test/render'
import { report } from '@/test/fixtures'
import { LabReportRow } from './LabReportRow'

describe('LabReportRow delete', () => {
  it('deletes a report under review after confirmation', async () => {
    let deleted = false
    server.use(http.delete(`${API}/reports/42/`, () => { deleted = true; return new HttpResponse(null, { status: 204 }) }))
    const user = userEvent.setup()
    renderPage(<LabReportRow report={report({ id: 42, status: 'NEEDS_REVIEW' })} patientId={7} />)

    await user.click(screen.getByRole('button', { name: 'Delete lab report' }))
    expect(await screen.findByText(/Nothing on the dashboard changes/)).toBeInTheDocument()
    expect(deleted).toBe(false)                                 // nothing happens before confirming

    await user.click(screen.getByRole('button', { name: /^Delete$/ }))
    await waitFor(() => expect(deleted).toBe(true))
  })

  it('warns that a confirmed report takes its values off the dashboard; cancel keeps it', async () => {
    let deleted = false
    server.use(http.delete(`${API}/reports/42/`, () => { deleted = true; return new HttpResponse(null, { status: 204 }) }))
    const user = userEvent.setup()
    renderPage(<LabReportRow report={report({ id: 42, status: 'CONFIRMED' })} patientId={7} />)

    await user.click(screen.getByRole('button', { name: 'Delete lab report' }))
    expect(await screen.findByText(/removed from the dashboard/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(deleted).toBe(false)
  })

  it('has no delete button where deleting is not allowed', () => {
    renderPage(<LabReportRow report={report({ id: 42, status: 'CONFIRMED' })} patientId={7} canDelete={false} />)
    expect(screen.queryByRole('button', { name: 'Delete lab report' })).not.toBeInTheDocument()
  })
})

describe('LabReportRow view', () => {
  const file = () => new HttpResponse(new Uint8Array([0x89, 0x50, 0x4e, 0x47]), {
    headers: { 'Content-Type': 'application/octet-stream' },
  })

  it('shows an uploaded image, fetching it only when opened', async () => {
    let fetched = 0
    server.use(http.get(`${API}/reports/42/download/`, () => { fetched += 1; return file() }))
    const user = userEvent.setup()
    renderPage(<LabReportRow report={report({ id: 42, name: 'CBC scan', status: 'CONFIRMED', file_type: 'PNG' })} patientId={7} />)
    expect(fetched).toBe(0)

    await user.click(screen.getByRole('button', { name: 'View report' }))
    expect(await screen.findByRole('img', { name: 'CBC scan' })).toHaveAttribute('src', 'blob:report')
    expect(fetched).toBe(1)
  })

  it('shows a PDF in a frame, also for a report still under review', async () => {
    server.use(http.get(`${API}/reports/42/download/`, () => file()))
    const user = userEvent.setup()
    renderPage(<LabReportRow report={report({ id: 42, name: 'Lipid profile', status: 'NEEDS_REVIEW', file_type: 'PDF' })} patientId={7} />)
    await user.click(screen.getByRole('button', { name: 'View report' }))
    expect(await screen.findByTitle('Lipid profile')).toHaveAttribute('src', 'blob:report')
  })

  it('explains when the file is no longer available', async () => {
    server.use(http.get(`${API}/reports/42/download/`, () => HttpResponse.json(
      { code: 'no_file', message: 'The original file of this report is no longer available.' }, { status: 404 })))
    const user = userEvent.setup()
    renderPage(<LabReportRow report={report({ id: 42, status: 'CONFIRMED', file_type: 'PDF' })} patientId={7} />)
    await user.click(screen.getByRole('button', { name: 'View report' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/no longer available/)
  })

  it('has no view button for a rejected report (its file was deleted)', () => {
    renderPage(<LabReportRow report={report({ id: 42, status: 'REJECTED' })} patientId={7} />)
    expect(screen.queryByRole('button', { name: 'View report' })).not.toBeInTheDocument()
  })
})

describe('LabReportRow saved document', () => {
  it('shows "Saved - no card values" with view and delete', () => {
    renderPage(<LabReportRow report={report({ id: 42, status: 'SAVED_NO_VALUES', fields: [] })} patientId={7} />)
    expect(screen.getByText('Saved - no card values')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'View report' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete lab report' })).toBeInTheDocument()
  })
})
