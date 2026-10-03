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
  /** Not returned by the API; files are fetched through the download endpoint. */
  file?: string
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

/** POST /smart-symptom-check/ (Naive Bayes + TOPSIS). Any status other than "ok" falls back to the keyword check. */
export type SmartCheckStatus = 'ok' | 'not_enough_info' | 'low_confidence' | 'model_unavailable'

export interface SmartCheckDoctor {
  id: number
  name: string
  department: string
  specialization: string
  score: number
  free_hours: number
  caseload: number
  reason: string
}

export interface SmartCheckResult {
  status: SmartCheckStatus
  symptoms: string[]
  illnesses?: { name: string; probability: number }[]
  department?: string
  dept_probability?: number
  doctors?: SmartCheckDoctor[]
  doctors_department?: string | null
  doctors_note?: string
  history_id?: number
  /** The patient the check was saved for (null for a guest check). */
  patient?: { id: number; patient_id: string; name: string } | null
  disclaimer: string
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
// Mirrors the API contract in docs/lab-reports-api.md. The backend enforces all
// medical and matching rules; the frontend only displays what it returns.

/**
 * PENDING_CONFIRMATION: identity verified, preview waiting for the user to confirm.
 * NEEDS_REVIEW: the identity gate could not verify the report; an admin decides.
 * REJECTED: an admin rejected it. CONFIRMED: applied to the record.
 */
export type LabReportStatus =
  | 'PENDING' | 'PROCESSING' | 'PENDING_CONFIRMATION' | 'NEEDS_REVIEW' | 'REJECTED' | 'CONFIRMED' | 'FAILED'
  /** No health card values: waits for "Save report only". */
  | 'NO_VALUES_SAVEABLE'
  /** Kept as a document only; no values or history rows. */
  | 'SAVED_NO_VALUES'

/**
 * Planned outcome while PENDING_CONFIRMATION, actual outcome once CONFIRMED.
 * SKIPPED: not saved (see `flag` / `skip_reason`). HISTORY: kept in history only,
 * because a newer result is already shown.
 */
export type LabFieldChangeStatus = 'INSERTED' | 'UPDATED' | 'UNCHANGED' | 'SKIPPED' | 'HISTORY'

/** Why a value was not saved. Only `out_of_range` values can be accepted on confirm. */
export type LabFieldFlag = '' | 'out_of_range' | 'unknown_unit' | 'invalid' | 'blood_group_conflict' | 'too_large'

export interface LabReportField {
  id: number
  field_name: string
  patient_field: string
  /** Value and unit as printed on the report. */
  extracted_value: string
  unit: string
  /** Value and unit used on the dashboard (after unit conversion). */
  converted_value: string
  converted_unit: string
  previous_value: string
  reference_range: string
  change_status: LabFieldChangeStatus
  skip_reason: string
  flag: LabFieldFlag
}

export interface ExtractedValue { value: string; unit: string }

export interface LabReport {
  id: number
  patient: number
  patient_name?: string
  patient_id_code?: string
  name: string
  file_type?: string
  size?: number | null
  uploaded_by?: number | null
  uploaded_by_name?: string | null
  uploaded_at: string
  /** Date printed on the report, when it could be read. */
  report_date?: string | null
  identity_verified?: boolean
  status: LabReportStatus
  error_message?: string
  detected_count: number
  updated_count: number
  unchanged_count: number
  processed_at?: string | null
  confirmed_at?: string | null
  confirmed_by_name?: string | null
  ocr_confidence?: number | null
  review_reasons?: string[]
  review_messages?: string[]
  review_note?: string
  reviewed_at?: string | null
  /** Values read from the report; tests that were not found are null. */
  extracted?: {
    report_date: string | null
    blood_group: string | null
    tests: Record<'hemoglobin' | 'cholesterol_total' | 'blood_sugar_random', ExtractedValue | null>
    other_tests: Record<string, ExtractedValue>
  }
  // Nested
  fields?: LabReportField[]
  detected_fields?: LabReportField[]
  updated_fields?: LabReportField[]
  unchanged_fields?: LabReportField[]
  skipped_fields?: LabReportField[]
  /** Which label the date came from: 'reporting', 'collection', 'user' (typed in the preview) or ''. */
  report_date_source?: string
  report_date_user_entered?: boolean
  /** Report date ordering check (null once confirmed or rejected). */
  date_check_status?: 'ok' | 'first_report' | 'older_than_latest' | 'date_missing' | null
  latest_report_date?: string | null
  date_message?: string
  /** True when confirming needs acknowledge_older_report. */
  date_ack_required?: boolean
  /** No health card values were found; the report can be kept as a document only. */
  can_save_without_values?: boolean
  no_values_message?: string
}

/** Review queue item (admin only): includes what was read from the report header. */
export interface LabReviewItem extends LabReport {
  identity: { patient_id: string | null; name: string | null; dob: string | null }
}

export interface LabReportStatusInfo {
  id: number
  status: LabReportStatus
  review_reasons: string[]
  review_messages: string[]
  review_note: string
  uploaded_at: string
  reviewed_at: string | null
  confirmed_at: string | null
  updated_count: number
}

export interface ConfirmPayload {
  /** Corrected values, in the dashboard unit, keyed by test (e.g. { hemoglobin: "13.9" }). */
  values?: Record<string, string>
  /** Out-of-range tests the user explicitly accepts. */
  accept_flagged?: string[]
  /** Required to confirm a report older than the latest confirmed one. */
  acknowledge_older_report?: boolean
}

export type LabResultStatus = 'Low' | 'Normal' | 'High'

export interface DashboardTest {
  test: string
  label: string
  unit: string
  latest: { value: string; date: string | null } | null
  status: LabResultStatus | null
  /** Far outside the normal range. */
  severe: boolean
  reference: string
  history: { date: string; value: number }[]
  trend: 'up' | 'down' | 'stable' | null
}

export interface LabDashboard {
  patient_id: string
  age: number | null
  gender: string
  blood_group: string | null
  body: {
    height: string | null
    weight: string | null
    bmi: number | null
    bmi_status: LabResultStatus | null
    bmi_severe: boolean
  }
  tests: DashboardTest[]
  disclaimer: string
}

/** Error body returned by the lab report endpoints. */
export interface ApiErrorBody {
  code: LabUploadErrorCode | string
  message: string
  errors?: Record<string, string | string[]>
}

export type LabUploadErrorCode =
  | 'invalid_file' | 'file_too_large' | 'unreadable' | 'no_text' | 'no_values' | 'values_not_usable' | 'duplicate'
  | 'patient_id_mismatch' | 'invalid_values' | 'not_pending' | 'server_error'
