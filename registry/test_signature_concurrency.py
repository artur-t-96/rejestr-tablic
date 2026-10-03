"""Real PostgreSQL locks and PAdES on fictional documents, without operator I/O."""

import email
import hashlib
import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from . import edor_delivery, integrations, signatures
from .integrations import enqueue, enqueue_ezd, process_job
from .models import AuditLog, IntegrationJob, Letter, User
from .services import create_request
from .signatures import load_profile, local_sign, sign_letter, verify_signed_pdf
from .tests import data, fixtures


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL row locks.")
class SignatureConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.admin, self.ump, self.actor, self.other = fixtures()
        self.actor.office.ade = "AE:PL-11111-11111-AAAAA-11"
        self.actor.office.save(update_fields=["ade"])
        self.ump.office.ade = "AE:PL-22222-22222-BBBBB-22"
        self.ump.office.email = "ump@test.invalid"
        self.ump.office.save(update_fields=["ade", "email"])
        self.letter = create_request(self.actor, data()).letters.get()
        self.original = bytes(self.letter.pdf)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.mail_dir = root / "mail"
        signing = root / "signing"
        call_command("create_demo_signing", email=self.actor.email, directory=str(signing), stdout=StringIO())
        key_file = root / "ezd-key"
        key_file.write_text("fictional-key-not-an-operator-credential")
        key_file.chmod(0o600)
        ezd = {
            "api_url": "https://api.ezd.test.invalid",
            "token_url": "https://sso.ezd.test.invalid/connect/token",
            "web_host": "web.ezd.test.invalid",
            "pid": "fictional-office",
            "aki": "fictional-key-id",
            "sid": "fictional-space",
            "api_key_file": str(key_file),
        }
        edor = {
            "environment": "INT",
            "sender_ade": self.actor.office.ade,
            "system_name": "DYNA.TEST",
            "ua_url": "https://ua.test.invalid/api/v3",
            "se_url": "https://se.test.invalid/api/se/v4",
            "token_url": "https://iam.test.invalid/auth/realms/EDOR/protocol/openid-connect/token",
            "audience": "https://iam.test.invalid/auth/realms/EDOR",
            "private_key_file": str(signing / "key.pem"),
            "certificate_file": str(signing / "certificate.pem"),
        }
        config_paths = {}
        for name, profile in (("ezd", ezd), ("edor", edor)):
            path = root / f"{name}.json"
            path.write_text(json.dumps({"offices": {self.actor.office_id: profile}}))
            path.chmod(0o600)
            config_paths[name] = str(path)
        settings = self.settings(
            LOCAL=True,
            SIGNING_CONFIG_FILE=str(signing / "profile.json"),
            EZDRP_CONFIG_FILE=config_paths["ezd"],
            EDOR_CONFIG_FILE=config_paths["edor"],
        )
        settings.enable()
        self.addCleanup(settings.disable)
        self.payload = local_sign(self.original, load_profile(self.actor.office_id), reason="Fictional race")

    def work(self, name, action, pids, started):
        close_old_connections()
        try:
            actor = User.objects.get(pk=self.actor.pk)
            # Both operations start with their own stale instance, before waiting.
            letter = Letter.objects.get(pk=self.letter.pk)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pids[name] = cursor.fetchone()[0]
            started.set()
            try:
                return "accepted", action(actor, letter)
            except ValidationError as exc:
                return "rejected", exc
        finally:
            connection.close()

    def sign(self, actor, letter):
        return sign_letter(actor, letter, uploaded=self.payload, reason="Fictional concurrent signature")

    def queue(self, provider):
        if provider == "EZD":
            return lambda actor, letter: enqueue_ezd(
                actor, letter, case_id="fictional-case", reason="Fictional association"
            )
        return lambda actor, letter: enqueue(actor, letter, provider)

    def wait_for_lock(self, pid, blocker):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT wait_event_type, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid=%s",
                    [pid],
                )
                row = cursor.fetchone()
            if row and row[0] == "Lock" and blocker in row[1]:
                return
            time.sleep(0.02)
        self.fail("The second PostgreSQL transaction did not wait on the first transaction's lock.")

    def ordered_race(self, provider, *, signing_first, rollback=False):
        held, release, started_first, started_second = Event(), Event(), Event(), Event()
        pids = {}
        queue = self.queue(provider)
        first_action, second_action = (self.sign, queue) if signing_first else (queue, self.sign)
        module = signatures if signing_first else edor_delivery if provider == "EDOR" else integrations
        action = "letter.signed" if signing_first else "integration.queued"
        original_audit = module.audit

        def pause_before_commit(actor, name, obj, *args, **kwargs):
            if name == action and obj.pk == self.letter.pk:
                held.set()
                if not release.wait(8):
                    raise TimeoutError("First transaction was not released.")
                if rollback:
                    raise ValidationError("Fictional failure before commit")
            return original_audit(actor, name, obj, *args, **kwargs)

        with patch.object(module, "audit", side_effect=pause_before_commit), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.work, "first", first_action, pids, started_first)
            try:
                self.assertTrue(held.wait(5), "First operation did not reach the commit boundary.")
                second = pool.submit(self.work, "second", second_action, pids, started_second)
                self.assertTrue(started_second.wait(5))
                self.assertNotEqual(pids["first"], pids["second"])
                self.wait_for_lock(pids["second"], pids["first"])
            finally:
                release.set()
            first_result = first.result(timeout=5)
            second_result = second.result(timeout=5)

        current = Letter.objects.get(pk=self.letter.pk)
        self.assertEqual(bytes(current.pdf), self.original)
        if rollback:
            self.assertEqual(first_result[0], "rejected")
            self.assertEqual(second_result[0], "accepted")
        else:
            self.assertEqual(first_result[0], "accepted")
            self.assertEqual(second_result[0], "accepted" if signing_first else "rejected")
        if signing_first:
            job = IntegrationJob.objects.get(letter=current)
            expected = self.original if rollback else self.payload
            self.assertEqual(bytes(job.payload), expected)
            self.assertEqual(job.payload_sha256, hashlib.sha256(expected).hexdigest())
            self.assertEqual(job.provider, provider)
            self.assertEqual(AuditLog.objects.filter(action="integration.queued").count(), 1)
            self.assertEqual(AuditLog.objects.filter(action="letter.signed").count(), 0 if rollback else 1)
            if rollback:
                self.assertIsNone(current.signed_pdf)
            else:
                self.assertEqual(bytes(current.signed_pdf), self.payload)
                self.assertEqual(current.signature_status, "TEST_SIGNED")
        elif rollback:
            self.assertFalse(IntegrationJob.objects.filter(letter=current).exists())
            self.assertEqual(bytes(current.signed_pdf), self.payload)
            self.assertEqual(AuditLog.objects.filter(action="letter.signed").count(), 1)
            self.assertFalse(AuditLog.objects.filter(action="integration.queued").exists())
        else:
            self.assertIsNone(current.signed_pdf)
            job = IntegrationJob.objects.get(letter=current)
            self.assertEqual(bytes(job.payload), self.original)
            self.assertEqual(job.payload_sha256, current.sha256)
            self.assertFalse(AuditLog.objects.filter(action="letter.signed").exists())
            self.assertEqual(AuditLog.objects.filter(action="integration.queued").count(), 1)
            self.assertIn("Stan pisma zmienił się", str(second_result[1]))

    def test_smtp_waits_for_signature_commit_and_queues_signed_bytes(self):
        self.ordered_race("SMTP", signing_first=True)
        # Execute the real worker and file mail backend, then inspect the MIME
        # attachment. This proves more than equality of a row in the queue.
        job = IntegrationJob.objects.get(letter=self.letter)
        with self.settings(
            EMAIL_BACKEND="django.core.mail.backends.filebased.EmailBackend",
            EMAIL_FILE_PATH=self.mail_dir,
        ):
            self.assertEqual(process_job(job).status, "LOCAL_SAVED")
            self.assertEqual(process_job(job).status, "LOCAL_SAVED")
        files = list(self.mail_dir.glob("*.log"))
        self.assertEqual(len(files), 1)
        message = email.message_from_bytes(files[0].read_bytes())
        attachments = [part for part in message.walk() if part.get_content_type() == "application/pdf"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].get_payload(decode=True), self.payload)
        self.assertEqual(message["To"], "ump@test.invalid")
        self.assertEqual(AuditLog.objects.filter(action="integration.result").count(), 1)

    def test_ezd_waits_for_signature_commit_and_queues_signed_bytes(self):
        self.ordered_race("EZD", signing_first=True)

    def test_edor_waits_for_signature_commit_and_queues_signed_bytes(self):
        self.ordered_race("EDOR", signing_first=True)

    def test_signature_waits_for_smtp_commit_and_cannot_change_queued_original(self):
        self.ordered_race("SMTP", signing_first=False)

    def test_signature_waits_for_ezd_commit_and_cannot_change_queued_original(self):
        self.ordered_race("EZD", signing_first=False)

    def test_signature_waits_for_edor_commit_and_cannot_change_queued_original(self):
        self.ordered_race("EDOR", signing_first=False)

    def test_signature_rollback_allows_waiting_queue_to_use_original(self):
        self.ordered_race("SMTP", signing_first=True, rollback=True)

    def test_queue_rollback_allows_waiting_signature_to_commit(self):
        self.ordered_race("SMTP", signing_first=False, rollback=True)

    def test_two_verified_signatures_commit_only_one_and_preserve_archive(self):
        barrier = Barrier(2)
        held, release = Event(), Event()
        pids, winner = {}, []

        def both_verified(*args, **kwargs):
            report = verify_signed_pdf(*args, **kwargs)
            barrier.wait(timeout=5)
            return report

        def pause_sign_audit(actor, name, obj, *args, **kwargs):
            if name == "letter.signed":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    winner.append(cursor.fetchone()[0])
                held.set()
                if not release.wait(8):
                    raise TimeoutError("Signature transaction was not released.")
            return integrations.audit(actor, name, obj, *args, **kwargs)

        with (
            patch.object(signatures, "verify_signed_pdf", side_effect=both_verified),
            patch.object(signatures, "audit", side_effect=pause_sign_audit),
            ThreadPoolExecutor(2) as pool,
        ):
            first = pool.submit(self.work, "one", self.sign, pids, Event())
            second = pool.submit(self.work, "two", self.sign, pids, Event())
            try:
                self.assertTrue(held.wait(5))
                waiter = next(pid for pid in pids.values() if pid != winner[0])
                self.wait_for_lock(waiter, winner[0])
            finally:
                release.set()
            results = [first.result(timeout=5), second.result(timeout=5)]
        self.assertEqual(sorted(result[0] for result in results), ["accepted", "rejected"])
        self.letter.refresh_from_db()
        self.assertEqual(bytes(self.letter.pdf), self.original)
        self.assertEqual(bytes(self.letter.signed_pdf), self.payload)
        self.assertEqual(AuditLog.objects.filter(action="letter.signed").count(), 1)
        self.assertEqual(self.letter.signature_report["qualification"], "NOT_ASSESSED")
        self.assertFalse(IntegrationJob.objects.exists())

    def test_slow_crypto_holds_no_transaction_and_queue_can_commit(self):
        preparing, release = Event(), Event()
        pids = {}

        def slow_crypto(*args, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            preparing.set()
            if not release.wait(8):
                raise TimeoutError("Cryptographic preparation was not released.")
            return local_sign(*args, **kwargs)

        def sign_locally(actor, letter):
            return sign_letter(actor, letter, reason="Fictional slow signature")

        with patch.object(signatures, "local_sign", side_effect=slow_crypto), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.work, "signer", sign_locally, pids, Event())
            try:
                self.assertTrue(preparing.wait(5))
                second = pool.submit(self.work, "queue", self.queue("SMTP"), pids, Event())
                result = second.result(timeout=3)
                self.assertEqual(result[0], "accepted")
            finally:
                release.set()
            self.assertEqual(first.result(timeout=5)[0], "rejected")
        self.letter.refresh_from_db()
        self.assertIsNone(self.letter.signed_pdf)
        self.assertEqual(bytes(IntegrationJob.objects.get().payload), self.original)
        self.assertFalse(AuditLog.objects.filter(action="letter.signed").exists())
