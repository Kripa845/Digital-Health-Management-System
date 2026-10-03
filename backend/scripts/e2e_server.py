"""Start an isolated backend for the end-to-end tests (used by frontend/playwright.config.ts).

Uses its own SQLite database (backend/e2e.sqlite3) and media folder, so your
development data is never touched. Each start recreates the database, applies
migrations, creates the e2e patient (seed_e2e) and serves on 127.0.0.1:8001.
"""
import os
import pathlib
import shutil
import subprocess
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
DB = BACKEND / 'e2e.sqlite3'
MEDIA = BACKEND / 'e2e-media'

env = dict(os.environ)
env.update({
    'DATABASE_URL': f'sqlite:///{DB.as_posix()}',
    'MEDIA_ROOT': str(MEDIA),
    'DEBUG': 'True',
    'ALLOWED_HOSTS': '127.0.0.1,localhost',
    'CORS_ALLOWED_ORIGINS': '',
    'DJANGO_ADMIN_PASSWORD': '',          # don't create the .env admin in the test database
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'LAB_UPLOAD_THROTTLE_RATE': '1000/hour',
})

DB.unlink(missing_ok=True)
shutil.rmtree(MEDIA, ignore_errors=True)


def manage(*args):
    subprocess.run([sys.executable, 'manage.py', *args], cwd=BACKEND, env=env, check=True)


manage('migrate', '--noinput', '-v', '0')
manage('seed_e2e')
sys.exit(subprocess.call([sys.executable, 'manage.py', 'runserver', '127.0.0.1:8001', '--noreload'],
                         cwd=BACKEND, env=env))
