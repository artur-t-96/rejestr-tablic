import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DYNA_DATA_DIR", BASE_DIR / "var"))
DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
LOCAL = os.environ.get("DYNA_ENV", "local") == "local"
secret_file = DATA_DIR / "secret-key"
if LOCAL and not secret_file.exists():
    fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(secrets.token_urlsafe(64))
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (secret_file.read_text() if LOCAL else "")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY jest wymagany poza środowiskiem lokalnym.")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "registry",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "registry.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "registry.context.app_context",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
if os.environ.get("PGHOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["PGDATABASE"],
            "USER": os.environ["PGUSER"],
            "PASSWORD": os.environ.get("PGPASSWORD", ""),
            "HOST": os.environ["PGHOST"],
            "PORT": os.environ.get("PGPORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATA_DIR / "registry.sqlite3",
            "TEST": {"NAME": DATA_DIR / "test_registry.sqlite3"},
            "OPTIONS": {"timeout": 30, "transaction_mode": "IMMEDIATE"},
        }
    }
AUTH_USER_MODEL = "registry.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "pl"
TIME_ZONE = "Europe/Warsaw"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
LOGIN_URL = "/logowanie/"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 3600
SESSION_WARNING_SECONDS = 120
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_SECURE = not LOCAL
CSRF_COOKIE_SECURE = not LOCAL
CSRF_FAILURE_VIEW = "registry.views.csrf_failure"
SECURE_SSL_REDIRECT = not LOCAL
SECURE_HSTS_SECONDS = 31536000 if not LOCAL else 0
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.filebased.EmailBackend"
    if LOCAL
    else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_FILE_PATH = DATA_DIR / "mail"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "0") == "1"
EMAIL_TIMEOUT = 15
MS_MAIL_TENANT_ID = os.environ.get("MS_MAIL_TENANT_ID", "")
MS_MAIL_CLIENT_ID = os.environ.get("MS_MAIL_CLIENT_ID", "")
MS_MAIL_MAILBOX_ID = os.environ.get("MS_MAIL_MAILBOX_ID", "")
MS_MAIL_CERTIFICATE = os.environ.get("MS_MAIL_CERTIFICATE", "")
MS_MAIL_PRIVATE_KEY = os.environ.get("MS_MAIL_PRIVATE_KEY", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "rejestr@localhost")
APP_URL = os.environ.get("APP_URL", "http://127.0.0.1:8765")
APP_REVISION = os.environ.get("APP_REVISION", "local")
RESERVATION_DAYS = 14
RESERVATION_REMINDER_DAYS = int(os.environ.get("RESERVATION_REMINDER_DAYS", "3"))
POOL_ALERT_PERCENT = int(os.environ.get("POOL_ALERT_PERCENT", "80"))
if not (0 < RESERVATION_REMINDER_DAYS < RESERVATION_DAYS and 1 <= POOL_ALERT_PERCENT <= 100):
    raise RuntimeError("Niepoprawny próg przypomnienia o rezerwacji lub alertu puli.")
PDF_FONT = os.environ.get("PDF_FONT", str(BASE_DIR / "registry" / "fonts" / "DejaVuSans.ttf"))
EZDRP_CONFIG_FILE = os.environ.get("EZDRP_CONFIG_FILE", "")
EDOR_CONFIG_FILE = os.environ.get("EDOR_CONFIG_FILE", "")
SIGNING_CONFIG_FILE = os.environ.get("SIGNING_CONFIG_FILE", "")

# CAPTCHA nie usuwa niezależnego limitu HTML/API; oba liczone na REMOTE_ADDR.
PUBLIC_QUERY_LIMIT = int(os.environ.get("PUBLIC_QUERY_LIMIT", "30"))
PUBLIC_CAPTCHA_THRESHOLD = int(os.environ.get("PUBLIC_CAPTCHA_THRESHOLD", "10"))
PUBLIC_CAPTCHA_COST = int(os.environ.get("PUBLIC_CAPTCHA_COST", "5000"))
if not (0 < PUBLIC_CAPTCHA_THRESHOLD < PUBLIC_QUERY_LIMIT <= 1000 and 100 <= PUBLIC_CAPTCHA_COST <= 20000):
    raise RuntimeError("Niepoprawne progi publicznego wyszukiwania lub koszt ALTCHA.")
