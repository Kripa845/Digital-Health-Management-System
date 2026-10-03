import { describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { API, server } from '@/test/server'
import { renderPage } from '@/test/render'
import { SymptomChecker } from './SymptomChecker'

const DISCLAIMER = 'Suggestion only, not a medical diagnosis.'

const smartOk = {
  status: 'ok',
  symptoms: ['itching', 'nodal skin eruptions', 'skin rash'],
  illnesses: [
    { name: 'Fungal infection', probability: 0.4954 },
    { name: 'Drug Reaction', probability: 0.4154 },
    { name: 'Psoriasis', probability: 0.0288 },
  ],
  department: 'Dermatology',
  dept_probability: 0.9694,
  doctors: [
    { id: 4, name: 'Anita Rai', department: 'Dermatology', specialization: 'Cosmetic Dermatology', score: 0.82, free_hours: 12, caseload: 1, reason: 'most free hours, lightest caseload' },
    { id: 9, name: 'Ram Thapa', department: 'Dermatology', specialization: 'Dermatology', score: 0.4, free_hours: 6, caseload: 4, reason: '6 free hours this week, 4 active patients' },
  ],
  doctors_department: 'Dermatology',
  doctors_note: '',
  history_id: 12,
  disclaimer: DISCLAIMER,
}

const keywordResult = {
  id: 3, symptoms: 'itching', pain_level: 4, recommended_department: 'Dermatology', confidence: 60,
  reason: 'Recommended Dermatology (confidence 60%).', clinical_severity: 10, ranked_doctors: [],
}

async function describeSymptoms(text: string) {
  const user = userEvent.setup()
  renderPage(<SymptomChecker />)
  await user.click(screen.getByLabelText(/What are you feeling/))
  await user.paste(text)
  await user.click(screen.getByRole('button', { name: /Find the right doctor/ }))
  return user
}

describe('SymptomChecker smart check', () => {
  it('shows the likely area, illnesses, ranked doctors and the disclaimer', async () => {
    let keywordCalled = false
    server.use(
      http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json(smartOk)),
      http.post(`${API}/recommendations/`, () => { keywordCalled = true; return HttpResponse.json(keywordResult, { status: 201 }) }),
    )
    await describeSymptoms('itching, skin rash and nodal skin eruptions')

    expect(await screen.findByText('Likely area: Dermatology (97%)')).toBeInTheDocument()
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument()
    const illnesses = screen.getByText('Possible illnesses').parentElement!
    expect(within(illnesses).getByText('Fungal infection')).toBeInTheDocument()
    expect(within(illnesses).getByText('50%')).toBeInTheDocument()
    expect(within(illnesses).getByText('Psoriasis')).toBeInTheDocument()
    expect(screen.getByText('Dr. Anita Rai')).toBeInTheDocument()
    expect(screen.getByText('most free hours, lightest caseload')).toBeInTheDocument()
    expect(screen.getByText('Best match')).toBeInTheDocument()
    expect(keywordCalled).toBe(false)                    // no fallback needed
  })

  it('asks for more symptoms and shows the keyword match when there is not enough information', async () => {
    server.use(
      http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({ status: 'not_enough_info', symptoms: ['itching'], disclaimer: DISCLAIMER })),
      http.post(`${API}/recommendations/`, () => HttpResponse.json(keywordResult, { status: 201 })),
    )
    await describeSymptoms('itching')

    expect(await screen.findByRole('status')).toHaveTextContent(/Please add more symptoms/)
    expect(screen.getByText('Recommended department')).toBeInTheDocument()     // the old keyword result
    expect(screen.getByText('Dermatology')).toBeInTheDocument()
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument()
  })

  it('explains a low-confidence result and falls back', async () => {
    server.use(
      http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({ status: 'low_confidence', symptoms: ['cough', 'headache'], disclaimer: DISCLAIMER })),
      http.post(`${API}/recommendations/`, () => HttpResponse.json(keywordResult, { status: 201 })),
    )
    await describeSymptoms('headache and cough')
    expect(await screen.findByRole('status')).toHaveTextContent(/could point to several areas/)
  })

  it('falls back to the keyword match when the smart check fails', async () => {
    server.use(
      http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({ detail: 'error' }, { status: 500 })),
      http.post(`${API}/recommendations/`, () => HttpResponse.json(keywordResult, { status: 201 })),
    )
    await describeSymptoms('itching')
    expect(await screen.findByText('Recommended department')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(/not available right now/)
  })

  it('shows the note when doctors come from another department', async () => {
    server.use(http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({
      ...smartOk, department: 'Emergency Medicine', doctors_department: 'General Medicine',
      doctors_note: 'No Emergency Medicine doctor is available right now, so General Medicine doctors are shown as a first point of contact.',
    })))
    await describeSymptoms('chest pain, breathlessness and sweating')
    expect(await screen.findByText(/No Emergency Medicine doctor is available/)).toBeInTheDocument()
  })
})
