"""Rzeczywiste OTP, bezpieczny powrót i odrzucanie nieaktualnych formularzy."""

import re
from datetime import timedelta

from django.contrib.sessions.models import Session
from django.core import mail
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .authentication import safe_login_return
from .models import Request
from .services import create_request
from .tests import data, fixtures


class LoginReturnValidationTests(SimpleTestCase):
    def test_only_relative_panel_targets_are_allowed(self):
        self.assertEqual(safe_login_return("/panel/wnioski/?status=SENT"), "/panel/wnioski/?status=SENT")
        for value in [
            None,
            3,
            "",
            "https://example.org/panel/",
            "//example.org/panel/",
            "https://testserver/panel/",
            "/\\example.org/panel/",
            "/panel/\\example.org",
            "/logowanie/",
            "/api/requests/",
            "/panel/\nLocation: https://example.org",
            "/panel/" + "x" * 2048,
            "/panel/../wyloguj/",
            "/panel/%2e%2e/wyloguj/",
            "/panel/%5cexample.org",
            "/panel/%0aLocation",
        ]:
            with self.subTest(value=value):
                self.assertEqual(safe_login_return(value), "")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AuthenticationFlowTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def order_code(self, next_path="", email=None):
        response = self.client.post(
            reverse("login_email"), {"email": email or self.a.email, "next": next_path}
        )
        self.assertRedirects(response, reverse("login_code"))
        return re.search(r"Kod: (\d{8})", mail.outbox[-1].body).group(1)

    def test_otp_returns_to_protected_request_and_rotates_session(self):
        req = create_request(self.a, data())
        target = reverse("request_detail", args=[req.uuid])
        response = self.client.get(target)
        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response["Location"])
        self.assertContains(self.client.get(response["Location"]), f'value="{target}"')
        code = self.order_code(target)
        old_session_key = self.client.session.session_key
        response = self.client.post(reverse("login_code"), {"code": code})
        self.assertRedirects(response, target)
        self.assertNotEqual(self.client.session.session_key, old_session_key)
        self.assertNotIn("login_next", self.client.session)
        self.assertNotIn("login_code_id", self.client.session)

    def test_code_failure_and_ordering_again_preserve_target(self):
        target = "/panel/ewidencja/?status=ISSUED"
        self.order_code(target)
        response = self.client.post(reverse("login_code"), {"code": "bad"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session["login_next"], target)
        self.assertContains(response, "?next=/panel/ewidencja/%3Fstatus%3DISSUED")
        self.assertContains(self.client.get(reverse("login_email"), {"next": target}), "next")

    def test_malicious_target_is_rechecked_after_otp(self):
        code = self.order_code("https://example.org/panel/")
        self.assertEqual(self.client.session["login_next"], "")
        session = self.client.session
        session["login_next"] = "//example.org/panel/"
        session.save()
        self.assertRedirects(self.client.post(reverse("login_code"), {"code": code}), reverse("dashboard"))

    def test_authenticated_shortcut_does_not_skip_office_scope(self):
        req = create_request(self.b, data())
        target = reverse("request_detail", args=[req.uuid])
        self.client.force_login(self.a)
        response = self.client.get(reverse("login_email"), {"next": target}, follow=True)
        self.assertEqual(response.status_code, 404)
        response = self.client.get(reverse("login_email"), {"next": "https://example.org/panel/"})
        self.assertRedirects(response, reverse("dashboard"))

    def test_expired_session_cannot_write_and_login_keeps_original_screen(self):
        self.client.force_login(self.a)
        Session.objects.filter(session_key=self.client.session.session_key).update(
            expire_date=timezone.now() - timedelta(seconds=1)
        )
        response = self.client.post(reverse("request_new"), data())
        self.assertEqual(response.status_code, 302)
        self.assertIn("next=/panel/wnioski/nowy/", response["Location"])
        self.assertFalse(Request.objects.exists())
        code = self.order_code(reverse("request_new"))
        self.assertRedirects(self.client.post(reverse("login_code"), {"code": code}), reverse("request_new"))
        self.assertFalse(Request.objects.exists())

    def test_old_form_csrf_is_rejected_after_otp_and_does_not_write(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.get(reverse("login_email"))
        old_csrf = self.client.cookies["csrftoken"].value
        response = self.client.post(
            reverse("login_email"), {"email": self.a.email, "csrfmiddlewaretoken": old_csrf}
        )
        self.assertEqual(response.status_code, 302)
        code = re.search(r"Kod: (\d{8})", mail.outbox[-1].body).group(1)
        self.client.post(reverse("login_code"), {"code": code, "csrfmiddlewaretoken": old_csrf})
        self.assertNotEqual(old_csrf, self.client.cookies["csrftoken"].value)
        response = self.client.post(reverse("request_new"), {**data(), "csrfmiddlewaretoken": old_csrf})
        self.assertContains(response, "Nie wykonano tej operacji", status_code=403)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertNotContains(response, "CSRF token", status_code=403)
        self.assertFalse(Request.objects.exists())

    def test_api_csrf_failure_is_polish_json_without_internal_reason(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.a)
        response = client.post("/api/requests/", data(), content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertIn("Nie można potwierdzić", response.json()["error"])
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertFalse(Request.objects.exists())
