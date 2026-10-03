# How lab report reading works in Mero Care Card

This document explains, step by step, how the system turns an uploaded lab report (PDF or photo) into
values on the patient's health dashboard: how the file is read, how the text is found, how test values
and the patient ID are extracted, how the report is checked to belong to the right patient, and how the
values reach the dashboard. It describes the code as it is now; it contains no code changes.

---

## 1. The whole process at a glance

```
 Upload (PDF / PNG / JPG)
   │
   ▼
 1. File checks ............ type from content, ≤ 10 MB, duplicate check
   │
   ▼
 2. Get the text
      Digital PDF ──► PDF text layer (PyMuPDF), table rows rebuilt
      Scanned PDF / photo ──► page images (200 dpi) ──► clean-up ──► Tesseract OCR, table rows rebuilt
   │
   ▼
 3. Extract
      • test values (haemoglobin, cholesterol, sugar, HbA1C, urea, ...) with their units
      • patient ID, name, date of birth, report date
   │
   ├── no usable value found? ──► optional AI fallback (off by default)
   │
   ▼
 4. Identity check ("is this report this patient's?")
      pass ─────────► preview (PENDING_CONFIRMATION)
      doubt ────────► admin review (NEEDS_REVIEW)
      other patient ► rejected (422), nothing stored
   │
   ▼
 5. Report date check (compared with the patient's latest confirmed report)
      same day or later / first report ► continue
      older ────────► warning; the user must confirm it (or refused, if the policy is "block")
      no date ──────► the user types the date in the preview
   │
   ▼
 6. Check every value: unit conversion, plausible range
      values found but none usable ► refused (422 values_not_usable), nothing stored
   │
   ▼
 7. Preview shown to the user ── nothing on the record has changed yet
      no card values at all ► "Save report only" (kept as a document, no values)
   │
   ▼
 8. User clicks Confirm ──► values saved with history ──► dashboard cards update
    (or "Save report only" ──► file kept, status SAVED_NO_VALUES, dashboard unchanged)
```

Two principles run through every step:

- **Nothing is guessed.** A value that cannot be read clearly is left out, never invented.
- **Nothing is applied without a person.** Extraction only produces a preview; the patient (or an
  admin) must confirm it, and a report that cannot be verified goes to an admin first.

---

## 2. Where the code lives

All of it is in `backend/apps/lab_reports/`.

| File | What it does |
| --- | --- |
| `views.py` | The API endpoints (upload, confirm, discard, delete, download, dashboard, review queue). Thin: they call the services below. |
| `services/upload.py` | The upload pipeline: runs steps 1–6 in order and decides the outcome. |
| `services/files.py` | File checks: real file type from its first bytes, size limit, SHA-256 hash, safe display name. |
| `ocr_service.py` | Getting the text: PDF reading with PyMuPDF, image clean-up, Tesseract OCR, rebuilding table rows. |
| `services/ocr.py` | Small wrapper that turns file-reading errors into an "unreadable" result. |
| `extractor.py` | Finding test values in the text (labels, patterns, units, OCR-error handling). |
| `services/extractor.py` | Finding the patient ID; combines values, ID and identity into one result. |
| `identity.py` | Finding the patient's name, date of birth and report date in the text. |
| `services/verifier.py` | The identity check: patient ID, name, date of birth, scan quality. |
| `services/validator.py` + `units.py` | Unit conversion and plausible-range checks for each value. |
| `services/llm.py` | The optional AI fallback (Anthropic Claude), off unless switched on. |
| `services/dashboard.py` | Building the preview, applying a confirmed report, deleting a report, the dashboard data. |
| `crypto.py` | Encrypting stored report files. |

The frontend pages are in `frontend/src/features/lab-reports/` (upload dialog, preview/confirm, history,
viewer) and `frontend/src/features/patient/HealthVitalsCard.tsx` (the dashboard cards).

---

## 3. Step 1 — Upload and file checks

`services/files.py`, `services/upload.py`

1. **Allowed types:** PDF, PNG, JPG/JPEG, **up to 10 MB**.
2. **Real type, not the file name.** The first bytes of the file are checked (`%PDF-` for PDF, the PNG
   signature, `FF D8 FF` for JPEG). A file renamed from `.exe` to `.pdf` is refused with `invalid_file`.
3. **Duplicate check.** A SHA-256 hash of the file is compared with this patient's earlier uploads; the
   same file twice gives `409 duplicate`.
4. **Rate limit:** 20 uploads per hour per user (`LAB_UPLOAD_THROTTLE_RATE`).
5. **Who uploads for whom:** a patient always uploads to their own record; an admin chooses the patient.

---

## 4. Step 2 — Getting the text out of the file

`ocr_service.py`

### 4.1 Digital PDFs (made by the lab's computer)

A digital PDF already contains its text (the "text layer"). The system opens it with **PyMuPDF**
(no Poppler or other external program is needed) and reads up to 5 pages (`OCR_MAX_PDF_PAGES`).

**The table problem and how it is solved.** Inside a PDF, text is stored in the order it was drawn, and
lab systems often draw a results table *column by column*: first all test names, then all results. Read
naively, "Haemoglobin" and "13.4" end up far apart and can never be paired.

So instead of reading the text in stored order, the system takes **every word with its position on the
page** and rebuilds the rows itself:

1. Words are sorted top to bottom by the middle of their height.
2. Words whose vertical centres are within half a line height of each other belong to the **same row**
   (the row's centre follows the words slightly, so a gently tilted page still works).
3. Within a row, words are ordered left to right. A wide gap (more than about 2½ character widths)
   becomes **two spaces**, a normal gap one space — this keeps table columns apart, like OCR output.

Result: `Haemoglobin (Hb)  12.8  g/dL  12.0-15.5` on one line, as on the printed page.

If the text layer has **more than 50 characters**, it is used and counts as 100 % reliable. Otherwise
the PDF is treated as a scan (below).

### 4.2 Scanned PDFs and photos

Each PDF page is rendered as a **greyscale image at 200 dpi** (`OCR_PDF_DPI`); a PNG/JPG is used as it is.
Then:

**Image clean-up** (`preprocess_image`), so Tesseract reads more reliably:

| Step | Why |
| --- | --- |
| Convert to greyscale | Colour adds nothing for text |
| Enlarge small images to at least 1200 px | Tesseract needs characters of a certain size |
| Contrast × 1.8, sharpness × 2.0 | Faint or soft print becomes crisp |
| Median filter (3 px) | Removes scanner speckle |
| Black/white threshold at 180 | Clean black text on white background |

**OCR with Tesseract.** Tesseract (page segmentation mode 3, "automatic layout") returns every word it
recognises together with its **position and a confidence score (0–100)**.

**The same table problem, the same solution.** Tesseract also reads tables column by column — on a real
blood-count report, all 18 test names came out first and all 18 results 33 lines later. So the word
positions are regrouped into rows exactly as for digital PDFs (4.1). If that ever yields nothing, the
system falls back to Tesseract's plain text.

The **mean word confidence** of the scan is kept: below 50 the report is sent to an admin (step 6).

### 4.3 When the file cannot be read

| Situation | Result |
| --- | --- |
| Damaged PDF, PDF with no pages | `400 unreadable` — "The PDF is damaged or is not a valid PDF file." |
| Password-protected PDF | `400 unreadable` — "...is password-protected. Upload a copy without a password." |
| Damaged image | `400 unreadable` — "The image is damaged or is not a valid PNG/JPG file." |
| Scan but Tesseract not installed, or a scan with no readable text | Not an error any more: with no values and nothing to identify the patient by, the report can be saved as an **unverified document** (section 12) |

---

## 5. Step 3a — Cleaning up the OCR text

`extractor.py` → `normalize_ocr_text`

Before searching, typical OCR damage is repaired:

- Runs of spaces and tabs are collapsed; `|` and `_` (table borders) become spaces.
- A lone `O` or `l` right before a number becomes `0` or `1` ("O 9.5" → "0 9.5"), but letters that are
  part of a unit ("mmol/L", "g/L") are left alone.
- A **decimal comma** becomes a decimal point: `13,13 g/dl` → `13.13`. A thousands separator such as
  `1,234` (three digits after the comma) is left alone.

---

## 6. Step 3b — Extracting the test values

`extractor.py` → `extract_medical_fields`

Each test (haemoglobin, cholesterol, HbA1C, urea, ...) is searched for in **four passes**. The first pass
that finds a value wins; later passes only look for tests still missing.

### Pass 1 — Label, then the number after it

Every test has a list of **label spellings (aliases)**, including abbreviations and common OCR misreads:

| Test | Some of the labels recognised |
| --- | --- |
| Haemoglobin | Haemoglobin, Hemoglobin, Hb, HGB, and misreads like "Haemoglobln", "Hemog1obin" |
| Total cholesterol | Total Cholesterol, Cholesterol Total, T. Chol, Serum Cholesterol |
| Random blood sugar | Random Blood Sugar, RBS, RBG, Glucose Random, Blood Sugar (Random) |
| Fasting blood sugar | Fasting Blood Sugar, FBS, FBG, Glucose Fasting |
| HbA1C | HbA1c, Hb A1c, A1c, Glycated / Glycosylated Haemoglobin, Haemoglobin A1c, and OCR forms "HbAIC", "HbAlC", "HbA1 C" |
| Others | HDL, LDL, triglycerides, creatinine, urea, uric acid, SGPT/ALT, SGOT/AST, bilirubin, TSH, T3, T4, sodium, potassium, WBC, RBC, platelets, haematocrit, ESR, blood pressure, pulse, SpO2, temperature, blood group |

For each line containing a label, the system takes **the first number after the label**, allowing up to
30 non-digit characters in between (":", "(Hb)", table spacing). If the line has no number, it looks at
the next one or two lines (some layouts print the value below the label). The **unit** printed right
after the number is read too (g/dL, mg/dL, mmol/L, %, U/L, mEq/L, ...).

Safeguards built into this pass:

- **A reference range is not a result.** A number followed by a dash and another number ("12-15") is
  skipped.
- **A number stuck to letters is not a result.** OCR garbage such as `a4l` is ignored instead of
  becoming "4".
- **"SGPT: 34 SGOT: 28"** — taking the number right after each label keeps SGOT = 28, not 34.
- **Haemoglobin is not taken from look-alike lines.** Lines about HbA1C ("Glycated Haemoglobin 5.8 %")
  and red-cell indices ("Mean Cell Haemoglobin 29.8", MCH, MCHC) contain the word "Haemoglobin" but are
  skipped when looking for haemoglobin.

### Pass 2 — Detailed patterns per test

Each test also has one or more **regular expressions** written for the formats labs use, for example
"Blood Sugar (Fasting) 99 mg/dL", "Blood sugar 140 mg/dL (random)", "Haemoglobin (Hb) 12.9 g/dL (13–17)".
They catch layouts pass 1 misses and also read the printed reference range when present.

### Pass 3 — Flexible patterns for the main dashboard tests

For haemoglobin, total cholesterol and random blood sugar, a last, more forgiving pattern allows **up to
40 non-digit characters** between label and number, ignoring case. It understands "HGB ...... 13.6",
"Cholesterol, Total 198", "Glucose - Random 132", "Hb (Cyanmeth method) 12.9", and a plain "Blood Sugar
145" (taken as random), while **excluding** fasting and post-prandial sugar ("Blood Sugar Fasting",
"(F)", "PP") and HbA1C.

### Pass 4 — Blood pressure

A final search for "120/80"-style values next to BP labels.

Each value found is stored as: test, value as printed, unit as printed, label text matched.

---

## 7. Step 3c — Extracting the patient's identity

### 7.1 Patient ID (`services/extractor.py` → `find_patient_ids`)

The patient ID is found in three kinds of places:

1. **After an ID label:** "Patient ID", "PID", "UHID", "MRN", "Reg. No.", "Card No."... OCR often reads
   the "I" of "ID" as `1`, `l` or `|`, so "Patient 1D: 79028232" is accepted too.
2. **A Mero Care Card ID anywhere:** `PAT` followed by 4–12 letters/digits containing a digit, e.g.
   "PAT-79028232" or "PAT 7902 8232", also when OCR misreads the prefix (P4T, PA7). Words such as
   "Patient" or "Pathology" are not mistaken for IDs because the code must contain a digit.
3. **In brackets beside the name:** "Name: KARUNA SHRESTHA (SBHF31965)", "Name: Hari Tamang (ID: 7902
   8232)". The bracket may also start the **next line** when the name wraps:
   ```
   Name: KARUNA SHRESTHA
   (SBHF31965)
   ```
   A doctor's number ("Doctor Name: Dr. Rai (NMC 12345)") or an age ("(36 Y)", fewer than 4 digits) is
   not taken as an ID.

IDs printed with `PAT` are kept as "card IDs"; others as "labelled IDs". The difference matters for the
identity check (section 8).

### 7.2 Name, date of birth and report date (`identity.py`)

- **Name:** the text after "Patient Name", "Name", "Name of Patient" (also OCR "Narne"), up to the next
  field ("Age", "Sex", "Date", two spaces, a digit...). Titles (Mr., Mrs., Dr., Kumari...), sex markers
  ("(M)", "Female"), relations ("S/O Ram Tamang") and an ID in brackets are removed. A name printed
  *below* its label (table layouts) is also found. A name right after "Ref. by", "Doctor", "Consultant"
  is ignored — that is not the patient.
- **Date of birth:** after "DOB", "D.O.B", "Date of Birth".
- **Report date:** the **reporting** date, after "Report Date", "Reporting Date", "Reported on" or
  "Date of Report". Only when no reporting date is printed is the **collection / sample** date used
  ("Collection Date", "Collected on", "Sample Date"); the source is recorded (`report_date_source`).
  Registration, printed and birth dates, and a bare "Date:", are never used.
  Formats: `14/09/2026`, `2026-09-14`, `2026-09-14 16:17:14`, `14 Sep 2026`. Day comes first (Nepal);
  `LAB_REPORT_DATE_ORDER=MDY` switches numeric dates to month first. OCR look-alikes are corrected only
  inside numeric dates (`l4/O9/2O26` → 14 Sep 2026; O→0, I/l→1, S→5), so month names are untouched.
  **Bikram Sambat dates** (years ~2070–2090) and **future dates** are rejected, because they cannot be
  compared with Gregorian dates. When no date is found, the user can type it in the preview (section 9);
  otherwise the upload date is used.
- **Age:** **not read and not compared.** (It was removed because lab portals print today's age on
  reprinted old reports, which caused false mismatches.)

---

## 8. Step 4 — The identity check: is this report this patient's?

`services/verifier.py` → `verify`

### 8.1 Patient ID — compared on its digits only

All letters are ignored on both sides: `PAT-79028232`, `PAT 7902 8232`, `Patient ID: 79028232`,
`SBHF31965` vs `PAT-31965` → compared as `79028232` / `31965`. If an ID has fewer than 4 digits, the whole
code is compared instead (2 digits would match too easily). New patient IDs must have at least 4 digits,
and no two patients may share the same number, so this comparison stays unambiguous.

| What the report shows | Outcome |
| --- | --- |
| The patient's number | ✓ continue |
| The number only after correcting OCR look-alikes (O→0, I/L→1, S→5, Z→2), e.g. `79O28232` | review: "patient_id_unclear" |
| A **different number printed with `PAT`** | **rejected (422)**, nothing stored, audit entry with the ID masked (`PAT-7B****D2`) |
| A different bare number (could be the lab's own ID) | review: "patient_id_missing" |
| No ID at all | review: "patient_id_missing" |

### 8.2 The other checks

| Check | How | If it fails |
| --- | --- | --- |
| Name | Report name vs record: first and last name must both appear (any order), small OCR errors allowed (1 letter for short names, 2 for long), titles ignored, one extra middle name allowed; otherwise a fuzzy similarity score (rapidfuzz, threshold 85). If no name label exists, the whole text is searched for the name. | review: "name_mismatch" |
| Date of birth | Only when the report prints one: must equal the record's. | review: "dob_mismatch" |
| Scan quality | Tesseract mean confidence below 50. | review: "low_ocr_confidence" |

**Outcomes:**

| Situation | Status |
| --- | --- |
| All checks pass, values found | **Preview** (`PENDING_CONFIRMATION`) |
| All checks pass, **no card values** found | **Can be saved as a document** (`NO_VALUES_SAVEABLE`) |
| Any doubt | **Admin review** (`NEEDS_REVIEW`; every admin is notified; approve or reject under *Lab Report Review*). An approved report without values becomes `NO_VALUES_SAVEABLE`. |
| No values, and nothing to identify the patient by (no ID, name or date of birth) on an empty or low-confidence scan | `NO_VALUES_SAVEABLE` with `identity_verified = false`, shown as unverified |
| Another patient's `PAT` ID | **Rejected** (422), nothing stored |

Messages never reveal what was read from the report (no other person's name or ID).

---

## 9. Step 5 — Report date check: is this report older than the latest one?

`services/date_check.py` → `check_report_date`

Runs after the identity check passes (never for a report rejected as another patient's) and before
the preview is built. The new report's date is compared with the **latest report date among this
patient's confirmed reports**. That date is worked out from the data every time: previews that were
never confirmed, rejected reports, deleted reports and reports without a date do not count, and
deleting the latest confirmed report falls back to the next one. Other patients' reports never count.

| Result (`date_check_status`) | When | What the user sees |
| --- | --- | --- |
| `first_report` | No confirmed report with a date yet | Nothing extra |
| `ok` | Same day as the latest confirmed report, or later | Nothing extra |
| `older_than_latest` | Earlier than the latest confirmed report | Yellow warning "This report (1 Mar 2026) is older than your latest report (14 Sep 2026)" with a checkbox "I understand this is an older report, upload anyway" that enables Confirm |
| `date_missing` | No reporting or collection date could be read | "Enter the date printed on the report", with an editable date field; the upload is not blocked |

What happens to an older report depends on `LAB_REPORT_OLDER_DATE_POLICY`:

- **`warn`** (default): the preview shows the warning, and **confirm is refused on the server**
  (`400 older_report_not_acknowledged`) unless the request includes `acknowledge_older_report: true`.
  Confirming with the acknowledgement writes an `OVERRIDE_OLDER_REPORT_DATE` audit entry.
- **`block`**: the upload is refused with `422 older_report` and nothing is stored.
- **`allow`**: no warning.

The preview shows the detected date in an editable field so the user can correct an OCR mistake or
type a missing date (`POST reports/{id}/report-date/`). The new date is checked (not in the future),
compared again, marked `report_date_user_entered` (source `user`), and the preview is planned again,
since an older date turns a value into history only.

This is an extra safeguard. As before, an older report never replaces a newer value on the dashboard;
it only adds dated history rows (section 13). Logs record only the status (ok / older / missing),
never the dates.

The preview response carries `report_date`, `report_date_source`, `report_date_user_entered`,
`date_check_status`, `latest_report_date`, `date_message` and `date_ack_required`.

---

## 10. Step 6 — Checking each value

`services/validator.py`, `units.py`

**Unit conversion** to the unit the dashboard uses:

| Test | Converted from | Factor |
| --- | --- | --- |
| Blood sugar | mmol/L → mg/dL | × 18.016 |
| Cholesterol (total, HDL, LDL) | mmol/L → mg/dL | × 38.67 |
| Triglycerides | mmol/L → mg/dL | × 88.57 |
| Haemoglobin | g/L → g/dL | × 0.1 (and g%, gm/dl accepted) |
| Creatinine | µmol/L → mg/dL | ÷ 88.42 |
| Urea | mmol/L → mg/dL | × 6.006 |
| Uric acid | µmol/L → mg/dL | ÷ 59.48 |
| Bilirubin | µmol/L → mg/dL | ÷ 17.1 |
| HbA1C | mmol/mol → % | NGSP formula (48 mmol/mol → 6.54 %) |

No unit printed → the dashboard unit is assumed. An unrecognised unit → the value is flagged
`unknown_unit` and not saved unless the user types it.

**Plausible ranges** catch misreads (a dropped decimal point turns 13.4 into 134):

- **Main tests — haemoglobin 3–25 g/dL, total cholesterol 50–500 mg/dL, random sugar 20–800 mg/dL:**
  a value outside is treated as a misread, shown as "not saved", and **cannot be accepted**.
- **Other tests** (e.g. triglycerides 10–1000, potassium 1.5–10): a value outside is flagged
  `out_of_range`; it is saved only if the user ticks "This value is correct".
- **Blood group** is checked against the eight valid groups.

Two different "nothing usable" cases:

- **No card values at all** (for example a urine or thyroid-ultrasound report): not an error. The
  report can be kept as a document only (section 12).
- **Values were found, but every one failed** the range or unit checks: refused with
  `422 values_not_usable` ("Values were found on this report, but none could be used ... Nothing was
  saved."). It is never silently turned into a document. Values that are only flagged as out of range
  still get the normal preview with "This value is correct".

---

## 11. The optional AI fallback

`services/llm.py` — **off by default** (`LAB_LLM_FALLBACK=False`).

When switched on (and an `ANTHROPIC_API_KEY` is set), it is used **only** when steps 2–3 found no usable
value. The page images (scaled to at most 2000 px, re-encoded, photo metadata removed) are sent to
Anthropic's Claude with an instruction to return **only JSON**:

```json
{"hemoglobin": {"value": "13.2", "unit": "g/dL"},
 "total_cholesterol": null,
 "blood_sugar": {"value": "118", "unit": "mg/dL"},
 "patient_id": "PAT-79028232"}
```

with the rules: copy numbers exactly as printed, use the patient's result not the reference range, use
null when unsure, never guess. The reply is treated as untrusted: anything that is not exactly this
shape, with plain numbers and short units, is thrown away. Values from the AI then go through **the same
identity check, unit conversion, range checks and patient confirmation** as any other value, and the
audit log notes that the AI was used.

It is off by default because **patient data leaves the server** when it is used.

---

## 12. Step 7 — Preview and storage

`services/upload.py`, `services/dashboard.py` → `build_preview`

- The original file is **encrypted** (Fernet: AES-128 + HMAC) before it is stored, under a random file
  name. The extracted text itself is **never stored or logged**.
- One row per value is saved with its planned outcome, shown to the user:

| Status | Meaning |
| --- | --- |
| INSERTED | New value for an empty field |
| UPDATED | Replaces the current value |
| UNCHANGED | Same as the current value |
| HISTORY | Older than the value already shown — kept in history only |
| SKIPPED | Not saved, with the reason (out of range, unknown unit, invalid, blood group conflict) |

- **Nothing on the patient record changes at this point.**
- **No card values found** (status `NO_VALUES_SAVEABLE`): there are no value rows. The preview says
  "No health card values were found. You can save this report as a document only. Dashboard values will
  not change." with the buttons **Save report only** and **Cancel**, and the report date field and
  older-date warning as usual. Nothing is saved without the user's click.
- **Cancel** deletes the report and its encrypted file at once.
- **Unconfirmed previews expire:** `python manage.py purge_lab_uploads` (run it daily) deletes
  `PENDING_CONFIRMATION` and `NO_VALUES_SAVEABLE` previews older than 24 hours, with their files.

---

## 13. Step 8 — Confirm and the dashboard

`services/dashboard.py` → `apply_report`, `build_dashboard`

On **Confirm**, in one database transaction with the report and patient rows locked:

- The user's corrections (typed in the preview) are checked again on the server.
- **Every value gets a dated history row** (`LabResult`), which feeds the trend charts.
- The patient record shows the **latest** value; a report dated earlier than the current value only
  adds history.
- **Blood group** is filled only when empty, never overwritten.
- An audit entry records counts and test names — **never values**.

**Save report only** (a report with no card values), in one transaction: the status becomes
`SAVED_NO_VALUES`, the encrypted file and the report details are kept, and **no value or history rows**
are written, so the dashboard does not change. The older-date acknowledgement applies as for any report,
and a saved document counts as a confirmed report for the date comparison. The audit entry reads
"saved without card values" with the patient ID **masked**. The report appears in the patient's report
list as **"Saved - no card values"**, with view and delete; doctors with access can see it too.

The **dashboard** shows haemoglobin, total cholesterol and random sugar as large cards, then fasting
sugar, HDL, LDL, triglycerides, blood pressure and HbA1C, and then **every other test the patient has a
result for** (urea, creatinine, SGPT, platelets, TSH...). Each shows the latest value, date, trend and a
**Low / Normal / High** badge from adult reference ranges (sex-specific where it matters, e.g.
haemoglobin, creatinine, haematocrit).

**Deleting** a confirmed report removes its values and history; each dashboard value falls back to the
newest remaining result (or is cleared). Deleting a `SAVED_NO_VALUES` report removes its file and record;
the dashboard is untouched, since it never had values.

---

## 14. Worked example

A scanned hospital report (illustrative values):

```
Name: RAM KUMAR SHARMA            EncID: SBHF31965-57
(SBHF31965)                       Reporting Date: 2026-07-26 16:17:14
BLOOD
Haemoglobin        13,13   g/dl    12-15
HbAIC              5.8     %       4-5.7
Mean Cell Haemoglobin   29.8   pg   26-34
```

| Step | What happens |
| --- | --- |
| Read | It is a scan, so the page is rendered at 200 dpi, cleaned and OCR'd; words are regrouped into rows so each result sits beside its test name. |
| Clean-up | `13,13` → `13.13`. |
| Values | Haemoglobin **13.13** (from the "Haemoglobin" line, not the "Mean Cell Haemoglobin" line); HbA1C **5.8 %** (OCR wrote "HbAIC", a known misread). |
| Identity | ID `SBHF31965` found in brackets on the line below the name → digits **31965** = patient `PAT-31965` ✓. Name matches ✓. Report date 26 Jul 2026. |
| Values check | 13.13 g/dL within 3–25 ✓; 5.8 % within 3–20 ✓. |
| Outcome | Preview → patient clicks **Confirm** → dashboard: Haemoglobin 13.13 (Low for a man, normal 13.5–17.5), HbA1C 5.8 (High, normal below 5.7). |

---

## 15. Settings (`backend/.env`)

| Setting | Default | Purpose |
| --- | --- | --- |
| `OCR_MAX_PDF_PAGES` | 5 | Pages read per PDF |
| `OCR_PDF_DPI` | 200 | Resolution of rendered PDF pages |
| `TESSERACT_CMD` | auto | Path to tesseract.exe if not in the default place |
| `LAB_UPLOAD_THROTTLE_RATE` | 20/hour | Uploads per user |
| `LAB_REPORT_ENCRYPTION_KEY` | derived from SECRET_KEY | Key for stored files (set it in production) |
| `LAB_USE_LIBMAGIC` | False | Detect file types with libmagic (leave off on Windows) |
| `LAB_REPORT_OLDER_DATE_POLICY` | warn | A report older than the latest confirmed one: `warn` (must be acknowledged), `block` (refused) or `allow` |
| `LAB_REPORT_DATE_ORDER` | DMY | Numeric report dates: `DMY` (14/09/2026) or `MDY` (09/14/2026) |
| `LAB_LLM_FALLBACK` | False | Turn on the AI fallback (patient data leaves the server) |
| `ANTHROPIC_API_KEY` | empty | Key for the AI fallback |
| `LAB_LLM_MODEL`, `LAB_LLM_TIMEOUT` | claude-opus-5-5, 45 s | AI model and timeout |

**Needed on the server:** Tesseract OCR for scans and photos. Digital PDFs need nothing extra.

---

## 16. Known limitations

- **Dropped decimal points on some scans.** The black/white threshold in the image clean-up can erase
  small dots, so "130.2" may be read as "1302" and "4.1" as "41". Range checks catch most of these (shown
  as "not saved" or flagged), but the user should check flagged values before accepting them.
- **OCR runs inside the upload request** (a few seconds; pages capped). A background job queue would
  scale better.
- **Very tilted or blurry photos** may not group into rows correctly; a flat scan or the lab's own PDF
  works best.
- **Bikram Sambat dates** are not converted, so such reports count as having no report date.
- **External lab IDs** (UHID, Reg. No.) match only when their digits equal the patient's ID number.
- **Reference ranges** for the badges are general adult ranges, not the lab's own or for children.
- **Count units** (WBC, RBC, platelets) are printed in many forms, so those tiles show no Low/Normal/High
  badge.
- The comment at the top of `identity.py` still mentions an age check; age is no longer compared
  (documentation only).

---

## 17. Tests

```bash
cd backend
python -m pytest apps/lab_reports            # all lab report tests
python -m pytest apps/lab_reports -k "Reading or ReadPdf or ScannedTable or HbA1c or IdentityGate"
python -m pytest apps/lab_reports/tests_date_check.py   # report date ordering check
python -m pytest apps/lab_reports/tests_no_values.py    # reports saved without card values
```

They cover: digital PDFs with table columns, scanned PDFs (with the AI call mocked), damaged files,
reports with no values, label spellings and OCR misreads (Hb/HGB, "Cholesterol, Total", "HbAIC",
"Patient 1D"), decimal commas, numbers stuck to letters, the ID beside the name (same line and wrapped),
digit-only ID matching, rejection of another patient's report, out-of-range values, confirm/update rules,
deleting reports, the report date check (first, later, same-day, older with and without acknowledgement,
the block and allow policies, missing and typed dates, OCR misreads in dates, day/month order, choosing
the reporting date, other patients' and unconfirmed or deleted reports ignored), and that logs never
contain names, IDs, values or dates. Real sample reports (all fake data)
are in `backend/samples/lab_reports/`.
