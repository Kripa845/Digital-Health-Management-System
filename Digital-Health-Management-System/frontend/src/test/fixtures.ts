/** Synthetic API responses matching docs/lab-reports-api.md. */
import type { DashboardTest, LabDashboard, LabReport, LabReportField } from '@/lib/types'

export function field(overrides: Partial<LabReportField> = {}): LabReportField {
  return {
    id: 1, field_name: 'Haemoglobin', patient_field: 'hemoglobin', extracted_value: '12.8', unit: 'g/dL',
    converted_value: '12.8', converted_unit: 'g/dL', previous_value: '', reference_range: '',
    change_status: 'INSERTED', skip_reason: '', flag: '', ...overrides,
  }
}

export function report(overrides: Partial<LabReport> = {}): LabReport {
  return {
    id: 42, patient: 7, patient_name: 'Asha Gurung', patient_id_code: 'PAT-0E2E0001', name: 'Lipid profile',
    file_type: 'PDF', size: 2048, uploaded_at: '2026-10-01T10:00:00Z', report_date: '2026-09-14',
    identity_verified: true, status: 'PENDING_CONFIRMATION', detected_count: 2, updated_count: 2, unchanged_count: 0,
    review_reasons: [], review_messages: [],
    fields: [
      field(),
      field({
        id: 2, field_name: 'Total Cholesterol', patient_field: 'cholesterol_total', extracted_value: '5.2', unit: 'mmol/L',
        converted_value: '201.08', converted_unit: 'mg/dL',
      }),
      field({
        id: 3, field_name: 'Blood Sugar (Random)', patient_field: 'blood_sugar_random', extracted_value: '950',
        unit: 'mg/dL', converted_value: '950', change_status: 'SKIPPED', flag: 'out_of_range',
        skip_reason: 'Outside the expected range (20–800 mg/dL), so it may have been misread.',
      }),
    ],
    ...overrides,
  }
}

export function test_(overrides: Partial<DashboardTest> = {}): DashboardTest {
  return {
    test: 'hemoglobin', label: 'Haemoglobin', unit: 'g/dL', latest: { value: '11.20', date: '2026-09-14' },
    status: 'Low', severe: false, reference: '12–15.5 g/dL',
    history: [{ date: '2026-06-01', value: 12.9 }, { date: '2026-09-14', value: 11.2 }], trend: 'down', ...overrides,
  }
}

export function dashboard(overrides: Partial<LabDashboard> = {}): LabDashboard {
  return {
    patient_id: 'PAT-0E2E0001', age: 34, gender: 'Female', blood_group: 'O+',
    body: { height: '158.00', weight: '54.00', bmi: 21.6, bmi_status: 'Normal', bmi_severe: false },
    tests: [
      test_(),
      test_({ test: 'cholesterol_total', label: 'Total Cholesterol', unit: 'mg/dL', latest: { value: '201.08', date: '2026-09-14' },
        status: 'High', reference: 'below 200 mg/dL', history: [{ date: '2026-09-14', value: 201.08 }], trend: null }),
      test_({ test: 'blood_sugar_random', label: 'Blood Sugar (Random)', unit: 'mg/dL', latest: null, status: null,
        history: [], trend: null }),
    ],
    disclaimer: 'Informational only, not medical advice.',
    ...overrides,
  }
}
