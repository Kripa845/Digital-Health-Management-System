import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { API, server } from '@/test/server'
import { renderPage } from '@/test/render'
import { report } from '@/test/fixtures'
import { LabUploadPage } from './LabUploadPage'

const pdf = () => new File(['%PDF-1.4 synthetic'], 'report.pdf', { type: 'application/pdf' })

function setup() {
  const user = userEvent.setup()
  renderPage(<LabUploadPage />, {
    path: '/patient/lab-reports/upload',
    routes: { '/patient/lab-reports/:id/confirm': <p>Confirm page</p> },
  })
  return user
}

async function chooseAndUpload(user: ReturnType<typeof userEvent.setup>, file = pdf()) {
  await user.upload(screen.getByTestId('file-input'), file)
  await user.click(screen.getByRole('button', { name: /upload and read/i }))
}

function replyWith(status: number, body: object) {
  server.use(http.post(`${API}/reports/upload/`, () => HttpResponse.json(body, { status })))
}

describe('LabUploadPage', () => {
  it('rejects a wrong file type before uploading', async () => {
    const user = userEvent.setup({ applyAccept: false })
    renderPage(<LabUploadPage />, { path: '/' })
    await user.upload(screen.getByTestId('file-input'), new File(['x'], 'virus.exe'))
    expect(screen.getByRole('alert')).toHaveTextContent('Choose a PDF, PNG or JPG file.')
    expect(screen.getByRole('button', { name: /upload and read/i })).toBeDisabled()
  })

  it('goes to the confirm page when the report is verified', async () => {
    replyWith(201, report({ id: 42, status: 'PENDING_CONFIRMATION' }))
    const user = setup()
    await chooseAndUpload(user)
    expect(await screen.findByText('Confirm page')).toBeInTheDocument()
  })

  it('shows the ID mismatch message and saves nothing', async () => {
    replyWith(422, { code: 'patient_id_mismatch', message: 'Patient ID does not match this account.' })
    const user = setup()
    await chooseAndUpload(user)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Patient ID does not match this account')
    expect(alert).toHaveTextContent('Nothing was saved')
  })

  it('explains when the report needs review', async () => {
    replyWith(201, report({ status: 'NEEDS_REVIEW', review_messages: ['The report does not show a Mero Care Card patient ID.'] }))
    const user = setup()
    await chooseAndUpload(user)
    expect(await screen.findByText(/being checked by the care team/i)).toBeInTheDocument()
    expect(screen.getByText(/does not show a Mero Care Card patient ID/)).toBeInTheDocument()
  })

  it('tells the user about a duplicate file', async () => {
    replyWith(409, { code: 'duplicate', message: 'This file has already been uploaded for this patient.' })
    const user = setup()
    await chooseAndUpload(user)
    expect(await screen.findByText('This report was already uploaded')).toBeInTheDocument()
  })

  it('offers a retry after a network error', async () => {
    let calls = 0
    server.use(http.post(`${API}/reports/upload/`, () => {
      calls += 1
      return calls === 1 ? HttpResponse.error() : HttpResponse.json(report({ id: 9 }), { status: 201 })
    }))
    const user = setup()
    await chooseAndUpload(user)
    expect(await screen.findByText('Could not reach the server')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /retry/i }))
    await waitFor(() => expect(screen.getByText('Confirm page')).toBeInTheDocument())
  })
})
