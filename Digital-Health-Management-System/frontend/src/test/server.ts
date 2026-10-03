/** MSW server shared by component tests. Tests add handlers with server.use(). */
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

export const API = '/api/v1'

export const server = setupServer(
  // The auth context asks who is logged in; tests run as a patient.
  http.get(`${API}/auth/me/`, () => HttpResponse.json({
    id: 1, username: 'asha', first_name: 'Asha', last_name: 'Gurung', role: 'PATIENT',
    patient_profile: { id: 7, patient_id: 'PAT-0E2E0001', first_name: 'Asha', last_name: 'Gurung' },
  })),
)
