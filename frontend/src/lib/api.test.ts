import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { API, server } from '@/test/server'
import { patientService } from './api'

describe('list endpoints', () => {
  it('return rows from every page, not just the first', async () => {
    server.use(http.get(`${API}/patients/`, ({ request }) => {
      const page = Number(new URL(request.url).searchParams.get('page') ?? 1)
      const rows = page === 1 ? [{ id: 1 }, { id: 2 }] : [{ id: 3 }]
      return HttpResponse.json({ count: 3, next: page === 1 ? 'next' : null, previous: null, results: rows })
    }))
    const patients = await patientService.list()
    expect(patients.map((p) => p.id)).toEqual([1, 2, 3])
  })
})
