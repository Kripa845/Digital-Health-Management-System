# Mero Care Card — Project Report

**A digital health management system built around a scannable QR health card**

> **Note (October 2026):** the symptom checker now uses DDXPlus (110 symptoms, 49 illnesses, synthetic data)
> and a Random Forest instead of the Kaggle dataset and Bernoulli Naive Bayes described in sections 5, 6.2
> and 8; see `backend/ml/RESULTS.md` for current figures.

| | |
| --- | --- |
| Backend | Python 3.13, Django 6, Django REST Framework, PostgreSQL |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS |
| Intelligence | Tesseract OCR, PyMuPDF, scikit-learn (Bernoulli Naive Bayes), TOPSIS, rule-based negation detection |
| Tests | 279 backend, 52 frontend component, 2 end-to-end browser tests |
| Date | October 2026 |

---

## Abstract

Mero Care Card gives every patient a printable health card. Its QR code opens a small emergency
profile for anyone who scans it, while an authorised doctor can request access to the full record.
Around the card, the system manages patients, doctors, appointments, prescriptions, documents and lab
results through three role-based portals (patient, doctor, administrator).

Two features apply automated reasoning. **Lab report reading** turns an uploaded PDF or photo into
dashboard values using OCR, pattern-based extraction, unit conversion, range checks, an identity check
and a report-date check; nothing reaches the patient record until the patient confirms it. The
**symptom checker** detects negated symptoms with a rule-based algorithm, predicts likely illnesses with
a Bernoulli Naive Bayes model, maps them to a hospital department and ranks that department's doctors
with the TOPSIS multi-criteria method; an administrator can then assign the patient to a recommended
doctor. Privacy is protected by role-based access, an access rule for doctors, encryption of stored lab
files and an append-only audit log.

---

## Contents

1. Introduction and objectives
2. System architecture
3. Users, roles and login
4. Data model
5. Process implementation, step by step
6. Algorithms
7. Security and privacy
8. Testing and evaluation
9. Deployment and configuration
10. Limitations and future work
11. Conclusion
- Appendix A — API reference
- Appendix B — Running the project

---

## 1. Introduction and objectives

In many clinics a patient's identity, blood group, allergies and test results are spread across paper
files, lab printouts and separate systems. In an emergency, staff may not know who the patient is or
whom to contact; between visits, results are hard to follow over time.

**Objectives**

1. Give every patient a **QR health card** that identifies them safely: emergency essentials for anyone,
   the full record only for authorised doctors.
2. Provide **separate portals** for patients, doctors and administrators, each showing only what that
   role may see.
3. Manage **appointments, prescriptions and documents** in one place.
4. **Read lab reports automatically** and keep a dated history of results, without applying any value
   the patient has not confirmed.
5. **Suggest the right department and doctor** from a description of symptoms, as guidance and never
   as a diagnosis, and let an administrator assign the patient to that doctor.
6. Protect patient data with role-based access, encryption and an append-only audit trail.

---

## 2. System architecture

The system is a single-page web application that talks to a REST API. The browser never reads the
database directly: every request goes through the API, which checks who the user is and what they may do.

```
 Browser (React app)  ──── JSON over HTTPS, JWT access token ────►  Django REST API (/api/v1/)
                                                                        │
            ┌───────────────────────────┬───────────────────────────────┼────────────────────────┐
            ▼                           ▼                               ▼                        ▼
       PostgreSQL              Media storage                    OCR: PyMuPDF +            ml/ package:
   (records, history,       (encrypted lab files,               Tesseract                 Naive Bayes model,
    audit log)               documents, photos)                                           TOPSIS, negation
                                                                        ┆
                                                       optional, off by default: Anthropic API
                                                       (AI fallback for unreadable lab reports)
```

### 2.1 Backend

The backend is a Django project divided into apps, one per area. Every app has the same layers:
**models** (database tables), **serializers** (validation and the JSON shape), **views** (the API
endpoints) and **permissions** (who may call them). Heavier logic lives in service modules so that views
stay small.

| App / package | Responsibility |
| --- | --- |
| `users` | Accounts, roles, login, password change and reset, admin statistics |
| `patients` | Patient records, typed patient IDs, QR tokens, public profile, doctor scan |
| `doctors` | Doctors, assignments, access requests, prescriptions, the doctor access rule |
| `appointments` | Booking against weekly schedules, approval, cancellation, completion |
| `documents` | Uploaded medical documents with authenticated downloads |
| `lab_reports` | OCR, value extraction, identity and date checks, preview, confirm, dashboard |
| `recommendations` | Keyword symptom checker and the smart symptom check endpoint |
| `notifications` | In-app notifications |
| `audit` | Append-only audit log |
| `ml` (package) | Negation detection, Naive Bayes training and prediction, TOPSIS, evaluation scripts |

### 2.2 Frontend

The React app is organised by feature: `public` (landing page, login, public QR profile), `patient`,
`doctor`, `admin`, `lab-reports`, `symptom-checker` and `shared`. Every page is protected by route
guards: `PrivateRoute` requires a login, `RoleRoute` requires a particular role. One API client adds the
login token to every request and renews it automatically; TanStack Query fetches, caches and refreshes
server data. The visual design comes from one set of design tokens with light and dark themes.

**Portal menus**

| Portal | Pages |
| --- | --- |
| Patient | Overview (dashboard), Health Card, Appointments, Lab Reports, Documents, Symptom Checker, My Profile |
| Doctor | Overview, My Patients, Scan a Card, Appointments, My Profile |
| Admin | Overview, Patients, Doctors, Appointments, Symptom Checker, Access Requests, Lab Report Review, Audit Log, Settings |
| Public | Landing page (with a guest symptom checker), Login, Public QR profile |

### 2.3 Technology stack

| Layer | Technologies |
| --- | --- |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS 4, Radix UI, TanStack Query, React Router, react-qr-code, html5-qrcode |
| Backend | Python 3.13, Django 6, Django REST Framework, SimpleJWT, django-filter, WhiteNoise, gunicorn |
| Data | PostgreSQL (SQLite for development), optional Cloudinary media storage |
| Documents and OCR | PyMuPDF, Tesseract (pytesseract), Pillow, rapidfuzz, cryptography (Fernet) |
| Machine learning | scikit-learn (BernoulliNB), pandas, NumPy, joblib, matplotlib |
| Testing | pytest, Vitest, Testing Library, Mock Service Worker, Playwright |

---

## 3. Users, roles and login

There is one `User` table with a **role**: ADMIN, DOCTOR or PATIENT. A doctor or patient user is linked
one-to-one to a `Doctor` or `Patient` profile.

1. **Accounts are created by administrators only** (no self-registration). The login details are
   emailed to the new user; if the email cannot be sent, the administrator is shown them once.
2. **The first login forces a password change.** Administrators can reset any doctor's or patient's
   password, which issues a new temporary one.
3. **Login uses JSON Web Tokens.** The access token lasts 60 minutes; the refresh token lasts 7 days and
   is replaced on every use (the old one is blacklisted). Logging out revokes it on the server.
4. **Login attempts are rate-limited** to 10 per minute per IP address.
5. After login, the app asks `GET /auth/me/` who the user is and opens the matching portal.

---

## 4. Data model

| Table | Main contents |
| --- | --- |
| Patient | Typed patient ID (`PAT-79028232`), random QR token, name, date of birth, gender, blood group, contacts, height and weight, about 28 clinical values, allergies, medication |
| Doctor | Doctor ID, licence number, one of 21 departments, specialization, weekly availability (e.g. Monday `09:00-17:00`) |
| DoctorAssignment | Which doctor looks after which patient (Active / Inactive) |
| AccessRequest | A doctor's request to see a patient's record (Pending / Approved / Declined) |
| Prescription | Diagnosis, medications and notes |
| Appointment | Patient, doctor, date, time, status |
| Document | Uploaded medical files |
| LabReport | An uploaded lab report: status, encrypted file, report date and its source, identity result, review reasons |
| LabReportField | Each value read from a report with its planned or actual outcome |
| LabResult | The dated history of every confirmed value (feeds trends) |
| RecommendationHistory | Every symptom-checker result |
| Notification | In-app messages |
| AuditLog | Append-only record of important actions |

**Lab report statuses:** `PENDING_CONFIRMATION` (preview waiting for confirmation), `NEEDS_REVIEW`
(admin must check it), `NO_VALUES_SAVEABLE` (no card values; can be saved as a document),
`CONFIRMED`, `SAVED_NO_VALUES` (kept as a document only) and `REJECTED`.

---

## 5. Process implementation, step by step

### 5.1 Registering doctors and patients

1. The administrator fills in the doctor or patient form. Names, Nepal phone numbers, email, address,
   height and weight are validated in the browser and again on the server.
2. For a patient, the administrator types **only the number part** of the patient ID; the system adds
   `PAT-`, requires at least four digits and checks that no other patient uses the same number.
3. The server creates the user account with a generated password, links the profile, emails the login
   details and writes an audit entry.
4. For a new patient, the health card with its QR code opens immediately, ready to print.

### 5.2 The health card and QR identity

1. The QR code contains a link with a **random token**, not the patient ID:
   `<site address>/public-profile/<token>`.
2. **Anyone** who scans it sees only name, photo, age, gender, blood group and emergency contact — no
   date of birth, phone number or medical data.
3. **A logged-in doctor** who scans it reaches the doctor scan page; without access they can send an
   access request.
4. If a card is lost, the administrator issues a new token; the old card stops working and the patient
   ID stays the same.

### 5.3 Doctor access

A doctor sees a patient's medical record, documents, lab reports and prescriptions only when **both**
hold: an **active assignment** links them, **and** an **approved access request** exists. An
administrator assigning the doctor counts as approval. The rule is in one module
(`apps/doctors/access.py`) used by every endpoint that returns medical data. Administrators approve or
decline requests; doctor and patient are notified.

### 5.4 Appointments

1. A patient books a doctor for a date and time; the time is checked against the doctor's weekly
   schedule, and a database constraint allows only one live booking per doctor slot.
2. An administrator accepts or declines it.
3. It can be cancelled while pending or accepted; the visit is marked completed afterwards.
4. Each change notifies the people involved.

```
PENDING ──accept──► ACCEPTED ──visit──► COMPLETED
   │                    │
   ├──decline──► DECLINED
   └──cancel───► CANCELLED ◄──cancel──┘
```

### 5.5 Documents, notifications and audit

- **Documents** are stored under random names and downloaded only through an authenticated endpoint
  that applies the access rule.
- **Notifications** are stored in the database; the header bell checks for new ones every 60 seconds.
- **The audit log** records logins, account changes, uploads, assignments, recommendations and lab
  report decisions. Entries cannot be edited or deleted, and never contain lab values or report text.

### 5.6 Lab report reading (end to end)

```
Upload → 1 file checks → 2 get text → 3 extract values and identity → 4 identity check
       → 5 report date check → 6 value checks → 7 preview → 8 confirm → dashboard
```

1. **File checks.** PDF, PNG or JPG up to 10 MB; the real type is read from the file's first bytes; a
   SHA-256 hash blocks the same file twice for one patient; at most 20 uploads per hour per user.
2. **Get the text.** A digital PDF's own text is read with PyMuPDF. A scan or photo is rendered at
   200 dpi, cleaned and read with Tesseract OCR. In both cases the words are regrouped into table rows
   by position (Algorithm 6.6).
3. **Extract.** Test values and units are found by label patterns (Algorithm 6.7); the patient ID, name,
   date of birth and report date are found by their labels.
4. **Identity check** (Algorithms 6.8 and 6.9). Match → continue; doubt → admin review; another
   patient's `PAT` ID → rejected, nothing stored.
5. **Report date check** (Algorithm 6.11). A report older than the patient's latest confirmed report
   shows a warning and must be acknowledged before confirming.
6. **Value checks** (Algorithm 6.10). Units are converted; implausible values are dropped or flagged.
   If values were found but none is usable, the upload is refused (`values_not_usable`).
7. **Preview.** The file is encrypted and stored; each value is shown with its planned outcome
   (will be added / updated / same as now / history only / won't be saved). The user can correct values
   and the report date. **Nothing on the record has changed yet.**
   - If the report has **no card values at all** (for example a urine report), the preview offers
     **Save report only** instead.
8. **Confirm.** In one database transaction: every value becomes a dated history row; the record shows
   the latest value; an older report only adds history; blood group is never overwritten. **Save report
   only** keeps the file as a document with no values.

Reports can be viewed (PDF or image inside the page), downloaded or deleted. Deleting a confirmed report
removes its values and history; each dashboard value falls back to the newest remaining result.
Unconfirmed previews are deleted after 24 hours by `python manage.py purge_lab_uploads`.

### 5.7 Health dashboard

Haemoglobin, total cholesterol and random sugar appear as large cards; fasting sugar, HDL, LDL,
triglycerides, blood pressure and HbA1C follow; then every other test the patient has a result for
(urea, creatinine, SGPT, platelets…). Each shows the latest value and date, a trend chart, a trend arrow
and a Low / Normal / High badge (Algorithm 6.12). Reports saved without values never appear here.

### 5.8 Symptom checker and doctor assignment

1. The user describes symptoms in their own words. An administrator first picks the patient from a
   dropdown of all patients (or checks without one); a patient always checks for themselves.
2. **Negation detection** keeps only the symptoms that are present (Algorithm 6.1).
3. **Naive Bayes** estimates the probability of each of 41 illnesses (Algorithm 6.2); the three most
   likely are shown.
4. The illness probabilities are added up per department; the best department must reach at least 40 %
   from at least two symptoms (Algorithm 6.3). Otherwise the **keyword checker** is used as a fallback
   (Algorithm 6.5).
5. **TOPSIS** ranks the active doctors of that department by free hours this week and current caseload
   (Algorithm 6.4). If the department has no doctor, General Medicine doctors are suggested.
6. The page shows the three steps, the top three doctors with their TOPSIS score and a reason, and the
   statement **"Suggestion only, not a medical diagnosis."** The result is saved to the symptom history.
7. **Assign.** Beside each recommended doctor, an administrator has an **Assign** button. With a patient
   chosen it assigns that patient at once; otherwise it opens a dialog to pick the patient. Assigning also
   approves the doctor's access to the record and is audited.

---

## 6. Algorithms

### 6.1 Rule-based negation detection (`ml/negation.py`)

**Purpose:** "no fever but headache and cough" must give *headache, cough*, not *fever*.

1. Lower-case the text, turn underscores into spaces, and make commas, semicolons and full stops
   separate words.
2. Match each known symptom as a **sequence of words** (so "chest pain" is one symptom).
3. For each match at word position *i*, look back up to **4 words**, nearest first:
   - a **stopper** (`but`, `however`, `although`, `though`, `,`, `.`) ends the search → not negated;
   - a **negation** (`no`, `not`, `without`, `never`, `denies`, `deny`) → negated.
4. A symptom is present if at least one of its mentions is not negated.

Verified by 24 test cases (24/24 pass).

### 6.2 Bernoulli Naive Bayes (`ml/train_nb.py`, `ml/symptom_model.py`)

**Data:** a public Kaggle dataset of 41 illnesses and 131 symptoms. Of its 4,920 rows, 4,616 are
duplicates, so duplicates are removed **before** splitting, leaving 304 unique rows (5–10 per illness).
Each description becomes a 0/1 vector (symptom present or absent). Training uses an 80/20 stratified
split and `BernoulliNB(alpha=1.0)` (Laplace smoothing).

**Model.** For each illness *d* and symptom vector *x*:

```
score(d) = P(d) × Π P(xᵢ = 1 | d)        for every symptom present
               × Π (1 − P(xᵢ = 1 | d))  for every symptom absent

P(d | x) = score(d) / Σ score(all illnesses)
```

**Worked example (unit test).** Priors Flu 0.40, Migraine 0.30, Cold 0.30; fever present, cough present,
headache absent; P(fever|d) = 0.90 / 0.10 / 0.30, P(cough|d) = 0.80 / 0.05 / 0.90,
P(headache|d) = 0.50 / 0.95 / 0.30.
Scores: Flu 0.4 × 0.9 × 0.8 × 0.5 = **0.1440**; Migraine 0.3 × 0.1 × 0.05 × 0.05 = **0.000075**;
Cold 0.3 × 0.3 × 0.9 × 0.7 = **0.0567** → normalised **Flu 71.7 %, Cold 28.2 %, Migraine 0.04 %**.
scikit-learn's BernoulliNB given the same parameters returns the same posteriors.

The trained model is saved with joblib and **loaded once when the server starts**, never per request.

### 6.3 Illness → department aggregation (`ml/disease_dept.py`)

Each of the 41 illnesses maps to one of the hospital's 21 departments (unknown illnesses → General
Medicine). The probability of a department is the **sum** of its illnesses' probabilities, so several
moderately likely liver illnesses together point clearly to Gastroenterology. Thresholds: at least
**2 recognised symptoms** and a best department of at least **40 %**; otherwise the status is
`not_enough_info` or `low_confidence` and the keyword checker answers instead. The map is marked as
needing review by a medical professional.

### 6.4 TOPSIS doctor ranking (`ml/topsis.py`)

TOPSIS (Technique for Order of Preference by Similarity to Ideal Solution) ranks options by how close
they are to an ideal option and how far from the worst one.

**Criteria from real data:** free hours this week (benefit: scheduled hours from today to Sunday minus
30 minutes per open booking) and current caseload (cost: active assignments). The default weights
0.4 / 0.4 / 0.2 include experience, which the Doctor model does not store, so the live ranking uses
two criteria at 0.5 / 0.5.

1. Normalise each column: value ÷ √(sum of squares of the column).
2. Multiply by the weights.
3. Ideal best = maximum for benefit, minimum for cost; ideal worst = the opposite.
4. Euclidean distance of each doctor to the best (d⁺) and to the worst (d⁻).
5. **Score = d⁻ ÷ (d⁺ + d⁻)**, from 0 to 1; higher is better. One doctor scores 1.0.

**Worked example (unit test):** doctors A, B, C with [free hours, caseload, experience] =
[10, 20, 5], [6, 8, 10], [12, 25, 15] score **0.377, 0.582, 0.465** → ranking **B, C, A**.

**Sensitivity:**

| Weights (free / caseload / experience) | A | B | C | Ranking |
| --- | --- | --- | --- | --- |
| 0.4 / 0.4 / 0.2 (default) | 0.377 | 0.582 | 0.465 | B > C > A |
| 0.6 / 0.2 / 0.2 | 0.498 | 0.344 | 0.700 | C > A > B |
| 0.2 / 0.6 / 0.2 | 0.296 | 0.778 | 0.294 | B > A > C |
| Equal | 0.301 | 0.565 | 0.555 | B > C > A |
| 0.2 / 0.2 / 0.6 | 0.147 | 0.520 | 0.761 | C > B > A |

### 6.5 Keyword symptom checker (fallback; `apps/recommendations/views.py`)

1. **Department scores:** 21 departments × 219 weighted keywords; each keyword found (and not negated)
   adds its weight; a keyword in the medical history adds half its weight.
2. **Confidence** = best department's score ÷ total score, kept between 25 % and 98 %.
3. **Clinical severity index** = highest severity weight among the 132-symptom severity table ÷ 7 × 100.
4. **Doctor points:** department match (up to 50), medical history relates (15), age suits the
   department (up to 15), pain level (up to 10), available today (5), caseload (5 ÷ (1 + active patients)).
5. Top three doctors, or two when the case is urgent (pain ≥ 8 or severity ≥ 70).

### 6.6 OCR text reconstruction (`apps/lab_reports/ocr_service.py`)

1. **Image clean-up** for scans: greyscale → enlarge to at least 1200 px → contrast × 1.8 →
   sharpness × 2 → 3-pixel median filter (removes speckle) → black/white threshold at 180.
2. **Tesseract OCR** returns every word with its bounding box and a confidence score (0–100).
3. **Row reconstruction** (both PDFs and OCR read tables column by column):
   - sort words by the vertical centre of their box;
   - a word joins the current row if its centre is within half a line height of the row's centre; the
     row centre follows its words slightly so a tilted scan still works;
   - within a row, sort by horizontal position; a gap wider than about 2½ character widths becomes two
     spaces (a column break), otherwise one.
   Result: "Haemoglobin  13.13  g/dl  12-15" on one line, as printed.
4. **Text clean-up:** a lone `O`/`l` before a number becomes `0`/`1`; a decimal comma (`13,13`) becomes a
   decimal point; thousands (`1,234`) are left alone.

### 6.7 Value extraction (`apps/lab_reports/extractor.py`)

Four passes; the first one that finds a test wins:

1. **Label → number.** Each test has a list of label spellings including OCR misreads (Hb, HGB,
   Haemoglobin; T. Chol; RBS; HbA1C read as "HbAIC"). The value is the first number after the label (up
   to 30 characters later) or on the next line; the unit after it is read too.
2. **Detailed patterns** per test for common lab layouts.
3. **Flexible patterns** for the three main tests (up to 40 non-digit characters between label and number).
4. **Blood pressure** as `120/80`.

**Guards:** a reference range ("12-15") is never taken as the result; a number stuck to letters (`a4l`)
is ignored; lines about HbA1C or red-cell indices (Mean Cell Haemoglobin) are never read as haemoglobin;
fasting and post-meal sugar are not read as random sugar.

### 6.8 Fuzzy name matching (`apps/lab_reports/identity.py`)

1. Names are split into words; titles (Mr., Dr., Kumari…), sex markers and "S/O …" are removed.
2. Two words match if equal, or within an **edit distance** (Levenshtein) of 1 for words up to
   6 letters and 2 for longer words (OCR errors), when both have at least 3 letters.
3. The patient's first and last names must both appear (any order). A recorded middle name may be
   missing; with no recorded middle name, one extra word is allowed only between first and last name.
4. If that fails, a fuzzy similarity score (rapidfuzz `token_set_ratio`) below **85** means "different
   name" → admin review.

### 6.9 Patient ID matching (`apps/lab_reports/services/verifier.py`)

1. **Finding the ID:** after labels ("Patient ID", "PID", "UHID", "MRN"… including OCR's "Patient 1D"),
   as `PAT-…` anywhere, or in brackets beside the name — "Name: KARUNA SHRESTHA (SBHF31965)", even when
   the bracket wraps to the next line.
2. **Comparison on digits only:** all letters are removed on both sides, so `SBHF31965` = `PAT-31965`.
   An ID with fewer than 4 digits is compared whole.
3. **OCR look-alikes:** if the digits only match after correcting O→0, I/L→1, S→5, Z→2, the report goes to
   admin review ("unclear ID").
4. **Outcome:** match → continue; another patient's `PAT` ID → rejected (422) and audited with the ID
   masked (`PAT-79****32`); a different bare number (possibly the lab's own) or no ID → admin review.

### 6.10 Unit conversion and plausibility ranges (`services/validator.py`, `units.py`)

| Test | Conversion to the dashboard unit |
| --- | --- |
| Blood sugar | mmol/L × 18.016 → mg/dL |
| Cholesterol (total, HDL, LDL) | mmol/L × 38.67 → mg/dL |
| Triglycerides | mmol/L × 88.57 → mg/dL |
| Haemoglobin | g/L ÷ 10 → g/dL |
| Creatinine | µmol/L ÷ 88.42 → mg/dL |
| Urea | mmol/L × 6.006 → mg/dL |
| HbA1C | mmol/mol → % (NGSP formula; 48 → 6.54 %) |

**Ranges:** haemoglobin 3–25 g/dL, total cholesterol 50–500 mg/dL and random sugar 20–800 mg/dL — values
outside are treated as misreads and never saved. Other tests outside their range are flagged and saved
only if the user ticks "This value is correct". An unknown unit is not saved unless the user types the value.

### 6.11 Report date ordering check (`services/date_check.py`)

1. **Which date:** the *reporting* date ("Report Date", "Reporting Date", "Reported on", "Date of Report");
   the collection/sample date only if no reporting date is printed. Day first by default
   (`LAB_REPORT_DATE_ORDER`); OCR look-alikes are corrected inside numeric dates (`l4/O9/2O26` →
   14 Sep 2026); future and Bikram Sambat dates are rejected.
2. **Compared with:** the latest report date among the patient's **confirmed** reports (including saved
   documents), worked out from the data each time.
3. **Result:** `first_report`, `ok` (same day or later), `older_than_latest`, or `date_missing` (the user
   types the date).
4. **Policy** (`LAB_REPORT_OLDER_DATE_POLICY`): `warn` (default) — confirming needs an explicit
   acknowledgement, enforced on the server and audited; `block` — refused; `allow` — no warning.

### 6.12 Dashboard status and trend (`services/dashboard.py`)

- **Status:** Low / Normal / High from adult reference ranges (sex-specific for haemoglobin, creatinine,
  uric acid, haematocrit, ESR). A value far outside the range is marked severe.
- **Trend:** compare the last two results; a change above +2 % is "up", below −2 % "down", otherwise
  "stable" (needs at least two results).

### 6.13 Encryption and duplicate detection

- Lab report files are encrypted with **Fernet** (AES-128-CBC with HMAC-SHA256) before storage.
- A **SHA-256** hash of each uploaded file detects the same file uploaded twice for a patient.

### 6.14 Optional AI fallback (`services/llm.py`)

Off by default. When switched on and the text gave no usable value, the page images are sent to
Anthropic's Claude with a request for **JSON only** (haemoglobin, total cholesterol, blood sugar, patient
ID, each with its unit; null when unsure; never guess). The reply is validated strictly — any other shape
is ignored — and its values pass the same identity, date and range checks and need the user's
confirmation. It is off by default because report images would leave the server.

---

## 7. Security and privacy

| Concern | Measure |
| --- | --- |
| Who sees what | Role checks on every endpoint; the doctor access rule for all medical data |
| Sessions | Short JWT access tokens, rotating refresh tokens, server-side logout, login rate limit |
| Accounts | Admin-created only; forced password change on first login |
| Uploaded files | Real type from content, size limit, random names, authenticated downloads; lab files encrypted |
| QR card | Random, replaceable token; public page shows identity essentials only |
| Logs | Append-only audit log; no lab values, report text, dates of reports or full IDs read from reports are logged |
| External services | AI fallback off by default; the symptom model runs on the server |
| Production | The server refuses to start without a secret key, allowed hosts and allowed origins |

---

## 8. Testing and evaluation

### 8.1 Automated tests

| Area | Tool | Tests |
| --- | --- | --- |
| Lab reports (OCR, extraction, identity, dates, no-values, confirm, delete, security) | pytest | 169 |
| Patients (IDs, QR, profile) | pytest | 46 |
| Symptom checkers (keyword and smart endpoint, assignment of the chosen patient) | pytest | 21 |
| Users and login | pytest | 16 |
| Doctors, appointments, documents | pytest | 23 |
| Machine-learning modules (negation, TOPSIS, Naive Bayes, department map) | pytest | 4 suites |
| **Backend total** | pytest | **279** |
| Frontend components (lab upload/confirm/view/delete, dashboard, admin forms, symptom checker, assign) | Vitest, Testing Library, MSW | **52** |
| End to end (upload a matching and a mismatching report in a real browser) | Playwright | **2** |

### 8.2 Symptom checker evaluation (`python -m ml.evaluate`)

| Metric | Value |
| --- | --- |
| Naive Bayes accuracy (61 held-out rows) | 96.7 % |
| Macro F1 | 0.955 |
| Without deduplication (misleading) | 100 % |

| Method (50 standard + 12 negation cases) | Correct | Accuracy |
| --- | --- | --- |
| Keyword checker | 27 / 62 | 43.5 % |
| Naive Bayes only | 55 / 62 | 88.7 % |
| **New system with keyword fallback** | **56 / 62** | **90.3 %** |
| Naive Bayes without negation detection | 52 / 62 | 83.9 % |

On the negation cases, negation detection doubled Naive Bayes accuracy (3 → 6 of 12).
**Caveat:** the Kaggle dataset is clean and synthetic-looking, so these figures are far higher than
real-world performance would be; the illness-to-department map needs medical review.

---

## 9. Deployment and configuration

The backend ships as a Docker image that includes Tesseract OCR and runs gunicorn with several workers;
WhiteNoise serves static files; PostgreSQL is configured through `DATABASE_URL`; media can be stored on
Cloudinary. The frontend is a static Vite build (`VITE_API_URL` for the API, `VITE_FRONTEND_URL` for the
address printed in QR codes).

| Setting | Default | Purpose |
| --- | --- | --- |
| `LAB_REPORT_ENCRYPTION_KEY` | derived from SECRET_KEY | Key for stored lab files |
| `LAB_UPLOAD_THROTTLE_RATE` | 20/hour | Uploads per user |
| `OCR_MAX_PDF_PAGES`, `OCR_PDF_DPI` | 5, 200 | Pages read and render resolution |
| `LAB_REPORT_OLDER_DATE_POLICY` | warn | Older reports: warn / block / allow |
| `LAB_REPORT_DATE_ORDER` | DMY | Numeric dates: day or month first |
| `LAB_LLM_FALLBACK`, `ANTHROPIC_API_KEY` | False, empty | Optional AI fallback |

Scheduled job: `python manage.py purge_lab_uploads` (daily) removes unconfirmed previews after 24 hours.

---

## 10. Limitations and future work

- OCR runs inside the upload request; a background job queue would scale better.
- Poor scans can lose decimal points (130.2 → 1302); range checks catch most cases.
- Bikram Sambat (Nepali calendar) dates are not converted.
- Reference ranges are general adult ranges, not laboratory- or child-specific.
- The symptom model knows 41 illnesses and the dataset's symptom names only; plain "fever" is not in its
  vocabulary (a synonym list would help).
- The illness-to-department map, TOPSIS weights and the assumed 30 minutes per appointment need review.
- The Doctor model stores no experience, so TOPSIS uses two criteria instead of three.
- After removing the patient "Find a Doctor" and admin "Recommendations" pages, past symptom checks are
  saved but not listed on any page.
- **Future work:** real clinical training data, a background OCR queue, appointment durations, a
  recommendation history view, and native mobile apps for scanning cards.

---

## 11. Conclusion

Mero Care Card brings patient identity, records, appointments and results into one role-based system
around a simple QR card. Its automated features assist people rather than replace them: lab reports
become dashboard values only after an identity check, a date check and the patient's confirmation, and
any doubt goes to an administrator; the symptom checker combines rule-based negation detection, a
probabilistic Naive Bayes model and multi-criteria TOPSIS ranking, labels every result as a suggestion,
and lets an administrator act on it by assigning the patient to a doctor. Privacy is built in through the
access rule, encryption, minimal public data and an append-only audit log.

---

## Appendix A — API reference

All paths are under `/api/v1/`.

| Area | Endpoints |
| --- | --- |
| Login | `auth/login/`, `auth/refresh/`, `auth/logout/`, `auth/me/`, `auth/change-password/` |
| Administration | `auth/admin/reset-password/`, `auth/admin/manage-admins/`, `auth/admin/stats/`, `audit-logs/` |
| Patients | `patients/`, `patients/me/`, `patients/public/<token>/`, `patients/scan/<token>/`, `patients/{id}/regenerate_qr/`, `toggle_status/`, `reset_password/` |
| Doctors | `doctors/`, `doctors/{id}/reset_password/`, `doctors/{id}/available-dates/`, `doctors/{id}/available-slots/?date=YYYY-MM-DD`, `assignments/`, `access-requests/` (approve / decline), `prescriptions/` |
| Appointments | `appointments/`, `appointments/{id}/accept/`, `decline/`, `cancel/`, `complete/` |
| Documents | `documents/`, `documents/{id}/download/` |
| Lab reports | `reports/upload/`, `reports/{id}/confirm/`, `discard/`, `report-date/`, `download/`, `status/`, `reprocess/`, `DELETE reports/{id}/`, `dashboard/`, `admin/review-queue/`, `admin/reports/{id}/resolve/` |
| Symptom checkers | `recommendations/` (keyword), `smart-symptom-check/` (negation + Naive Bayes + TOPSIS) |
| Notifications | `notifications/`, `notifications/{id}/mark-read/`, `notifications/mark-all-read/` |

## Appendix B — Running the project

```bash
# Backend (from backend/)
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo          # demo data and logins
python -m ml.train_nb               # train the symptom model
python manage.py runserver

# Frontend (from frontend/)
npm install
npm run dev                         # http://localhost:5173

# Tests and evaluation
python -m pytest                    # backend (from backend/)
python -m ml.evaluate               # symptom checker evaluation → ml/RESULTS.md
npm test                            # frontend component tests
npm run test:e2e                    # end-to-end browser tests
```

Demo logins after `seed_demo`: administrator `admin`, doctor `dr.sharma`, patient `hari.tamang`.
