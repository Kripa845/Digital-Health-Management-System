import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { API, server } from '@/test/server'
import { renderPage } from '@/test/render'
import { AdminPatients } from './AdminPatients'

const UUID = '6f1c2a3b-0000-4000-8000-000000000001'

const created = {
  id: 42, patient_id: 'PAT-AB12CD34', uuid_token: UUID, first_name: 'Sunita', middle_name: '',
  last_name: 'Maharjan', dob: '1992-03-14', gender: 'Female', blood_group: 'B+', phone: '9841234567',
  emergency_contact: '9841234568', email: 'sunita@example.com', address: 'Patan, Lalitpur', status: 'Active',
  height: '158.00', weight: '54.00',
}

/** The form's inputs sit next to their labels (Field does not link them). */
function inputFor(label: string) {
  const el = screen.getByText(label).closest('div')!.querySelector('input')
  if (!el) throw new Error(`No input for ${label}`)
  return el
}

async function fillForm(user: ReturnType<typeof userEvent.setup>) {
  const values: [string, string][] = [
    ['First name', 'Sunita'], ['Last name', 'Maharjan'], ['Phone', '9841234567'],
    ['Emergency contact', '9841234568'], ['Email', 'sunita@example.com'], ['Address', 'Patan, Lalitpur'],
    ['Height (cm)', '158'], ['Weight (kg)', '54'],
  ]
  for (const [label, value] of values) {
    await user.click(inputFor(label))
    await user.paste(value)
  }
  await user.type(inputFor('Date of birth'), '1992-03-14')
}

describe('AdminPatients — patient ID typed by the admin', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_FRONTEND_URL', 'https://card.example.org')
    server.use(http.get(`${API}/patients/`, () => HttpResponse.json({ count: 0, next: null, previous: null, results: [] })))
  })
  afterEach(() => vi.unstubAllEnvs())

  it('takes only the number part, validates it and can generate one', async () => {
    const user = userEvent.setup()
    renderPage(<AdminPatients />)
    await user.click((await screen.findAllByRole('button', { name: /Add patient/ }))[0])

    const id = screen.getByLabelText(/Patient ID/)
    await user.type(id, 'ab1')
    expect(id).toHaveValue('AB1')

    await user.click(screen.getByRole('button', { name: 'Register patient' }))
    expect(screen.getByText(/4 to 12 letters or digits with at least 4 digits/)).toBeInTheDocument()

    await user.clear(id)
    await user.click(id)
    await user.paste('PAT-79028232')               // a pasted full ID keeps only the number
    expect(id).toHaveValue('79028232')

    await user.click(screen.getByRole('button', { name: /Generate/ }))
    expect((id as HTMLInputElement).value).toMatch(/^\d{8}$/)
  })

  it('lets the admin change an existing patient ID', async () => {
    let sent: FormData | null = null
    server.use(
      http.get(`${API}/patients/`, () => HttpResponse.json({ count: 1, next: null, previous: null, results: [{ ...created, patient_id: 'PAT-OLD00001' }] })),
      http.patch(`${API}/patients/42/`, async ({ request }) => {
        sent = await request.formData()
        return HttpResponse.json({ ...created, patient_id: 'PAT-79028232' })
      }),
    )
    const user = userEvent.setup()
    renderPage(<AdminPatients />)
    await user.click((await screen.findAllByRole('button', { name: 'Actions' }))[0])
    await user.click(await screen.findByRole('menuitem', { name: /Edit/ }))

    const id = screen.getByLabelText(/Patient ID/)
    expect(id).toHaveValue('OLD00001')
    await user.clear(id)
    await user.type(id, '79028232')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await vi.waitFor(() => expect(sent).not.toBeNull())
    expect(sent!.get('patient_id')).toBe('PAT-79028232')
  }, 20000)

  it('shows the server "already exists" error under the field, then opens the QR after create', async () => {
    let attempts = 0
    let sent: FormData | null = null
    server.use(http.post(`${API}/patients/`, async ({ request }) => {
      attempts += 1
      sent = await request.formData()
      if (attempts === 1) {
        return HttpResponse.json({ patient_id: ['A patient with ID PAT-AB12CD34 already exists.'] }, { status: 400 })
      }
      return HttpResponse.json({ success: true, email_sent: true, message: 'Patient registered.', patient: created }, { status: 201 })
    }))

    const user = userEvent.setup()
    renderPage(<AdminPatients />)
    await user.click((await screen.findAllByRole('button', { name: /Add patient/ }))[0])
    await user.type(screen.getByLabelText(/Patient ID/), 'ab12cd34')
    await fillForm(user)

    await user.click(screen.getByRole('button', { name: 'Register patient' }))
    expect(await screen.findByText('A patient with ID PAT-AB12CD34 already exists.')).toBeInTheDocument()
    expect(sent!.get('patient_id')).toBe('PAT-AB12CD34')

    await user.click(screen.getByRole('button', { name: 'Register patient' }))
    const dialog = await screen.findByRole('dialog', { name: 'Health card QR' })
    const qr = dialog.querySelector('svg[data-link]')!
    // The QR encodes the configured site address and the uuid token, never the patient ID.
    expect(qr.getAttribute('data-link')).toBe(`https://card.example.org/public-profile/${UUID}`)
    expect(qr.getAttribute('data-link')).not.toContain('PAT-AB12CD34')
    expect(within(dialog).getByText('PAT-AB12CD34')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: /Print card/ })).toBeInTheDocument()
  }, 20000)
})
