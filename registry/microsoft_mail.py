"""Microsoft Graph: jeden nadawca, certyfikat aplikacji i pojedynczy POST MIME.

Zakres skrzynki jest nadawany w Exchange Application RBAC. HTTP 202 oznacza
przyjęcie do wysyłki, nie doręczenie. Nie ponawiamy niejednoznacznego POST.
"""

import base64
import hashlib
import time
import uuid
from datetime import datetime, timezone
from email.utils import getaddresses
from threading import RLock

import httpx
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.mail.backends.base import BaseEmailBackend
from django.core.validators import validate_email

BACKEND = "registry.microsoft_mail.EmailBackend"
SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
# Konserwatywny limit całego zakodowanego MIME, razem z PDF i nagłówkami.
MAX_MIME_BYTES = 3 * 1024 * 1024


def validated_credentials(values):
    """Walidacja bez sieci; wyjątek nigdy nie zawiera sekretu ani PEM."""
    try:
        tenant = str(uuid.UUID(values["MS_MAIL_TENANT_ID"]))
        client = str(uuid.UUID(values["MS_MAIL_CLIENT_ID"]))
        mailbox = str(uuid.UUID(values["MS_MAIL_MAILBOX_ID"]))
        sender = values["DEFAULT_FROM_EMAIL"]
        validate_email(sender)
        if any(character in sender for character in "\r\n"):
            raise ValueError()
        cert = x509.load_pem_x509_certificate(values["MS_MAIL_CERTIFICATE"].encode())
        key = serialization.load_pem_private_key(values["MS_MAIL_PRIVATE_KEY"].encode(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ValueError()
        if cert.public_key().public_numbers() != key.public_key().public_numbers():
            raise ValueError()
        now = datetime.now(timezone.utc)
        if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
            raise ValueError()
        thumbprint = base64.urlsafe_b64encode(hashlib.sha256(
            cert.public_bytes(serialization.Encoding.DER)).digest()).decode().rstrip("=")
    except (KeyError, TypeError, ValueError, AttributeError, ValidationError):
        raise ImproperlyConfigured(
            "Poczta Microsoft wymaga identyfikatorów organizacji/aplikacji, "
            "poprawnego nadawcy i ważnego certyfikatu RSA zgodnego z kluczem."
        ) from None
    return tenant, client, mailbox, sender, key, thumbprint


def configuration_ready():
    if settings.EMAIL_BACKEND == SMTP_BACKEND:
        return bool(settings.EMAIL_HOST)
    if settings.EMAIL_BACKEND == BACKEND:
        try:
            validated_credentials({name: getattr(settings, name, "") for name in (
                "MS_MAIL_TENANT_ID", "MS_MAIL_CLIENT_ID", "MS_MAIL_MAILBOX_ID", "MS_MAIL_CERTIFICATE",
                "MS_MAIL_PRIVATE_KEY", "DEFAULT_FROM_EMAIL")})
        except ImproperlyConfigured:
            return False
        return True
    return settings.LOCAL


def transport_name():
    if settings.LOCAL and settings.EMAIL_BACKEND.endswith("filebased.EmailBackend"):
        return "file"
    return "Microsoft Graph" if settings.EMAIL_BACKEND == BACKEND else "SMTP"


class EmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, *, transport=None, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        values = {name: getattr(settings, name, "") for name in (
            "MS_MAIL_TENANT_ID", "MS_MAIL_CLIENT_ID", "MS_MAIL_MAILBOX_ID", "MS_MAIL_CERTIFICATE",
            "MS_MAIL_PRIVATE_KEY", "DEFAULT_FROM_EMAIL")}
        self.tenant, self.client_id, mailbox, self.sender, self.key, self.thumbprint = validated_credentials(values)
        self.token_url = f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/token"
        self.send_url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/sendMail"
        self.transport = transport
        self.http = None
        self.token = ""
        self.expires_at = 0
        self.lock = RLock()

    def open(self):
        if self.http is not None:
            return False
        self.http = httpx.Client(timeout=httpx.Timeout(15, connect=5), verify=True,
                                 follow_redirects=False, trust_env=False, transport=self.transport)
        return True

    def close(self):
        if self.http is not None:
            self.http.close()
            self.http = None
        self.token = ""
        self.expires_at = 0

    def _access_token(self):
        if self.token and time.monotonic() < self.expires_at:
            return self.token
        now = int(time.time())
        assertion = jwt.encode({"aud": self.token_url, "iss": self.client_id,
            "sub": self.client_id, "jti": str(uuid.uuid4()), "iat": now, "nbf": now,
            "exp": now + 300}, self.key, algorithm="PS256",
            headers={"x5t#S256": self.thumbprint})
        response = self.http.post(self.token_url, data={"client_id": self.client_id,
            "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": assertion})
        if response.status_code != 200 or len(response.content) > 65536:
            raise RuntimeError("Microsoft odmówił uwierzytelnienia aplikacji pocztowej.")
        try:
            result = response.json()
            token = result["access_token"]
            lifetime = int(result["expires_in"])
            if (result.get("token_type", "").lower() != "bearer" or not isinstance(token, str)
                or not token or any(c.isspace() for c in token) or lifetime < 60):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("Microsoft zwrócił niepoprawną odpowiedź uwierzytelnienia.") from None
        self.token = token
        self.expires_at = time.monotonic() + min(lifetime - 30, 3600)
        return token

    def _mime(self, message):
        if message.from_email != self.sender:
            raise ValueError("Wysyłka wymaga skonfigurowanego nadawcy projektu.")
        for address in message.recipients():
            validate_email(address)
        mime = message.message()
        # Dodatkowe nagłówki nie mogą podmienić nadawcy ani adresatów.
        if getaddresses(mime.get_all("From", [])) != [("", self.sender)]:
            raise ValueError("Niepoprawny nagłówek nadawcy.")
        if any(mime.get_all(name) for name in ("Sender", "Resent-From", "Resent-To", "Bcc")):
            raise ValueError("Nieobsługiwane nagłówki przekierowania poczty.")
        recipients = [address for _, address in getaddresses(mime.get_all("To", []) + mime.get_all("Cc", []))]
        if recipients != list(message.to) + list(message.cc):
            raise ValueError("Nagłówki nie odpowiadają adresatom wiadomości.")
        # Graph odczytuje adresatów z MIME, a Django pomija Bcc w message().
        if message.bcc:
            mime["Bcc"] = ", ".join(message.bcc)
        content = base64.b64encode(mime.as_bytes(linesep="\r\n"))
        if len(content) > MAX_MIME_BYTES:
            raise ValueError("Wiadomość przekracza limit 3 MiB wysyłki Microsoft.")
        return content

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        accepted = 0
        with self.lock:
            opened = self.open()
            try:
                for message in email_messages:
                    if not message.recipients():
                        continue
                    try:
                        content = self._mime(message)
                        token = self._access_token()
                        response = self.http.post(self.send_url, content=content,
                            headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"})
                        if response.status_code != 202:
                            raise RuntimeError("Microsoft nie potwierdził przyjęcia wiadomości.")
                        accepted += 1
                    except Exception:
                        # Nie ujawniamy tokenu, PEM, treści poczty ani odpowiedzi operatora.
                        if not self.fail_silently:
                            raise RuntimeError("Wysyłka Microsoft nie została potwierdzona; "
                                               "sprawdź wynik przed ponowieniem.") from None
            finally:
                if opened:
                    self.close()
        return accepted
