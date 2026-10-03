"""Granice uprawnień, wersje kont, poczta i niepewne wyniki trwałej kolejki."""

import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from io import StringIO
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch

from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from .account_invitations import (
    enqueue_invitation,
    manage_invitation,
    process_invitation,
    recover_invitations,
)
from .models import AccountInvitation, AuditLog, Letter, LoginCode, User
from .tests import fixtures


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AccountInvitationTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        self.client.force_login(self.admin)

    def account_data(self, **changes):
        return {
            "email": "Fikcyjne.Konto@Test.Invalid",
            "first_name": "Osoba",
            "last_name": "Fikcyjna",
            "role": "COUNTY",
            "office": self.a.office_id,
            "is_active": "on",
            "reason": "Fikcyjne konto testowe",
            **changes,
        }

    def queue(self, user=None):
        return enqueue_invitation(self.admin, (user or self.a).pk, "Test fikcyjny")

    def review_data(self, item, **changes):
        page = self.client.get(reverse("account_invitation_manage", args=[item.user_id, item.uuid]))
        return {
            "version": page.context["form"].initial["version"],
            "action": "retry",
            "reason": "Weryfikacja operatora",
            **changes,
        }

    def test_create_account_queues_welcome_atomically_without_letter_or_otp(self):
        response = self.client.post(reverse("admin_new", args=["user"]), self.account_data())
        self.assertRedirects(response, reverse("admin_panel"))
        user = User.objects.get(email="fikcyjne.konto@test.invalid")
        self.assertFalse(user.has_usable_password())
        item = AccountInvitation.objects.get(user=user)
        self.assertEqual(item.status, "QUEUED")
        self.assertEqual(item.email, user.email)
        self.assertFalse(Letter.objects.exists())
        self.assertFalse(LoginCode.objects.exists())
        event = AuditLog.objects.get(action="admin.user_saved")
        self.assertEqual(event.after["office"], self.a.office_id)
        self.assertEqual(event.reason, "Fikcyjne konto testowe")
        self.assertEqual(len(mail.outbox), 0)

    def test_case_insensitive_duplicate_returns_form_error_and_changes_nothing(self):
        response = self.client.post(
            reverse("admin_new", args=["user"]), self.account_data(email=self.a.email.upper())
        )
        self.assertContains(response, "Konto z tym adresem e-mail już istnieje.")
        self.assertEqual(User.objects.count(), 4)
        self.assertFalse(AccountInvitation.objects.exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_queue_failure_rolls_back_new_account_and_audit(self):
        with patch(
            "registry.account_invitations.enqueue_invitation",
            side_effect=ValidationError("Nie można zaprosić"),
        ):
            response = self.client.post(reverse("admin_new", args=["user"]), self.account_data())
        self.assertContains(response, "Nie można zaprosić")
        self.assertEqual(User.objects.count(), 4)
        self.assertFalse(AuditLog.objects.exists())

    def test_inactive_account_has_no_invitation_and_cannot_be_invited(self):
        payload = self.account_data()
        payload.pop("is_active")
        self.client.post(reverse("admin_new", args=["user"]), payload)
        user = User.objects.get(email="fikcyjne.konto@test.invalid")
        with self.assertRaises(ValidationError):
            self.queue(user)
        self.assertFalse(AccountInvitation.objects.exists())

    def test_changed_domain_blocks_otp_and_existing_session(self):
        self.a.office.allowed_domains = ["test.invalid"]
        self.a.office.save()
        client = Client()
        client.post(reverse("login_email"), {"email": self.a.email})
        import re

        otp = re.search(r"Kod: (\d{6})", mail.outbox[-1].body).group(1)
        signed_in = Client()
        signed_in.force_login(self.a)
        self.a.office.allowed_domains = ["inny-urzad.invalid"]
        self.a.office.save()
        self.assertEqual(client.post(reverse("login_code"), {"code": otp}).status_code, 200)
        self.assertNotIn("_auth_user_id", client.session)
        before = len(mail.outbox)
        client.post(reverse("login_email"), {"email": self.a.email})
        self.assertEqual(len(mail.outbox), before)
        self.assertEqual(signed_in.get(reverse("dashboard")).status_code, 302)
        self.assertNotIn("_auth_user_id", signed_in.session)

    @override_settings(LOCAL=False)
    def test_onprem_requires_configured_domains_but_admin_remains_accessible(self):
        self.assertFalse(self.a.access_allowed)
        with self.assertRaises(ValidationError):
            self.queue()
        self.assertContains(self.client.get(reverse("admin_panel")), "Konta użytkowników")
        self.a.office.allowed_domains = ["test.invalid"]
        self.a.office.save()
        self.assertTrue(self.a.access_allowed)
        self.assertEqual(self.queue().status, "QUEUED")

    def test_malformed_domain_json_is_rejected_and_cannot_authorize_by_substring(self):
        for domains in [
            "test.invalid",
            {"test.invalid": True},
            [42],
            ["*.invalid"],
            ["a@test.invalid"],
            ["https://test.invalid"],
        ]:
            with self.subTest(domains=domains):
                self.a.office.allowed_domains = domains
                with self.assertRaises(ValidationError):
                    self.a.office.full_clean()
        for domains in ["test.invalid", {"test.invalid": True}, [42]]:
            self.a.office.allowed_domains = domains
            self.assertFalse(self.a.access_allowed)
        self.a.office.allowed_domains = [" TEST.INVALID ", "test.invalid"]
        self.a.office.full_clean()
        self.assertEqual(self.a.office.allowed_domains, ["test.invalid"])
        self.assertTrue(self.a.access_allowed)
        from .models import Office

        Office.objects.filter(pk=self.a.office_id).update(allowed_domains="test.invalid")
        response = self.client.post(reverse("admin_new", args=["user"]), self.account_data())
        self.assertContains(response, "Niepoprawna konfiguracja domen e-mail urzędu")
        self.assertEqual(User.objects.count(), 4)

    def test_domain_and_role_constraints_are_enforced(self):
        self.a.office.allowed_domains = ["urzad.invalid"]
        self.a.office.save()
        response = self.client.post(reverse("admin_new", args=["user"]), self.account_data())
        self.assertContains(response, "Domena adresu e-mail nie jest dozwolona")
        response = self.client.post(reverse("admin_new", args=["user"]), self.account_data(role="MAIN"))
        self.assertContains(response, "Rola urzędnika nie odpowiada")
        self.assertEqual(User.objects.count(), 4)

    def test_edit_stale_account_does_not_overwrite_current_data(self):
        url = reverse("admin_edit", args=["user", self.a.pk])
        page = self.client.get(url)
        version = page.context["form"].initial["account_version"]
        User.objects.filter(pk=self.a.pk).update(last_name="Aktualna wartość")
        response = self.client.post(url, self.account_data(email=self.a.email, account_version=version))
        self.assertContains(response, "Konto zmieniło się w międzyczasie")
        self.a.refresh_from_db()
        self.assertEqual(self.a.last_name, "Aktualna wartość")
        self.assertFalse(AuditLog.objects.exists())

    def test_edit_account_audits_before_and_after_but_does_not_send_new_invitation(self):
        url = reverse("admin_edit", args=["user", self.a.pk])
        version = self.client.get(url).context["form"].initial["account_version"]
        response = self.client.post(url, self.account_data(email=self.a.email, account_version=version))
        self.assertRedirects(response, reverse("admin_panel"))
        event = AuditLog.objects.get(action="admin.user_saved")
        self.assertEqual(event.before["first_name"], "")
        self.assertEqual(event.after["first_name"], "Osoba")
        self.assertFalse(AccountInvitation.objects.exists())

    def test_invitation_views_deny_business_roles_and_csrf(self):
        item = self.queue()
        urls = [
            reverse("account_invitations", args=[self.a.pk]),
            reverse("account_invitation_manage", args=[self.a.pk, item.uuid]),
        ]
        for user in [self.a, self.b, self.ump]:
            self.client.force_login(user)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {"action": "invite"}).status_code, 403)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(urls[0], {"action": "invite"}).status_code, 403)

    def test_duplicate_invitation_is_blocked(self):
        self.queue()
        with self.assertRaises(ValidationError):
            self.queue()
        self.assertEqual(AccountInvitation.objects.count(), 1)

    def test_changed_account_or_office_prevents_welcome_to_old_address(self):
        item = self.queue()
        User.objects.filter(pk=self.a.pk).update(email="changed@test.invalid")
        self.assertEqual(process_invitation(item.pk).status, "CANCELLED")
        self.assertEqual(len(mail.outbox), 0)
        item = self.queue()
        self.a.office.active = False
        self.a.office.save()
        self.assertEqual(process_invitation(item.pk).status, "CANCELLED")
        self.assertEqual(len(mail.outbox), 0)

    def test_content_tampering_is_held_for_review(self):
        item = self.queue()
        AccountInvitation.objects.filter(pk=item.pk).update(body="zmieniona treść")
        self.assertEqual(process_invitation(item.pk).status, "REVIEW_REQUIRED")
        self.assertEqual(len(mail.outbox), 0)

    def test_file_message_contains_login_url_and_no_otp_and_is_sent_once(self):
        item = self.queue()
        with (
            tempfile.TemporaryDirectory() as folder,
            override_settings(
                EMAIL_BACKEND="django.core.mail.backends.filebased.EmailBackend", EMAIL_FILE_PATH=folder
            ),
        ):
            self.assertEqual(process_invitation(item.pk).status, "LOCAL_SAVED")
            process_invitation(item.pk)
            files = list(Path(folder).glob("*.log"))
            self.assertEqual(len(files), 1)
            message = BytesParser(policy=policy.default).parsebytes(files[0].read_bytes())
            self.assertEqual(message["To"], self.a.email)
            self.assertEqual(message["Message-ID"], f"<account-{item.uuid}@dyna-rejestr.local>")
            self.assertIn("/logowanie/", message.get_content())
            self.assertEqual(list(message.iter_attachments()), [])
        self.assertFalse(LoginCode.objects.exists())

    def test_uncertain_smtp_result_never_retries_without_operator_check(self):
        item = self.queue()
        with patch(
            "registry.account_invitations.EmailMessage.send", side_effect=OSError("secret-operator-detail")
        ) as sender:
            process_invitation(item.pk)
            process_invitation(item.pk)
            recover_invitations()
            process_invitation(item.pk)
        sender.assert_called_once()
        item.refresh_from_db()
        self.assertNotIn("secret", item.error)
        with self.assertRaises(ValidationError):
            manage_invitation(self.admin, item.pk, item.updated_at.isoformat(), "retry", "Sprawdzenie")
        self.assertEqual(item.status, "REVIEW_REQUIRED")
        manage_invitation(
            self.admin,
            item.pk,
            item.updated_at.isoformat(),
            "confirm",
            "Sprawdzenie",
            "Operator: wiadomość przyjęta; identyfikator testowy",
            True,
        )
        item.refresh_from_db()
        self.assertEqual(item.status, "CONFIRMED_SENT")
        self.assertEqual(
            AuditLog.objects.get(action="account.invitation_reconciled").after["acknowledged"], True
        )

    def test_proven_not_sent_requeues_same_message_and_stale_review_fails(self):
        item = self.queue()
        AccountInvitation.objects.filter(pk=item.pk).update(status="REVIEW_REQUIRED")
        item.refresh_from_db()
        old = item.updated_at.isoformat()
        manage_invitation(
            self.admin, item.pk, old, "retry", "Sprawdzenie", "Operator nie przyjął wiadomości", True
        )
        with self.assertRaises(ValidationError):
            manage_invitation(self.admin, item.pk, old, "cancel", "Nieaktualny formularz")
        self.assertEqual(AccountInvitation.objects.count(), 1)
        self.assertEqual(process_invitation(item.pk).status, "ACCEPTED")
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(
        LOCAL=False, EMAIL_HOST="", EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend"
    )
    def test_missing_configuration_is_retryable_without_an_attempt(self):
        self.a.office.allowed_domains = ["test.invalid"]
        self.a.office.save()
        item = process_invitation(self.queue().pk)
        self.assertEqual(item.status, "CONFIG_ERROR")
        self.assertEqual(item.attempts, 0)
        manage_invitation(self.admin, item.pk, item.updated_at.isoformat(), "retry", "Dodano SMTP")
        item.refresh_from_db()
        self.assertEqual(item.status, "QUEUED")

    @override_settings(LOCAL=False, EMAIL_HOST="", EMAIL_BACKEND="registry.microsoft_mail.EmailBackend")
    def test_graph_invitation_does_not_require_smtp_and_is_accepted_once(self):
        self.a.office.allowed_domains = ["test.invalid"]
        self.a.office.save()
        with patch("registry.microsoft_mail.validated_credentials"), \
                patch("registry.account_invitations.EmailMessage.send", return_value=1) as sender:
            item = process_invitation(self.queue().pk)
            self.assertEqual(item.status, "ACCEPTED")
            process_invitation(item.pk)
        sender.assert_called_once()
        self.assertEqual(item.attempts, 1)

    def test_new_invitation_form_rejects_changed_account_and_forged_token(self):
        url = reverse("account_invitations", args=[self.a.pk])
        version = self.client.get(url).context["form"].initial["version"]
        User.objects.filter(pk=self.a.pk).update(first_name="Zmiana po podglądzie")
        response = self.client.post(url, {"version": version, "action": "invite", "reason": "Test"})
        self.assertContains(response, "Konto zmieniło się")
        response = self.client.post(url, {"version": version + "x", "action": "invite", "reason": "Test"})
        self.assertContains(response, "Formularz wygasł lub został zmieniony")
        self.assertFalse(AccountInvitation.objects.exists())

    def test_recovery_during_send_does_not_overwrite_uncertain_result(self):
        item = self.queue()

        def interrupted():
            AccountInvitation.objects.filter(pk=item.pk).update(
                claimed_until=timezone.now() - timedelta(seconds=1)
            )
            self.assertEqual(recover_invitations(), 1)
            return 1

        with patch("registry.account_invitations.EmailMessage.send", side_effect=interrupted):
            self.assertEqual(process_invitation(item.pk).status, "REVIEW_REQUIRED")
        process_invitation(item.pk)
        self.assertEqual(AccountInvitation.objects.get(pk=item.pk).attempts, 1)
        self.assertTrue(AuditLog.objects.filter(action="account.invitation_interrupted").exists())


class AccountInvitationStorageTests(TransactionTestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_watch_processes_invitation_once(self):
        item = enqueue_invitation(self.admin, self.a.pk, "Test kolejki")
        with patch(
            "registry.management.commands.process_account_invitations.time.sleep",
            side_effect=KeyboardInterrupt,
        ):
            call_command("process_account_invitations", watch=True, interval=1, stdout=StringIO())
        item.refresh_from_db()
        self.assertEqual(item.status, "ACCEPTED")
        self.assertEqual(len(mail.outbox), 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_enqueue_creates_exactly_one_pending_message(self):
        barrier = Barrier(2)

        def enqueue():
            close_old_connections()
            try:
                barrier.wait(5)
                try:
                    enqueue_invitation(User.objects.get(pk=self.admin.pk), self.a.pk, "Wyścig testowy")
                    return "created"
                except ValidationError:
                    return "duplicate"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(lambda _: enqueue(), range(2))), ["created", "duplicate"])
        self.assertEqual(AccountInvitation.objects.count(), 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_workers_send_only_once(self):
        item = enqueue_invitation(self.admin, self.a.pk, "Wyścig testowy")
        entered, resume = Event(), Event()

        def send():
            entered.set()
            if not resume.wait(5):
                raise TimeoutError("Drugi proces nie zwolnił testu")
            return 1

        def first():
            close_old_connections()
            try:
                return process_invitation(item.pk).status
            finally:
                close_old_connections()

        with patch("registry.account_invitations.EmailMessage.send", side_effect=send) as sender:
            with ThreadPoolExecutor(max_workers=1) as pool:
                task = pool.submit(first)
                try:
                    self.assertTrue(entered.wait(5))
                    self.assertEqual(process_invitation(item.pk).status, "SENDING")
                finally:
                    resume.set()
                self.assertEqual(task.result(5), "ACCEPTED")
        sender.assert_called_once()

    def test_real_backup_restore_holds_pending_invitation(self):
        item = enqueue_invitation(self.admin, self.a.pk, "Kopia testowa")
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            archive, target = folder / "backup.zip", folder / "restored"
            call_command("backup_registry", output=str(archive), stdout=StringIO())
            if connection.vendor == "sqlite":
                import sqlite3

                call_command("restore_registry", str(archive), target=str(target), stdout=StringIO())
                with sqlite3.connect(target / "registry.sqlite3") as restored:
                    status, sha, body = restored.execute(
                        "SELECT status,content_sha256,body FROM registry_accountinvitation"
                    ).fetchone()
                self.assertEqual(status, "REVIEW_REQUIRED")
                self.assertEqual(sha, item.content_sha256)
                self.assertEqual(body, item.body)
            else:
                import uuid

                import psycopg
                from psycopg import sql

                from .postgres_backup import connection_parameters, restore_postgres

                database = "dytest_invite_" + uuid.uuid4().hex
                try:
                    report = restore_postgres(archive, target, database)
                    self.assertEqual(report["account_invitations_held"], 1)
                    with psycopg.connect(**connection_parameters(database)) as restored:
                        status, sha, body = restored.execute(
                            "SELECT status,content_sha256,body FROM registry_accountinvitation"
                        ).fetchone()
                    self.assertEqual(status, "REVIEW_REQUIRED")
                    self.assertEqual(sha, item.content_sha256)
                    self.assertEqual(body, item.body)
                finally:
                    with psycopg.connect(**connection_parameters("postgres"), autocommit=True) as admin:
                        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database)))
