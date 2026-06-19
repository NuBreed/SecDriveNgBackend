import os
from datetime import timedelta
from pathlib import Path

# Load .env file if present
_env_path = Path(__file__).resolve().parent.parent / '.env'
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _v = _line.split('=', 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name, default=''):
    return [v.strip() for v in os.getenv(name, default).split(',') if v.strip()]


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv(
    'SECRET_KEY',
    'django-insecure-necu%*=0e!k@^--&k*k%^wgsh45x6&=8qg3(p6t+ngbq@=!#4+',
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool('DEBUG', True)

ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'localhost,127.0.0.1')


# Application definition

DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_filters',
    'drf_spectacular',
    'django_celery_beat',
    'channels',
]

LOCAL_APPS = [
    'accounts',
    'vehicles',
    'drivers',
    'journeys',
    'tracking',
    'incidents',
    'safety',
    'notifications',
    'operators',
    'analytics',
    'integrations',
    'common',
    'kyc',
    'qr_codes',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
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
ASGI_APPLICATION = 'config.asgi.application'


SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': True,
    "UPDATE_LAST_LOGIN": True,
}

REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379')

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [REDIS_URL],
        },
    },
}

# Django 6 ships a built-in Redis cache backend, so no third-party
# django-redis dependency is required.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": f"{REDIS_URL}/1",
    }
}

CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', f'{REDIS_URL}/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', f'{REDIS_URL}/0')
# Run tasks inline (synchronously) when no worker is available — keeps OTP
# delivery working in dev without a Celery worker running.
CELERY_TASK_ALWAYS_EAGER = env_bool('CELERY_TASK_ALWAYS_EAGER', not env_bool('CELERY_WORKER', False))
CELERY_TASK_EAGER_PROPAGATES = True

# Periodic tasks (django-celery-beat database scheduler).
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_BEAT_SCHEDULE = {
    'scan-expiring-documents': {
        'task': 'kyc.tasks.scan_expiring_documents',
        'schedule': 60 * 60 * 24,  # daily
    },
}

# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

# my server
DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': os.getenv('POSTGRES_DB', 'isafepass'),
        'USER': os.getenv('POSTGRES_USER', 'justwin'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD', ''),
        'HOST': os.getenv('POSTGRES_HOST', 'localhost'),
        'PORT': os.getenv('POSTGRES_PORT', '5432'),
    }
}


# DRF + JWT
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'PAGE_SIZE': 10,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'otp': os.getenv('THROTTLE_OTP', '10/hour'),
        'login': os.getenv('THROTTLE_LOGIN', '20/min'),
    },
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'SecDrive API',
    'DESCRIPTION': 'SecDrive transportation safety platform API.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    # Give distinct names to the two status choice sets so drf-spectacular
    # doesn't collide them into an auto-numbered enum like "Status4acEnum".
    'ENUM_NAME_OVERRIDES': {
        'VerificationStatusEnum': 'kyc.models.VerificationStatus',
        'EntityStatusEnum': 'drivers.models.DriverVerification.Status',
    },
}

# CORS
CORS_ALLOW_ALL_ORIGINS = env_bool('CORS_ALLOW_ALL_ORIGINS', DEBUG)
CORS_ALLOWED_ORIGINS = env_list('CORS_ALLOWED_ORIGINS')

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    'accounts.backends.EmailPhoneOrUsernameBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')  # Collect static files here

# Add this if you want to serve additional static files
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# Media Files
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')


EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'justwin.com.ng')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', 'info@justwin.com.ng')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', "JustWin <noreply@justwin.com.ng>")

GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')

GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', 'AIzaSyCSanpCDSN8k25LiVW57PnZyaOQSSL_XKE')

# OAuth client IDs allowed as the `aud` of Google ID tokens accepted by
# /api/auth/google/. With google_sign_in's serverClientId set, the token's
# `aud` is the Web client ID — so it must appear here. Comma-separated env var;
# defaults to the Web client from google-services.json (project 408333176328).
# Add the iOS client ID here too once created.
GOOGLE_OAUTH_CLIENT_IDS = [
    c.strip()
    for c in os.getenv(
        'GOOGLE_OAUTH_CLIENT_IDS',
        '408333176328-dg5776ui7jl7ko6slr2b1h0kot5pu290.apps.googleusercontent.com',
    ).split(',')
    if c.strip()
]

FIREBASE_CREDENTIALS_PATH = os.getenv(
    'FIREBASE_CREDENTIALS_PATH',
    os.path.join(BASE_DIR, 'isafepass-firebase-adminsdk-fbsvc-5d54d6615c.json'),
)

# ── Authentication & Identity Management ─────────────────────────────
# OTP (account verification + password reset)
OTP_LENGTH = int(os.getenv('OTP_LENGTH', '6'))
OTP_EXPIRY_MINUTES = int(os.getenv('OTP_EXPIRY_MINUTES', '10'))
OTP_MAX_ATTEMPTS = int(os.getenv('OTP_MAX_ATTEMPTS', '5'))
OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv('OTP_RESEND_COOLDOWN_SECONDS', '60'))

# Account lockout after repeated failed logins
LOGIN_MAX_FAILED_ATTEMPTS = int(os.getenv('LOGIN_MAX_FAILED_ATTEMPTS', '5'))
LOGIN_LOCKOUT_MINUTES = int(os.getenv('LOGIN_LOCKOUT_MINUTES', '15'))

# SMS delivery — swappable backend. Defaults to a console backend that logs the
# message and surfaces the code as `dev_otp` in API responses (dev only).
SMS_BACKEND = os.getenv('SMS_BACKEND', 'accounts.services.sms.ConsoleSMSBackend')
AFRICASTALKING_USERNAME = os.getenv('AFRICASTALKING_USERNAME', 'sandbox')
AFRICASTALKING_API_KEY = os.getenv('AFRICASTALKING_API_KEY', '')
AFRICASTALKING_SENDER_ID = os.getenv('AFRICASTALKING_SENDER_ID', '')

# iSafePass trusted backend bridge. When BASE_URL or the
# service secret are unset the bridge is disabled and the SSO endpoints return
# a clean 503 instead of attempting a live call.
ISAFEPASS_BASE_URL = os.getenv('ISAFEPASS_BASE_URL', '')
ISAFEPASS_SERVICE_SECRET = os.getenv('ISAFEPASS_SERVICE_SECRET', '')
ISAFEPASS_TIMEOUT_SECONDS = int(os.getenv('ISAFEPASS_TIMEOUT_SECONDS', '10'))

# ── KYC & Verification ───────────────────────────────────────────────
# Sensitive KYC documents are stored outside the public MEDIA_ROOT and served
# only through an authenticated download endpoint.
PRIVATE_MEDIA_ROOT = os.getenv('PRIVATE_MEDIA_ROOT', os.path.join(BASE_DIR, 'private_media'))

# Identity verification provider. Default is a no-op (manual admin review);
# swap in an external NIN / face-match provider later.
KYC_IDENTITY_PROVIDER = os.getenv('KYC_IDENTITY_PROVIDER', 'kyc.services.providers.NoOpProvider')

# Days before a document's expiry to start sending reverification reminders.
VERIFICATION_REMINDER_DAYS = int(os.getenv('VERIFICATION_REMINDER_DAYS', '30'))

# Public base URL embedded in verification QR codes.
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', 'http://localhost:8000')

# Trust score factor weights (sum need not be 100; score is clamped 0-100).
TRUST_WEIGHTS = {
    'identity_verified': 30,
    'driver_verified': 25,
    'vehicle_verified': 15,
    'documents_valid': 20,
    'incident_history': 10,   # 0 until the incidents epic lands
    'complaint_history': 10,  # 0 until the complaints feature lands
}

# ── Test overrides ───────────────────────────────────────────────────
# Disable throttling and use an in-memory cache when running `manage.py test`
# so Redis throttle counters from previous runs don't bleed into new test runs.
import sys as _sys
if 'test' in _sys.argv:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }
    REST_FRAMEWORK = {**REST_FRAMEWORK, 'DEFAULT_THROTTLE_CLASSES': []}
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }

if _sys.platform == 'win32':
    GDAL_LIBRARY_PATH = r"C:\OSGeo4W\bin\gdal313.dll"
    GEOS_LIBRARY_PATH = r"C:\OSGeo4W\bin\geos_c.dll"
else:
    import glob as _glob
    _gdal = _glob.glob('/usr/lib/x86_64-linux-gnu/libgdal.so*')
    _geos = _glob.glob('/usr/lib/x86_64-linux-gnu/libgeos_c.so*')
    if _gdal:
        GDAL_LIBRARY_PATH = sorted(_gdal)[-1]
    if _geos:
        GEOS_LIBRARY_PATH = sorted(_geos)[-1]