import hashlib
import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase

from ._backup_test_helpers import restored_database
from .edor_delivery import unsent_block_reason
from .integrations import enqueue
from .models import DeliveryEvidence, IntegrationJob, PublicChallenge
from .services import create_request
from .tests import data, fixtures


class IntegrationRestoreTests(TransactionTestCase):
    def test_restored_queue_never_resends_a_snapshot_job_automatically(self):
        _, _, county, _ = fixtures()
        letter = create_request(county, data()).letters.get()
        from datetime import timedelta

        from django.utils import timezone

        PublicChallenge.objects.create(
            binding="0" * 64, challenge={}, expires_at=timezone.now() + timedelta(minutes=5)
        )
        job = enqueue(county, letter, "SMTP")
        edor = IntegrationJob.objects.create(
            letter=letter,
            provider="EDOR",
            key="EDOR:restore:SEND",
            status="MONITORING",
            payload=bytes(letter.pdf),
            payload_sha256=hashlib.sha256(bytes(letter.pdf)).hexdigest(),
            result={"steps": {"send": {"state": "COMPLETED", "output": {"task_id": "synthetic-task"}}}},
        )
        proof = DeliveryEvidence.objects.create(
            job=edor,
            remote_id="synthetic-proof",
            kind="A.1",
            content=b"<FikcyjnyDowod/>",
            sha256=hashlib.sha256(b"<FikcyjnyDowod/>").hexdigest(),
        )
        failed = IntegrationJob.objects.create(
            letter=letter,
            provider="EDOR",
            key="EDOR:restore:failed",
            status="CONFIG_ERROR",
            payload=bytes(letter.pdf),
            payload_sha256=hashlib.sha256(bytes(letter.pdf)).hexdigest(),
            result={"steps": {}, "submission_guard_version": 1},
        )
        with tempfile.TemporaryDirectory() as temp:
            backup = Path(temp) / "snapshot.zip"
            target = Path(temp) / "restored"
            call_command("backup_registry", output=str(backup), stdout=StringIO())
            # Po zrobieniu kopii operator mógł już przyjąć tę operację.
            IntegrationJob.objects.filter(pk=job.pk).update(status="ACCEPTED")
            # Dawny CONFIG_ERROR mógł już zostać naprawiony i wysłany po kopii.
            IntegrationJob.objects.filter(pk=failed.pk).update(status="MONITORING")
            with restored_database(backup, target) as (db, placeholder):
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM registry_publicchallenge WHERE consumed_at IS NULL"
                    ).fetchone()[0],
                    0,
                )
                rows = db.execute(
                    "SELECT status,payload,payload_sha256 FROM registry_integrationjob"
                ).fetchall()
                self.assertEqual(len(rows), 3)
                for status, payload, sha in rows:
                    self.assertIn(status, {"REVIEW_REQUIRED", "CONFIG_ERROR"})
                    self.assertEqual(hashlib.sha256(payload).hexdigest(), sha)
                restored_status, result = db.execute(
                    f"SELECT status,result FROM registry_integrationjob WHERE id={placeholder}", [failed.pk]
                ).fetchone()
                self.assertEqual(restored_status, "CONFIG_ERROR")
                failed.status = restored_status
                failed.result = json.loads(result) if isinstance(result, str) else result
                self.assertIs(failed.result["restore_requires_reconciliation"], True)
                self.assertIn("Odtworzona kopia", unsent_block_reason(failed))
                payload, sha = db.execute("SELECT content,sha256 FROM registry_deliveryevidence").fetchone()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), sha)
        job.refresh_from_db()
        self.assertEqual(job.status, "ACCEPTED")
        edor.refresh_from_db()
        self.assertEqual(edor.status, "MONITORING")
        failed.refresh_from_db()
        self.assertEqual(failed.status, "MONITORING")
        self.assertNotIn("restore_requires_reconciliation", failed.result)
        self.assertEqual(bytes(proof.content), b"<FikcyjnyDowod/>")

    def test_backup_rejects_corrupted_evidence_and_queue_payload(self):
        _, _, county, _ = fixtures()
        letter = create_request(county, data()).letters.get()
        job = enqueue(county, letter, "SMTP")
        proof = DeliveryEvidence.objects.create(
            job=job,
            remote_id="test",
            kind="A.1",
            content=b"bad",
            sha256=hashlib.sha256(b"original").hexdigest(),
        )
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(CommandError):
                call_command("backup_registry", output=str(Path(temp) / "bad-proof.zip"), stdout=StringIO())
            proof.content = b"original"
            proof.save()
            IntegrationJob.objects.filter(pk=job.pk).update(payload=b"tampered")
            with self.assertRaises(CommandError):
                call_command("backup_registry", output=str(Path(temp) / "bad-payload.zip"), stdout=StringIO())
