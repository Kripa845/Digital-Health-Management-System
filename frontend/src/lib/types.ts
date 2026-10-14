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
  /** Years in practice (set by admins; used to rank doctors). */
  experience_years?: number
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
  /** Login username of the linked user account. */
  login_username?: string
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

/** GET /doctors/:id/available-dates/ — dates are Kathmandu "YYYY-MM-DD". */
export interface AvailableDates {
  doctor: number
  today: string
  days: number
  dates: string[]
}

/** GET /doctors/:id/available-slots/?date= — slot start times as "HH:MM". */
export interface AvailableSlots {
  doctor: number
  date: string
  slots: string[]
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

/** POST /smart-symptom-check/ (red flags + Random Forest + AHP-weighted TOPSIS). "emergency" means a red-flag
 *  rule matched: the model was not run and there is no fallback. Any other status except "ok" may carry a
 *  follow-up question, then falls back to the keyword check. */
export type SmartCheckStatus =
  | 'ok' | 'emergency' | 'needs_confirmation' | 'not_enough_info' | 'low_confidence' | 'model_unavailable'

/** A word only close to a known symptom ("feverr" → fever?): confirm with { [symptom]: true } in answers,
 *  or send the term in dismissed. Never used by the model until confirmed. */
export interface SmartCheckSuggestion {
  term: string
  /** Symptom name (DDXPlus code) to send back in answers. */
  symptom: string
  label: string
  score: number
}

/** One information-gain follow-up question; answer it with { [symptom]: true | false }. */
export interface SmartCheckQuestion {
  /** Symptom name from the schema (a DDXPlus code), sent back in "answers". */
  symptom: string
  /** Short English name, e.g. "coloured sputum". */
  label: string
  /** The question to show. */
  text: string
}

export interface SmartCheckDoctor {
  id: number
  name: string
  department: string
  specialization: string
  score: number
  /** Hours from now to the first free slot in the next 14 days (336 when none). */
  earliest_slot_hours: number
  free_hours: number
  caseload: number
  experience_years: number
  /** Specialisation match: 1 for the suggested department, the model's share for others. */
  match: number
  reason: string
}

/** How one phrase from the text was mapped to a symptom (shown by its label). */
export interface SmartCheckMatch {
  term: string
  symptom: string
  method: 'exact' | 'synonym' | 'lemma' | 'fuzzy'
  /** rapidfuzz similarity (0–100) for fuzzy matches, else null. */
  score: number | null
}

export interface SmartCheckResult {
  status: SmartCheckStatus
  symptoms: string[]
  /** Non-negated phrases and the symptom each was mapped to. */
  matched?: SmartCheckMatch[]
  /** Symptoms the text said are absent ("no fever"). */
  negated?: string[]
  /** Words that matched no symptom; shown so nothing typed is silently ignored. */
  unrecognized?: string[]
  /** "Did you mean ...?" (status needs_confirmation). */
  suggestions?: SmartCheckSuggestion[]
  /** Why the model is unsure (low_confidence). */
  reason?: string
  /** Red-flag rules matched (status "emergency"). */
  red_flags?: { id: string; message: string }[]
  /** "Not enough information" advice (not_enough_info / low_confidence), or the emergency message. */
  message?: string
  /** When to get emergency help (not_enough_info / low_confidence). */
  safety_net?: string
  /** Follow-up question when the model is unsure (not_enough_info / low_confidence), else null. */
  question?: SmartCheckQuestion | null
  illnesses?: { name: string; probability: number }[]
  department?: string
  dept_probability?: number
  /** Probability per department (the model's illness probabilities summed). */
  departments?: Record<string, number>
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

export type ActivityFlagStatus = 'NEW' | 'REVIEWED' | 'DISMISSED'

export interface ActivityFlagReason {
  feature: string
  value: number
  /** Median of the same feature among users with the same role. */
  median: number
  /** Robust z-score (median/MAD). */
  z: number
  text: string
}

/** One reason on a saved flag, worded by the API: plain text, plus the numbers behind it for a tooltip. */
export interface ActivityFlagReasonText {
  metric: string
  /** e.g. "12 failed login attempts. Most patients had none." */
  text: string
  /** e.g. "failed_logins = 12, role median 0, robust z +5.6" */
  detail: string
}

/** From the strongest reason's robust z (thresholds in backend reason_text.SEVERITY_THRESHOLDS). */
export type ActivityFlagSeverity = 'HIGH' | 'MEDIUM' | 'LOW'

/** A user whose activity stood out (DBSCAN noise point). For review only. */
export interface ActivityFlag {
  id: number
  user: number
  username: string
  full_name: string
  role: 'ADMIN' | 'DOCTOR' | 'PATIENT'
  window_start: string
  window_end: string
  features: Record<string, number>
  reasons: ActivityFlagReasonText[]
  severity: ActivityFlagSeverity
  eps: number
  status: ActivityFlagStatus
  reviewed_by: number | null
  reviewed_by_username: string | null
  note: string
  created_at: string
}

/** One user's day of activity that DBSCAN found unlike recent normal days. For review only. */
export interface SuspiciousAlert {
  id: number
  user: number
  username: string
  full_name: string
  role: 'ADMIN' | 'DOCTOR' | 'PATIENT'
  day: string
  /** The two features furthest from normal, e.g. "failed_logins = 25 (normal about 0)". */
  reason: string
  features: Record<string, number>
  status: ActivityFlagStatus
  created_at: string
}

/** One DBSCAN run over today's activity (POST /suspicious-alerts/detect/). */
export interface SuspiciousDetection {
  day: string
  history: number
  eps: number
  min_samples: number
  /** DBSCAN only runs for a role with at least this many user-days. */
  min_rows: number
  user_days: number
  enough_data: boolean
  checked: number
  clusters: number
  created: number
  updated: number
  roles: { role: string; user_days: number; checked: number; clusters: number; suspicious: number; skipped: boolean; message: string }[]
  ran_at: string
}

export interface ActivitySettings {
  activity_window_days: number
  dbscan_eps: number
  dbscan_min_samples: number
  updated_at: string
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
  /** OCR confidence (0–100) of the word(s) the value was read from; 100 for a PDF's own text. */
  ocr_confidence?: number | null
  /** Must be checked against the scan before it is saved (unconfirmed values are never saved). */
  needs_confirmation?: boolean
  /** Why the value may have been MISREAD (decimal_point also covers an auto-corrected scan reading). */
  confirmation_reasons?: { code: LabConfirmationCode; message: string; value?: string }[]
  /** A reading suggested for a value that lost its decimal point (dashboard unit). */
  suggested_value?: string
  /** Clinical: the value against the range printed on its own row (null when no range was read). */
  reference_flag?: 'low' | 'normal' | 'high' | null
  /** 'not_read' when the report's range could not be read; no default range is substituted. */
  range_status?: 'read' | 'not_read'
}

export type LabConfirmationCode =
  | 'low_confidence' | 'far_outside_range' | 'decimal_point'
  | 'conflict' | 'readings_differ' | 'range_misread' | 'loose_match'

/** A row of the report's results table whose test name was not recognised (never saved). */
export interface LabUnmatchedRow { name: string; value: string; unit: string; range: string; reason: string }

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
    unmatched_rows?: LabUnmatchedRow[]
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
  /** Values needing confirmation that the user checked against the scan. */
  confirmed?: string[]
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

/** GET/PUT /ranking-settings/: the admin's AHP comparisons for ranking doctors. */
export interface RankingCriterion {
  key: string
  label: string
  /** True = more is better; false = less is better. */
  benefit: boolean
}

export interface RankingSettings {
  /** 5x5 Saaty comparison matrix, rows and columns in `criteria` order. */
  ahp_pairwise: number[][]
  ahp_weights: Record<string, number>
  /** Consistency ratio; saved only when below 0.10. */
  ahp_cr: number
  criteria: RankingCriterion[]
  updated_at: string
}

export type ActivityPointKind = 'core' | 'border' | 'noise'

/** One user in the step-by-step DBSCAN analysis. */
export interface ActivityAnalysisUser {
  user_id: number
  username: string
  /** Step 2: counts in the window. */
  raw: Record<string, number>
  /** Step 3: log1p of each count. */
  log: Record<string, number>
  /** Step 4: log value scaled to mean 0, sd 1 within the role. */
  scaled: Record<string, number>
  /** Robust z-score (median/MAD) of each raw count, used to explain a flag. */
  z: Record<string, number>
  /** DBSCAN cluster label; -1 is noise, null when DBSCAN was not run. */
  cluster: number | null
  kind: ActivityPointKind | null
  /** Distance to the k-th nearest neighbour in scaled space. */
  kdist: number | null
  /** 2-D PCA projection, for the picture only. */
  x: number
  y: number
  reasons: ActivityFlagReason[]
}

export interface ActivityAnalysis {
  role: 'ADMIN' | 'DOCTOR' | 'PATIENT'
  demo: boolean
  /** eps and min_samples were picked from the data (the suggested values), not typed in. */
  auto: boolean
  days: number
  window_start: string
  window_end: string
  n_users: number
  min_users: number
  eps: number
  min_samples: number
  k: number
  features: string[]
  skipped: boolean
  message: string
  scaling: Record<string, { mean: number; sd: number }>
  kdist_sorted: number[]
  suggested_eps: number | null
  /** Suggested min_samples for this many users and the eps that goes with it (null when no clear jump). */
  suggested: { min_samples: number; eps: number } | null
  explained_variance: [number, number]
  n_clusters: number
  counts: Record<ActivityPointKind, number>
  users: ActivityAnalysisUser[]
  /** Suspicious alerts (failed-login rule or daily DBSCAN) for this role on days inside the window; empty for demo. */
  suspicious_alerts: AnalysisAlert[]
}

export type AnalysisAlert = Pick<SuspiciousAlert, 'id' | 'username' | 'full_name' | 'day' | 'reason' | 'status'> & { user_id: number }

export interface ActivityAnalysisParams {
  role: 'ADMIN' | 'DOCTOR' | 'PATIENT'
  days: number
  /** Ignored when auto is true. */
  eps?: number
  min_samples?: number
  demo: boolean
  /** Use the suggested eps and min_samples for this role's users. */
  auto?: boolean
}
