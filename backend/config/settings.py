
from pathlib import Path
from datetime import timedelta
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

# Security
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if os.environ.get('DEBUG', 'True') == 'True':
        SECRET_KEY = 'django-insecure-local-dev-only-do-not-use-in-production'
    else:
        raise RuntimeError(
            "SECRET_KEY environment variable is not set. "
            "Set it before starting the server in production."
        )

DEBUG = os.environ.get('DEBUG', 'True') == 'True'

_allowed_hosts = os.environ.get('ALLOWED_HOSTS', '')
if _allowed_hosts:
    ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts.split(',') if h.strip()]
elif DEBUG:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]', 'testserver']
else:
    raise RuntimeError(
        "ALLOWED_HOSTS environment variable is not set. "
        "Set it to your API host name(s) before starting the server in production."
    )

# Production security hardening
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    # The host's proxy already serves HTTPS; set False if it does not send X-Forwarded-Proto (redirect loop).
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True') == 'True'
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_filters',
    'cloudinary_storage',
    'cloudinary',

    # Project apps
    'apps.users',
    'apps.patients',
    'apps.doctors',
    'apps.recommendations',
    'apps.documents',
    'apps.audit',
    'apps.appointments',
    'apps.notifications',
    'apps.lab_reports',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
DATABASES = {
    'default': dj_database_url.config(
        default=f'sqlite:///{BASE_DIR / "db.sqlite3"}',
        conn_max_age=600,
    )
}

# Custom User Model
AUTH_USER_MODEL = 'users.User'

# Authentication backends
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_PAGINATION_CLASS': 'config.pagination.StandardPagination',
    'PAGE_SIZE': 10,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/day',
        'user': '1000/day',
        'login': os.environ.get('LOGIN_THROTTLE_RATE', '10/min'),
        'lab_upload': os.environ.get('LAB_UPLOAD_THROTTLE_RATE', '20/hour'),
    },
}

# Brute-force rule (apps/audit/brute_force.py): this many failed logins for one
# account within this many minutes raises a suspicious-activity alert at once.
BRUTE_FORCE_MAX_FAILED_LOGINS = int(os.environ.get('BRUTE_FORCE_MAX_FAILED_LOGINS', '5'))
BRUTE_FORCE_WINDOW_MINUTES = int(os.environ.get('BRUTE_FORCE_WINDOW_MINUTES', '10'))

# Simple JWT
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# Frontend URL
FRONTEND_URL = os.environ.get('FRONTEND_URL', '').rstrip('/')

# CORS
_cors_origins = os.environ.get('CORS_ALLOWED_ORIGINS', '')
if _cors_origins:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_origins.split(',') if o.strip()]
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOW_CREDENTIALS = True
elif DEBUG:
    # Local development only (Vite also proxies /api, so this is rarely needed).
    CORS_ALLOW_ALL_ORIGINS = True
    CORS_ALLOW_CREDENTIALS = False
else:
    raise RuntimeError(
        "CORS_ALLOWED_ORIGINS environment variable is not set. "
        "Set it to your frontend origin(s) before starting the server in production."
    )

# Internationalisation
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kathmandu'
USE_I18N = True
USE_TZ = True

# Static & Media files
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = Path(os.environ.get('MEDIA_ROOT', BASE_DIR / 'media'))

# Cloudinary
CLOUDINARY_STORAGE = {
    'CLOUD_NAME': os.environ.get('CLOUDINARY_CLOUD_NAME', ''),
    'API_KEY': os.environ.get('CLOUDINARY_API_KEY', ''),
    'API_SECRET': os.environ.get('CLOUDINARY_API_SECRET', ''),
}

_cloudinary_configured = all([
    CLOUDINARY_STORAGE['CLOUD_NAME'],
    CLOUDINARY_STORAGE['API_KEY'],
    CLOUDINARY_STORAGE['API_SECRET'],
])

if _cloudinary_configured:
    STORAGES['default']['BACKEND'] = 'cloudinary_storage.storage.MediaCloudinaryStorage'
elif not DEBUG:
    import warnings
    warnings.warn(
        'Media storage is using the local disk in production. Uploaded files '
        'will be lost on redeploy and may not be served. Configure CLOUDINARY_* '
        'environment variables for persistent media.',
        RuntimeWarning,
    )

# Lab report files are encrypted at rest (apps/lab_reports/crypto.py). Set a
# Fernet key in production; generate one with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Without it a key is derived from SECRET_KEY.
LAB_REPORT_ENCRYPTION_KEY = os.environ.get('LAB_REPORT_ENCRYPTION_KEY', '')
# Detect uploaded file types with python-magic (needs the libmagic system library;
# leave off on Windows, where importing python-magic without it hangs).
LAB_USE_LIBMAGIC = os.environ.get('LAB_USE_LIBMAGIC', 'False') == 'True'
# A lab report dated before the patient's latest confirmed report:
# "warn" (shown with a warning; confirming needs an explicit acknowledgement),
# "block" (refused, nothing stored) or "allow" (no warning).
LAB_REPORT_OLDER_DATE_POLICY = os.environ.get('LAB_REPORT_OLDER_DATE_POLICY', 'warn')
# Smart symptom check: symptom synonyms (JSON) and the rapidfuzz similarity (0–100)
# a misspelt word needs to be matched to a known symptom without asking. Words from
# SMART_CHECK_SUGGEST_THRESHOLD up to it are shown as "Did you mean ...?" and only used once
# confirmed. 85 was too low: "redness" matched "tiredness" (87.5) and became fatigue.
SMART_CHECK_SYNONYMS_PATH = os.environ.get('SMART_CHECK_SYNONYMS_PATH', str(BASE_DIR / 'ml' / 'data' / 'symptom_synonyms.json'))
SMART_CHECK_FUZZY_THRESHOLD = float(os.environ.get('SMART_CHECK_FUZZY_THRESHOLD', '93'))
SMART_CHECK_SUGGEST_THRESHOLD = float(os.environ.get('SMART_CHECK_SUGGEST_THRESHOLD', '80'))
# When ml/symptom_model.joblib cannot be loaded, wait this long before trying again,
# doubling after each failure up to the maximum (seconds).
SMART_CHECK_MODEL_RETRY_SECONDS = float(os.environ.get('SMART_CHECK_MODEL_RETRY_SECONDS', '30'))
SMART_CHECK_MODEL_RETRY_MAX_SECONDS = float(os.environ.get('SMART_CHECK_MODEL_RETRY_MAX_SECONDS', '600'))
# Numeric report dates such as 04/05/2026: "DMY" (day first, the default) or "MDY".
LAB_REPORT_DATE_ORDER = os.environ.get('LAB_REPORT_DATE_ORDER', 'DMY')
# Optional AI fallback: when neither the PDF text nor OCR yields a dashboard
# value, the page images are sent to Anthropic's API to read them. Off by
# default because patient data then leaves this server.
# Lab report OCR preprocessing (OpenCV; see apps/lab_reports/ocr_service.preprocess_image).
LAB_OCR_TARGET_WIDTH = int(os.environ.get('LAB_OCR_TARGET_WIDTH', '2000'))          # px
LAB_OCR_MAX_UPSCALE = float(os.environ.get('LAB_OCR_MAX_UPSCALE', '3.0'))
LAB_OCR_MAX_DESKEW_ANGLE = float(os.environ.get('LAB_OCR_MAX_DESKEW_ANGLE', '10'))  # degrees
LAB_OCR_DESKEW_STEP = float(os.environ.get('LAB_OCR_DESKEW_STEP', '0.5'))           # degrees
LAB_OCR_DENOISE_STRENGTH = int(os.environ.get('LAB_OCR_DENOISE_STRENGTH', '7'))
LAB_OCR_ADAPTIVE_BLOCK_SIZE = int(os.environ.get('LAB_OCR_ADAPTIVE_BLOCK_SIZE', '71'))  # px, odd
LAB_OCR_ADAPTIVE_C = int(os.environ.get('LAB_OCR_ADAPTIVE_C', '20'))
# A value needs the user's confirmation when its OCR word confidence is below this (0–100),
# or it is more than LAB_FAR_OUTSIDE_FACTOR times outside the range printed on the report.
# NEEDS REVIEW: starting points to tune on real reports, not validated figures.
LAB_VALUE_MIN_CONFIDENCE = float(os.environ.get('LAB_VALUE_MIN_CONFIDENCE', '80'))
LAB_FAR_OUTSIDE_FACTOR = float(os.environ.get('LAB_FAR_OUTSIDE_FACTOR', '3'))
LAB_LLM_FALLBACK = os.environ.get('LAB_LLM_FALLBACK', 'False') == 'True'
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
LAB_LLM_MODEL = os.environ.get('LAB_LLM_MODEL', 'claude-opus-5-5')
LAB_LLM_TIMEOUT = float(os.environ.get('LAB_LLM_TIMEOUT', '45'))

# Misc
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Email Settings
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', 'merocarecard@gmail.com')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'
# Without a timeout an unreachable SMTP server blocks account creation forever;
# after it, the admin is shown the new login details instead.
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', 15))
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'Mero Care Card <merocarecard@gmail.com>')

