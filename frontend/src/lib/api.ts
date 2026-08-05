import axios, { type AxiosInstance } from 'axios'
import type {
  AccessRequest, AdminStats, Appointment, AppointmentStats, AuditLog,
  CurrentUser, Doctor, DoctorAssignment, LabReport, LoginResponse, MedDocument,
  Notification, Patient, Prescription, Recommendation, Session,
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

function unwrap<T>(data: any): T[] {
  return Array.isArray(data) ? data : (data?.results ?? [])
}

// ── Auth ──────────────────────────────────────────────────────────────
export const authService = {
  login: async (username: string, password: string): Promise<LoginResponse> => {
    const res = await axios.post(`${BASE}/auth/login/`, { username, password })
    if (res.data.access) session.save(res.data)
    return res.data
  },
  me: async (): Promise<CurrentUser> => (await api.get('/auth/me/')).data,
  logout: () => session.clear(),
  changePassword: async (old_password: string, new_password: string) => {
    const res = await api.post('/auth/change-password/', { old_password, new_password })
    localStorage.setItem('must_change_password', 'false')
    return res.data
  },
  adminStats: async (): Promise<AdminStats> => (await api.get('/auth/admin/stats/')).data,
  adminResetPassword: async (user_id: number, new_password: string) =>
    (await api.post('/auth/admin/reset-password/', { user_id, new_password })).data,
  listAdmins: async (): Promise<CurrentUser[]> => unwrap((await api.get('/auth/admin/manage-admins/')).data),
  createAdmin: async (data: any) => (await api.post('/auth/admin/manage-admins/', data)).data,
}

// ── Patients ──────────────────────────────────────────────────────────
export const patientService = {
  list: async (params?: any): Promise<Patient[]> => unwrap((await api.get('/patients/', { params })).data),
  retrieve: async (id: number | string): Promise<Patient> => (await api.get(`/patients/${id}/`)).data,
  create: async (data: FormData) =>
    (await api.post('/patients/', data, { headers: { 'Content-Type': 'multipart/form-data' } })).data,
  update: async (id: number | string, data: FormData) =>
    (await api.patch(`/patients/${id}/`, data, { headers: { 'Content-Type': 'multipart/form-data' } })).data,
  remove: async (id: number | string) => (await api.delete(`/patients/${id}/`)).data,
  publicProfile: async (uuid: string): Promise<Patient> =>
    (await axios.get(`${BASE}/patients/public/${uuid}/`)).data,
  scan: async (uuid: string) => (await api.get(`/patients/scan/${uuid}/`)).data,
  qrUrl: (id: number | string) => `${BASE}/patients/${id}/qr/`,
  toggleStatus: async (id: number | string) => (await api.patch(`/patients/${id}/toggle_status/`)).data,
  resetPassword: async (id: number | string, new_password?: string) =>
    (await api.post(`/patients/${id}/reset_password/`, new_password ? { new_password } : {})).data,
  stats: async () => (await api.get('/patients/stats/')).data,
}

// ── Doctors ───────────────────────────────────────────────────────────
export const doctorService = {
  list: async (params?: any): Promise<Doctor[]> => unwrap((await api.get('/doctors/', { params })).data),
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
  list: async (params?: any): Promise<DoctorAssignment[]> => unwrap((await api.get('/assignments/', { params })).data),
  create: async (doctor: number, patient: number) => (await api.post('/assignments/', { doctor, patient })).data,
  remove: async (id: number) => (await api.delete(`/assignments/${id}/`)).data,
}

// ── Prescriptions ─────────────────────────────────────────────────────
export const prescriptionService = {
  list: async (params?: any): Promise<Prescription[]> => unwrap((await api.get('/prescriptions/', { params })).data),
  create: async (data: { patient: number; diagnosis: string; medications: string; notes?: string }) =>
    (await api.post('/prescriptions/', data)).data,
  update: async (id: number, data: Partial<Prescription>) => (await api.patch(`/prescriptions/${id}/`, data)).data,
  remove: async (id: number) => (await api.delete(`/prescriptions/${id}/`)).data,
}

// ── Recommendations ───────────────────────────────────────────────────
export const recommendationService = {
  list: async (params?: any): Promise<Recommendation[]> => unwrap((await api.get('/recommendations/', { params })).data),
  create: async (data: {
    symptoms: string; pain_level: number; age: number; medical_history?: string; patient_id?: number
  }): Promise<Recommendation> => (await axios.post(`${BASE}/recommendations/`, data, {
    headers: session.access ? { Authorization: `Bearer ${session.access}` } : {},
  })).data,
}

// ── Documents ─────────────────────────────────────────────────────────
export const documentService = {
  list: async (params?: any): Promise<MedDocument[]> => unwrap((await api.get('/documents/', { params })).data),
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
  list: async (params?: any): Promise<Appointment[]> => unwrap((await api.get('/appointments/', { params })).data),
  mine: async (params?: any): Promise<Appointment[]> => unwrap((await api.get('/appointments/my/', { params })).data),
  forDoctor: async (params?: any): Promise<Appointment[]> => unwrap((await api.get('/appointments/doctor/', { params })).data),
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
  list: async (): Promise<Notification[]> => unwrap((await api.get('/notifications/')).data),
  markRead: async (id: string) => (await api.post(`/notifications/${id}/mark-read/`)).data,
  markAllRead: async () => (await api.post('/notifications/mark-all-read/')).data,
}

// ── Access requests ───────────────────────────────────────────────────
export const accessRequestService = {
  list: async (params?: any): Promise<AccessRequest[]> => unwrap((await api.get('/access-requests/', { params })).data),
  create: async (patient: number, reason?: string) => (await api.post('/access-requests/', { patient, reason })).data,
  approve: async (id: number) => (await api.post(`/access-requests/${id}/approve/`)).data,
  decline: async (id: number) => (await api.post(`/access-requests/${id}/decline/`)).data,
}

// ── Audit ─────────────────────────────────────────────────────────────
export const auditService = {
  list: async (params?: any): Promise<AuditLog[]> => unwrap((await api.get('/audit-logs/', { params })).data),
}

// ── Lab Reports ───────────────────────────────────────────────────────────────
export const labReportService = {
  /**
   * List lab reports.  Pass { patient: id } to scope to one patient.
   */
  list: async (params?: any): Promise<LabReport[]> =>
    unwrap((await api.get('/lab-reports/', { params })).data),

  retrieve: async (id: number): Promise<LabReport> =>
    (await api.get(`/lab-reports/${id}/`)).data,

  /**
   * Upload a lab report and trigger OCR + CDSA processing.
   * Returns the full LabReport (including extracted fields and summary) on success.
   *
   * @param patientId   numeric Patient.id  (admin must supply; patient is ignored for own)
   * @param name        display name for the report
   * @param file        the uploaded File object
   * @param onProgress  optional upload-progress callback (0–100)
   */
  upload: async (
    patientId: number,
    name: string,
    file: File,
    onProgress?: (pct: number) => void,
  ): Promise<LabReport> => {
    const fd = new FormData()
    fd.append('patient', String(patientId))
    fd.append('name', name.trim())
    fd.append('file', file)
    const res = await api.post('/lab-reports/', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress
        ? (evt) => {
            if (evt.total) onProgress(Math.round((evt.loaded / evt.total) * 100))
          }
        : undefined,
    })
    return res.data as LabReport
  },

  /** Download the original (unmodified) uploaded file. */
  download: async (id: number): Promise<Blob> =>
    (await api.get(`/lab-reports/${id}/download/`, { responseType: 'blob' })).data,

  /** Admin-only: re-run OCR + CDSA on an existing report. */
  reprocess: async (id: number): Promise<LabReport> =>
    (await api.post(`/lab-reports/${id}/reprocess/`)).data,

  remove: async (id: number): Promise<void> => {
    await api.delete(`/lab-reports/${id}/`)
  },
}
