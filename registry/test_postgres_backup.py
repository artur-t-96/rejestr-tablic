"""Prawdziwe pg_dump/pg_restore na odrębnych, fikcyjnych bazach testowych."""

import hashlib
import json
import tempfile
import uuid
import zipfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

import psycopg
from django.contrib.auth.hashers import make_password
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from psycopg import sql

from .edor_delivery import unsent_block_reason
from .integrations import enqueue
from .models import (
    DeliveryEvidence,
    EZDCaseLink,
    EZDIncomingDocument,
    IntegrationJob,
    LoginCode,
    PublicChallenge,
)
from .postgres_backup import (
    backup_postgres,
    connection_parameters,
    database_properties,
    restore_postgres,
    run_tool,
)
from .services import create_request, decide_request, send_request
from .signatures import load_profile, sign_letter, verify_signed_pdf
from .tests import data, fixtures


@skipUnless(
    connection.vendor == "postgresql", "Wymaga rzeczywistej bazy PostgreSQL i narzędzi pg_dump/pg_restore."
)
class PostgresBackupTests(TransactionTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.created = []
        self.admin, self.ump, self.a, self.b = fixtures()
        self.req = create_request(self.a, data())
        send_request(self.a, self.req.uuid)
        decide_request(self.ump, self.req.uuid, True)
        self.letter = self.req.letters.get(kind="APPROVAL")
        self.backup = self.root / "backup.zip"

    def tearDown(self):
        # Tylko losowe bazy utworzone przez ten konkretny test, bez FORCE.
        with psycopg.connect(**connection_parameters("postgres"), autocommit=True) as admin:
            for name in self.created:
                admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        super().tearDown()

    def target(self):
        name = "dytest_restore_" + uuid.uuid4().hex
        self.created.append(name)
        return name, self.root / name

    def rewrite_archive(self, *, manifest_change=None, corrupt_dump=False):
        with zipfile.ZipFile(self.backup) as archive:
            dump = archive.read("database.dump")
            manifest = json.loads(archive.read("manifest.json"))
        if manifest_change:
            manifest_change(manifest)
        if corrupt_dump:
            dump += b"corrupted"
        path = self.root / "modified.zip"
        with zipfile.ZipFile(path, "w") as out:
            out.writestr("database.dump", dump)
            out.writestr("manifest.json", json.dumps(manifest))
        return path

    def test_real_backup_restore_signed_pdf_evidence_queue_sessions_and_counters(self):
        profile = self.root / "signing"
        call_command("create_demo_signing", email=self.ump.email, directory=str(profile), stdout=StringIO())
        with override_settings(SIGNING_CONFIG_FILE=str(profile / "profile.json")):
            signed = sign_letter(self.ump, self.letter, reason="Fikcyjna próba backupu")
            job = enqueue(self.ump, signed, "SMTP")
            job.status = "PROCESSING"
            job.claimed_until = timezone.now() + timedelta(minutes=5)
            job.remote_id = "SYNTHETIC-REMOTE-ID"
            job.result = {"checkpoint": "SYNTHETIC-NOT-SENT"}
            job.save()
            edor = IntegrationJob.objects.create(
                letter=signed,
                provider="EDOR",
                key="EDOR:backup:failed",
                status="CONFIG_ERROR",
                payload=bytes(signed.signed_pdf),
                payload_sha256=hashlib.sha256(bytes(signed.signed_pdf)).hexdigest(),
                result={"steps": {}, "submission_guard_version": 1},
            )
            content = b"SYNTHETIC EVIDENCE; NOT AN OPERATOR PROOF"
            incoming = EZDIncomingDocument.objects.create(
                office=signed.recipient,
                target_hash="a" * 64,
                rpw_number=17,
                rpw_year=2026,
                document_id="SYNTHETIC-DOC",
                version_id="SYNTHETIC-VERSION",
                workspace_id="SYNTHETIC-SPACE",
                letter=signed,
                content=bytes(signed.signed_pdf),
                sha256=signed.signed_sha256,
                status="MATCHED",
            )
            DeliveryEvidence.objects.create(
                job=job,
                remote_id="SYNTHETIC-PROOF",
                kind="TEST",
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
            )
            link = EZDCaseLink.objects.create(
                office=self.ump.office,
                scope_id=self.req.uuid,
                scope_kind="REQUEST",
                state="CREATING",
                title="Test",
                year=timezone.localdate().year,
                target_hash="0" * 64,
            )
            LoginCode.objects.create(
                user=self.a, digest=make_password("123456"), expires_at=timezone.now() + timedelta(minutes=1)
            )
            Session.objects.create(
                session_key="synthetic-session",
                session_data="synthetic",
                expire_date=timezone.now() + timedelta(minutes=1),
            )
            PublicChallenge.objects.create(
                binding="0" * 64, challenge={}, expires_at=timezone.now() + timedelta(minutes=5)
            )
            call_command("backup_registry", output=str(self.backup), stdout=StringIO())
            self.assertEqual(self.backup.stat().st_mode & 0o777, 0o600)
            name, target = self.target()
            call_command(
                "restore_registry",
                str(self.backup),
                target=str(target),
                target_database=name,
                stdout=StringIO(),
            )
            report = json.loads((target / "restore-manifest.json").read_text())
            self.assertEqual((target / "restore-manifest.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(report["jobs_held"], 1)
            with psycopg.connect(**connection_parameters(name)) as restored:
                self.assertEqual(database_properties(restored), report["backup"]["database_properties"])
                self.assertEqual(restored.execute("SELECT COUNT(*) FROM django_session").fetchone()[0], 0)
                self.assertEqual(
                    restored.execute(
                        "SELECT COUNT(*) FROM registry_publicchallenge WHERE consumed_at IS NULL"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    restored.execute("SELECT COUNT(*) FROM registry_logincode WHERE NOT used").fetchone()[0],
                    0,
                )
                state, until, remote, result, payload = restored.execute(
                    "SELECT status,claimed_until,remote_id,result,payload FROM registry_integrationjob WHERE id=%s",
                    [job.pk],
                ).fetchone()
                self.assertEqual(
                    (state, until, remote, result), ("REVIEW_REQUIRED", None, job.remote_id, job.result)
                )
                self.assertEqual(bytes(payload), bytes(signed.signed_pdf))
                incoming_payload, incoming_digest = restored.execute(
                    "SELECT content,sha256 FROM registry_ezdincomingdocument WHERE id=%s", [incoming.pk]
                ).fetchone()
                self.assertEqual(bytes(incoming_payload), bytes(signed.signed_pdf))
                self.assertEqual(incoming_digest, signed.signed_sha256)
                restored_status, restored_result = restored.execute(
                    "SELECT status,result FROM registry_integrationjob WHERE id=%s", [edor.pk]
                ).fetchone()
                edor.status, edor.result = restored_status, restored_result
                self.assertEqual(edor.status, "CONFIG_ERROR")
                self.assertIs(edor.result["restore_requires_reconciliation"], True)
                self.assertIn("Odtworzona kopia", unsent_block_reason(edor))
                original, signed_pdf, number = restored.execute(
                    "SELECT pdf,signed_pdf,number FROM registry_letter WHERE id=%s", [signed.pk]
                ).fetchone()
                self.assertEqual(
                    (bytes(original), bytes(signed_pdf), number),
                    (bytes(signed.pdf), bytes(signed.signed_pdf), signed.number),
                )
                self.assertTrue(
                    verify_signed_pdf(bytes(signed_pdf), bytes(original), load_profile(self.ump.office_id))[
                        "signatures"
                    ][0]["intact"]
                )
                self.assertEqual(
                    bytes(restored.execute("SELECT content FROM registry_deliveryevidence").fetchone()[0]),
                    content,
                )
                self.assertEqual(
                    restored.execute(
                        "SELECT state FROM registry_ezdcaselink WHERE id=%s", [link.pk]
                    ).fetchone()[0],
                    "REVIEW_REQUIRED",
                )
            # Źródłowy default nie jest przełączany. Kontrolujemy watermark
            # i identyfikator bezpośrednio w odrębnej bazie odtworzenia.
            with psycopg.connect(**connection_parameters(name)) as restored:
                self.assertEqual(
                    restored.execute(
                        "SELECT last_value FROM registry_numbersequence WHERE scope='REQUEST' AND year=%s",
                        [self.req.reference_year],
                    ).fetchone()[0],
                    self.req.reference_ordinal,
                )
                self.assertEqual(
                    restored.execute(
                        "SELECT reference_number FROM registry_request WHERE id=%s", [self.req.pk]
                    ).fetchone()[0],
                    self.req.reference,
                )
        job.refresh_from_db()
        self.assertEqual(job.status, "PROCESSING")
        self.assertTrue(Session.objects.filter(session_key="synthetic-session").exists())

    def test_tampered_archive_and_existing_target_never_overwrite_source(self):
        backup_postgres(self.backup)
        corrupt = self.rewrite_archive(corrupt_dump=True)
        name, target = self.target()
        with self.assertRaisesMessage(CommandError, "suma kontrolna"):
            restore_postgres(corrupt, target, name)
        with psycopg.connect(**connection_parameters("postgres")) as admin:
            self.assertIsNone(admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", [name]).fetchone())
        with self.assertRaisesMessage(CommandError, "odrębnej nowej"):
            restore_postgres(self.backup, target, connection.settings_dict["NAME"])
        name, target = self.target()
        restore_postgres(self.backup, target, name)
        with self.assertRaisesMessage(CommandError, "już istnieje"):
            restore_postgres(self.backup, self.root / "another-target", name)

    def test_manifest_mismatch_quarantines_only_new_database(self):
        backup_postgres(self.backup)
        modified = self.rewrite_archive(manifest_change=lambda m: m["counts"].update(registry_request=999))
        name, target = self.target()
        with self.assertRaisesMessage(CommandError, "nie odpowiadają manifestowi"):
            restore_postgres(modified, target, name)
        self.assertFalse(target.exists())
        with psycopg.connect(**connection_parameters("postgres")) as admin:
            self.assertFalse(
                admin.execute("SELECT datallowconn FROM pg_database WHERE datname=%s", [name]).fetchone()[0]
            )
            self.assertTrue(
                admin.execute(
                    "SELECT datallowconn FROM pg_database WHERE datname=%s",
                    [connection.settings_dict["NAME"]],
                ).fetchone()[0]
            )

    def test_snapshot_counts_and_dump_exclude_concurrent_committed_request(self):
        original = run_tool

        def during_dump(name, arguments, parameters, directory=None):
            if name == "pg_dump" and "--format=custom" in arguments:
                create_request(self.a, data("P1TEST"))
            return original(name, arguments, parameters, directory)

        with patch("registry.postgres_backup.run_tool", side_effect=during_dump):
            manifest = backup_postgres(self.backup)
        self.assertEqual(manifest["counts"]["registry_request"], 1)
        name, target = self.target()
        restore_postgres(self.backup, target, name)
        with psycopg.connect(**connection_parameters(name)) as restored:
            self.assertEqual(restored.execute("SELECT COUNT(*) FROM registry_request").fetchone()[0], 1)
        from .models import Request

        self.assertEqual(Request.objects.count(), 2)

    def test_corrupt_source_document_and_rewound_counter_prevent_backup(self):
        from .models import Letter, NumberSequence

        Letter.objects.filter(pk=self.letter.pk).update(pdf=b"broken")
        with self.assertRaisesMessage(CommandError, "Uszkodzony dokument"):
            backup_postgres(self.backup)
        self.assertFalse(self.backup.exists())
        Letter.objects.filter(pk=self.letter.pk).update(pdf=self.letter.pdf)
        NumberSequence.objects.filter(scope="REQUEST").update(last_value=0)
        with self.assertRaisesMessage(CommandError, "cofnięte"):
            backup_postgres(self.backup)
        self.assertFalse(self.backup.exists())

    def test_existing_backup_is_preserved_and_missing_tool_does_not_publish(self):
        self.backup.write_bytes(b"keep")
        with self.assertRaisesMessage(CommandError, "już istnieje"):
            backup_postgres(self.backup)
        self.assertEqual(self.backup.read_bytes(), b"keep")
        other = self.root / "missing-tool.zip"
        with self.assertRaisesMessage(CommandError, "Nie znaleziono narzędzia"):
            backup_postgres(other, str(self.root / "missing-tools"))
        self.assertFalse(other.exists())
