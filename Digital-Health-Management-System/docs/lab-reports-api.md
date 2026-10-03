# Lab reports API contract

Shared by the backend (`backend/apps/lab_reports/`) and the frontend
(`frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`). All paths are under
`/api/v1/`. Examples below were captured from the running API with synthetic data.

## Conventions

- **Auth:** `Authorization: Bearer <access token>` on every request. Get tokens from
  `POST auth/login/` and refresh them with `POST auth/refresh/` (SimpleJWT, rotating refresh tokens).
- **Who sees what:** a patient sees only their own reports and dashboard. An admin sees all.
  A doctor sees only **confirmed** reports of patients they have approved access to, read-only.
- **Errors** use one shape. `detail` repeats `message` for older clients; `errors` is present
  only for field-level problems.

  ```json
  { "code": "patient_id_mismatch", "message": "Patient ID does not match this account.", "detail": "Patient ID does not match this account." }
  ```

| HTTP | `code` | When |
| --- | --- | --- |
| 400 | `invalid_file`, `file_too_large`, `unreadable`, `invalid_values`, `invalid_patient`, `invalid_decision`, `invalid_date`, `older_report_not_acknowledged` | Bad file or bad input |
| 401 | (DRF default) | Not logged in or token expired |
| 403 | (DRF default), `forbidden` | Not allowed for this role |
| 404 | (DRF default), `no_file`, `not_found` | Not found or not yours (other patients' reports are 404, not 403) |
| 409 | `duplicate`, `not_pending`, `not_in_review` | Same file uploaded again; report not in the right state |
| 422 | `patient_id_mismatch`, `values_not_usable`, `older_report` | The report belongs to someone else; values found but none usable; older report refused (policy "block") |
| 429 | (DRF default) | Upload rate limit (`LAB_UPLOAD_THROTTLE_RATE`, default 20/hour) |

## Report statuses

| Status | Meaning | Next step |
| --- | --- | --- |
| `PENDING_CONFIRMATION` | Patient ID verified; values shown as a preview | Owner (or admin) confirms or cancels |
| `NEEDS_REVIEW` | No matching patient ID (a different bare number counts as none), an unclear ID (O/0, I/1, S/5...), or name / DOB disagree (the age on a report is not compared), or OCR confidence < 50 | Admin approves (→ `PENDING_CONFIRMATION`) or rejects |
| `CONFIRMED` | Applied to the record | — |
| `REJECTED` | Admin rejected it; the file is deleted | — |

IDs are compared on the part after `PAT` (`PAT-79028232`, `PAT 7902 8232` and `Patient ID: 79028232` are the same).
A report showing **someone else's** `PAT` ID is not stored at all (422).

Per value (`fields[].change_status`): `INSERTED`, `UPDATED`, `UNCHANGED`, `HISTORY`
(kept in history only, because a newer result is shown) and `SKIPPED` (not saved; see `flag`).
`flag` is one of `out_of_range` (can be accepted on confirm), `unknown_unit`, `invalid` (never saved; this
includes haemoglobin outside 3–25 g/dL, total cholesterol outside 50–500 mg/dL and random sugar outside
20–800 mg/dL),
`blood_group_conflict` or `too_large`.

---

## POST `reports/upload/`

`multipart/form-data`: `file` (PDF, PNG or JPG, ≤ 10 MB; the type is checked from the content),
`name` (optional display name). Admins also send `patient` (the patient's numeric id). Patients
always upload to their own record.

Runs OCR, extraction, the identity gate, unit conversion and range checks. **Returns a preview
only: nothing is written to the patient record or to the value history.**

**201** (`PENDING_CONFIRMATION`):

```json
{
  "id": 1,
  "patient": 1,
  "patient_name": "Hari Tamang",
  "patient_id_code": "PAT-7228A542",
  "name": "Lipid profile",
  "file_type": "PDF",
  "size": 35,
  "uploaded_at": "2026-10-03T12:45:53.659543+05:45",
  "report_date": "2026-09-14",
  "identity_verified": true,
  "status": "PENDING_CONFIRMATION",
  "ocr_confidence": 96.4,
  "review_reasons": [],
  "review_messages": [],
  "extracted": {
    "report_date": "2026-09-14",
    "blood_group": null,
    "tests": {
      "hemoglobin": { "value": "13.4", "unit": "g/dL" },
      "cholesterol_total": { "value": "5.2", "unit": "mmol/L" },
      "blood_sugar_random": { "value": "950", "unit": "mg/dL" }
    },
    "other_tests": {}
  },
  "fields": [
    {
      "id": 1, "field_name": "Blood Sugar (Random)", "patient_field": "blood_sugar_random",
      "extracted_value": "950", "unit": "mg/dL", "converted_value": "950", "converted_unit": "mg/dL",
      "previous_value": "", "change_status": "SKIPPED", "flag": "invalid",
      "skip_reason": "Outside the expected range (20–800 mg/dL), so it was treated as a misread and not saved."
    },
    {
      "id": 3, "field_name": "Total Cholesterol", "patient_field": "cholesterol_total",
      "extracted_value": "5.2", "unit": "mmol/L", "converted_value": "201.08", "converted_unit": "mg/dL",
      "previous_value": "", "change_status": "INSERTED", "flag": "", "skip_reason": ""
    }
  ]
}
```

(The full response also includes `detected_fields`, `updated_fields`, `unchanged_fields` and
`skipped_fields`, all with the same shape as `fields`.)

Missing tests are `null` in `extracted.tests` and have no row in `fields`; nothing is guessed.

**201** (`NEEDS_REVIEW`): same body, with:

```json
{ "status": "NEEDS_REVIEW", "identity_verified": false,
  "review_reasons": ["patient_id_missing"],
  "review_messages": ["The report does not show a Mero Care Card patient ID."] }
```

Review reason codes: `patient_id_missing`, `patient_id_unclear`, `name_mismatch`,
`dob_mismatch`, `low_ocr_confidence` (`age_mismatch` only appears on reports uploaded before age checks were removed).

**422** (another patient's ID; nothing stored, attempt audited with a masked ID):

```json
{ "code": "patient_id_mismatch", "message": "Patient ID does not match this account.", "detail": "..." }
```

**409** `duplicate` (same file already uploaded for this patient), **400** `invalid_file` /
`file_too_large` / `unreadable`, **422** `values_not_usable`.

**201** with `status: "NO_VALUES_SAVEABLE"`, `can_save_without_values: true` and `no_values_message` when no
card values were found: `POST reports/{id}/confirm/` then saves it as a document only (`SAVED_NO_VALUES`,
no value or history rows); `POST reports/{id}/discard/` deletes it and its file.

## POST `reports/{id}/confirm/`

Body (both optional):

```json
{ "values": { "hemoglobin": "13.6" }, "accept_flagged": ["blood_sugar_random"] }
```

- `values`: corrections typed by the user, **in the dashboard unit**. Only tests in this report are
  allowed. Every value is re-validated on the server.
- `accept_flagged`: out-of-range tests the user explicitly accepts. Without it they are not saved.

In one transaction (report and patient rows locked), the update rules are applied and an audit
entry is written:

- **Blood group:** set only if the record has none. A different value is flagged and not overwritten.
- **Age:** never taken from a report.
- **Numeric tests:** a new dated history row every time. The card shows the latest. A report dated
  before the current latest value goes to history only (`HISTORY`).

**200:** the report with `status: "CONFIRMED"` and actual outcomes in `fields`:

```json
{ "id": 1, "status": "CONFIRMED", "updated_count": 2, "confirmed_at": "2026-10-03T12:45:53.738165+05:45",
  "fields": [ { "patient_field": "blood_sugar_random", "change_status": "SKIPPED", "flag": "invalid",
                "skip_reason": "Outside the expected range (20–800 mg/dL), so it was treated as a misread and not saved." } ] }
```

**400** (nothing written):

```json
{ "code": "invalid_values", "message": "Some values need correcting.", "errors": { "hemoglobin": "Enter a number." } }
```

**409** `not_pending`: already confirmed, or still under review.

## POST `reports/{id}/discard/`

Cancels a report that is `PENDING_CONFIRMATION` or `NEEDS_REVIEW`; the report and its file are
deleted. **204.**

## DELETE `reports/{id}/`

Owner or admin; any status. Deletes the report and its stored file. For a `CONFIRMED` report its
history rows are deleted too, and each dashboard value it set falls back to the newest remaining
result for that test (or is cleared). A value changed since, by hand or by another report, is kept;
blood group is never changed. Audited without values. **204.** Doctors get 403.

## GET `reports/` · GET `reports/{id}/` · GET `reports/{id}/status/` · GET `reports/{id}/download/`

History (paginated `{count, next, previous, results}`), one report (same shape as the upload
response), status only, and the original file (decrypted, as an attachment).

```json
{ "id": 1, "status": "PENDING_CONFIRMATION", "review_reasons": [], "review_messages": [],
  "review_note": "", "uploaded_at": "2026-10-03T12:45:53.659543+05:45",
  "reviewed_at": null, "confirmed_at": null, "updated_count": 2 }
```

## GET `dashboard/`

Patients get their own; admins and doctors with approved access pass `?patient=<id>`.
Statuses are computed on the server from adult reference ranges.

```json
{
  "patient_id": "PAT-7228A542",
  "age": 36,
  "gender": "Male",
  "blood_group": "O+",
  "body": { "height": "170.00", "weight": "70.00", "bmi": 24.2, "bmi_status": "Normal", "bmi_severe": false },
  "tests": [
    {
      "test": "hemoglobin", "label": "Haemoglobin", "unit": "g/dL",
      "latest": { "value": "13.60", "date": "2026-09-14" },
      "status": "Normal", "severe": false, "reference": "13.5–17.5 g/dL",
      "history": [ { "date": "2026-09-14", "value": 13.6 } ],
      "trend": null
    }
  ],
  "disclaimer": "Informational only, not medical advice."
}
```

`tests` always lists, in order: `hemoglobin`, `cholesterol_total`, `blood_sugar_random`,
`blood_sugar_fasting`, `cholesterol_hdl`, `cholesterol_ldl`, `triglycerides`,
`blood_pressure`, `hba1c`; then any other test the patient has a value for (kidney, liver, blood count,
thyroid: `serum_creatinine`, `blood_urea`, `ssgpt_alt`, `hematocrit`, `platelet_count`, `tsh`...). `latest` is `null` when not recorded. `status` is `"Low"`, `"Normal"`,
`"High"` or `null`. `trend` is `"up"`, `"down"`, `"stable"` or `null` (fewer than two points).

## GET `admin/review-queue/` (admin)

Reports in `NEEDS_REVIEW`, oldest first. Same shape as a report, plus what was read from the
report header (patient ID masked):

```json
{ "identity": { "patient_id": null, "name": "Hari Tamang", "dob": null } }
```

## POST `admin/reports/{id}/resolve/` (admin)

```json
{ "decision": "approve", "note": "ID checked against hospital record" }
```

- `approve` → `PENDING_CONFIRMATION`. Nothing is applied; the values still need confirming.
- `reject` → `REJECTED`, and the stored file is deleted.

The patient is notified either way. **200** returns the report:

```json
{ "id": 2, "status": "PENDING_CONFIRMATION", "review_note": "ID checked against hospital record",
  "reviewed_at": "2026-10-03T12:45:54.401003+05:45" }
```

**409** `not_in_review` if it is not under review.
