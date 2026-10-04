"""Oddzielny profil Render; nie zmienia konfiguracji lokalnej ani urzędowej."""

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email
from psycopg.conninfo import conninfo_to_dict


def build_settings(environment, current):
    def fail(message):
        raise ImproperlyConfigured(message) from None

    if environment.get("DYNA_ENV") != "render" or current["LOCAL"] or current["DEBUG"]:
        fail("Profil Render wymaga DYNA_ENV=render oraz wyłączonego DEBUG.")
    secret = current["SECRET_KEY"]
    if len(secret) < 50 or len(set(secret)) < 5 or secret.startswith("django-insecure-"):
        fail("Ustaw niezależny losowy DJANGO_SECRET_KEY, co najmniej 50 znaków.")
    url = urlsplit(environment.get("APP_URL", ""))
    try:
        valid_port = url.port in (None, 443)
    except ValueError:
        valid_port = False
    if (
        url.scheme != "https" or not url.hostname or not valid_port
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", url.hostname)
        or any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
               for label in url.hostname.split("."))
        or len(url.hostname) > 253 or url.username or url.password
        or url.query or url.fragment or url.path not in ("", "/")
        or url.hostname in {"localhost", "127.0.0.1", "testserver"}
    ):
        fail("APP_URL musi wskazywać jedną publiczną domenę HTTPS.")
    hosts = environment.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if hosts != [url.hostname]:
        fail("DJANGO_ALLOWED_HOSTS musi wskazywać dokładnie domenę APP_URL.")
    if environment.get("DYNA_DEMO") and environment["DYNA_DEMO"] != url.hostname:
        # Flaga skopiowana na inną usługę nie włączy wejścia bez kodu e-mail.
        fail("DYNA_DEMO musi być równe domenie APP_URL tej instancji demonstracyjnej.")
    revision = environment.get("RENDER_GIT_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
        fail("Brak pełnego RENDER_GIT_COMMIT.")
    data_dir = Path(environment.get("DYNA_DATA_DIR", ""))
    if not data_dir.is_absolute() or data_dir.resolve().is_relative_to(current["BASE_DIR"].resolve()):
        fail("DYNA_DATA_DIR musi wskazywać trwały dysk poza katalogiem kodu.")
    try:
        database = conninfo_to_dict(environment.get("DATABASE_URL", ""))
    except Exception:
        # Nie ujawniamy connection string ani hasła w wyjątku.
        fail("Niepoprawny DATABASE_URL.")
    if not all(database.get(key) for key in ("host", "dbname", "user", "password")):
        fail("DATABASE_URL musi zawierać pełne dane PostgreSQL.")
    host = database["host"]
    if not re.fullmatch(r"dpg-[a-z0-9-]+", host):
        fail("Profil wymaga wewnętrznego hosta Render Postgres w tym samym regionie.")
    try:
        proxy_networks = tuple(ipaddress.ip_network(value.strip()) for value in
                               environment.get("RENDER_PROXY_CIDRS", "").split(","))
    except ValueError:
        fail("Ustaw potwierdzone RENDER_PROXY_CIDRS.")
    if not proxy_networks or any(network.prefixlen == 0 for network in proxy_networks):
        fail("Nie można ufać wszystkim adresom proxy.")
    try:
        edge_networks = tuple(ipaddress.ip_network(value.strip()) for value in
                              environment.get("RENDER_EDGE_CIDRS", "").split(","))
    except ValueError:
        fail("Ustaw potwierdzone publiczne RENDER_EDGE_CIDRS Cloudflare.")
    if not edge_networks or any(
        network.prefixlen == 0 or not network.network_address.is_global
        or not any(network.version == proxy.version and network.subnet_of(proxy)
                   for proxy in proxy_networks)
        for network in edge_networks
    ):
        fail("Zakresy edge muszą być publiczne i zawarte w RENDER_PROXY_CIDRS.")
    from registry.microsoft_mail import BACKEND, validated_credentials

    if current["EMAIL_BACKEND"] == BACKEND:
        validated_credentials(current)
    elif (current["EMAIL_BACKEND"] != "django.core.mail.backends.smtp.EmailBackend"
        or not current["EMAIL_HOST"]
        or current["EMAIL_USE_TLS"] == current["EMAIL_USE_SSL"]):
        fail("Render wymaga SMTP z TLS/STARTTLS albo skonfigurowanej poczty Microsoft.")
    try:
        validate_email(current["DEFAULT_FROM_EMAIL"])
        if current["DEFAULT_FROM_EMAIL"].rsplit("@", 1)[-1].lower() in {"localhost", "invalid"}:
            raise ValidationError("Niepoprawny nadawca.")
    except ValidationError:
        fail("Ustaw poprawny DEFAULT_FROM_EMAIL.")
    return {
        "ALLOWED_HOSTS": hosts,
        "APP_URL": environment["APP_URL"].rstrip("/"),
        "APP_REVISION": revision,
        "DATABASES": {"default": {
            "ENGINE": "django.db.backends.postgresql", "NAME": database["dbname"],
            "USER": database["user"], "PASSWORD": database["password"], "HOST": host,
            "PORT": database.get("port", "5432"), "CONN_MAX_AGE": 60,
            "OPTIONS": {"connect_timeout": 5, "sslmode": "require"},
        }},
        "CSRF_TRUSTED_ORIGINS": [environment["APP_URL"].rstrip("/")],
        "RENDER_PROXY_NETWORKS": proxy_networks,
        "RENDER_EDGE_NETWORKS": edge_networks,
        "SECURE_PROXY_SSL_HEADER": ("HTTP_X_FORWARDED_PROTO", "https"),
        "SECURE_REDIRECT_EXEMPT": [r"^api/health/$"],
        "MIDDLEWARE": ["registry.render_proxy.RenderProxyMiddleware",
                       current["MIDDLEWARE"][0], "whitenoise.middleware.WhiteNoiseMiddleware",
                       *current["MIDDLEWARE"][1:]],
        "STORAGES": {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                     "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"}},
        "WHITENOISE_ALLOW_ALL_ORIGINS": False,
        "WHITENOISE_MAX_AGE": 60,
    }
