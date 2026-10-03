"""Jawny profil jednej instalacji urzędowej; walidacja bez połączeń z operatorem."""

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email


def build_settings(environment, current):
    def fail(message):
        raise ImproperlyConfigured(message)

    if environment.get("DYNA_ENV") != "onprem" or current["LOCAL"]:
        fail("Profil urzędowy wymaga DYNA_ENV=onprem.")
    if current["DEBUG"]:
        fail("Profil urzędowy nie dopuszcza DEBUG.")
    secret = current["SECRET_KEY"]
    if len(secret) < 50 or len(set(secret)) < 5 or secret.startswith("django-insecure-"):
        fail("Ustaw niezależny, losowy DJANGO_SECRET_KEY o długości co najmniej 50 znaków.")
    url = urlsplit(environment.get("APP_URL", ""))
    try:
        port = url.port
    except ValueError:
        fail("Niepoprawny port APP_URL.")
    if (
        url.scheme != "https"
        or not url.hostname
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", url.hostname)
        or any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
            for label in url.hostname.split(".")
        )
        or len(url.hostname) > 253
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in ("", "/")
        or port not in (None, 443)
    ):
        fail("APP_URL musi wskazywać pojedynczą domenę HTTPS bez ścieżki i danych logowania.")
    hosts = [part.strip() for part in environment.get("DJANGO_ALLOWED_HOSTS", "").split(",")]
    if hosts != [url.hostname] or url.hostname in {"localhost", "127.0.0.1", "::1", "testserver"}:
        fail("DJANGO_ALLOWED_HOSTS musi zawierać dokładnie domenę z APP_URL, bez wildcardów.")
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", environment.get("APP_REVISION", "")):
        fail("APP_REVISION musi wskazywać pełny SHA wdrażanego wydania.")
    data_dir = Path(environment.get("DYNA_DATA_DIR", ""))
    if not environment.get("DYNA_DATA_DIR") or not data_dir.is_absolute():
        fail("Ustaw bezwzględny DYNA_DATA_DIR poza katalogiem wydania.")
    if data_dir.resolve().is_relative_to(current["BASE_DIR"].resolve()):
        fail("Dane trwałe muszą znajdować się poza katalogiem wydania.")
    database = current["DATABASES"]["default"]
    if database["ENGINE"] != "django.db.backends.postgresql" or not all(
        database.get(key) for key in ("NAME", "USER", "HOST")
    ):
        fail("Profil urzędowy wymaga PostgreSQL: PGHOST, PGDATABASE i PGUSER.")
    host = database["HOST"]
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    options = dict(database.get("OPTIONS", {}))
    options["connect_timeout"] = 5
    if not host.startswith("/") and not loopback:
        if environment.get("PGSSLMODE") != "verify-full" or not environment.get("PGSSLROOTCERT"):
            fail("Zdalny PostgreSQL wymaga PGSSLMODE=verify-full i PGSSLROOTCERT.")
        options.update(sslmode="verify-full", sslrootcert=environment["PGSSLROOTCERT"])
    elif environment.get("PGSSLMODE"):
        options["sslmode"] = environment["PGSSLMODE"]
        if environment.get("PGSSLROOTCERT"):
            options["sslrootcert"] = environment["PGSSLROOTCERT"]
    if (
        current["EMAIL_BACKEND"] != "django.core.mail.backends.smtp.EmailBackend"
        or not current["EMAIL_HOST"]
        or current["EMAIL_USE_TLS"] == current["EMAIL_USE_SSL"]
    ):
        fail("Ustaw SMTP oraz dokładnie jeden transport: STARTTLS lub TLS (EMAIL_USE_SSL).")
    try:
        validate_email(current["DEFAULT_FROM_EMAIL"])
        if current["DEFAULT_FROM_EMAIL"].rsplit("@", 1)[-1].lower() == "localhost":
            raise ValidationError("Lokalny nadawca nie jest adresem urzędu.")
    except ValidationError:
        fail("Ustaw poprawny DEFAULT_FROM_EMAIL dla urzędu.")
    return {
        "ALLOWED_HOSTS": hosts,
        "APP_URL": environment["APP_URL"].rstrip("/"),
        "APP_REVISION": environment["APP_REVISION"],
        "DATABASES": {"default": {**database, "OPTIONS": options}},
        "CSRF_TRUSTED_ORIGINS": [environment["APP_URL"].rstrip("/")],
        "TRUSTED_PROXY_ADDRESSES": ("127.0.0.1",),
        "SECURE_PROXY_SSL_HEADER": ("HTTP_X_FORWARDED_PROTO", "https"),
        "MIDDLEWARE": ["registry.middleware.OnPremProxyMiddleware", *current["MIDDLEWARE"]],
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": False,
        "SECURE_HSTS_PRELOAD": False,
        "LOGGING": {
            "version": 1,
            "disable_existing_loggers": False,
            "handlers": {"console": {"class": "logging.StreamHandler"}},
            "root": {"handlers": ["console"], "level": "WARNING"},
            "loggers": {"django": {"handlers": ["console"], "level": "WARNING", "propagate": False}},
        },
    }
