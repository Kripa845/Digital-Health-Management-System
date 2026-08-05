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
venv\Scripts\activate            # Windows PowerShell/cmd  ·  Git Bash: source venv/Scripts/activate
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
Vite proxies `/api` and `/media` to the backend, so no CORS setup is needed in dev.

### Demo accounts
| Role | Username | Password |
| --- | --- | --- |
| Admin | `admin` | `admin12345` |
| Doctor | `dr.sharma` | `doctor12345` |
| Patient | `hari.tamang` | `patient12345` |

(Full list printed by `seed_demo`, and in [`docs/DEMO_CREDENTIALS.md`](docs/DEMO_CREDENTIALS.md).
Sign-in is a simple username + password — no email step.)

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

## Documentation
- [`docs/BACKEND_SPEC.md`](docs/BACKEND_SPEC.md) — models, endpoints, the recommendation formula.
- [`docs/FRONTEND_GUIDE.md`](docs/FRONTEND_GUIDE.md) — component inventory & conventions.
- [`docs/DEMO_CREDENTIALS.md`](docs/DEMO_CREDENTIALS.md) — accounts & run commands.

## Security notes
JWT sessions with rotating refresh tokens, a first-login forced password change, role-based access
enforced on every endpoint, and append-only audit logging. The public QR profile never exposes
medical data. (This build has no email dependency — sign-in is username + password, and admins read
new-account credentials directly from the UI after creating an account.)
