import copy
import ipaddress
import secrets
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from whitenoise import WhiteNoise

from config.render import build_settings
from registry.render_proxy import RenderProxyMiddleware


class RenderSettingsTests(SimpleTestCase):
    def setUp(self):
        self.environment = {
            "DYNA_ENV": "render", "APP_URL": "https://rejestr.example.org",
            "DJANGO_ALLOWED_HOSTS": "rejestr.example.org", "RENDER_GIT_COMMIT": "a" * 40,
            "DYNA_DATA_DIR": "/var/data",
            "DATABASE_URL": "postgresql://dyna:fixture-password@dpg-fixture/dyna",
            "RENDER_PROXY_CIDRS": "10.0.0.0/8,203.0.113.0/24",
        }
        self.current = {
            "LOCAL": False, "DEBUG": False, "SECRET_KEY": secrets.token_urlsafe(64),
            "BASE_DIR": Path("/opt/render/project/src"),
            "MIDDLEWARE": ["django.middleware.security.SecurityMiddleware", "registry.middleware.AccountMiddleware"],
            "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "EMAIL_HOST": "smtp.example.org", "EMAIL_USE_TLS": True,
            "EMAIL_USE_SSL": False, "DEFAULT_FROM_EMAIL": "rejestr@example.org",
        }

    def test_profile_uses_commit_tls_private_postgres_and_public_static_only(self):
        result = build_settings(self.environment, self.current)
        self.assertEqual(result["APP_REVISION"], "a" * 40)
        self.assertEqual(result["DATABASES"]["default"]["OPTIONS"]["sslmode"], "require")
        self.assertEqual(result["MIDDLEWARE"][:3], ["registry.render_proxy.RenderProxyMiddleware",
                         "django.middleware.security.SecurityMiddleware", "whitenoise.middleware.WhiteNoiseMiddleware"])
        self.assertNotIn("WHITENOISE_ROOT", result)

    def test_bad_origin_host_revision_path_and_proxy_scope_fail(self):
        for key, value in [
            ("APP_URL", "http://rejestr.example.org"), ("APP_URL", "https://user:pass@rejestr.example.org"),
            ("APP_URL", "https://rejestr.example.org/path"), ("APP_URL", "https://rejestr.example.org:bad"),
            ("APP_URL", "https://rejestr.example.org?data=x"), ("APP_URL", "https://rejestr.example.org#data"),
            ("DJANGO_ALLOWED_HOSTS", "*"), ("RENDER_GIT_COMMIT", "main"),
            ("DYNA_DATA_DIR", "var"), ("DYNA_DATA_DIR", "/opt/render/project/src/data"),
            ("RENDER_PROXY_CIDRS", "0.0.0.0/0"), ("RENDER_PROXY_CIDRS", "::/0"),
            ("RENDER_PROXY_CIDRS", ""), ("DYNA_ENV", "local"),
        ]:
            with self.subTest(key=key, value=value), self.assertRaises(ImproperlyConfigured):
                build_settings({**self.environment, key: value}, self.current)

    def test_missing_postgres_external_host_and_secrets_are_rejected_without_echo(self):
        for value in ["", "postgresql://dyna@dpg-fixture/dyna",
                      "postgresql://dyna:fixture-password@example.org/dyna", "bad"]:
            with self.subTest(value=value), self.assertRaises(ImproperlyConfigured) as error:
                build_settings({**self.environment, "DATABASE_URL": value}, self.current)
            self.assertNotIn("fixture-password", str(error.exception))

    def test_local_debug_weak_secret_and_unusable_email_fail(self):
        for key, value in [("LOCAL", True), ("DEBUG", True), ("SECRET_KEY", "weak"),
                           ("EMAIL_HOST", ""), ("EMAIL_USE_SSL", True),
                           ("EMAIL_BACKEND", "django.core.mail.backends.filebased.EmailBackend"),
                           ("DEFAULT_FROM_EMAIL", "rejestr@localhost")]:
            with self.subTest(key=key), self.assertRaises(ImproperlyConfigured):
                build_settings(self.environment, {**copy.deepcopy(self.current), key: value})


@override_settings(RENDER_PROXY_NETWORKS=(ipaddress.ip_network("10.0.0.0/8"),
                                        ipaddress.ip_network("203.0.113.0/24")))
class RenderProxyTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.received = []
        self.middleware = RenderProxyMiddleware(self.respond)

    def respond(self, request):
        self.received.append(request.META.copy())
        return JsonResponse({"ip": request.META["REMOTE_ADDR"], "secure": request.is_secure()})

    def request(self, chain="198.51.100.7, 203.0.113.8", **kwargs):
        return self.factory.get("/", REMOTE_ADDR="10.1.2.3", HTTP_X_FORWARDED_FOR=chain,
                                HTTP_X_FORWARDED_PROTO="https", **kwargs)

    def test_spoofed_prefix_is_ignored_and_custom_identity_headers_removed(self):
        response = self.middleware(self.request("192.0.2.99, 198.51.100.7, 203.0.113.8",
                                  HTTP_CF_CONNECTING_IP="192.0.2.99", HTTP_X_FORWARDED_HOST="evil.example"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.received[0]["REMOTE_ADDR"], "198.51.100.7")
        self.assertNotIn("HTTP_CF_CONNECTING_IP", self.received[0])
        self.assertNotIn("HTTP_X_FORWARDED_HOST", self.received[0])

    def test_direct_untrusted_peer_cannot_supply_forwarded_identity(self):
        request = self.request(); request.META["REMOTE_ADDR"] = "198.51.100.7"
        self.assertEqual(self.middleware(request).status_code, 400)
        self.assertEqual(self.received, [])

    def test_malformed_empty_all_trusted_and_overlong_chains_fail_closed(self):
        for chain in ["", "not-an-ip", "10.1.2.3, 203.0.113.8", ",198.51.100.7,", "," * 21]:
            with self.subTest(chain=chain):
                self.assertEqual(self.middleware(self.request(chain)).status_code, 400)
        self.assertEqual(self.received, [])

    def test_ipv6_client_survives_normalization(self):
        self.assertEqual(self.middleware(self.request("2001:db8::7,203.0.113.8")).status_code, 200)
        self.assertEqual(self.received[0]["REMOTE_ADDR"], "2001:db8::7")

    def test_health_probe_without_forwarded_identity_is_limited_to_health(self):
        for path, status in [("/api/health/", 200), ("/api/availability/", 400), ("/panel/", 400)]:
            request = self.factory.get(path, REMOTE_ADDR="10.1.2.3")
            self.assertEqual(self.middleware(request).status_code, status)


class RenderStaticTests(SimpleTestCase):
    def test_static_server_does_not_expose_sibling_private_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); public = root / "static"; public.mkdir()
            (public / "app.css").write_text("body{color:black}")
            (root / "private.pdf").write_bytes(b"private-fixture")
            fallback = lambda environ, start: (start("404 Not Found", []), [b"missing"])[1]
            application = WhiteNoise(fallback, root=str(public), prefix="/static/")
            for path, expected in [("/static/app.css", "200 OK"), ("/private.pdf", "404 Not Found"),
                                   ("/static/../private.pdf", "404 Not Found")]:
                statuses = []
                response = application({"REQUEST_METHOD": "GET", "PATH_INFO": path},
                                       lambda status, headers: statuses.append(status))
                body = b"".join(response)
                if hasattr(response, "close"):
                    response.close()
                self.assertEqual(statuses, [expected])
                self.assertNotIn(b"private-fixture", body)

    def test_supervisor_refuses_missing_persistent_mount_before_migration(self):
        from deploy.render_start import main

        with patch.dict("os.environ", {"DYNA_DATA_DIR": "/var/data"}), \
                patch("os.path.ismount", return_value=False), patch("subprocess.run") as run:
            with self.assertRaises(SystemExit):
                main()
            run.assert_not_called()
