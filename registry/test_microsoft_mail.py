import base64
import copy
import secrets
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMessage
from django.test import SimpleTestCase, override_settings

from config.render import build_settings
from .microsoft_mail import BACKEND, EmailBackend, configuration_ready, validated_credentials


class MicrosoftMailTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Disposable mail test")])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(cls.key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=1))
                .sign(cls.key, hashes.SHA256()))
        cls.values = {"MS_MAIL_TENANT_ID": "11111111-1111-1111-1111-111111111111",
            "MS_MAIL_CLIENT_ID": "22222222-2222-2222-2222-222222222222",
            "MS_MAIL_MAILBOX_ID": "33333333-3333-3333-3333-333333333333",
            "DEFAULT_FROM_EMAIL": "registry@example.org",
            "MS_MAIL_PRIVATE_KEY": cls.key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode(),
            "MS_MAIL_CERTIFICATE": cert.public_bytes(serialization.Encoding.PEM).decode(),
            "EMAIL_BACKEND": BACKEND, "LOCAL": False, "EMAIL_HOST": ""}

    def setUp(self):
        self.configuration = override_settings(**self.values)
        self.configuration.enable()
        self.addCleanup(self.configuration.disable)
        self.requests = []

    def response(self, request):
        self.requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "disposable-test-token",
                                            "token_type": "Bearer", "expires_in": 3600})
        return httpx.Response(202)

    def mail(self):
        return EmailMessage("Kod logowania — test", "Kod testowy; ważny 10 minut.",
                            self.values["DEFAULT_FROM_EMAIL"], ["recipient@example.org"],
                            headers={"Message-ID": "<test-id@example.org>"})

    def test_certificate_assertion_and_mime_otp_pdf_acceptance(self):
        mail = self.mail()
        mail.attach("decyzja.pdf", b"%PDF-1.7\nDisposable test", "application/pdf")
        backend = EmailBackend(transport=httpx.MockTransport(self.response))
        self.assertEqual(backend.send_messages([mail]), 1)
        auth, send = self.requests
        assertion = parse_qs(auth.content.decode())["client_assertion"][0]
        claims = jwt.decode(assertion, self.key.public_key(), algorithms=["PS256"],
                            audience=backend.token_url)
        self.assertEqual(claims["sub"], self.values["MS_MAIL_CLIENT_ID"])
        self.assertEqual(claims["exp"] - claims["iat"], 300)
        self.assertIn("x5t#S256", jwt.get_unverified_header(assertion))
        self.assertEqual(str(send.url), "https://graph.microsoft.com/v1.0/users/33333333-3333-3333-3333-333333333333/sendMail")
        self.assertEqual(send.headers["content-type"], "text/plain")
        mime = BytesParser(policy=policy.default).parsebytes(base64.b64decode(send.content))
        self.assertEqual(mime["Message-ID"], "<test-id@example.org>")
        self.assertEqual(mime["Subject"], mail.subject)
        self.assertEqual(list(mime.iter_attachments())[0].get_payload(decode=True), mail.attachments[0].content)
        self.assertIsNone(backend.http)
        self.assertEqual(backend.token, "")

    def test_batch_reuses_token_but_sends_each_message_once(self):
        backend = EmailBackend(transport=httpx.MockTransport(self.response))
        self.assertEqual(backend.send_messages([self.mail(), self.mail()]), 2)
        self.assertEqual([request.url.host for request in self.requests],
                         ["login.microsoftonline.com", "graph.microsoft.com", "graph.microsoft.com"])

    def test_rejected_redirect_and_unknown_send_results_are_never_retried(self):
        for status in (200, 302, 401, 403, 429, 500):
            self.requests = []
            def respond(request):
                if request.url.host == "login.microsoftonline.com":
                    return self.response(request)
                self.requests.append(request)
                return httpx.Response(status, headers={"Location": "https://untrusted.invalid"},
                                      text="sensitive operator response")
            with self.subTest(status=status), self.assertRaises(RuntimeError) as error:
                EmailBackend(transport=httpx.MockTransport(respond)).send_messages([self.mail()])
            self.assertEqual(len(self.requests), 2)
            self.assertNotIn("sensitive", str(error.exception))

    def test_timeout_has_unknown_outcome_and_is_not_retried(self):
        def respond(request):
            if request.url.host == "login.microsoftonline.com":
                return self.response(request)
            self.requests.append(request)
            raise httpx.ReadTimeout("secret request body", request=request)
        with self.assertRaises(RuntimeError) as error:
            EmailBackend(transport=httpx.MockTransport(respond)).send_messages([self.mail()])
        self.assertEqual(len(self.requests), 2)
        self.assertNotIn("secret", str(error.exception))

    def test_bad_authentication_response_never_sends_mail_or_leaks_body(self):
        for result in ({"error": "secret operator detail"}, {"access_token": "token\r\ninjected",
                       "expires_in": 3600, "token_type": "Bearer"}):
            self.requests = []
            def respond(request):
                self.requests.append(request)
                return httpx.Response(200, json=result)
            with self.subTest(result=result), self.assertRaises(RuntimeError) as error:
                EmailBackend(transport=httpx.MockTransport(respond)).send_messages([self.mail()])
            self.assertEqual(len(self.requests), 1)
            self.assertNotIn("secret", str(error.exception))

    def test_sender_recipient_and_header_spoofing_fail_before_network(self):
        mails = []
        mail = self.mail(); mail.from_email = "other@example.org"; mails.append(mail)
        mail = self.mail(); mail.extra_headers["From"] = "other@example.org"; mails.append(mail)
        mail = self.mail(); mail.extra_headers["To"] = "other@example.org"; mails.append(mail)
        mail = self.mail(); mail.to = ["invalid\r\nBcc: secret@example.org"]; mails.append(mail)
        mail = self.mail(); mail.extra_headers["Sender"] = "other@example.org"; mails.append(mail)
        for mail in mails:
            with self.subTest(headers=mail.extra_headers), self.assertRaises(RuntimeError):
                EmailBackend(transport=httpx.MockTransport(self.response)).send_messages([mail])
        self.assertEqual(self.requests, [])

    def test_cc_bcc_are_not_silently_lost_in_graph_mime(self):
        mail = self.mail(); mail.cc = ["cc@example.org"]; mail.bcc = ["bcc@example.org"]
        self.assertEqual(EmailBackend(transport=httpx.MockTransport(self.response)).send_messages([mail]), 1)
        mime = BytesParser(policy=policy.default).parsebytes(base64.b64decode(self.requests[-1].content))
        self.assertEqual(mime["Cc"], "cc@example.org")
        self.assertEqual(mime["Bcc"], "bcc@example.org")

    def test_oversized_mime_fails_before_authentication(self):
        mail = self.mail(); mail.body = "x" * (3 * 1024 * 1024)
        with self.assertRaises(RuntimeError):
            EmailBackend(transport=httpx.MockTransport(self.response)).send_messages([mail])
        self.assertEqual(self.requests, [])

    def test_empty_and_silent_failure_return_actual_accepted_count(self):
        backend = EmailBackend(fail_silently=True, transport=httpx.MockTransport(self.response))
        self.assertEqual(backend.send_messages([]), 0)
        mail = self.mail(); mail.from_email = "wrong@example.org"
        self.assertEqual(backend.send_messages([mail]), 0)
        self.assertEqual(self.requests, [])

    def test_invalid_or_mismatching_credentials_are_redacted_and_not_ready(self):
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_pem = other_key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        for key, value in [("MS_MAIL_TENANT_ID", "../other"), ("MS_MAIL_CLIENT_ID", ""),
                           ("MS_MAIL_MAILBOX_ID", "registry@example.org"),
                           ("MS_MAIL_PRIVATE_KEY", "secret invalid PEM"),
                           ("MS_MAIL_PRIVATE_KEY", other_pem), ("MS_MAIL_CERTIFICATE", "invalid")]:
            with self.subTest(key=key), self.assertRaises(ImproperlyConfigured) as error:
                validated_credentials({**self.values, key: value})
            self.assertNotIn("secret", str(error.exception))
            with override_settings(**{key: value}):
                self.assertFalse(configuration_ready())
        self.assertTrue(configuration_ready())

    def test_render_accepts_graph_with_valid_certificate_without_smtp(self):
        environment = {"DYNA_ENV": "render", "APP_URL": "https://rejestr.example.org",
            "DJANGO_ALLOWED_HOSTS": "rejestr.example.org", "RENDER_GIT_COMMIT": "a" * 40,
            "DYNA_DATA_DIR": "/var/data", "RENDER_PROXY_CIDRS": "172.64.0.0/13",
            "RENDER_EDGE_CIDRS": "172.64.0.0/13",
            "DATABASE_URL": "postgresql://dyna:disposable-test@dpg-fixture/dyna"}
        current = {**self.values, "DEBUG": False, "SECRET_KEY": secrets.token_urlsafe(64),
            "BASE_DIR": Path("/opt/render/project/src"), "MIDDLEWARE": ["security"],
            "EMAIL_USE_TLS": False, "EMAIL_USE_SSL": False}
        self.assertEqual(build_settings(environment, current)["APP_REVISION"], "a" * 40)
        invalid = copy.copy(current); invalid["MS_MAIL_PRIVATE_KEY"] = "private-placeholder"
        with self.assertRaises(ImproperlyConfigured):
            build_settings(environment, invalid)
