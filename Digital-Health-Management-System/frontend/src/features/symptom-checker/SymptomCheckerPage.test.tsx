import { describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { API, server } from '@/test/server'
import { renderPage } from '@/test/render'
import { SymptomCheckerPage } from './SymptomCheckerPage'

const DISCLAIMER = 'Suggestion only, not a medical diagnosis.'

// Radix Select (the patient dropdown) uses pointer capture and scrollIntoView, which jsdom lacks.
Element.prototype.hasPointerCapture ??= () => false
Element.prototype.releasePointerCapture ??= () => {}
Element.prototype.scrollIntoView ??= () => {}

const ok = {
  status: 'ok',
  symptoms: ['chest pain', 'breathlessness', 'sweating'],
  illnesses: [
    { name: 'Heart attack', probability: 0.7587 },
    { name: 'GERD', probability: 0.0884 },
    { name: 'Bronchial Asthma', probability: 0.0884 },
  ],
  department: 'Emergency Medicine',
  dept_probability: 0.7587,
  doctors: [
    { id: 6, name: 'Gita Shrestha', department: 'General Medicine', specialization: 'Internal Medicine', score: 1, free_hours: 5, caseload: 2, reason: 'only active doctor in this department' },
  ],
  doctors_department: 'General Medicine',
  doctors_note: 'No Emergency Medicine doctor is available right now, so General Medicine doctors are shown as a first point of contact.',
  history_id: 9,
  disclaimer: DISCLAIMER,
}

async function check(text: string) {
  const user = userEvent.setup()
  renderPage(<SymptomCheckerPage />)
  await user.click(screen.getByLabelText(/What are you feeling/))
  await user.paste(text)
  await user.click(screen.getByRole('button', { name: /Check symptoms/ }))
  return user
}

describe('SymptomCheckerPage', () => {
  it('explains the three steps before a check and always shows the disclaimer', () => {
    renderPage(<SymptomCheckerPage />)
    expect(screen.getByText('Negation detection')).toBeInTheDocument()
    expect(screen.getByText('Naive Bayes')).toBeInTheDocument()
    expect(screen.getByText('TOPSIS')).toBeInTheDocument()
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument()
  })

  it('shows symptoms, illnesses with the likely area, and TOPSIS-ranked doctors', async () => {
    let sent: unknown = null
    server.use(http.post(`${API}/smart-symptom-check/`, async ({ request }) => {
      sent = await request.json()
      return HttpResponse.json(ok)
    }))
    await check('no fever, but chest pain, breathlessness and sweating')

    const step1 = await screen.findByRole('region', { name: /Step 1/ })
    expect(within(step1).getByText('breathlessness')).toBeInTheDocument()
    const step2 = screen.getByRole('region', { name: /Step 2/ })
    expect(within(step2).getByText('Likely area: Emergency Medicine (76%)')).toBeInTheDocument()
    expect(within(step2).getByText('Heart attack')).toBeInTheDocument()
    expect(within(step2).getAllByText('9%')).toHaveLength(2)
    const step3 = screen.getByRole('region', { name: /Step 3/ })
    expect(within(step3).getByText('Dr. Gita Shrestha')).toBeInTheDocument()
    expect(within(step3).getByText('1.00')).toBeInTheDocument()            // TOPSIS score
    expect(within(step3).getByText(/No Emergency Medicine doctor/)).toBeInTheDocument()
    expect(sent).toMatchObject({ text: 'no fever, but chest pain, breathlessness and sweating' })
  })

  it('asks for more symptoms and shows the keyword match when not confident', async () => {
    let keywordBody: any = null
    server.use(
      http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({ status: 'not_enough_info', symptoms: ['itching'], disclaimer: DISCLAIMER })),
      http.post(`${API}/recommendations/`, async ({ request }) => {
        keywordBody = await request.json()
        return HttpResponse.json({ id: 1, symptoms: 'itching', pain_level: 5, recommended_department: 'Dermatology', confidence: 70, reason: 'Keyword reason.', ranked_doctors: [] }, { status: 201 })
      }),
    )
    await check('itching')
    expect(await screen.findByRole('status')).toHaveTextContent(/Please add more symptoms/)
    expect(screen.getByText('Keyword match')).toBeInTheDocument()
    expect(screen.getByText('Dermatology')).toBeInTheDocument()
    expect(keywordBody).toMatchObject({ symptoms: 'itching', pain_level: 5 })
  })

  it('fills the text box from an example', async () => {
    const user = userEvent.setup()
    renderPage(<SymptomCheckerPage />)
    await user.click(screen.getByRole('button', { name: 'itching, skin rash and nodal skin eruptions' }))
    expect(screen.getByLabelText(/What are you feeling/)).toHaveValue('itching, skin rash and nodal skin eruptions')
  })
})

describe('SymptomCheckerPage patient section', () => {
  const hari = {
    id: 42, patient_id: 'PAT-79028232', first_name: 'Hari', middle_name: '', last_name: 'Tamang', age: 36,
    gender: 'Male', blood_group: 'O+', allergies: 'Penicillin', current_medication: '', status: 'Active',
  }

  function asAdmin() {
    server.use(http.get(`${API}/auth/me/`, () => HttpResponse.json({
      id: 1, username: 'admin', first_name: 'Site', last_name: 'Admin', role: 'ADMIN',
    })))
  }

  it('lists all patients in a dropdown and checks symptoms for the chosen one', async () => {
    asAdmin()
    let sent: any = null
    const sita = { ...hari, id: 43, patient_id: 'PAT-31965', first_name: 'Sita', last_name: 'Gurung', allergies: '' }
    server.use(
      http.get(`${API}/patients/`, () => HttpResponse.json({ count: 2, next: null, previous: null, results: [sita, hari] })),
      http.post(`${API}/smart-symptom-check/`, async ({ request }) => {
        sent = await request.json()
        return HttpResponse.json({ ...ok, patient: { id: 42, patient_id: 'PAT-79028232', name: 'Hari Tamang' } })
      }),
    )
    const user = userEvent.setup()
    renderPage(<SymptomCheckerPage />)

    await user.click(await screen.findByRole('combobox'))
    const options = await screen.findAllByRole('option')
    expect(options.map((o) => o.textContent)).toEqual([
      'No patient (check not linked to a patient)', 'Hari Tamang · PAT-79028232', 'Sita Gurung · PAT-31965',
    ])                                                                     // every patient, sorted by name
    await user.click(screen.getByRole('option', { name: 'Hari Tamang · PAT-79028232' }))
    expect(screen.getByText('Penicillin')).toBeInTheDocument()            // allergies shown for context

    await user.click(screen.getByLabelText('Symptoms of Hari Tamang'))
    await user.paste('chest pain, breathlessness and sweating')
    await user.click(screen.getByRole('button', { name: /Check symptoms/ }))

    expect(await screen.findByText(/Saved to the symptom history of Hari Tamang \(PAT-79028232\)/)).toBeInTheDocument()
    expect(sent).toMatchObject({ text: 'chest pain, breathlessness and sweating', patient_id: 42 })

    await user.click(screen.getByRole('combobox'))                       // switching patient clears the result
    await user.click(await screen.findByRole('option', { name: 'Sita Gurung · PAT-31965' }))
    await waitFor(() => expect(screen.queryByText(/Saved to the symptom history/)).not.toBeInTheDocument())
    expect(screen.getByLabelText('Symptoms of Sita Gurung')).toBeInTheDocument()
  })

  it('an admin can run a check without choosing a patient', async () => {
    asAdmin()
    let sent: any = null
    server.use(http.post(`${API}/smart-symptom-check/`, async ({ request }) => {
      sent = await request.json()
      return HttpResponse.json({ ...ok, patient: null })
    }))
    await check('chest pain, breathlessness and sweating')
    expect(await screen.findByRole('region', { name: /Step 3/ })).toBeInTheDocument()
    expect(sent.patient_id).toBeUndefined()
  })

  it('a patient checks for themselves (no patient picker)', async () => {
    server.use(http.get(`${API}/auth/me/`, () => HttpResponse.json({
      id: 2, username: 'hari', first_name: 'Hari', last_name: 'Tamang', role: 'PATIENT',
      patient_profile: { id: 7, patient_id: 'PAT-79028232', first_name: 'Hari', last_name: 'Tamang' },
    })))
    renderPage(<SymptomCheckerPage />)
    expect(await screen.findByText(/you \(Hari Tamang, PAT-79028232\)/)).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/Search by name, patient ID/)).not.toBeInTheDocument()
  })
})

describe('SymptomCheckerPage assigning a recommended doctor', () => {
  const hari = {
    id: 42, patient_id: 'PAT-79028232', first_name: 'Hari', middle_name: '', last_name: 'Tamang', age: 36,
    gender: 'Male', blood_group: 'O+', allergies: '', current_medication: '', status: 'Active',
  }
  const okForHari = { ...ok, patient: { id: 42, patient_id: 'PAT-79028232', name: 'Hari Tamang' } }

  function adminServer(assignments: any[]) {
    server.use(
      http.get(`${API}/auth/me/`, () => HttpResponse.json({ id: 1, username: 'admin', first_name: 'Site', last_name: 'Admin', role: 'ADMIN' })),
      http.get(`${API}/patients/`, () => HttpResponse.json({ count: 1, next: null, previous: null, results: [hari] })),
      http.get(`${API}/assignments/`, () => HttpResponse.json({ count: assignments.length, next: null, previous: null, results: assignments })),
      http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json(okForHari)),
    )
  }

  async function checkForHari() {
    const user = userEvent.setup()
    renderPage(<SymptomCheckerPage />)
    await user.click(await screen.findByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: 'Hari Tamang · PAT-79028232' }))
    await user.click(screen.getByLabelText('Symptoms of Hari Tamang'))
    await user.paste('chest pain, breathlessness and sweating')
    await user.click(screen.getByRole('button', { name: /Check symptoms/ }))
    return user
  }

  it('assigns the chosen patient to a recommended doctor', async () => {
    const assignments: any[] = []
    let posted: any = null
    adminServer(assignments)
    server.use(http.post(`${API}/assignments/`, async ({ request }) => {
      posted = await request.json()
      assignments.push({ id: 5, doctor: 6, patient: 42, status: 'Active', assigned_date: '2026-10-03' })
      return HttpResponse.json(assignments[0], { status: 201 })
    }))
    const user = await checkForHari()

    await user.click(await screen.findByRole('button', { name: 'Assign Hari Tamang to Dr. Gita Shrestha' }))
    expect(await screen.findByText('Assigned')).toBeInTheDocument()
    expect(posted).toEqual({ doctor: 6, patient: 42 })
  })

  it('shows "Assigned" for a doctor already assigned to the patient', async () => {
    adminServer([{ id: 5, doctor: 6, patient: 42, status: 'Active', assigned_date: '2026-10-01' }])
    await checkForHari()
    expect(await screen.findByText('Assigned')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Assign / })).not.toBeInTheDocument()
  })

  it('shows the server message when assigning fails', async () => {
    adminServer([])
    server.use(http.post(`${API}/assignments/`, () =>
      HttpResponse.json({ non_field_errors: ['This patient is already assigned to this doctor.'] }, { status: 400 })))
    const errorToast = vi.spyOn(toast, 'error')
    const user = await checkForHari()
    await user.click(await screen.findByRole('button', { name: /^Assign / }))
    await waitFor(() => expect(errorToast).toHaveBeenCalledWith(expect.stringMatching(/already assigned to this doctor/)))
    errorToast.mockRestore()
  })

  it('a patient does not get assign buttons', async () => {
    server.use(http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json(okForHari)))
    await check('chest pain, breathlessness and sweating')
    expect(await screen.findByRole('region', { name: /Step 3/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Assign / })).not.toBeInTheDocument()
  })
})
