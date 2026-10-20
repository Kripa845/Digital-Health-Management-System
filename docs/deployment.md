# Deploying Mero Care Card

Three free services, plus Cloudinary for uploaded files:

```
Phone scans QR ─▶ Frontend (Vercel) ──API calls──▶ Backend (Hugging Face Space) ──▶ Database (Neon Postgres)
                                                         └──▶ Photos, documents, lab reports (Cloudinary)
```

| Part | Service | Why |
|---|---|---|
| Frontend (React) | **Vercel** | Free, HTTPS (the QR scanner camera needs it), deploys from GitHub. |
| Backend (Django) | **Hugging Face Spaces** (Docker) | Free with 16 GB RAM. The symptom model needs ~1 GB per worker, more than Render/Railway free tiers (512 MB). |
| Database | **Neon** (PostgreSQL) | Free and does not expire. The server's disk is wiped on restart, so SQLite cannot be used. |
| Uploaded files | **Cloudinary** | Same reason: files saved on the server's disk would disappear. |

Do the steps in order: later steps need addresses from earlier ones.

---

## 1. Database — Neon

1. Sign up at <https://neon.tech> and create a project (region: Singapore is closest to Nepal).
2. On the dashboard click **Connect** and copy the connection string. It looks like
   `postgresql://user:password@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`.
   This is your **`DATABASE_URL`**. Keep it secret.

The tables are created automatically when the backend starts (`migrate` runs on every start).

## 2. File storage — Cloudinary

1. Sign up at <https://cloudinary.com>.
2. From the dashboard copy **Cloud name**, **API Key** and **API Secret**.

## 3. Frontend — Vercel (first deploy)

1. Make sure the code is pushed to GitHub (`main` branch).
2. Sign in at <https://vercel.com> with GitHub → **Add New → Project** → import
   `Digital-Health-Management-System`.
3. Set **Root Directory** to `frontend`. The framework (Vite) is detected automatically.
4. Pick the project name carefully: it becomes your address, e.g. `merocarecard` →
   `https://merocarecard.vercel.app`. **This address is printed inside every QR code.**
5. Click **Deploy**. It will build, but cannot reach the backend yet; that is fixed in step 5.

`frontend/vercel.json` sends every path to `index.html`, so a scanned link such as
`/public-profile/<token>` opens the app instead of a 404 page.

## 4. Backend — Hugging Face Space

### 4a. Create the Space

1. Sign up at <https://huggingface.co> → **New → Space**.
2. Name it, e.g. `merocarecard-api`. **SDK: Docker** (blank template). Hardware: **CPU basic (free)**.
   Visibility: **Public** (a private Space cannot be called by the website).
   Public means the backend code is visible, like a public GitHub repo; the secrets below are not.
3. Your API address will be `https://<username>-merocarecard-api.hf.space`.

### 4b. Add the secrets

In the Space: **Settings → Variables and secrets → New secret** for each of these.

| Name | Value |
|---|---|
| `DEBUG` | `False` |
| `SECRET_KEY` | A long random string. Generate: `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `ALLOWED_HOSTS` | `<username>-merocarecard-api.hf.space` (no `https://`) |
| `DATABASE_URL` | Neon connection string from step 1 |
| `CORS_ALLOWED_ORIGINS` | `https://merocarecard.vercel.app` (your Vercel address, no trailing `/`) |
| `FRONTEND_URL` | Same Vercel address |
| `CLOUDINARY_CLOUD_NAME` / `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET` | From step 2 |
| `LAB_REPORT_ENCRYPTION_KEY` | Generate once: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. **Save it somewhere safe and never change it**, or uploaded lab reports become unreadable. |
| `DJANGO_ADMIN_USERNAME` / `DJANGO_ADMIN_EMAIL` / `DJANGO_ADMIN_PASSWORD` | Your first admin account; created automatically on start. |
| `EMAIL_HOST_PASSWORD` | Gmail app password, for welcome/reset emails (the other email settings default to the Gmail account). |
| `WEB_CONCURRENCY` | `2` (the free Space has 2 CPUs) |

### 4c. Upload the backend

The backend is uploaded from your computer (not GitHub), because the trained model
`backend/ml/symptom_model.joblib` (60 MB) is not in git. In PowerShell, from `backend/`:

```powershell
# one time
.\venv\Scripts\pip install huggingface_hub
.\venv\Scripts\hf auth login     # token from https://huggingface.co/settings/tokens with "Write" access

# each deploy
.\scripts\deploy_huggingface.ps1 -Space <username>/merocarecard-api
```

The script never uploads `.env`, databases, `venv`, `media` or training data. The Space then
builds (first time ~5–10 minutes; watch the **Logs** tab). When it says **Running**, open
`https://<username>-merocarecard-api.hf.space/admin/` — the Django admin login page should appear.

## 5. Connect the frontend to the backend

In Vercel: **Project → Settings → Environment Variables** (Production):

| Name | Value |
|---|---|
| `VITE_API_URL` | `https://<username>-merocarecard-api.hf.space` (no trailing `/`) |
| `VITE_FRONTEND_URL` | `https://merocarecard.vercel.app` |

Then **Deployments → ⋯ → Redeploy**. `VITE_*` values are built into the site, so they only take
effect after a rebuild.

## 6. Check the QR flow

1. Open the Vercel site and log in with the admin account from step 4b.
2. Create a patient. Its QR card opens; **View QR** shows the link — it must start with your
   Vercel address, not `localhost`.
3. Scan the QR with a phone camera → the public profile (name, photo, blood group, emergency
   contact) opens.
4. Log in as a doctor on a phone → **Scan** → allow the camera → scan the card.

Print cards only after this works: the address inside a printed QR cannot be changed.
If a card was printed with a wrong address, use **Patients → View QR → Card lost?** to issue a
new one.

---

## Updating later

- **Frontend:** push to `main`; Vercel rebuilds automatically.
- **Backend:** run `.\scripts\deploy_huggingface.ps1 -Space <username>/merocarecard-api` again.
  New migrations run automatically on start.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Space log: `SECRET_KEY` / `ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS ... is not set` | A secret from step 4b is missing or misspelt. |
| Backend pages redirect forever | Add secret `SECURE_SSL_REDIRECT` = `False` (the proxy already provides HTTPS). |
| Website shows network/CORS errors | `CORS_ALLOWED_ORIGINS` must match the Vercel address exactly (`https://`, no trailing `/`); `VITE_API_URL` must be set and the site redeployed. |
| QR opens `localhost` | `VITE_FRONTEND_URL` was not set when the site was built: set it, redeploy, and reissue printed cards. |
| QR link shows Vercel 404 | `frontend/vercel.json` missing, or Root Directory is not `frontend`. |
| Doctor camera does not start | Must be HTTPS and camera permission allowed; the card ID can be typed in manually instead. |
| First visit takes ~1 minute | Free Spaces sleep after ~48 h without visits and wake on the next request. |
| Emails not sent | Check `EMAIL_HOST_PASSWORD` is a Gmail *app password*. If the Space blocks outgoing SMTP, use an email API service instead. |
| Uploaded photos vanish after a restart | Cloudinary secrets missing — files were saved on the temporary disk. |
