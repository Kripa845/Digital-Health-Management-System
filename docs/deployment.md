# Deploying Mero Care Card

Three free services, plus Cloudinary for uploaded files:

```
Phone scans QR ─▶ Frontend (Vercel) ──API calls──▶ Backend (Render) ──▶ Database (Neon Postgres)
                                                       └──▶ Photos, documents, lab reports (Cloudinary)
```

| Part | Service | Why |
|---|---|---|
| Frontend (React) | **Vercel** | Free, HTTPS (the QR scanner camera needs it), rebuilds on every push to GitHub. |
| Backend (Django) | **Render** free web service (Docker) | Free, builds from GitHub using `render.yaml`. 512 MB RAM: tested with 1 worker × 4 threads, peak ~370 MB during two parallel OCR uploads. |
| Database | **Neon** (PostgreSQL) | Free, does not expire. Render's disk is wiped on every restart, so SQLite cannot be used. |
| Uploaded files | **Cloudinary** | Same reason: files saved on the server's disk would disappear. |

The symptom model (`backend/ml/symptom_model.joblib`, 50 trees, 10 MB) is committed to git so
Render gets it. See `backend/ml/RESULTS.md` for its accuracy.

The app sends no email. Login is JWT (access token 60 min, rotating refresh token 7 days). When an
admin creates an account, the login details are shown once on screen to hand over to the user.

Do the steps in order: later steps need addresses from earlier ones.

---

## 1. Database — Neon

1. Sign up at <https://neon.tech> and create a project. Its region must match the backend's
   `region` in `render.yaml` (currently `virginia`, for Neon's **AWS US East 1 (N. Virginia)**);
   neither can be changed later.
2. Click **Connect**, turn **off** "Connection pooling" (the host must not contain `-pooler`), and copy the connection string, e.g.
   `postgresql://user:password@ep-xxxx.us-east-1.aws.neon.tech/neondb?sslmode=require`.
   This is your **`DATABASE_URL`**. Keep it secret.

Tables are created automatically: the backend runs `migrate` every time it starts.

## 2. File storage — Cloudinary

Sign up at <https://cloudinary.com>. From the dashboard copy **Cloud name**, **API Key** and
**API Secret**.

## 3. Frontend — Vercel

1. Sign in at <https://vercel.com> with GitHub → **Add New → Project** → import
   `Digital-Health-Management-System`.
2. **Root Directory**: click **Edit** → `frontend`. Framework **Vite** is detected; leave the
   build/output/install commands as they are.
3. **Project name** becomes your address, e.g. `merocarecard` → `https://merocarecard.vercel.app`.
   **This address is printed inside every QR code**, so choose it before printing cards.
4. **Environment Variables**:

   | Key | Value |
   |---|---|
   | `VITE_FRONTEND_URL` | `https://merocarecard.vercel.app` (your address, no trailing `/`) |
   | `VITE_API_URL` | `https://merocarecard-api.onrender.com` (the backend address from step 4; set it now if you know it, or add it after step 4 and redeploy) |

5. **Deploy**.

`frontend/vercel.json` sends every path to `index.html`, so a scanned link such as
`/public-profile/<token>` opens the app instead of a 404 page.

## 4. Backend — Render

1. Sign in at <https://render.com> with GitHub.
2. **New → Blueprint** → choose the `Digital-Health-Management-System` repo. Render reads
   `render.yaml` and shows one service, `merocarecard-api` (free, Virginia, Docker, `backend/`).
3. Fill in the values it asks for:

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | Neon connection string (step 1) |
   | `CORS_ALLOWED_ORIGINS` | `https://merocarecard.vercel.app` (exact, no trailing `/`) |
   | `CLOUDINARY_CLOUD_NAME` / `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET` | step 2 |
   | `LAB_REPORT_ENCRYPTION_KEY` | Generate once (below). **Keep a copy and never change it**, or uploaded lab reports become unreadable. |
   | `DJANGO_ADMIN_USERNAME` / `DJANGO_ADMIN_EMAIL` / `DJANGO_ADMIN_PASSWORD` | Your admin login for the live site; created automatically on start. |

   Generate the encryption key in PowerShell from `backend\`:
   ```powershell
   .\venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   Set by `render.yaml` automatically: `DEBUG=False`, a random `SECRET_KEY`, `WEB_CONCURRENCY=1`,
   `GUNICORN_THREADS=4`. `ALLOWED_HOSTS` is not needed: the app trusts
   Render's own address (`RENDER_EXTERNAL_HOSTNAME`).
4. **Apply**. The first build takes ~5–10 minutes (watch **Logs**). When it says **Live**, open
   `https://merocarecard-api.onrender.com/admin/` — the Django admin login page should appear.
   If the name was taken, Render picks a different address: use that one in `VITE_API_URL`.

## 5. Connect the two

If `VITE_API_URL` was not set yet, or the backend address differs: in Vercel, **Settings →
Environment Variables**, set it, then **Deployments → ⋯ → Redeploy**. `VITE_*` values are built
into the site, so they only change after a rebuild.

## 6. Check the QR flow

1. Open the Vercel site and log in with the admin account from step 4.
2. Create a patient. Its QR card opens; **View QR** shows the link — it must start with your
   Vercel address, not `localhost`.
3. Scan the QR with a phone camera → the public profile (name, photo, blood group, emergency
   contact) opens.
4. Log in as a doctor on a phone → **Scan** → allow the camera → scan the card.

Print cards only after this works: the address inside a printed QR cannot be changed.
If a card was printed with a wrong address, use **Patients → View QR → Card lost?** to issue a
new one.

## 7. Data on the live site

The live database (Neon) starts empty apart from the admin from step 4. Your local database is
not copied: its files and encrypted lab reports would not work online, and its demo accounts
use the public passwords from the repository.

- **Real use:** add doctors and patients from the admin pages of the live site.
- **Demo data (optional):** run `seed_demo` from your computer against Neon. Use a **new**
  PowerShell window, because these settings last only until it is closed:

  ```powershell
  cd C:\Users\kripa\Desktop\MeroCareCard\backend
  $env:DATABASE_URL = "postgresql://...neon.tech/neondb?sslmode=require"   # from step 1
  $env:CLOUDINARY_CLOUD_NAME = "..."; $env:CLOUDINARY_API_KEY = "..."; $env:CLOUDINARY_API_SECRET = "..."
  # Your own passwords: on Neon the public demo ones are refused.
  $env:SEED_DOCTOR_PASSWORD = "choose-one"; $env:SEED_PATIENT_PASSWORD = "choose-another"
  $env:SEED_ADMIN_PASSWORD = "choose-a-third"   # only used if no "admin" account exists yet

  .\venv\Scripts\python manage.py migrate
  .\venv\Scripts\python manage.py seed_demo      # prints every username and password
  ```

  Then **close the window**, so later commands use your local database again. `seed_demo` keeps
  an existing `admin` account and its password; rerunning it replaces only the demo doctors and
  patients. The same window can run `register_doctors`, `seed_activity` or `seed_demo_audit`
  (each has a `--remove`/`--reset` option to delete what it created).

---

## Updating later

Push to `main`: Vercel and Render both rebuild automatically. New migrations run on start.

## Free-plan limits

- The backend **sleeps after 15 minutes without visits**; the next visit takes about a minute to
  wake it. Open the site a minute before a demo.
- Render gives 750 free hours a month (enough for one service running all month).
- Neon free: 0.5 GB of data. Cloudinary free: ~25 GB of storage/bandwidth credits.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Render log: `SECRET_KEY` / `ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS ... is not set` | A value from step 4 is missing or misspelt. |
| Render log: `Worker ... was sent SIGKILL! Perhaps out of memory?` | Too many workers: keep `WEB_CONCURRENCY=1` on the free plan. |
| Website shows network/CORS errors | `CORS_ALLOWED_ORIGINS` must match the Vercel address exactly (`https://`, no trailing `/`); `VITE_API_URL` must be set and the site redeployed. |
| QR opens `localhost` | `VITE_FRONTEND_URL` was not set when the site was built: set it, redeploy, and reissue printed cards. |
| QR link shows Vercel 404 | `frontend/vercel.json` missing on GitHub, or Root Directory is not `frontend`. |
| Doctor camera does not start | Must be HTTPS and camera permission allowed; the card ID can be typed in manually instead. |
| Uploaded photos vanish after a restart | Cloudinary values missing — files were saved on the temporary disk. |
| Backend pages redirect forever | Set `SECURE_SSL_REDIRECT=False` in Render's Environment tab. |
