"""Local development overrides — uses plain PostgreSQL (no PostGIS) so you
don't need PostGIS installed locally. GIS spatial queries won't work, but
all other API features (auth, drivers, journeys, tracking, etc.) work fine."""
from config.settings import *  # noqa: F401, F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'secdriveng',
        'USER': 'secdrive',
        'PASSWORD': 'secdrive123',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}

# Swap out the GIS app for the standard contrib
INSTALLED_APPS = [
    app if app != 'django.contrib.gis' else 'django.contrib.postgres'
    for app in INSTALLED_APPS
]
