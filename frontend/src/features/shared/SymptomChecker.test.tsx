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
  symptoms: ['heartburn', 'worse after eating', 'worse lying down'],
  illnesses: [
    { name: 'GERD', probability: 0.4954 },
    { name: 'Pancreatic neoplasm', probability: 0.4154 },
    { name: 'Boerhaave', probability: 0.0288 },
  ],
  department: 'Gastroenterology',
  dept_probability: 0.9694,
  doctors: [
    { id: 4, name: 'Anita Rai', department: 'Gastroenterology', specialization: 'Hepatology', score: 0.82, free_hours: 12, caseload: 1, reason: 'most free hours, lightest caseload' },
    { id: 9, name: 'Ram Thapa', department: 'Gastroenterology', specialization: 'Gastroenterology', score: 0.4, free_hours: 6, caseload: 4, reason: '6 free hours this week, 4 active patients' },
  ],
  doctors_department: 'Gastroenterology',
  doctors_note: '',
  history_id: 12,
  disclaimer: DISCLAIMER,
}

const keywordResult = {
  id: 3, symptoms: 'heartburn', pain_level: 4, recommended_department: 'Gastroenterology', confidence: 60,
  reason: 'Recommended Gastroenterology (confidence 60%).', clinical_severity: 10, ranked_doctors: [],
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
    await describeSymptoms('heartburn, worse after eating and worse lying down')

    expect(await screen.findByText('Likely area: Gastroenterology (97%)')).toBeInTheDocument()
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument()
    const illnesses = screen.getByText('Possible illnesses').parentElement!
    expect(within(illnesses).getByText('GERD')).toBeInTheDocument()
    expect(within(illnesses).getByText('50%')).toBeInTheDocument()
    expect(within(illnesses).getByText('Boerhaave')).toBeInTheDocument()
    expect(screen.getByText('Dr. Anita Rai')).toBeInTheDocument()
    expect(screen.getByText('most free hours, lightest caseload')).toBeInTheDocument()
    expect(screen.getByText('Best match')).toBeInTheDocument()
    expect(keywordCalled).toBe(false)                    // no fallback needed
  })

  it('shows "not enough information" with General Medicine instead of a keyword guess', async () => {
    let keywordCalled = false
    server.use(
      http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({
        status: 'low_confidence', reason: 'unseen_combination', symptoms: ['fever', 'nausea', 'dizziness'],
        department: 'General Medicine', message: 'Not enough information to suggest a specific area of care.',
        safety_net: 'Get emergency help straight away if you faint.',
        doctors: [{ id: 6, name: 'Gita Shrestha', department: 'General Medicine', specialization: 'Internal Medicine', score: 1, reason: 'r' }],
        disclaimer: DISCLAIMER })),
      http.post(`${API}/recommendations/`, () => { keywordCalled = true; return HttpResponse.json(keywordResult, { status: 201 }) }),
    )
    await describeSymptoms('fever, nausea, dizziness')

    expect(await screen.findByText('Not enough information: General Medicine')).toBeInTheDocument()
    expect(screen.getByText(/Get emergency help/)).toBeInTheDocument()
    expect(screen.getByText('Dr. Gita Shrestha')).toBeInTheDocument()
    expect(keywordCalled).toBe(false)
  })

  it('lists unclear spellings instead of guessing', async () => {
    server.use(http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({
      status: 'needs_confirmation', symptoms: ['cough'], disclaimer: DISCLAIMER,
      suggestions: [{ term: 'feverr', symptom: 'E_91', label: 'fever', score: 90.9 }] })))
    await describeSymptoms('feverr and cough')
    expect(await screen.findByText('Please check the spelling')).toBeInTheDocument()
    expect(screen.getByText(/for “feverr”/)).toBeInTheDocument()
  })

  it('falls back to the keyword match when the smart check fails', async () => {
    server.use(
      http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({ detail: 'error' }, { status: 500 })),
      http.post(`${API}/recommendations/`, () => HttpResponse.json(keywordResult, { status: 201 })),
    )
    await describeSymptoms('heartburn')
    expect(await screen.findByText('Recommended department')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(/not available right now/)
  })

  it('shows the note when doctors come from another department', async () => {
    server.use(http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({
      ...smartOk, department: 'Emergency Medicine', doctors_department: 'General Medicine',
      doctors_note: 'No Emergency Medicine doctor is available right now, so General Medicine doctors are shown as a first point of contact.',
    })))
    await describeSymptoms('palpitations, shortness of breath and feeling faint')
    expect(await screen.findByText(/No Emergency Medicine doctor is available/)).toBeInTheDocument()
  })

  it('shows an emergency alert for red-flag symptoms without a keyword fallback', async () => {
    let keywordCalled = false
    server.use(
      http.post(`${API}/smart-symptom-check/`, () => HttpResponse.json({
        status: 'emergency', symptoms: ['chest pain at rest'], department: 'Emergency Medicine',
        red_flags: [{ id: 'chest_pain_at_rest', message: 'Chest pain at rest' }],
        message: 'Please go to the nearest emergency department now.', disclaimer: DISCLAIMER,
      })),
      http.post(`${API}/recommendations/`, () => { keywordCalled = true; return HttpResponse.json(keywordResult, { status: 201 }) }),
    )
    await describeSymptoms('chest pain at rest')
    expect(await screen.findByRole('alert')).toHaveTextContent('Chest pain at rest')
    expect(screen.queryByText('Recommended department')).not.toBeInTheDocument()
    expect(keywordCalled).toBe(false)
  })
})
