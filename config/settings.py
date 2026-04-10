import logging
import sys
from importlib.util import find_spec
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent
HAS_WHITENOISE = find_spec("whitenoise") is not None
IS_TESTING = "test" in sys.argv


def env_bool(name: str, default: bool) -> bool:
    raw_value = config(name, default=None)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}

SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-dev-secret-key-change-me",
)
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost", cast=Csv())

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'emails',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

if HAS_WHITENOISE:
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
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

DB_ENGINE = config("DB_ENGINE", default="sqlite")

if DB_ENGINE == "mysql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": config("DB_NAME"),
            "USER": config("DB_USER"),
            "PASSWORD": config("DB_PASSWORD"),
            "HOST": config("DB_HOST", default="127.0.0.1"),
            "PORT": config("DB_PORT", default=3306, cast=int),
            "OPTIONS": {
                "charset": "utf8mb4",
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": config("SQLITE_PATH", default=str(BASE_DIR / "db.sqlite3")),
        }
    }

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

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'

USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
if HAS_WHITENOISE:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG and not IS_TESTING)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG)
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=0 if DEBUG else 3600, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
USE_PROXY_SSL_HEADER = env_bool("USE_PROXY_SSL_HEADER", False)
if USE_PROXY_SSL_HEADER:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "account-list"
LOGOUT_REDIRECT_URL = "login"

WHM_HOST = config("WHM_HOST", default="")
WHM_USER = config("WHM_USER", default="")
WHM_TOKEN = config("WHM_TOKEN", default="")
WHM_VERIFY_SSL = env_bool("WHM_VERIFY_SSL", True)
HIDDEN_CPANEL_DOMAINS = {
    value.strip().lower()
    for value in config("HIDDEN_CPANEL_DOMAINS", default="", cast=Csv())
    if value.strip()
}

CPANEL_HOST = config("CPANEL_HOST", default="")
CPANEL_USER = config("CPANEL_USER", default="")
CPANEL_TOKEN = config("CPANEL_TOKEN", default="")
CPANEL_DOMAIN = config("CPANEL_DOMAIN", default="")
CPANEL_VERIFY_SSL = env_bool("CPANEL_VERIFY_SSL", True)
REQUEST_TIMEOUT = config("REQUEST_TIMEOUT", default=30, cast=int)
CAPITAL_MOBILE_SMS_ENDPOINT = config(
    "CAPITAL_MOBILE_SMS_ENDPOINT",
    default="https://portal.capitalmobile.com.br/post/index.php",
)
CAPITAL_MOBILE_SMS_USER = config("CAPITAL_MOBILE_SMS_USER", default="")
CAPITAL_MOBILE_SMS_PASSWORD = config("CAPITAL_MOBILE_SMS_PASSWORD", default="")
CAPITAL_MOBILE_SMS_COOKIE = config("CAPITAL_MOBILE_SMS_COOKIE", default="")
CAPITAL_MOBILE_SMS_MAX_LENGTH = config("CAPITAL_MOBILE_SMS_MAX_LENGTH", default=160, cast=int)

EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=25, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
_from_email_addr = config("DEFAULT_FROM_EMAIL", default=EMAIL_HOST_USER or "webmaster@localhost")
DEFAULT_FROM_EMAIL = f"Gestão de E-mails <{_from_email_addr}>"
GOOGLE_WORKSPACE_DOMAIN = config("GOOGLE_WORKSPACE_DOMAIN", default="")
GOOGLE_WORKSPACE_ADMIN_EMAIL = config("GOOGLE_WORKSPACE_ADMIN_EMAIL", default="")
GOOGLE_SERVICE_ACCOUNT_FILE = config("GOOGLE_SERVICE_ACCOUNT_FILE", default="")
GOOGLE_SERVICE_ACCOUNT_JSON = config("GOOGLE_SERVICE_ACCOUNT_JSON", default="")
GOOGLE_SERVICE_ACCOUNT_PROJECT_ID = config("GOOGLE_SERVICE_ACCOUNT_PROJECT_ID", default="")
GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID = config("GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID", default="")
GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY = config("GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY", default="")
GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL = config("GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL", default="")
GOOGLE_SERVICE_ACCOUNT_CLIENT_ID = config("GOOGLE_SERVICE_ACCOUNT_CLIENT_ID", default="")
GOOGLE_SERVICE_ACCOUNT_TOKEN_URI = config("GOOGLE_SERVICE_ACCOUNT_TOKEN_URI", default="https://oauth2.googleapis.com/token")
GOOGLE_WORKSPACE_DEFAULT_ORG_UNIT = config("GOOGLE_WORKSPACE_DEFAULT_ORG_UNIT", default="")
GOOGLE_WORKSPACE_LICENSING_ENABLED = env_bool("GOOGLE_WORKSPACE_LICENSING_ENABLED", False)
GOOGLE_WORKSPACE_PRODUCT_ID = config("GOOGLE_WORKSPACE_PRODUCT_ID", default="")
GOOGLE_WORKSPACE_SKU_ID = config("GOOGLE_WORKSPACE_SKU_ID", default="")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "emails": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

if not WHM_VERIFY_SSL:
    logging.getLogger("urllib3").warning(
        "WHM_VERIFY_SSL desativado. As chamadas HTTPS ao WHM nao validarao o certificado."
    )

if not CPANEL_VERIFY_SSL:
    logging.getLogger("urllib3").warning(
        "CPANEL_VERIFY_SSL desativado. As chamadas HTTPS ao cPanel nao validarao o certificado."
    )
