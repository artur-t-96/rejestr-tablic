import hashlib
import json
import tempfile
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .decision_notifications import enqueue_decision_notice
from .forms import DecisionForm, PoolForm
from .integrations import process_job, recover_stale_jobs
from .models import AuditLog, IntegrationJob, Letter, Pool
from .services import create_request, decide_request, issue_slot, send_request
from .tests import fixtures


def pending_request(author, kind="III"):
    req = create_request(
        author,
        {
            "kind": kind,
            "case_number": "TEST/NOTICE/1",
            "count": 2,
            "justification": "Fikcyjne zapotrzebowanie",
            "station": "Stacja Fikcyjna",
        },
    )
    send_request(author, req.uuid)
    return req


def period_data():
    return {
        "prefix": "P0",
        "start": 1,
        "end": 2,
        "valid_from": timezone.localdate(),
        "valid_until": timezone.localdate() + timedelta(days=30),
    }


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class DecisionNoticeTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.author, self.other = fixtures()
        self.req = pending_request(self.author)

    def approve(self):
        decide_request(self.ump, self.req.uuid, True, pool_data=period_data())
        return IntegrationJob.objects.get(operation="DECISION_NOTICE")

    @override_settings(EMAIL_HOST="", EMAIL_BACKEND="registry.microsoft_mail.EmailBackend")
    def test_graph_notice_records_actual_transport_and_no_delivery_claim(self):
        job = self.approve()
        with patch("registry.microsoft_mail.validated_credentials"), \
                patch("registry.decision_notifications.EmailMessage.send", return_value=1) as sender:
            result = process_job(job)
            process_job(job)
        sender.assert_called_once()
        self.assertEqual(result.status, "ACCEPTED")
        self.assertEqual(result.result, {"transport": "Microsoft Graph", "delivery_confirmed": False})

    def test_approval_queues_once_atomically_without_sending_email_in_request(self):
        job = self.approve()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(job.status, "QUEUED")
        self.assertEqual(job.letter.kind, "POOL")
        self.assertEqual(job.letter.request_id, self.req.pk)
        repeated = enqueue_decision_notice(self.ump, self.req, job.letter)
        self.assertEqual(repeated.pk, job.pk)
        with self.assertRaises(ValidationError):
            decide_request(self.ump, self.req.uuid, True, pool_data=period_data())
        self.assertEqual(IntegrationJob.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="integration.queued").count(), 1)

    def test_worker_notifies_author_using_immutable_snapshot_and_no_pdf_or_private_details(self):
        self.author.office.email = "office@test.invalid"
        self.author.office.save()
        job = self.approve()
        snapshot = json.loads(bytes(job.payload))
        self.author.email = "changed@test.invalid"
        self.author.save()
        job.letter.body = "Zmieniona treść zawierająca dane osobowe"
        job.letter.save()
        result = process_job(job)
        self.assertEqual(result.status, "ACCEPTED")  # locmem, nie dowód SMTP
        message = mail.outbox[0]
        self.assertEqual(message.to, ["a@test.invalid"])
        self.assertEqual(message.subject, snapshot["subject"])
        self.assertEqual(message.body, snapshot["body"])
        self.assertIn(str(self.req.uuid), message.body)
        self.assertIn("po zalogowaniu", message.body)
        self.assertNotIn("Stacja Fikcyjna", message.body)
        self.assertNotIn("Zmieniona treść", message.body)
        self.assertEqual(message.attachments, [])
        self.assertFalse(result.result["delivery_confirmed"])
        process_job(result)
        self.assertEqual(len(mail.outbox), 1)

    def test_rejection_notifies_author_and_does_not_require_pool_dates(self):
        decide_request(self.ump, self.req.uuid, False, reason="Fikcyjna odmowa")
        job = IntegrationJob.objects.get()
        self.assertEqual(job.letter.kind, "REJECTION")
        self.assertFalse(Pool.objects.exists())
        process_job(job)
        self.assertIn("Odrzucony", mail.outbox[0].body)
        self.assertNotIn("Fikcyjna odmowa", mail.outbox[0].body)

    def test_outbox_failure_rolls_back_entire_decision_pool_letter_and_audit(self):
        letters, audits = Letter.objects.count(), AuditLog.objects.count()
        with patch("registry.decision_notifications.audit", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError):
                self.approve()
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, "SENT")
        self.assertFalse(Pool.objects.exists())
        self.assertFalse(IntegrationJob.objects.exists())
        self.assertEqual(Letter.objects.count(), letters)
        self.assertEqual(AuditLog.objects.count(), audits)

    def test_missing_and_reversed_periods_leave_request_pending_and_no_notice(self):
        for end in (None, timezone.localdate() - timedelta(days=1)):
            with self.subTest(end=end), self.assertRaises(ValidationError):
                decide_request(self.ump, self.req.uuid, True, pool_data={**period_data(), "valid_until": end})
            self.req.refresh_from_db()
            self.assertEqual(self.req.status, "SENT")
            self.assertFalse(Pool.objects.exists())
            self.assertFalse(IntegrationJob.objects.exists())

    def test_iii_database_constraint_cannot_be_bypassed_by_update(self):
        job = self.approve()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Pool.objects.filter(request=self.req).update(valid_until=None)
        self.assertEqual(job.letter.pool.valid_until, period_data()["valid_until"])

    def test_both_validity_boundaries_are_inclusive_and_outside_dates_block_issue(self):
        self.approve()
        pool = Pool.objects.get(request=self.req)
        first, second = list(pool.slots.all())
        for day in (pool.valid_from - timedelta(days=1), pool.valid_until + timedelta(days=1)):
            with patch("registry.services.timezone.localdate", return_value=day):
                with self.assertRaises(ValidationError):
                    issue_slot(self.author, pool.uuid, first.pk, "TEST/OUTSIDE")
        with patch("registry.services.timezone.localdate", return_value=pool.valid_from):
            issue_slot(self.author, pool.uuid, first.pk, "TEST/FIRST")
        with patch("registry.services.timezone.localdate", return_value=pool.valid_until):
            issue_slot(self.author, pool.uuid, second.pk, "TEST/LAST")
        self.assertEqual(pool.used, 2)

    def test_request_page_explains_local_notice_and_foreign_office_cannot_read_it(self):
        job = self.approve()
        url = reverse("request_detail", args=[self.req.uuid])
        self.client.force_login(self.author)
        self.assertContains(self.client.get(url), "Powiadomienie autora o decyzji")
        self.assertContains(self.client.get(url), "W kolejce")
        with (
            tempfile.TemporaryDirectory() as temp,
            override_settings(
                EMAIL_BACKEND="django.core.mail.backends.filebased.EmailBackend", EMAIL_FILE_PATH=temp
            ),
        ):
            self.assertEqual(process_job(job).status, "LOCAL_SAVED")
        self.assertContains(self.client.get(url), "bez wysyłki do adresata")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertNotContains(self.client.get(reverse("integrations")), job.letter.number)

    def test_unknown_transport_result_and_interrupted_worker_never_retry_automatically(self):
        job = self.approve()
        with patch(
            "registry.decision_notifications.EmailMessage.send", side_effect=OSError("synthetic timeout")
        ) as send:
            self.assertEqual(process_job(job).status, "REVIEW_REQUIRED")
            process_job(job)
            self.assertEqual(send.call_count, 1)
        IntegrationJob.objects.filter(pk=job.pk).update(
            status="PROCESSING", claimed_until=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(recover_stale_jobs(), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, "REVIEW_REQUIRED")
        process_job(job)
        self.assertEqual(len(mail.outbox), 0)

    def test_corrupt_or_missing_snapshot_does_not_fall_back_to_sending_letter_pdf(self):
        job = self.approve()
        for payload in (b"tampered", None):
            IntegrationJob.objects.filter(pk=job.pk).update(status="QUEUED", payload=payload)
            self.assertEqual(process_job(job).status, "REVIEW_REQUIRED")
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_snapshot_header_is_diagnosed_before_transport(self):
        job = self.approve()
        message = json.loads(bytes(job.payload))
        message["to"] = "a@test.invalid\nBcc: other@test.invalid"
        payload = json.dumps(message).encode()
        IntegrationJob.objects.filter(pk=job.pk).update(
            payload=payload, payload_sha256=hashlib.sha256(payload).hexdigest()
        )
        self.assertEqual(process_job(job).status, "CONFIG_ERROR")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST="")
    def test_unconfigured_smtp_preserves_decision_and_marks_notice_configuration_error(self):
        job = self.approve()
        self.assertEqual(process_job(job).status, "CONFIG_ERROR")
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, "APPROVED")

    def test_form_reports_end_date_error_on_field_and_rejection_and_module_two_still_work(self):
        values = {**period_data(), "valid_until": "", "decision": "approve"}
        form = DecisionForm(values, kind="III")
        self.assertFalse(form.is_valid())
        self.assertIn("valid_until", form.errors)
        self.assertTrue(DecisionForm({"decision": "reject", "reason": "Odmowa"}, kind="III").is_valid())
        self.assertTrue(DecisionForm(values, kind="II").is_valid())
        self.assertFalse(PoolForm({**values, "kind": "III", "office": "a"}).is_valid())
        self.client.force_login(self.ump)
        page = self.client.post(reverse("request_detail", args=[self.req.uuid]), values)
        self.assertContains(page, "Podaj termin końca puli modułu III.")
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, "SENT")
        self.assertFalse(IntegrationJob.objects.exists())


class NoticeBackupTests(TransactionTestCase):
    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_watch_processes_notice_once_and_leaves_other_operations_queued(self):
        _, ump, author, _ = fixtures()
        req = pending_request(author)
        decide_request(ump, req.uuid, True, pool_data=period_data())
        job = IntegrationJob.objects.get(operation="DECISION_NOTICE")
        other = IntegrationJob.objects.create(
            key="SMTP:other:SEND",
            provider="SMTP",
            operation="SEND",
            letter=job.letter,
            payload=bytes(job.letter.pdf),
            payload_sha256=job.letter.sha256,
        )
        output = StringIO()
        with patch(
            "registry.management.commands.process_integrations.time.sleep", side_effect=KeyboardInterrupt
        ):
            call_command(
                "process_integrations",
                watch=True,
                interval=1,
                provider="SMTP",
                operation="DECISION_NOTICE",
                stdout=output,
            )
        job.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(job.status, "ACCEPTED")
        self.assertEqual(other.status, "QUEUED")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Proces kolejki zatrzymany.", output.getvalue())

    def test_real_file_message_backup_and_restore_quarantine(self):
        _, ump, author, _ = fixtures()
        req = pending_request(author)
        decide_request(ump, req.uuid, True, pool_data=period_data())
        job = IntegrationJob.objects.get()
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            backup, target = folder / "notice.zip", folder / "restored"
            call_command("backup_registry", output=str(backup), stdout=StringIO())
            with override_settings(
                EMAIL_BACKEND="django.core.mail.backends.filebased.EmailBackend",
                EMAIL_FILE_PATH=folder / "mail",
            ):
                self.assertEqual(process_job(job).status, "LOCAL_SAVED")
                messages = list((folder / "mail").glob("*.log"))
                self.assertEqual(len(messages), 1)
                message = BytesParser(policy=policy.default).parsebytes(messages[0].read_bytes())
                self.assertEqual(message["To"], author.email)
                self.assertEqual(message["Message-ID"], f"<{job.uuid}@dyna-rejestr.local>")
                self.assertEqual(list(message.iter_attachments()), [])
                self.assertIn(str(req.uuid), message.get_content())
            from ._backup_test_helpers import restored_database

            with restored_database(backup, target) as (db, _):
                status, payload, sha = db.execute(
                    "SELECT status,payload,payload_sha256 FROM registry_integrationjob WHERE operation='DECISION_NOTICE'"
                ).fetchone()
            self.assertEqual(status, "REVIEW_REQUIRED")
            self.assertEqual(hashlib.sha256(payload).hexdigest(), sha)
            self.assertEqual(json.loads(payload)["to"], author.email)


class FinitePeriodMigrationTests(TransactionTestCase):
    def test_legacy_missing_period_stops_migration_without_guessing_or_deleting_data(self):
        old_target = [("registry", "0008_refresh_builtin_templates")]
        target = [("registry", "0009_require_finite_module_three_period")]
        executor = MigrationExecutor(connection)
        executor.migrate(old_target)
        old_apps = executor.loader.project_state(old_target).apps
        OldOffice = old_apps.get_model("registry", "Office")
        OldPool = old_apps.get_model("registry", "Pool")
        office = OldOffice.objects.create(id="legacy", name="Fikcyjny urząd", kind="COUNTY", city="Test")
        pool = OldPool.objects.create(
            kind="III",
            office=office,
            prefix="P0",
            start=1,
            end=2,
            valid_from=timezone.localdate(),
            valid_until=None,
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "Nie przypisano automatycznie dat"):
                MigrationExecutor(connection).migrate(target)
            pool.refresh_from_db()
            self.assertIsNone(pool.valid_until)
            self.assertEqual(OldPool.objects.count(), 1)
        finally:
            # Tylko fikcyjny rekord testu; nie jest to reguła uzupełniania danych urzędu.
            OldPool.objects.filter(pk=pool.pk).update(valid_until=timezone.localdate() + timedelta(days=30))
            MigrationExecutor(connection).migrate(target)
        try:
            with self.assertRaises(IntegrityError), transaction.atomic():
                Pool.objects.filter(pk=pool.pk).update(valid_until=None)
        finally:
            # Kolejne testy na tej bazie potrzebują aktualnego schematu, nie stanu 0009.
            latest = MigrationExecutor(connection).loader.graph.leaf_nodes("registry")
            MigrationExecutor(connection).migrate(latest)
