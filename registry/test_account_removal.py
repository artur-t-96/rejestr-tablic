"""Usuwanie kont: puste kasujemy, konto z historią zamykamy bez utraty śladu."""

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from .account_invitations import enqueue_invitation
from .accounts import remove_account
from .audit_presentation import present_event
from .forms import account_settings_snapshot
from .models import AccountInvitation, AuditLog, LoginCode, User
from .services import audit, create_request
from .tests import data, fixtures


def version(user):
    return account_settings_snapshot(User.objects.get(pk=user.pk))


class AccountRemovalTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        for user, name in ((self.a, "Anna"), (self.b, "Bartosz")):
            User.objects.filter(pk=user.pk).update(first_name=name, last_name="Fikcyjna")
            user.refresh_from_db()

    def test_account_without_history_is_really_deleted_with_its_invitations(self):
        enqueue_invitation(self.admin, self.b.pk, "Fikcyjne zaproszenie")
        pk = self.b.pk
        self.assertEqual(remove_account(self.admin, pk, version(self.b), "Założone omyłkowo"), "deleted")
        self.assertFalse(User.objects.filter(pk=pk).exists())
        self.assertFalse(AccountInvitation.objects.filter(user_id=pk).exists())
        event = AuditLog.objects.get(action="admin.user_deleted")
        self.assertEqual((event.object_id, event.reason), (str(pk), "Założone omyłkowo"))
        self.assertNotIn("b@test.invalid", str(event.before) + str(event.after))

    def test_account_with_history_is_closed_and_keeps_only_the_name(self):
        req = create_request(self.a, data())
        enqueue_invitation(self.admin, self.a.pk, "Fikcyjne zaproszenie")
        LoginCode.objects.create(user=self.a, digest="x", expires_at=req.created_at)
        self.assertEqual(
            remove_account(self.admin, self.a.pk, version(self.a), "Odejście z urzędu"), "closed"
        )
        user = User.objects.get(pk=self.a.pk)
        self.assertIsNotNone(user.removed_at)
        self.assertFalse(user.is_active)
        self.assertFalse(user.access_allowed)
        self.assertEqual(user.email, f"usuniete-{user.pk}@usuniete.invalid")
        self.assertEqual(user.username, user.email)
        self.assertEqual(user.get_full_name(), "Anna Fikcyjna")
        self.assertFalse(LoginCode.objects.filter(user=user).exists())
        invitation = AccountInvitation.objects.get(user=user)
        self.assertEqual(invitation.status, "CANCELLED")
        self.assertNotIn(
            "a@test.invalid", invitation.email + invitation.body + str(invitation.account_context)
        )
        req.refresh_from_db()
        self.assertEqual(req.author_id, user.pk)
        event = AuditLog.objects.get(action="admin.user_closed")
        self.assertNotIn("a@test.invalid", str(event.before) + str(event.after))
        with self.assertRaisesRegex(ValidationError, "już usunięte"):
            remove_account(self.admin, user.pk, version(user), "Ponownie")

    def test_refusals_leave_the_account_untouched(self):
        stale = version(self.b)
        User.objects.filter(pk=self.b.pk).update(last_name="Zmieniona")
        cases = (
            (self.admin, self.b.pk, stale, "Powód", ValidationError),
            (self.admin, self.b.pk, version(self.b), " ", ValidationError),
            (self.admin, self.admin.pk, version(self.admin), "Powód", ValidationError),
            (self.ump, self.b.pk, version(self.b), "Powód", PermissionDenied),
        )
        for actor, pk, token, reason, error in cases:
            with self.subTest(actor=actor.role, pk=pk, reason=reason), self.assertRaises(error):
                remove_account(actor, pk, token, reason)
        self.assertEqual(User.objects.filter(removed_at__isnull=True, is_active=True).count(), 4)

    def test_history_shows_removed_account_by_name_without_email(self):
        req = create_request(self.a, data())
        edit = audit(
            self.admin, "admin.user_saved", self.a, {"email": "old@test.invalid"}, {"email": self.a.email}
        )
        remove_account(self.admin, self.a.pk, version(self.a), "Odejście")
        created = AuditLog.objects.get(action="request.created", object_id=str(req.pk))
        self.assertEqual(present_event(created)["actor_label"], "Anna Fikcyjna (konto usunięte)")
        shown = str(present_event(AuditLog.objects.get(pk=edit.pk)))
        self.assertNotIn("a@test.invalid", shown)
        self.assertNotIn("old@test.invalid", shown)
        self.client.force_login(self.ump)
        page = self.client.get(reverse("request_detail", args=[req.uuid]))
        self.assertContains(page, "Anna Fikcyjna (konto usunięte)")
        self.assertNotContains(page, "usuniete.invalid")


class AccountRemovalViewTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        self.client.force_login(self.admin)

    def payload(self, user, **changes):
        token = signing.dumps(version(user), salt="admin-account-version")
        return {"action": "remove", "account_version": token, "reason": "Fikcyjne usunięcie", **changes}

    def test_admin_removes_account_from_edit_page_and_list_hides_closed_ones(self):
        create_request(self.a, data())
        url = reverse("admin_edit", args=["user", self.a.pk])
        self.assertContains(self.client.get(url), "Usuń konto")
        response = self.client.post(url, self.payload(self.a), follow=True)
        self.assertContains(response, "zamknięte")
        self.assertNotContains(self.client.get(reverse("admin_panel")), f"usuniete-{self.a.pk}@")
        self.assertContains(
            self.client.get(reverse("admin_panel"), {"usuniete": "1"}), f"usuniete-{self.a.pk}@"
        )
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(reverse("account_invitations", args=[self.a.pk])).status_code, 404)
        response = self.client.post(
            reverse("admin_edit", args=["user", self.b.pk]), self.payload(self.b), follow=True
        )
        self.assertContains(response, "Konto usunięte")
        self.assertFalse(User.objects.filter(pk=self.b.pk).exists())

    def test_missing_reason_or_stale_form_and_own_account_are_refused(self):
        url = reverse("admin_edit", args=["user", self.b.pk])
        response = self.client.post(url, self.payload(self.b, reason=""), follow=True)
        self.assertContains(response, "Podaj powód usunięcia konta")
        response = self.client.post(url, self.payload(self.b, account_version="zmienione"), follow=True)
        self.assertContains(response, "Formularz konta wygasł")
        own = reverse("admin_edit", args=["user", self.admin.pk])
        self.assertNotContains(self.client.get(own), "Usuń konto")
        self.assertContains(self.client.post(own, self.payload(self.admin), follow=True), "Własnego konta")
        self.assertEqual(User.objects.filter(removed_at__isnull=True).count(), 4)
        self.client.force_login(self.ump)
        self.assertEqual(self.client.post(url, self.payload(self.b)).status_code, 403)
