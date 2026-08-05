# Demo credentials & run commands

## Run the backend
```
cd C:/Users/ASUS/OneDrive/Desktop/Updated_Project/backend
venv\Scripts\activate            # PowerShell/cmd  (Git Bash: source venv/Scripts/activate)
python manage.py runserver 127.0.0.1:8000
```
Seed/refresh demo data: `python manage.py seed_demo`

## Run the frontend
```
cd C:/Users/ASUS/OneDrive/Desktop/Updated_Project/frontend
npm run dev        # http://localhost:5173  (Vite proxies /api -> 127.0.0.1:8000)
```

## Accounts (all must_change_password=False → sign in with just username + password)
| Role | Username | Password |
|------|----------|----------|
| ADMIN | `admin` | `admin12345` |
| DOCTOR | `dr.sharma` | `doctor12345` (Cardiology) |
| DOCTOR | `dr.gurung` | `doctor12345` (Neurology) |
| DOCTOR | `dr.thapa` | `doctor12345` (Pediatrics) |
| DOCTOR | `dr.rai` | `doctor12345` (Dermatology) |
| DOCTOR | `dr.karki` | `doctor12345` (Orthopedics) |
| DOCTOR | `dr.shrestha` | `doctor12345` (General Medicine) |
| PATIENT | `hari.tamang` | `patient12345` |
| PATIENT | `laxmi.poudel` | `patient12345` |
| PATIENT | `krishna.adhikari` | `patient12345` |
| (+ more patients, all `patient12345`) | | |

## New-account credentials (no email)

This build has **no email**. When an admin registers a patient or doctor, the system generates a
name-based username (e.g. `hari.tamang`, `dr.sharma`) and a temporary password, and returns them in
the create response — the Admin portal shows them once in a credentials dialog to copy and hand over.
There is no credential email, no login OTP, and no forgot-password flow; sign-in is username + password.
