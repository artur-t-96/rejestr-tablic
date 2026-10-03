"""Weryfikacja czasu sesji bez automatycznego przedłużania i zmiany tożsamości."""

from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .authentication import session_owner
from .models import AuditLog, Request
from .tests import data, fixtures


class SessionControlTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        self.client.force_login(self.a)
        self.headers = {"HTTP_X_DYNA_SESSION_OWNER": session_owner(self.a), "HTTP_ACCEPT": "application/json"}

    def stored(self):
        return Session.objects.get(session_key=self.client.session.session_key)

    def test_readonly_polling_keeps_database_deadline_and_does_not_extend(self):
        original = self.stored()
        for _ in range(3):
            response = self.client.get(reverse("session_status"), **self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(set(response.json()), {"remaining_seconds", "warning_seconds"})
            self.assertEqual(response.json()["warning_seconds"], 120)
            self.assertLessEqual(response.json()["remaining_seconds"], settings.SESSION_COOKIE_AGE)
        current = self.stored()
        self.assertEqual(current.expire_date, original.expire_date)
        self.assertEqual(current.session_data, original.session_data)
        self.assertFalse(AuditLog.objects.filter(action="auth.session_extended").exists())

    def test_explicit_extension_renews_database_deadline_without_changing_identity(self):
        Session.objects.filter(pk=self.stored().pk).update(expire_date=timezone.now() + timedelta(seconds=60))
        original_key = self.client.session.session_key
        response = self.client.post(reverse("session_extend"), data(), **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.json()["remaining_seconds"], settings.SESSION_COOKIE_AGE - 2)
        self.assertGreater(
            self.stored().expire_date, timezone.now() + timedelta(seconds=settings.SESSION_COOKIE_AGE - 2)
        )
        self.assertEqual(self.client.session.session_key, original_key)
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        self.assertEqual(AuditLog.objects.get(action="auth.session_extended").actor_id, self.a.pk)
        self.assertFalse(Request.objects.exists())

    def test_user_can_extend_at_least_ten_times(self):
        for _ in range(10):
            self.assertEqual(self.client.post(reverse("session_extend"), **self.headers).status_code, 200)
        self.assertEqual(AuditLog.objects.filter(action="auth.session_extended").count(), 10)

    def test_csrf_is_required_and_valid_extension_preserves_form_token(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.a)
        self.client.get(reverse("request_new"))
        csrf = self.client.cookies["csrftoken"].value
        old_deadline = self.stored().expire_date
        self.assertEqual(self.client.post(reverse("session_extend"), **self.headers).status_code, 403)
        self.assertEqual(self.stored().expire_date, old_deadline)
        response = self.client.post(reverse("session_extend"), **self.headers, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(csrf, self.client.cookies["csrftoken"].value)
        response = self.client.post(reverse("request_new"), {**data(), "csrfmiddlewaretoken": csrf})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Request.objects.count(), 1)

    def test_expired_and_logged_out_sessions_cannot_extend(self):
        Session.objects.filter(pk=self.stored().pk).update(expire_date=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get(reverse("session_status"), **self.headers).status_code, 401)
        self.assertEqual(self.client.post(reverse("session_extend"), **self.headers).status_code, 401)
        self.assertFalse(AuditLog.objects.filter(action="auth.session_extended").exists())

    def test_other_account_or_changed_office_cannot_extend_old_page_context(self):
        self.client.force_login(self.b)
        original = self.stored()
        for url in ["session_status", "session_extend"]:
            response = (self.client.get if url == "session_status" else self.client.post)(
                reverse(url), **self.headers
            )
            self.assertEqual(response.status_code, 409)
        self.assertEqual(self.stored().expire_date, original.expire_date)
        self.client.force_login(self.a)
        self.a.office = self.b.office
        self.a.save()
        self.assertEqual(self.client.post(reverse("session_extend"), **self.headers).status_code, 409)

    def test_disabled_office_cannot_extend(self):
        self.a.office.active = False
        self.a.office.save()
        self.assertEqual(self.client.post(reverse("session_extend"), **self.headers).status_code, 401)

    def test_html_fallback_returns_only_to_local_panel(self):
        response = self.client.post(
            reverse("session_extend"),
            {"session_owner": session_owner(self.a), "return_to": "/panel/wnioski/?status=SENT"},
        )
        self.assertRedirects(response, "/panel/wnioski/?status=SENT")
        response = self.client.post(
            reverse("session_extend"),
            {"session_owner": session_owner(self.a), "return_to": "https://example.org/panel/"},
        )
        self.assertRedirects(response, "/panel/")

    def test_all_roles_get_controls_but_public_page_does_not(self):
        for user in [self.a, self.ump, self.admin]:
            self.client.force_login(user)
            response = self.client.get(reverse("dashboard"), follow=True)
            self.assertContains(response, 'data-session-owner="' + session_owner(user) + '"')
            self.assertContains(response, "Przedłuż czas logowania")
            self.assertNotContains(response, "localStorage")
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("public")), 'id="session-notice"')

    def test_session_responses_are_not_cached_and_extension_is_post_only(self):
        self.assertEqual(
            self.client.get(reverse("session_status"), **self.headers)["Cache-Control"], "no-store"
        )
        self.assertEqual(
            self.client.post(reverse("session_extend"), **self.headers)["Cache-Control"], "no-store"
        )
        self.assertEqual(self.client.get(reverse("session_extend"), **self.headers).status_code, 405)
