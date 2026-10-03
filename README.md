# Mero Care Card

**A humane, secure digital health platform** — a scannable QR health card for every patient,
guided doctor matching, appointments, and private medical records, with dedicated portals for
patients, clinicians, and administrators.

This is a ground-up rebuild with a sophisticated, accessible UI (React + TypeScript + Tailwind v4,
a token-based design system, light/dark themes) on a clean Django REST Framework backend
(JWT auth, role-based permissions, a transparent recommendation engine, QR identity,
audit logging).

---

## Stack

**Frontend** — React 19, TypeScript, Vite, Tailwind CSS v4 (design tokens), shadcn-style components
on Radix primitives, TanStack Query, React Router, framer-motion, react-hook-form + zod, sonner,
lucide-react, react-qr-code, html5-qrcode. Self-hosted variable fonts (Fraunces · Hanken Grotesk · JetBrains Mono).

**Backend** — Django 6 + Django REST Framework, SimpleJWT (rotating refresh + blacklist),
django-filter, WhiteNoise, SQLite (dev) / PostgreSQL (prod), optional Cloudinary media.

---

## Quick start

### 1. Backend (http://127.0.0.1:8000)
```bash
cd backend
python -m venv venv              # first run only
venv\Scripts\activate            # Windows PowerShell/cmd  ·  Git Bash: source venv/Scripts/activate
pip install -r requirements-dev.txt  # first run only (production installs requirements.txt)
python manage.py migrate         # first run only
python manage.py seed_demo       # rich demo data + prints credentials
python manage.py runserver 127.0.0.1:8000
```

### 2. Frontend (http://localhost:5173)
```bash
cd frontend
npm install                      # first run only
npm run dev
```
Optionally copy `backend/.env.example` to `backend/.env` to override settings; without it the
backend runs with development defaults. With `DEBUG=False` the backend refuses to start unless
`SECRET_KEY`, `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS` are set.

Run the backend tests with `pytest` from `backend/`.

Vite proxies `/api` and `/media` to the backend, so no CORS setup is needed in dev.

### Demo accounts
| Role | Username | Password |
| --- | --- | --- |
| Admin | `admin` | `admin12345` |
| Doctor | `dr.sharma` | `doctor12345` |
| Patient | `hari.tamang` | `patient12345` |

(Full list printed by `seed_demo`.
Sign-in is a simple username + password.)

---

## What's inside

- **Public** — an editorial landing page, an interactive symptom checker (no account needed),
  and a privacy-preserving public QR profile that reveals identity essentials only.
- **Patient portal** — digital health card with printable QR, appointments, reports & prescriptions,
  doctor matching, profile.
- **Doctor portal** — assigned patients, QR card scanning with access requests, appointments,
  editable profile & availability.
- **Admin portal** — dashboards & stats, full patient/doctor management, appointments,
  recommendation history, access-request approvals, audit log, settings.

## Design system

A single token layer in `frontend/src/index.css` drives everything: warm-paper neutrals with a
subtle green bias, a healing emerald-teal brand accent, semantic colors kept distinct from the brand,
and full light/dark theming (system-aware, with a manual toggle). Components live in
`frontend/src/components/ui`.

## Security notes
- **Sessions:** JWT with rotating refresh tokens. Logging out revokes the refresh token on the server.
  Login attempts are rate limited (`LOGIN_THROTTLE_RATE`, default 10 per minute per IP).
- **New accounts:** login details are emailed to the new user (SMTP settings in `.env`). If the email
  cannot be sent, the admin is shown the details once to hand over in person. Every user must change
  the password on first sign-in.
- **Doctor access:** a doctor sees a patient's medical record, documents, lab reports and their own
  prescriptions only with an active assignment **and** an approved access request
  (`apps/doctors/access.py`). An admin assigning a doctor counts as approval.
- **Patient IDs and QR cards:** the admin types only the number part of the patient ID (e.g. `79028232`;
  4–12 letters or digits with at least one digit) and `PAT-` is added, so it is stored as `PAT-79028232`.
  **Generate** suggests an 8-digit number. IDs are unique regardless of case, and an admin can change one
  later (logged as `CHANGE_PATIENT_ID`); cards and reports printed with the old ID then no longer match.
  The new patient's QR card opens straight away, ready to print.
  The QR encodes `<VITE_FRONTEND_URL>/public-profile/<uuid_token>`, never the patient ID. Set
  `VITE_FRONTEND_URL` in `frontend/.env` to the public site address; without it, the address the page is
  opened from is used.
- **Public QR profile:** shows name, photo, age, gender, blood group and emergency contact only. If a card
  is lost, an admin can issue a new QR code (Patients → View QR → Card lost?), which disables the old one.
- **Files:** uploads are stored under random names and served only through authenticated download
  endpoints.
- **Lab reports:** see [Lab report upload](#lab-report-upload) below. Files are encrypted at rest, the
  report text is never stored or logged, and IDs read from reports are masked in the audit log.
- **Audit log:** append-only; entries cannot be edited or deleted.

---

## Lab report upload

A patient uploads a lab report (PDF, PNG or JPG). The system reads it, checks that it belongs to them,
and shows the values for confirmation. The dashboard changes only after they confirm.

```
upload → file checks → OCR → extract values → identity gate → preview → confirm → dashboard
                                                   │
                                   wrong patient ID: 422, nothing stored
                                   no or unclear ID, name/DOB/age mismatch: NEEDS_REVIEW (admin)
```

- **Identity gate:** the report must show the patient's ID. Only its **digits** are compared (all letters
  are ignored), so `PAT-79028232`, `PAT 7902 8232`, `Patient ID: 79028232` and an ID in brackets beside the
  name, `Name: Hari Tamang (79028232)`, all match `PAT-79028232`. An ID with fewer than 4 digits is compared
  whole. New or changed patient IDs need at least 4 digits, and no two patients may share the same number.
  - **Match** → preview.
  - **A different ID printed with `PAT`** → rejected (422) and nothing stored. A different bare number may be
    the lab's own ID, so it goes to review instead.
  - **No card ID, an OCR look-alike (O/0, I/1, S/5), a different name (rapidfuzz < 85), a different date of
    birth, or a hard-to-read scan** → `NEEDS_REVIEW`. The age printed on a report is not read or compared. An admin approves or rejects it under
    **Lab Report Review**. It is never auto-accepted.
- **Values:** haemoglobin, total cholesterol and random blood sugar, plus the other dashboard tests,
  blood group, name, date of birth and report date. Missing values are `null`; nothing is guessed.
  - Synonyms such as Hb/HGB/Haemoglobin, T. Chol and RBS are recognised.
  - Units are converted: glucose mmol/L ×18.016, haemoglobin g/L ÷10, cholesterol mmol/L ×38.67.
  - Haemoglobin outside 3–25 g/dL, total cholesterol outside 50–500 mg/dL and random sugar outside
    20–800 mg/dL are treated as misreads: shown as "not saved" and never saved. Other tests outside their
    range are flagged and saved only if the user ticks "This value is correct".
- **Reading the file:** a PDF's own text (PyMuPDF, table rows kept together) is used when it has more than
  50 characters; otherwise the page images (200 dpi) are read with Tesseract OCR. Flexible patterns catch
  wordings such as Hb/HGB, "Cholesterol, Total", T. Chol, RBS and "Glucose - Random". If no usable value is
  found, the optional AI fallback (below) can read the page images. When both find no card values, the report can still be saved as a document only ("Saved - no card values");
  values that were found but all failed the range checks are refused (`values_not_usable`).
  The log records only the method used and the text length, never names, IDs or values.
- **Update rules on confirm:** run in one transaction with the rows locked.
  - Blood group is set only when empty and never overwritten.
  - Age always comes from the date of birth.
  - Every value gets a new dated history row.
  - A report older than the latest value only adds history.
- **View:** the eye button on a report shows the original PDF or image in the page (owner, admin, or a doctor with
  approved access), fetched through the authenticated download endpoint.
- **Delete:** the patient or an admin can delete a report in any status (after a confirmation step). Deleting a
  confirmed report removes its values from the dashboard and history; earlier results are shown again.
- **Pages:** Dashboard (cards with Low/Normal/High badges and trend charts; the main tests always, every other
  test such as urea, SGPT or platelets once it has a result), Lab Reports (history),
  Upload, Confirm (the report beside editable values), and Lab Report Review for admins.
- **Code:** `backend/apps/lab_reports/services/` (ocr, extractor, verifier, validator, dashboard, upload).
  The views are thin. Frontend code is in `frontend/src/features/lab-reports/`.
- **API contract:** [docs/lab-reports-api.md](docs/lab-reports-api.md).

### Settings (`backend/.env`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `LAB_REPORT_ENCRYPTION_KEY` | derived from `SECRET_KEY` | Fernet key for stored report files. Set it in production. |
| `LAB_UPLOAD_THROTTLE_RATE` | `20/hour` | Upload rate limit per user |
| `LAB_USE_LIBMAGIC` | `False` | Detect file types with python-magic. Needs the libmagic system library (on in the Docker image). **On Windows without libmagic, importing python-magic hangs**, so leave it off; a built-in signature check is used. |
| `OCR_MAX_PDF_PAGES` | `5` | Pages read from a PDF |
| `OCR_PDF_DPI` | `200` | Resolution of PDF pages rendered for OCR and the AI fallback |
| `LAB_LLM_FALLBACK` | `False` | Send page images of reports that text and OCR could not read to Anthropic (Claude). **Patient data leaves the server** when used. |
| `ANTHROPIC_API_KEY` | empty | API key for the AI fallback (never put it in code) |
| `LAB_LLM_MODEL`, `LAB_LLM_TIMEOUT` | `claude-opus-5-5`, `45` | Model and timeout (seconds) for the AI fallback |
| `MEDIA_ROOT`, `EMAIL_BACKEND` | Django defaults | Overridable (used by the end-to-end test server) |

Digital PDFs need nothing extra. Scanned PDFs and photos need **Tesseract**, or the AI fallback. Poppler is
no longer needed: PDFs are opened and rendered with PyMuPDF.
Run `python manage.py purge_lab_uploads` daily to delete unconfirmed uploads older than 24 hours.

### Tests

```bash
# Backend (from backend/, venv active): 223 tests, including the lab report API suite
pytest
pytest apps/lab_reports/tests_api.py        # identity gate, conversion, update rules, security
pytest apps/patients/tests.py -k PatientId  # admin-typed patient IDs and QR links

# Frontend component tests (from frontend/): Vitest + Testing Library + MSW
npm test

# End-to-end (from frontend/): starts its own backend on :8001 with a separate
# SQLite database and the frontend on :5174, so your data is untouched.
npx playwright install chromium            # first run only
npm run test:e2e
```

Sample reports (all fake) are in `backend/samples/lab_reports/`; regenerate them with
`python samples/lab_reports/make_samples.py`. `python manage.py seed_e2e` creates their patient:
Asha Gurung, `PAT-0E2E0001`, login `e2e.patient` / `Kathmandu-Lab-2026` (development databases only).

### Assumptions

- A bare number on a report (without `PAT`) is matched only when it follows a label such as "Patient ID",
  "PID" or "UHID"; an unlabelled number elsewhere on the page is not used.
- External labs print their own IDs (UHID, Reg. No.), which can't be compared with Mero Care Card IDs. They
  are treated as "no ID", so such reports go to admin review until labs print the patient's card ID.
- Approving a report under review does not apply it; the values still need confirming.
- Extraction is regex-based. Report content is sent to another service only if `LAB_LLM_FALLBACK=True`, and
  then only for reports whose text gave no usable value. Its values still need the patient's confirmation.

### Known limitations

- OCR runs inside the upload request (a few seconds; capped pages). A background queue would scale better.
- Photographed reports often misread `0` as `O` in the card ID, which sends them to review by design.
- Reference ranges for the Low/Normal/High badges are general adult ranges, not lab-specific or for children.
- Bikram Sambat (Nepali calendar) dates on reports are not converted, so they count as "no report date".
