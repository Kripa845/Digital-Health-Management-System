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
  symptoms: ['palpitations', 'shortness of breath', 'feeling faint'],
  illnesses: [
    { name: 'Possible NSTEMI / STEMI', probability: 0.7587 },
    { name: 'Unstable angina', probability: 0.0884 },
    { name: 'Pulmonary embolism', probability: 0.0884 },
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
    expect(screen.getByText('Random Forest')).toBeInTheDocument()
    expect(screen.getByText('TOPSIS')).toBeInTheDocument()
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument()
  })

  it('shows symptoms, illnesses with the likely area, and TOPSIS-ranked doctors', async () => {
    let sent: unknown = null
    server.use(http.post(`${API}/smart-symptom-check/`, async ({ request }) => {
      sent = await request.json()
      return HttpResponse.json(ok)
    }))
    await check('no fever, but palpitations, shortness of breath and feeling faint')

    const step1 = await screen.findByRole('region', { name: /Step 1/ })
    expect(within(step1).getByText('shortness of breath')).toBeInTheDocument()
    const step2 = screen.getByRole('region', { name: /Step 2/ })
    expect(within(step2).getByText('Likely area: Emergency Medicine (76%)')).toBeInTheDocument()
    expect(within(step2).getByText('Possible NSTEMI / STEMI')).toBeInTheDocument()
    expect(within(step2).getAllByText('9%')).toHaveLength(2)
    const step3 = screen.getByRole('region', { name: /Step 3/ })
    expect(within(step3).getByText('Dr. Gita Shrestha')).toBeInTheDocument()
    expect(within(step3).getByText('1.00')).toBeInTheDocument()            // TOPSIS score
    expect(within(step3).getByText(/No Emergency Medicine doctor/)).toBeInTheDocument()
    expect(sent).toMatchObject({ text: 'no fever, but palpitations, shortness of breath and feeling faint', answers: {} })
  })

  it('shows an emergency message for red-flag symptoms and never falls back to the keyword match', async () => {
    let keywordCalled = false
    server.use(
      http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({
        status: 'emergency', symptoms: ['coughing up blood'], department: 'Emergency Medicine',
        red_flags: [{ id: 'coughing_up_blood', message: 'Coughing up blood' }],
        message: 'Please go to the nearest emergency department or call an ambulance now.',
        matched: [], negated: [], unrecognized: [], disclaimer: DISCLAIMER,
      })),
      http.post(`${API}/recommendations/`, () => { keywordCalled = true; return HttpResponse.json({}, { status: 201 }) }),
    )
    await check('coughing up blood')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Seek emergency care now')
    expect(alert).toHaveTextContent('Coughing up blood')
    expect(screen.queryByText('Keyword match')).not.toBeInTheDocument()
    expect(keywordCalled).toBe(false)
  })

  it('asks a follow-up question when unsure and sends the answer back', async () => {
    const bodies: any[] = []
    server.use(http.post(`${API}/smart-symptom-check/`, async ({ request }) => {
      const body: any = await request.json()
      bodies.push(body)
      return HttpResponse.json(Object.keys(body.answers ?? {}).length
        ? ok
        : { status: 'not_enough_info', symptoms: ['cough'], matched: [], negated: [], unrecognized: [], disclaimer: DISCLAIMER,
            question: { symptom: 'E_77', label: 'coloured sputum', text: 'Do you have a cough that produces colored sputum?' } })
    }))
    const user = await check('cough')
    const question = await screen.findByRole('region', { name: 'Follow-up question' })
    expect(question).toHaveTextContent('Do you have a cough that produces colored sputum?')
    await user.click(within(question).getByRole('button', { name: 'Yes' }))
    expect(await screen.findByRole('region', { name: /Step 2/ })).toBeInTheDocument()
    expect(bodies[1]).toMatchObject({ text: 'cough', answers: { E_77: true } })
  })

  const unsure = {
    status: 'low_confidence', reason: 'serious_illness', symptoms: ['itchy rash', 'skin lesions', 'swelling'],
    department: 'General Medicine',
    message: 'Not enough information to suggest a specific area of care. A General Medicine doctor is the right first point of contact.',
    safety_net: 'Get emergency help straight away if you have difficulty breathing.',
    doctors: [{ id: 6, name: 'Gita Shrestha', department: 'General Medicine', specialization: 'Internal Medicine', score: 1, free_hours: 5, caseload: 2, reason: 'r' }],
    doctors_department: 'General Medicine', disclaimer: DISCLAIMER,
  }

  it('skipping the follow-up questions shows "not enough information" and General Medicine, not a keyword guess', async () => {
    let keywordCalled = false
    server.use(
      http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({
        ...unsure, question: { symptom: 'E_77', label: 'coloured sputum', text: 'Coloured sputum?' } })),
      http.post(`${API}/recommendations/`, () => { keywordCalled = true; return HttpResponse.json({}, { status: 201 }) }),
    )
    const user = await check('rash, swelling, itching')
    await user.click(await screen.findByRole('button', { name: 'Skip questions' }))
    expect(await screen.findByRole('status')).toHaveTextContent(/Not enough information/)
    expect(screen.getByText('General Medicine')).toBeInTheDocument()
    expect(screen.getByText(/Dr. Gita Shrestha/)).toBeInTheDocument()
    expect(screen.getByText(/Get emergency help/)).toBeInTheDocument()
    expect(screen.queryByText('Keyword match')).not.toBeInTheDocument()
    expect(keywordCalled).toBe(false)
  })

  it('asks "Did you mean" for an unclear spelling and sends the confirmation or dismissal back', async () => {
    const bodies: any[] = []
    server.use(http.post(`${API}/smart-symptom-check/`, async ({ request }) => {
      const body: any = await request.json()
      bodies.push(body)
      return HttpResponse.json(bodies.length === 1
        ? { status: 'needs_confirmation', symptoms: ['cough', 'sore throat'], disclaimer: DISCLAIMER,
            suggestions: [{ term: 'feverr', symptom: 'E_91', label: 'fever', score: 90.9 }] }
        : ok)
    }))
    const user = await check('feverr, cough, sore throat')
    const box = await screen.findByRole('region', { name: 'Did you mean' })
    expect(box).toHaveTextContent('“feverr” → fever')
    await user.click(within(box).getByRole('button', { name: 'Yes' }))
    expect(await screen.findByRole('region', { name: /Step 2/ })).toBeInTheDocument()
    expect(bodies[1]).toMatchObject({ answers: { E_91: true }, dismissed: [] })
  })

  it('dismissing a suggestion sends the term back as dismissed', async () => {
    const bodies: any[] = []
    server.use(http.post(`${API}/smart-symptom-check/`, async ({ request }) => {
      bodies.push(await request.json())
      return HttpResponse.json(bodies.length === 1
        ? { status: 'needs_confirmation', symptoms: [], disclaimer: DISCLAIMER,
            suggestions: [{ term: 'redness', symptom: 'E_89', label: 'fatigue', score: 87.5 }] }
        : unsure)
    }))
    const user = await check('redness')
    await user.click(within(await screen.findByRole('region', { name: 'Did you mean' })).getByRole('button', { name: 'No' }))
    await screen.findByText(/Dr. Gita Shrestha/)
    expect(bodies[1]).toMatchObject({ answers: {}, dismissed: ['redness'] })
  })

  it('shows the keyword match only when the smart check is unavailable', async () => {
    server.use(
      http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({ status: 'model_unavailable' }, { status: 503 })),
      http.post(`${API}/recommendations/`, () => HttpResponse.json(
        { id: 1, symptoms: 'heartburn', pain_level: 5, recommended_department: 'Gastroenterology', confidence: 70, reason: 'Keyword reason.', ranked_doctors: [] },
        { status: 201 })),
    )
    await check('heartburn')
    expect(await screen.findByText('Keyword match')).toBeInTheDocument()
    expect(screen.getByText('Gastroenterology')).toBeInTheDocument()
  })

  it('shows how synonyms and typos were mapped, and the words it did not recognise', async () => {
    server.use(http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({
      ...ok,
      matched: [
        { term: 'palpitations', symptom: 'palpitations', method: 'exact', score: null },
        { term: 'breathless', symptom: 'shortness of breath', method: 'synonym', score: null },
        { term: 'feeling fant', symptom: 'feeling faint', method: 'fuzzy', score: 92.3 },
      ],
      negated: ['fever'],
      unrecognized: ['blorf'],
    })))
    await check('no fever, palpitations, breathless, feeling fant, blorf')

    const step1 = await screen.findByRole('region', { name: /Step 1/ })
    const list = within(step1).getByRole('list', { name: 'How your words were understood' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(2)        // exact matches are not repeated
    expect(list).toHaveTextContent('“breathless” → shortness of breath (synonym)')
    expect(list).toHaveTextContent('“feeling fant” → feeling faint (spelling, 92% similar)')
    expect(within(step1).getByText(/You said you don't have: fever/)).toBeInTheDocument()
    expect(within(step1).getByRole('note')).toHaveTextContent('We didn\'t recognise: “blorf”')
  })

  it('lists unrecognised words even when there is not enough information', async () => {
    server.use(
      http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({
        status: 'not_enough_info', symptoms: [], matched: [], negated: [], unrecognized: ['asdfgh qwerty'], disclaimer: DISCLAIMER,
      })),
      http.post(`${API}/recommendations/`, () => HttpResponse.json(
        { id: 1, symptoms: 'x', pain_level: 5, recommended_department: 'General Medicine', confidence: 10, reason: 'r', ranked_doctors: [] },
        { status: 201 })),
    )
    await check('asdfgh qwerty')
    expect(await screen.findByRole('note')).toHaveTextContent('We didn\'t recognise: “asdfgh qwerty”')
    expect(screen.getByText('No known symptoms were recognised.')).toBeInTheDocument()
  })

  it('fills the text box from an example', async () => {
    const user = userEvent.setup()
    renderPage(<SymptomCheckerPage />)
    await user.click(screen.getByRole('button', { name: 'fever, cough and sore throat' }))
    expect(screen.getByLabelText(/What are you feeling/)).toHaveValue('fever, cough and sore throat')
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

describe('SymptomCheckerPage Assign beside recommended doctors', () => {
  const hari = {
    id: 42, patient_id: 'PAT-79028232', first_name: 'Hari', middle_name: '', last_name: 'Tamang', age: 36,
    gender: 'Male', blood_group: 'O+', allergies: '', current_medication: '', status: 'Active',
  }
  const page = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results })

  function asAdminWith(smartReply: unknown) {
    server.use(
      http.get(`${API}/auth/me/`, () => HttpResponse.json({ id: 1, username: 'admin', first_name: 'Site', last_name: 'Admin', role: 'ADMIN' })),
      http.get(`${API}/patients/`, () => HttpResponse.json(page([hari]))),
      http.get(`${API}/assignments/`, () => HttpResponse.json(page([]))),
      http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json(smartReply)),
    )
  }

  it('shows Assign beside each doctor even with no patient chosen, and asks for the patient', async () => {
    let posted: unknown = null
    asAdminWith({ ...ok, patient: null })
    server.use(http.post(`${API}/assignments/`, async ({ request }) => {
      posted = await request.json()
      return HttpResponse.json({ id: 9, doctor: 6, patient: 42, status: 'Active', assigned_date: '2026-10-04' }, { status: 201 })
    }))
    const user = userEvent.setup()
    renderPage(<SymptomCheckerPage />)
    await user.click(await screen.findByLabelText(/What are you feeling/))
    await user.paste('chest pain, breathlessness and sweating')
    await user.click(screen.getByRole('button', { name: /Check symptoms/ }))

    const step3 = await screen.findByRole('region', { name: /Step 3/ })
    expect(within(step3).getByRole('columnheader', { name: 'Assign' })).toBeInTheDocument()
    await user.click(within(step3).getByRole('button', { name: 'Assign a patient to Dr. Gita Shrestha' }))

    const dialog = await screen.findByRole('dialog', { name: 'Assign to Dr. Gita Shrestha' })
    const confirm = within(dialog).getByRole('button', { name: 'Assign' })
    expect(confirm).toBeDisabled()                                      // a patient must be chosen first
    await user.click(within(dialog).getByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: 'Hari Tamang · PAT-79028232' }))
    await user.click(confirm)
    await waitFor(() => expect(posted).toEqual({ doctor: 6, patient: 42 }))
  })

  it('uses the chosen patient even if the reply does not name the patient', async () => {
    asAdminWith({ ...ok })                                              // no "patient" field
    const user = userEvent.setup()
    renderPage(<SymptomCheckerPage />)
    await user.click(await screen.findByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: 'Hari Tamang · PAT-79028232' }))
    await user.click(screen.getByLabelText('Symptoms of Hari Tamang'))
    await user.paste('chest pain, breathlessness and sweating')
    await user.click(screen.getByRole('button', { name: /Check symptoms/ }))
    expect(await screen.findByRole('button', { name: 'Assign Hari Tamang to Dr. Gita Shrestha' })).toBeInTheDocument()
  })
})

describe('SymptomCheckerPage TOPSIS experience column', () => {
  it('shows each doctor\'s years of experience in the ranking', async () => {
    server.use(http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({
      ...ok, doctors: [{ ...ok.doctors[0], experience_years: 14, reason: 'most experience' }],
    })))
    await check('chest pain, breathlessness and sweating')
    const step3 = await screen.findByRole('region', { name: /Step 3/ })
    expect(within(step3).getByRole('columnheader', { name: 'Experience (years)' })).toBeInTheDocument()
    expect(within(step3).getByRole('cell', { name: '14' })).toBeInTheDocument()
    expect(within(step3).queryByText('most experience')).not.toBeInTheDocument()   // "Best match" badge is enough
  })
})
