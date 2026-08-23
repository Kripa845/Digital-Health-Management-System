export type Role = 'ADMIN' | 'DOCTOR' | 'PATIENT'

export type Gender = 'Male' | 'Female' | 'Other'
export type BloodGroup = 'A+' | 'A-' | 'B+' | 'B-' | 'AB+' | 'AB-' | 'O+' | 'O-'
export type ActiveStatus = 'Active' | 'Inactive'

export interface Session {
  access: string
  refresh: string
  role: Role
  username: string
  first_name?: string
  last_name?: string
  profile_id?: string
  uuid_token?: string
  must_change_password?: boolean
}

export interface LoginResponse extends Partial<Session> {
  detail?: string
}

export interface UserRef {
  id: number
  username: string
  email?: string
  first_name?: string
  last_name?: string
  role: Role
  is_active?: boolean
}

export interface CurrentUser extends UserRef {
  must_change_password?: boolean
  doctor_profile?: Doctor
  patient_profile?: Patient
}

export interface Patient {
  id: number
  patient_id: string
  uuid_token: string
  first_name: string
  middle_name?: string | null
  last_name: string
  dob: string
  age?: number
  gender: Gender
  blood_group: BloodGroup
  phone: string
  emergency_contact: string
  email?: string | null
  address: string
  height: string | number
  weight: string | number
  // ── Clinical vitals (auto-updated by lab report OCR / CDSA) ──────────────
  blood_pressure?: string | null
  blood_sugar_fasting?: string | number | null
  blood_sugar_random?: string | number | null
  hemoglobin?: string | number | null
  cholesterol_total?: string | number | null
  cholesterol_hdl?: string | number | null
  cholesterol_ldl?: string | number | null
  triglycerides?: string | number | null
  heart_rate?: number | null
  spo2?: string | number | null
  temperature?: string | number | null
  hba1c?: string | number | null
  serum_creatinine?: string | number | null
  blood_urea?: string | number | null
  uric_acid?: string | number | null
  ssgpt_alt?: string | number | null
  ssgot_ast?: string | number | null
  bilirubin_total?: string | number | null
  tsh?: string | number | null
  t3?: string | number | null
  t4?: string | number | null
  sodium?: string | number | null
  potassium?: string | number | null
  wbc_count?: string | number | null
  rbc_count?: string | number | null
  platelet_count?: string | number | null
  hematocrit?: string | number | null
  esr?: string | number | null
  // ─────────────────────────────────────────────────────────────────────────
  allergies?: string | null
  current_medication?: string | null
  prescription?: string | null
  pain_log?: string | null
  status: ActiveStatus
  photo?: string | null
  registration_date?: string
  last_updated?: string
  created_by?: number | null
  created_by_name?: string
  login_username?: string
  account_active?: boolean
  generated_username?: string
  generated_password?: string
}

export interface Doctor {
  id: number
  doctor_id: string
  uuid_token?: string
  first_name?: string
  last_name?: string
  license_number: string
  department: string
  specialization: string
  dob?: string
  age?: number
  gender?: Gender
  phone?: string
  email?: string
  photo?: string | null
  status: ActiveStatus
  availability_schedule?: Record<string, string>
  registration_date?: string
  user?: UserRef
  // present on admin create response (shown once)
  generated_username?: string
  generated_password?: string
  // recommendation extras
  score?: number
  reasons?: string[]
}

export interface DoctorAssignment {
  id: number
  doctor: number
  patient: number
  doctor_detail?: Doctor
  patient_detail?: Patient
  assigned_date: string
  status: ActiveStatus
}

export type AppointmentStatus = 'PENDING' | 'ACCEPTED' | 'DECLINED' | 'COMPLETED' | 'CANCELLED'

export interface Appointment {
  id: string
  patient: number
  doctor: number
  patient_detail?: Patient
  doctor_detail?: Doctor
  patient_name?: string
  doctor_name?: string
  doctor_department?: string
  appointment_date: string
  appointment_time: string
  status: AppointmentStatus
  reason?: string | null
  notes?: string | null
  created_at?: string
  updated_at?: string
}

export interface AppointmentStats {
  total: number
  pending: number
  accepted: number
  completed: number
  declined: number
  cancelled: number
  today: number
}

export interface MedDocument {
  id: number
  patient: number
  name: string
  file: string
  file_type?: string
  size?: number | null
  uploaded_at: string
  report_type: 'MEDICAL' | 'ADDITIONAL'
  uploaded_by?: number | null
}

export interface Prescription {
  id: number
  patient: number
  doctor: number
  patient_name?: string
  doctor_name?: string
  diagnosis: string
  medications: string
  notes?: string | null
  prescription_date: string
}

export interface RankedDoctor extends Doctor {
  score?: number
  reasons?: string[]
}

export interface Recommendation {
  id?: number
  symptoms: string
  pain_level: number
  age?: number | null
  medical_history?: string | null
  recommended_department: string
  recommended_doctor?: number | null
  recommended_doctor_detail?: Doctor | null
  score?: number | null
  confidence?: number | null
  reason?: string | null
  clinical_severity?: number
  ranked_doctors?: RankedDoctor[]
  recommendation_date?: string
  patient?: number | null
  patient_name?: string
}

export interface Notification {
  id: string
  receiver: number
  role: Role
  title: string
  message: string
  related_appointment?: string | null
  read: boolean
  created_at: string
}

export interface AccessRequest {
  id: number
  doctor: number
  patient: number
  doctor_detail?: Doctor
  patient_detail?: Patient
  doctor_name?: string
  patient_name?: string
  status: 'PENDING' | 'APPROVED' | 'DECLINED'
  reason?: string | null
  created_at: string
  resolved_at?: string | null
}

export interface AuditLog {
  id: number
  user?: number | null
  user_name?: string
  action: string
  description: string
  timestamp: string
  ip_address?: string | null
}

export interface AdminStats {
  total_users: number
  total_patients: number
  total_doctors: number
  total_admins: number
  today_registrations: number
  active_users: number
  inactive_users: number
  recent_patients: Patient[]
  recent_doctors: Doctor[]
  registration_chart: { date: string; patients: number; doctors: number }[]
}

export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

// ── Lab Reports ───────────────────────────────────────────────────────────────

export type LabReportStatus = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED'
export type LabFieldChangeStatus = 'INSERTED' | 'UPDATED' | 'UNCHANGED'

export interface LabReportField {
  id: number
  field_name: string
  patient_field: string
  extracted_value: string
  previous_value: string
  unit: string
  reference_range: string
  change_status: LabFieldChangeStatus
}

export interface LabReport {
  id: number
  patient: number
  patient_name?: string
  patient_id_code?: string
  file: string
  name: string
  file_type?: string
  size?: number | null
  uploaded_by?: number | null
  uploaded_by_name?: string | null
  uploaded_at: string
  status: LabReportStatus
  error_message?: string
  ocr_text?: string
  detected_count: number
  updated_count: number
  unchanged_count: number
  processed_at?: string | null
  // Nested
  fields?: LabReportField[]
  detected_fields?: LabReportField[]
  updated_fields?: LabReportField[]
  unchanged_fields?: LabReportField[]
  // detail message from server when no fields found
  detail?: string
}
