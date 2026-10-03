import axios, { type AxiosInstance } from 'axios'
import type {
  AccessRequest, AdminStats, Appointment, AppointmentStats, AuditLog,
  CurrentUser, Doctor, DoctorAssignment, LabReport, LoginResponse, MedDocument,
  ApiErrorBody, ConfirmPayload, LabDashboard, LabReportStatusInfo, LabReviewItem,
  Notification, Patient, Prescription, Recommendation, Session, SmartCheckResult,
} from './types'

const API_ROOT =
  (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || ''
// In dev, Vite proxies /api -> backend. In prod, VITE_API_URL points at the API host.
const BASE = `${API_ROOT}/api/v1`

const SESSION_KEYS = [
  'access_token', 'refresh_token', 'user_role', 'user_name',
  'profile_id', 'uuid_token', 'must_change_password',
]

export const session = {
  get access() { return localStorage.getItem('access_token') },
  get refresh() { return localStorage.getItem('refresh_token') },
  get role() { return localStorage.getItem('user_role') as Session['role'] | null },
  get name() { return localStorage.getItem('user_name') },
  get profileId() { return localStorage.getItem('profile_id') },
  get uuidToken() { return localStorage.getItem('uuid_token') },
  get mustChangePassword() { return localStorage.getItem('must_change_password') === 'true' },
  save(data: Partial<Session>) {
    if (data.access) localStorage.setItem('access_token', data.access)
    if (data.refresh) localStorage.setItem('refresh_token', data.refresh)
    if (data.role) localStorage.setItem('user_role', data.role)
    const name = `${data.first_name || ''} ${data.last_name || ''}`.trim() || data.username
    if (name) localStorage.setItem('user_name', name)
    if (data.profile_id) localStorage.setItem('profile_id', data.profile_id)
    if (data.uuid_token) localStorage.setItem('uuid_token', data.uuid_token)
    localStorage.setItem('must_change_password', data.must_change_password ? 'true' : 'false')
  },
  clear() { SESSION_KEYS.forEach((k) => localStorage.removeItem(k)) },
}

export const api: AxiosInstance = axios.create({
  baseURL: BASE,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = session.access
  if (token && config.headers) config.headers.Authorization = `Bearer ${token}`
  return config
})

let refreshPromise: Promise<string> | null = null
async function refreshAccessToken(): Promise<string> {
  const refresh = session.refresh
  if (!refresh) throw new Error('No refresh token')
  const res = await axios.post(`${BASE}/auth/token/refresh/`, { refresh })
  localStorage.setItem('access_token', res.data.access)
  if (res.data.refresh) localStorage.setItem('refresh_token', res.data.refresh)
  return res.data.access as string
}

api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config
    if (error.response?.status === 401 && !original?._retry && session.refresh) {
      original._retry = true
      try {
        refreshPromise = refreshPromise || refreshAccessToken().finally(() => { refreshPromise = null })
        const token = await refreshPromise
        original.headers = original.headers || {}
        original.headers.Authorization = `Bearer ${token}`
        return api(original)
      } catch (e) {
        session.clear()
        if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
          window.location.href = '/login'
        }
        return Promise.reject(e)
      }
    }
    return Promise.reject(error)
  },
)

/**
 * GET a list endpoint and return every row. Paginated endpoints return 10 rows
 * per page by default, so reading only `results` silently dropped everything
 * after the first page; this follows the pages (200 rows each) to the end.
 */
async function listAll<T>(url: string, params?: Record<string, unknown>): Promise<T[]> {
  const rows: T[] = []
  for (let page = 1; page <= 100; page++) {
    const { data } = await api.get(url, { params: { ...params, page, page_size: 200 } })
    if (Array.isArray(data)) return data as T[]          // endpoint is not paginated
    rows.push(...((data?.results ?? []) as T[]))
    if (!data?.next) break
  }
  return rows
}

// ── Auth ──────────────────────────────────────────────────────────────
export const authService = {
  login: async (username: string, password: string): Promise<LoginResponse> => {
    const res = await axios.post(`${BASE}/auth/login/`, { username, password })
    if (res.data.access) {
      // Drop anything left from a previous user (e.g. a patient's QR token) first.
      session.clear()
      session.save(res.data)
    }
    return res.data
  },
  me: async (): Promise<CurrentUser> => (await api.get('/auth/me/')).data,
  /** Revoke the refresh token on the server, then clear the local session. */
  logout: async () => {
    const refresh = session.refresh
    session.clear()
    if (refresh) {
      try { await axios.post(`${BASE}/auth/logout/`, { refresh }) } catch { /* already signed out */ }
    }
  },
  changePassword: async (old_password: string, new_password: string) => {
    const res = await api.post('/auth/change-password/', { old_password, new_password })
    localStorage.setItem('must_change_password', 'false')
    return res.data
  },
  adminStats: async (): Promise<AdminStats> => (await api.get('/auth/admin/stats/')).data,
  adminResetPassword: async (user_id: number, new_password: string) =>
    (await api.post('/auth/admin/reset-password/', { user_id, new_password })).data,
  listAdmins: async (): Promise<CurrentUser[]> => listAll('/auth/admin/manage-admins/'),
  createAdmin: async (data: any) => (await api.post('/auth/admin/manage-admins/', data)).data,
}

// ── Patients ──────────────────────────────────────────────────────────
export const patientService = {
  list: async (params?: any): Promise<Patient[]> => listAll('/patients/', params),
  retrieve: async (id: number | string): Promise<Patient> => (await api.get(`/patients/${id}/`)).data,
  create: async (data: FormData) =>
    (await api.post('/patients/', data, { headers: { 'Content-Type': 'multipart/form-data' } })).data,
  update: async (id: number | string, data: FormData) =>
    (await api.patch(`/patients/${id}/`, data, { headers: { 'Content-Type': 'multipart/form-data' } })).data,
  remove: async (id: number | string) => (await api.delete(`/patients/${id}/`)).data,
  /** Patient: update own name, contact details and photo. */
  updateMe: async (data: FormData): Promise<Patient> =>
    (await api.patch('/patients/me/', data, { headers: { 'Content-Type': 'multipart/form-data' } })).data,
  publicProfile: async (uuid: string): Promise<Patient> =>
    (await axios.get(`${BASE}/patients/public/${uuid}/`)).data,
  scan: async (uuid: string) => (await api.get(`/patients/scan/${uuid}/`)).data,
  toggleStatus: async (id: number | string) => (await api.patch(`/patients/${id}/toggle_status/`)).data,
  resetPassword: async (id: number | string, new_password?: string) =>
    (await api.post(`/patients/${id}/reset_password/`, new_password ? { new_password } : {})).data,
  regenerateQr: async (id: number | string): Promise<{ patient_id: string; uuid_token: string }> =>
    (await api.post(`/patients/${id}/regenerate_qr/`)).data,
  stats: async () => (await api.get('/patients/stats/')).data,
}

// ── Doctors ───────────────────────────────────────────────────────────
export const doctorService = {
  list: async (params?: any): Promise<Doctor[]> => listAll('/doctors/', params),
  retrieve: async (id: number | string): Promise<Doctor> => (await api.get(`/doctors/${id}/`)).data,
  create: async (data: FormData) =>
    (await api.post('/doctors/', data, { headers: { 'Content-Type': 'multipart/form-data' } })).data,
  update: async (id: number | string, data: FormData) =>
    (await api.patch(`/doctors/${id}/`, data, { headers: { 'Content-Type': 'multipart/form-data' } })).data,
  remove: async (id: number | string) => (await api.delete(`/doctors/${id}/`)).data,
  resetPassword: async (id: number | string, new_password?: string) =>
    (await api.post(`/doctors/${id}/reset_password/`, new_password ? { new_password } : {})).data,
}

// ── Assignments ───────────────────────────────────────────────────────
export const assignmentService = {
  list: async (params?: any): Promise<DoctorAssignment[]> => listAll('/assignments/', params),
  create: async (doctor: number, patient: number) => (await api.post('/assignments/', { doctor, patient })).data,
  remove: async (id: number) => (await api.delete(`/assignments/${id}/`)).data,
}

// ── Prescriptions ─────────────────────────────────────────────────────
export const prescriptionService = {
  list: async (params?: any): Promise<Prescription[]> => listAll('/prescriptions/', params),
  create: async (data: { patient: number; diagnosis: string; medications: string; notes?: string }) =>
    (await api.post('/prescriptions/', data)).data,
  update: async (id: number, data: Partial<Prescription>) => (await api.patch(`/prescriptions/${id}/`, data)).data,
  remove: async (id: number) => (await api.delete(`/prescriptions/${id}/`)).data,
}

// ── Recommendations ───────────────────────────────────────────────────
export const recommendationService = {
  list: async (params?: any): Promise<Recommendation[]> => listAll('/recommendations/', params),
  create: async (data: {
    symptoms: string; pain_level: number; age?: number; medical_history?: string; patient_id?: number
  }): Promise<Recommendation> => (await axios.post(`${BASE}/recommendations/`, data, {
    headers: session.access ? { Authorization: `Bearer ${session.access}` } : {},
  })).data,
  /** Naive Bayes + TOPSIS suggestion; open to guests like create(). */
  smartCheck: async (data: { text: string; patient_id?: number }): Promise<SmartCheckResult> =>
    (await axios.post(`${BASE}/smart-symptom-check/`, data, {
      headers: session.access ? { Authorization: `Bearer ${session.access}` } : {},
    })).data,
}

// ── Documents ─────────────────────────────────────────────────────────
export const documentService = {
  list: async (params?: any): Promise<MedDocument[]> => listAll('/documents/', params),
  upload: async (patientId: number, name: string, file: File, reportType: 'MEDICAL' | 'ADDITIONAL' = 'ADDITIONAL') => {
    const fd = new FormData()
    fd.append('patient', String(patientId))
    fd.append('name', name)
    fd.append('file', file)
    fd.append('report_type', reportType)
    return (await api.post('/documents/', fd, { headers: { 'Content-Type': 'multipart/form-data' } })).data
  },
  download: async (id: number): Promise<Blob> =>
    (await api.get(`/documents/${id}/download/`, { responseType: 'blob' })).data,
  remove: async (id: number) => (await api.delete(`/documents/${id}/`)).data,
}

// ── Appointments ──────────────────────────────────────────────────────
export const appointmentService = {
  list: async (params?: any): Promise<Appointment[]> => listAll('/appointments/', params),
  mine: async (params?: any): Promise<Appointment[]> => listAll('/appointments/my/', params),
  forDoctor: async (params?: any): Promise<Appointment[]> => listAll('/appointments/doctor/', params),
  stats: async (): Promise<AppointmentStats> => (await api.get('/appointments/stats/')).data,
  create: async (data: { doctor: number; appointment_date: string; appointment_time: string; reason?: string }) =>
    (await api.post('/appointments/', data)).data,
  accept: async (id: string) => (await api.post(`/appointments/${id}/accept/`)).data,
  decline: async (id: string) => (await api.post(`/appointments/${id}/decline/`)).data,
  cancel: async (id: string) => (await api.post(`/appointments/${id}/cancel/`)).data,
  complete: async (id: string) => (await api.post(`/appointments/${id}/complete/`)).data,
}

// ── Notifications ─────────────────────────────────────────────────────
export const notificationService = {
  list: async (): Promise<Notification[]> => listAll('/notifications/'),
  markRead: async (id: string) => (await api.post(`/notifications/${id}/mark-read/`)).data,
  markAllRead: async () => (await api.post('/notifications/mark-all-read/')).data,
}

// ── Access requests ───────────────────────────────────────────────────
export const accessRequestService = {
  list: async (params?: any): Promise<AccessRequest[]> => listAll('/access-requests/', params),
  create: async (patient: number, reason?: string) => (await api.post('/access-requests/', { patient, reason })).data,
  approve: async (id: number) => (await api.post(`/access-requests/${id}/approve/`)).data,
  decline: async (id: number) => (await api.post(`/access-requests/${id}/decline/`)).data,
}

// ── Audit ─────────────────────────────────────────────────────────────
export const auditService = {
  list: async (params?: any): Promise<AuditLog[]> => listAll('/audit-logs/', params),
}

// ── Lab Reports ───────────────────────────────────────────────────────────────
// Contract: docs/lab-reports-api.md. Upload returns a preview only; nothing is
// saved to the health record until `confirm`.

export const labReportService = {
  /** Report history (newest first). Pass { patient: id } as an admin. */
  list: async (params?: any): Promise<LabReport[]> =>
    listAll('/reports/', params),

  retrieve: async (id: number): Promise<LabReport> =>
    (await api.get(`/reports/${id}/`)).data,

  status: async (id: number): Promise<LabReportStatusInfo> =>
    (await api.get(`/reports/${id}/status/`)).data,

  /**
   * Upload a PDF/PNG/JPG. Returns the report as a preview (PENDING_CONFIRMATION) or
   * NEEDS_REVIEW. Errors: 400 bad file, 409 duplicate, 422 patient ID mismatch / no values.
   * `patientId` is required for admins and ignored for patients (their own record is used).
   */
  upload: async (
    file: File,
    options: { name?: string; patientId?: number; onProgress?: (pct: number) => void } = {},
  ): Promise<LabReport> => {
    const fd = new FormData()
    fd.append('file', file)
    if (options.name) fd.append('name', options.name.trim())
    if (options.patientId != null) fd.append('patient', String(options.patientId))
    const res = await api.post('/reports/upload/', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: options.onProgress
        ? (evt) => { if (evt.total) options.onProgress!(Math.round((evt.loaded / evt.total) * 100)) }
        : undefined,
    })
    return res.data as LabReport
  },

  /** Apply the preview. Corrections and accepted out-of-range values are re-checked by the server. */
  confirm: async (id: number, payload: ConfirmPayload = {}): Promise<LabReport> =>
    (await api.post(`/reports/${id}/confirm/`, payload)).data,

  /** Set the report date typed or corrected in the preview (YYYY-MM-DD); returns the re-planned report. */
  setReportDate: async (id: number, report_date: string): Promise<LabReport> =>
    (await api.post(`/reports/${id}/report-date/`, { report_date })).data,

  /** Cancel an unconfirmed report; it and its file are deleted. */
  discard: async (id: number): Promise<void> => {
    await api.post(`/reports/${id}/discard/`)
  },

  /** The original uploaded file. */
  download: async (id: number): Promise<Blob> => {
    try {
      return (await api.get(`/reports/${id}/download/`, { responseType: 'blob' })).data
    } catch (err) {
      // Error bodies arrive as a Blob too; turn them back into JSON so the message can be shown.
      const res = (err as { response?: { data?: unknown } }).response
      if (res?.data instanceof Blob) {
        try { res.data = JSON.parse(await res.data.text()) } catch { /* not JSON: keep the generic message */ }
      }
      throw err
    }
  },

  /** Admin: read an unconfirmed report again and rebuild its preview. */
  reprocess: async (id: number): Promise<LabReport> =>
    (await api.post(`/reports/${id}/reprocess/`)).data,

  remove: async (id: number): Promise<void> => {
    await api.delete(`/reports/${id}/`)
  },

  /** Cards for the dashboard: latest value, status, history and trend per test. */
  dashboard: async (patientId?: number): Promise<LabDashboard> =>
    (await api.get('/dashboard/', { params: patientId != null ? { patient: patientId } : undefined })).data,

  /** Admin: reports the identity gate could not verify. */
  reviewQueue: async (): Promise<LabReviewItem[]> =>
    (await api.get('/admin/review-queue/')).data,

  /** Admin: approve (→ awaiting confirmation) or reject a report under review. */
  resolve: async (id: number, decision: 'approve' | 'reject', note = ''): Promise<LabReviewItem> =>
    (await api.post(`/admin/reports/${id}/resolve/`, { decision, note })).data,
}

/** Normalise any API failure to { code, message } (network failures included). */
export function apiErrorBody(err: unknown): ApiErrorBody & { status?: number } {
  const e = err as { response?: { status?: number; data?: any }; message?: string }
  const data = e?.response?.data
  if (!e?.response) {
    return { code: 'network_error', message: 'Could not reach the server. Check your connection and try again.' }
  }
  if (data && typeof data === 'object' && typeof data.message === 'string') {
    return { code: data.code ?? 'error', message: data.message, errors: data.errors, status: e.response.status }
  }
  return {
    code: 'error',
    message: (data && typeof data.detail === 'string' && data.detail) || 'Something went wrong. Please try again.',
    status: e.response.status,
  }
}
