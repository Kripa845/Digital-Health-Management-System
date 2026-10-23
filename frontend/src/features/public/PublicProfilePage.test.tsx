import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { API, server } from '@/test/server'
import { renderPage } from '@/test/render'
import { ThemeProvider } from '@/components/theme-provider'
import { PublicProfilePage } from './PublicProfilePage'

const UUID = '6f1c2a3b-0000-4000-8000-000000000001'
const TOKEN = '11111111-2222-4333-8444-555555555555'
const BASE = `${API}/patients/public/${UUID}`

const record = {
  medical: { allergies: 'Penicillin', current_medication: 'Metformin 500 mg', prescription: '' },
  body: { height: '170', weight: '70', bmi: 24.2, bmi_status: 'Normal', blood_pressure: '120/80', heart_rate: 72, spo2: '98', temperature: null },
  contact: { phone: '9800000001', email: '', address: 'Kathmandu' },
  lab_results: [{ test: 'hemoglobin', label: 'Haemoglobin', unit: 'g/dL', latest: { value: '13.4', date: '2026-10-01' }, status: 'Normal', reference: '13.0–17.0' }],
}

// jsdom has no matchMedia; the theme toggle asks for the system colour scheme.
window.matchMedia ??= ((query: string) => ({
  matches: false, media: query, onchange: null,
  addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {},
  dispatchEvent: () => false,
})) as unknown as typeof window.matchMedia

function renderProfile() {
  return renderPage(<ThemeProvider><PublicProfilePage /></ThemeProvider>, { path: '/public-profile/:uuid', route: `/public-profile/${UUID}` })
}

describe('PublicProfilePage — asking for more information', () => {
  beforeEach(() => {
    localStorage.clear()
    server.use(http.get(`${BASE}/`, () => HttpResponse.json({
      uuid: UUID, patient_id: 'PAT-0E2E0001', first_name: 'Hari', middle_name: null, last_name: 'Tamang',
      photo: null, age: 36, gender: 'Male', blood_group: 'O+', emergency_contact: '9800000002', status: 'Active',
    })))
  })
  afterEach(() => localStorage.clear())

  it('sends a request, then shows the extra information once approved', async () => {
    let sent: Record<string, string> | null = null
    server.use(
      http.post(`${BASE}/access-requests/`, async ({ request }) => {
        sent = await request.json() as Record<string, string>
        return HttpResponse.json({ token: TOKEN, status: 'PENDING', created_at: '2026-10-24T10:00:00Z', expires_at: null }, { status: 201 })
      }),
      http.get(`${BASE}/access-requests/${TOKEN}/`, () => HttpResponse.json({
        token: TOKEN, status: 'APPROVED', created_at: '2026-10-24T10:00:00Z', expires_at: '2026-10-25T10:00:00Z', record,
      })),
    )
    const user = userEvent.setup()
    renderProfile()
    expect(await screen.findByText('Hari Tamang')).toBeInTheDocument()
    expect(screen.queryByText('Penicillin')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Request more information' }))
    await user.type(screen.getByLabelText(/Your full name/), 'Sita Paramedic')
    await user.type(screen.getByLabelText(/Your mobile number/), '9812345678')
    await user.type(screen.getByLabelText(/Why do you need it/), 'Patient unconscious, need allergies.')
    await user.click(screen.getByRole('button', { name: 'Send request' }))

    expect(await screen.findByText('Penicillin')).toBeInTheDocument()
    expect(sent).toEqual({ requester_name: 'Sita Paramedic', requester_phone: '9812345678', reason: 'Patient unconscious, need allergies.' })
    expect(screen.getByText('Metformin 500 mg')).toBeInTheDocument()
    expect(screen.getByText('Haemoglobin')).toBeInTheDocument()
    expect(screen.getByText('9800000001')).toBeInTheDocument()
    expect(localStorage.getItem(`qr-access:${UUID}`)).toBe(TOKEN)   // kept on this phone only
  }, 20000)

  it('shows the server field errors', async () => {
    server.use(http.post(`${BASE}/access-requests/`, () =>
      HttpResponse.json({ requester_phone: ['Please enter a valid Nepal mobile number.'] }, { status: 400 })))
    const user = userEvent.setup()
    renderProfile()
    await user.click(await screen.findByRole('button', { name: 'Request more information' }))
    await user.click(screen.getByRole('button', { name: 'Send request' }))
    expect(await screen.findByText('Please enter a valid Nepal mobile number.')).toBeInTheDocument()
  })

  it('a waiting request says so; a declined one offers to ask again', async () => {
    localStorage.setItem(`qr-access:${UUID}`, TOKEN)
    let status = 'PENDING'
    server.use(http.get(`${BASE}/access-requests/${TOKEN}/`, () =>
      HttpResponse.json({ token: TOKEN, status, created_at: '2026-10-24T10:00:00Z', expires_at: null })))
    const view = renderProfile()
    expect(await screen.findByText('Waiting for an administrator')).toBeInTheDocument()

    status = 'DECLINED'
    view.unmount()
    renderProfile()
    expect(await screen.findByText('Request declined')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Request again' })).toBeInTheDocument()
  })

  it('forgets a request the server no longer knows (card replaced)', async () => {
    localStorage.setItem(`qr-access:${UUID}`, TOKEN)
    server.use(http.get(`${BASE}/access-requests/${TOKEN}/`, () => HttpResponse.json({ detail: 'Request not found.' }, { status: 404 })))
    renderProfile()
    expect(await screen.findByRole('button', { name: 'Request more information' })).toBeInTheDocument()
    await waitFor(() => expect(localStorage.getItem(`qr-access:${UUID}`)).toBeNull())
  })
})
