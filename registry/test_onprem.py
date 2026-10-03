import copy
import secrets
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.http import JsonResponse
from django.middleware.security import SecurityMiddleware
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from config.onprem import build_settings

from .middleware import OnPremProxyMiddleware
from .models import AuditLog, Letter, Office, PlateRecord, Request, User


class OnPremConfigurationTests(SimpleTestCase):
    def setUp(self):
        self.environment = {
            "DYNA_ENV": "onprem",
            "APP_URL": "https://rejestr.example.org",
            "DJANGO_ALLOWED_HOSTS": "rejestr.example.org",
            "APP_REVISION": "a" * 40,
            "DYNA_DATA_DIR": "/var/lib/dyna",
        }
        self.current = {
            "LOCAL": False,
            "DEBUG": False,
            "SECRET_KEY": secrets.token_urlsafe(64),
            "BASE_DIR": Path("/opt/dyna/releases/test"),
            "DATABASES": {
                "default": {
                    "ENGINE": "django.db.backends.postgresql",
                    "NAME": "dyna",
                    "USER": "dyna_runtime",
                    "HOST": "/var/run/postgresql",
                }
            },
            "MIDDLEWARE": ["django.middleware.security.SecurityMiddleware"],
            "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "EMAIL_HOST": "smtp.example.org",
            "EMAIL_USE_TLS": True,
            "EMAIL_USE_SSL": False,
            "DEFAULT_FROM_EMAIL": "rejestr@example.org",
        }

    def test_profile_keeps_one_host_and_enables_only_trusted_local_proxy(self):
        result = build_settings(self.environment, self.current)
        self.assertEqual(result["ALLOWED_HOSTS"], ["rejestr.example.org"])
        self.assertEqual(result["TRUSTED_PROXY_ADDRESSES"], ("127.0.0.1",))
        self.assertEqual(result["MIDDLEWARE"][0], "registry.middleware.OnPremProxyMiddleware")
        self.assertEqual(result["DATABASES"]["default"]["OPTIONS"]["connect_timeout"], 5)

    def test_wrong_environment_debug_weak_secret_and_sqlite_are_blocked(self):
        for key, value in [("LOCAL", True), ("DEBUG", True), ("SECRET_KEY", "weak")]:
            with self.subTest(key=key), self.assertRaises(ImproperlyConfigured):
                build_settings(self.environment, {**self.current, key: value})
        current = copy.deepcopy(self.current)
        current["DATABASES"]["default"]["ENGINE"] = "django.db.backends.sqlite3"
        with self.assertRaises(ImproperlyConfigured):
            build_settings(self.environment, current)
        with self.assertRaises(ImproperlyConfigured):
            build_settings({**self.environment, "DYNA_ENV": "local"}, self.current)

    def test_misleading_origins_wildcards_and_missing_revision_are_blocked(self):
        for url in [
            "http://rejestr.example.org",
            "https://user:pass@rejestr.example.org",
            "https://rejestr.example.org/panel",
            "https://rejestr.example.org?secret=x",
            "https://rejestr.example.org#x",
            "https://rejestr.example.org:8443",
            "https://rejestr.example.org:bad",
        ]:
            with self.subTest(url=url), self.assertRaises(ImproperlyConfigured):
                build_settings({**self.environment, "APP_URL": url}, self.current)
        for key, value in [
            ("DJANGO_ALLOWED_HOSTS", "*"),
            ("DJANGO_ALLOWED_HOSTS", ".example.org"),
            ("APP_REVISION", "main"),
            ("DYNA_DATA_DIR", "var"),
            ("DYNA_DATA_DIR", "/opt/dyna/releases/test/data"),
        ]:
            with self.subTest(key=key, value=value), self.assertRaises(ImproperlyConfigured):
                build_settings({**self.environment, key: value}, self.current)

    def test_remote_database_requires_verified_tls(self):
        self.current["DATABASES"]["default"]["HOST"] = "db.example.org"
        for values in [{}, {"PGSSLMODE": "require"}, {"PGSSLMODE": "verify-full"}]:
            with self.subTest(values=values), self.assertRaises(ImproperlyConfigured):
                build_settings({**self.environment, **values}, self.current)
        result = build_settings(
            {**self.environment, "PGSSLMODE": "verify-full", "PGSSLROOTCERT": "/etc/dyna/ca.pem"},
            self.current,
        )
        self.assertEqual(result["DATABASES"]["default"]["OPTIONS"]["sslmode"], "verify-full")

    def test_matching_wildcard_or_invalid_domain_still_cannot_start(self):
        for host in [
            ".example.org",
            "*.example.org",
            "bad..example.org",
            "-bad.example.org",
            "a" * 64 + ".org",
        ]:
            with self.subTest(host=host), self.assertRaises(ImproperlyConfigured):
                build_settings(
                    {**self.environment, "APP_URL": "https://" + host, "DJANGO_ALLOWED_HOSTS": host},
                    self.current,
                )

    def test_mail_requires_one_encrypted_transport_and_real_sender_format(self):
        for values in [
            {"EMAIL_USE_TLS": False},
            {"EMAIL_USE_SSL": True},
            {"EMAIL_HOST": ""},
            {"EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend"},
            {"DEFAULT_FROM_EMAIL": "rejestr@localhost"},
        ]:
            with self.subTest(values=values), self.assertRaises(ImproperlyConfigured):
                build_settings(self.environment, {**self.current, **values})


@override_settings(
    TRUSTED_PROXY_ADDRESSES=("127.0.0.1",),
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    SECURE_SSL_REDIRECT=True,
)
class OnPremProxyTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.app = OnPremProxyMiddleware(
            SecurityMiddleware(
                lambda req: JsonResponse(
                    {
                        "ip": req.META["REMOTE_ADDR"],
                        "secure": req.is_secure(),
                        "xff": req.META.get("HTTP_X_FORWARDED_FOR"),
                    }
                )
            )
        )

    def request(self, **kwargs):
        return self.factory.get(
            "/",
            HTTP_HOST="testserver",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_DYNA_CLIENT_IP="192.0.2.20",
            HTTP_X_FORWARDED_PROTO="https",
            **kwargs,
        )

    def test_trusted_peer_sees_distinct_client_ip_without_https_redirect_loop(self):
        response = self.app(self.request(HTTP_X_FORWARDED_FOR="198.51.100.99"))
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ip": "192.0.2.20", "secure": True, "xff": None})
        request = self.request()
        request.META["HTTP_X_DYNA_CLIENT_IP"] = "2001:db8::1"
        self.assertJSONEqual(self.app(request).content, {"ip": "2001:db8::1", "secure": True, "xff": None})

    def test_untrusted_peer_and_missing_or_chained_headers_are_rejected(self):
        for key, value in [
            ("REMOTE_ADDR", "198.51.100.1"),
            ("HTTP_X_DYNA_CLIENT_IP", ""),
            ("HTTP_X_DYNA_CLIENT_IP", "192.0.2.1, 192.0.2.2"),
            ("HTTP_X_FORWARDED_PROTO", "https,http"),
            ("HTTP_X_FORWARDED_PROTO", ""),
        ]:
            with self.subTest(key=key, value=value):
                request = self.request()
                request.META[key] = value
                self.assertEqual(self.app(request).status_code, 400)

    def test_trusted_http_request_is_redirected_to_https(self):
        request = self.request()
        request.META["HTTP_X_FORWARDED_PROTO"] = "http"
        response = self.app(request)
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://testserver/")


class OnPremHealthTests(TestCase):
    def test_database_failure_is_503_without_details(self):
        with patch("django.db.connection.cursor", side_effect=DatabaseError("private host and secret")):
            response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "private", status_code=503)


class OnPremInitializationTests(TestCase):
    def test_clean_install_has_inactive_catalogue_and_only_otp_admin(self):
        call_command("initialize_registry", admin_email="admin@example.invalid", stdout=StringIO())
        self.assertEqual(Office.objects.count(), 35)
        self.assertFalse(Office.objects.filter(active=True).exists())
        self.assertFalse(Office.objects.exclude(email="", ade="", allowed_domains=[]).exists())
        admin = User.objects.get()
        self.assertEqual((admin.role, admin.office_id), ("ADMIN", None))
        self.assertFalse(admin.has_usable_password())
        self.assertFalse(admin.is_superuser)
        self.assertEqual(AuditLog.objects.get(action="installation.initialized").actor_id, admin.pk)
        self.assertEqual(
            (Request.objects.count(), Letter.objects.count(), PlateRecord.objects.count()), (0, 0, 0)
        )
        with self.assertRaises(CommandError):
            call_command("initialize_registry", admin_email="other@example.invalid")
        self.assertEqual(User.objects.get().pk, admin.pk)

    @override_settings(LOCAL=False)
    def test_invalid_admin_does_not_leave_partial_installation(self):
        for email in ["broken", "admin@example.invalid"]:
            with self.subTest(email=email), self.assertRaises(CommandError):
                call_command("initialize_registry", admin_email=email)
            self.assertEqual((Office.objects.count(), User.objects.count()), (0, 0))

    def test_local_profile_cannot_pass_onprem_check(self):
        with self.assertRaises(CommandError):
            call_command("check_onprem", stdout=StringIO())

    def test_health_returns_release_without_business_data(self):
        with override_settings(APP_REVISION="b" * 40):
            response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revision"], "b" * 40)
        self.assertEqual(set(response.json()), {"status", "service", "mode", "revision"})
