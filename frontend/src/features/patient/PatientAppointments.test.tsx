import { describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { API, server } from '@/test/server'
import { renderPage } from '@/test/render'
import { PatientAppointments } from './PatientAppointments'

// Radix Select (the doctor dropdown) uses pointer capture and scrollIntoView, which jsdom lacks.
Element.prototype.hasPointerCapture ??= () => false
Element.prototype.releasePointerCapture ??= () => {}
Element.prototype.scrollIntoView ??= () => {}

const DOCTORS = [
  { id: 3, doctor_id: 'DOC-3', first_name: 'Arjun', last_name: 'Sharma', department: 'Cardiology', status: 'Active' },
  { id: 4, doctor_id: 'DOC-4', first_name: 'Mina', last_name: 'Rai', department: 'Neurology', status: 'Active' },
]
const DATES: Record<string, string[]> = { 3: ['2026-10-05', '2026-10-12'], 4: ['2026-10-07'] }

function mockApi({ slots = { '2026-10-05': ['10:30'], '2026-10-12': ['09:00', '09:30'], '2026-10-07': ['14:00'] } as Record<string, string[]> } = {}) {
  const posted: unknown[] = []
  const slotRequests: string[] = []
  server.use(
    http.get(`${API}/appointments/my/`, () => HttpResponse.json([])),
    http.get(`${API}/doctors/`, () => HttpResponse.json(DOCTORS)),
    http.get(`${API}/doctors/:id/available-dates/`, ({ params }) => HttpResponse.json({
      doctor: Number(params.id), today: '2026-10-05', days: 30, dates: DATES[params.id as string],
    })),
    http.get(`${API}/doctors/:id/available-slots/`, ({ params, request }) => {
      const date = new URL(request.url).searchParams.get('date')!
      slotRequests.push(date)
      return HttpResponse.json({ doctor: Number(params.id), date, slots: slots[date] ?? [] })
    }),
    http.post(`${API}/appointments/`, async ({ request }) => {
      posted.push(await request.json())
      return HttpResponse.json({ id: 'a1', status: 'PENDING' }, { status: 201 })
    }),
  )
  return { posted, slotRequests, slots }
}

async function openAndPickDoctor(user: ReturnType<typeof userEvent.setup>, name = 'Dr. Arjun Sharma · Cardiology') {
  renderPage(<PatientAppointments />)
  await user.click(screen.getAllByRole('button', { name: /book appointment/i })[0])
  const dialog = await screen.findByRole('dialog')
  await user.click(within(dialog).getByRole('combobox'))
  await user.click(await screen.findByRole('option', { name }))
  return dialog
}

describe('Booking an appointment from the doctor schedule', () => {
  it('enables only the available dates and books an offered time', async () => {
    const user = userEvent.setup()
    const { posted } = mockApi()
    const dialog = await openAndPickDoctor(user)

    expect(await within(dialog).findByRole('button', { name: 'Monday, October 12, 2026' })).toBeEnabled()
    expect(within(dialog).getByRole('button', { name: 'Tuesday, October 6, 2026, unavailable' })).toBeDisabled()

    await user.click(within(dialog).getByRole('button', { name: 'Monday, October 12, 2026' }))
    const times = await within(dialog).findByRole('group', { name: 'Available times' })
    expect(within(times).getAllByRole('button').map((b) => b.textContent)).toEqual(['9:00 AM', '9:30 AM'])

    await user.click(within(times).getByRole('button', { name: '9:30 AM' }))
    await user.click(within(dialog).getByRole('button', { name: 'Request appointment' }))

    await waitFor(() => expect(posted).toEqual([
      { doctor: 3, appointment_date: '2026-10-12', appointment_time: '09:30' },
    ]))
  })

  it('resets the time when the date changes and both when the doctor changes', async () => {
    const user = userEvent.setup()
    mockApi()
    const dialog = await openAndPickDoctor(user)

    await user.click(await within(dialog).findByRole('button', { name: 'Monday, October 12, 2026' }))
    await user.click(await within(dialog).findByRole('button', { name: '9:00 AM' }))
    expect(within(dialog).getByRole('button', { name: 'Request appointment' })).toBeEnabled()

    await user.click(within(dialog).getByRole('button', { name: 'Monday, October 5, 2026' }))
    expect(await within(dialog).findByRole('button', { name: '10:30 AM' })).toHaveAttribute('aria-pressed', 'false')
    expect(within(dialog).getByRole('button', { name: 'Request appointment' })).toBeDisabled()

    await user.click(within(dialog).getByRole('button', { name: '10:30 AM' }))
    await user.click(within(dialog).getByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: 'Dr. Mina Rai · Neurology' }))

    expect(await within(dialog).findByRole('button', { name: 'Wednesday, October 7, 2026' })).toHaveAttribute('aria-pressed', 'false')
    expect(within(dialog).queryByRole('group', { name: 'Available times' })).not.toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Request appointment' })).toBeDisabled()
  })

  it('refetches the times after the slot is taken by someone else', async () => {
    const user = userEvent.setup()
    const error = vi.spyOn(toast, 'error')
    const { slotRequests, slots } = mockApi()
    server.use(http.post(`${API}/appointments/`, () => {
      slots['2026-10-12'] = ['09:00']   // the other booking now holds 09:30
      return HttpResponse.json(
        { detail: 'Sorry, that time was just booked by someone else. Please choose another time.', code: 'slot_taken' },
        { status: 409 },
      )
    }))
    const dialog = await openAndPickDoctor(user)

    await user.click(await within(dialog).findByRole('button', { name: 'Monday, October 12, 2026' }))
    await user.click(await within(dialog).findByRole('button', { name: '9:30 AM' }))
    await user.click(within(dialog).getByRole('button', { name: 'Request appointment' }))

    await waitFor(() => expect(error).toHaveBeenCalledWith(
      'Sorry, that time was just booked by someone else. Please choose another time.',
    ))
    await waitFor(() => expect(within(dialog).queryByRole('button', { name: '9:30 AM' })).not.toBeInTheDocument())
    expect(slotRequests.filter((d) => d === '2026-10-12')).toHaveLength(2)
    expect(within(dialog).getByRole('button', { name: 'Request appointment' })).toBeDisabled()
  })
})
