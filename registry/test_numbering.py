import hashlib
import sqlite3
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from datetime import timezone as datetime_timezone
from io import BytesIO, StringIO
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from pypdf import PdfReader

from .models import Letter, NumberSequence, Request, User
from .services import create_letter_revision, create_request, decide_request, make_letter, send_request
from .tests import data, fixtures


class NumberingTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_sequential_letter_numbers_per_office_across_document_kinds(self):
        year = timezone.localdate().year
        first = create_request(self.a, data())
        second = create_request(self.a, data("P1TEST"))
        other = create_request(self.b, data("P2TEST"))
        self.assertEqual(first.letters.get().number, f"DRT/a/{year}/000001")
        self.assertEqual(second.letters.get().number, f"DRT/a/{year}/000002")
        self.assertEqual(other.letters.get().number, f"DRT/b/{year}/000001")
        self.assertEqual(first.reference, f"W/{year}/00001")
        self.assertEqual(second.reference, f"W/{year}/00002")
        self.assertEqual(other.reference, f"W/{year}/00003")
        send_request(self.a, first.uuid)
        decide_request(self.ump, first.uuid, True)
        send_request(self.a, second.uuid)
        decide_request(self.ump, second.uuid, False, reason="Test odmowy")
        self.assertEqual(first.letters.get(kind="APPROVAL").number, f"DRT/ump/{year}/000001")
        self.assertEqual(second.letters.get(kind="REJECTION").number, f"DRT/ump/{year}/000002")
        for letter in Letter.objects.all():
            text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(bytes(letter.pdf))).pages)
            self.assertIn(letter.number, text)
            self.assertIn("Numer systemowy pisma", text)
            self.assertEqual(hashlib.sha256(bytes(letter.pdf)).hexdigest(), letter.sha256)

    def test_new_year_new_sequences_without_changing_previous_numbers(self):
        with patch("registry.numbering.timezone.localdate", return_value=date(2026, 12, 31)):
            old = create_request(self.a, data())
        letter = old.letters.get()
        with patch("registry.numbering.timezone.localdate", return_value=date(2027, 1, 1)):
            new = create_request(self.a, data("P1TEST"))
        self.assertEqual(old.reference, "W/2026/00001")
        self.assertEqual(new.reference, "W/2027/00001")
        old.refresh_from_db()
        self.assertEqual(old.reference, "W/2026/00001")
        letter.refresh_from_db()
        self.assertEqual(letter.number, "DRT/a/2026/000001")
        self.assertEqual(new.letters.get().number, "DRT/a/2027/000001")

    def test_local_new_year_boundary_and_immutable_reference(self):
        # W Warszawie jest już nowy rok, mimo starego roku znacznika UTC.
        with patch(
            "django.utils.timezone.now",
            return_value=datetime(2026, 12, 31, 23, 30, tzinfo=datetime_timezone.utc),
        ):
            req = create_request(self.a, data())
        self.assertEqual(req.created_at.year, 2026)
        self.assertEqual(req.reference, "W/2027/00001")
        req.refresh_from_db()
        self.assertEqual(req.reference, "W/2027/00001")

    def test_document_render_failure_rolls_back_counters_and_reservation(self):
        with patch("registry.documents.render_pdf", side_effect=ValidationError("Błąd PDF")):
            with self.assertRaises(ValidationError):
                create_request(self.a, data())
        self.assertFalse(Request.objects.exists())
        self.assertFalse(Letter.objects.exists())
        self.assertFalse(NumberSequence.objects.exists())
        req = create_request(self.a, data())
        self.assertEqual(req.reference_ordinal, 1)
        self.assertEqual(req.letters.get().number_ordinal, 1)
        before = NumberSequence.objects.get(scope="LETTER.a").last_value
        with patch("registry.documents.render_pdf", side_effect=ValidationError("Błąd PDF")):
            with self.assertRaises(ValidationError):
                make_letter(self.a, "APPLICATION", req=req)
        self.assertEqual(NumberSequence.objects.get(scope="LETTER.a").last_value, before)

    def test_revision_new_number_preserves_previous_pdf(self):
        req = create_request(self.a, data())
        old = req.letters.get()
        pdf, sha, number = bytes(old.pdf), old.sha256, old.number
        new = create_letter_revision(self.a, old, "Nowa wersja")
        old.refresh_from_db()
        self.assertEqual((bytes(old.pdf), old.sha256, old.number), (pdf, sha, number))
        self.assertEqual(new.replaces, old)
        self.assertEqual(new.number_ordinal, old.number_ordinal + 1)
        self.assertNotEqual(new.sha256, sha)

    def test_missing_or_rewound_counter_does_not_reuse_existing_numbers(self):
        req = create_request(self.a, data())
        NumberSequence.objects.filter(scope="REQUEST").delete()
        NumberSequence.objects.filter(scope="LETTER.a").update(last_value=0)
        second = create_request(self.a, data("P1TEST"))
        self.assertEqual(second.reference_ordinal, req.reference_ordinal + 1)
        self.assertEqual(second.letters.get().number_ordinal, 2)

    def test_database_rejects_duplicate_ordinals_and_partial_number_parts(self):
        first = create_request(self.a, data())
        second = create_request(self.a, data("P1TEST"))
        for update in [
            {"reference_ordinal": first.reference_ordinal},
            {"reference_year": None},
            {"reference_ordinal": 0},
        ]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                Request.objects.filter(pk=second.pk).update(**update)
        for update in [{"number_ordinal": 1}, {"number_year": None}, {"number_ordinal": 0}]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                second.letters.update(**update)
        with self.assertRaises(IntegrityError), transaction.atomic():
            NumberSequence.objects.create(scope="REQUEST", year=first.reference_year)


class NumberingConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_simultaneous_first_request_numbers_are_unique(self):
        barrier = Barrier(4)

        def create(index):
            close_old_connections()
            try:
                user = User.objects.get(pk=self.a.pk if index < 2 else self.b.pk)
                barrier.wait(timeout=10)
                req = create_request(user, data(f"P{index}TEST"))
                return req.reference, req.letters.get().number
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(create, range(4)))
        self.assertEqual(len({reference for reference, _ in results}), 4)
        self.assertEqual(len({number for _, number in results}), 4)
        self.assertEqual(sorted(Request.objects.values_list("reference_ordinal", flat=True)), [1, 2, 3, 4])
        for user in [self.a, self.b]:
            self.assertEqual(
                sorted(Letter.objects.filter(office=user.office).values_list("number_ordinal", flat=True)),
                [1, 2],
            )

    def test_simultaneous_letter_revisions_preserve_original_and_get_unique_numbers(self):
        req = create_request(self.a, data())
        original = req.letters.get()
        barrier = Barrier(2)

        def revise(_):
            close_old_connections()
            try:
                user = User.objects.get(pk=self.a.pk)
                letter = Letter.objects.get(pk=original.pk)
                barrier.wait(timeout=10)
                return create_letter_revision(user, letter, "Równoczesna wersja testowa").number
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(revise, range(2)))
        self.assertEqual(len(set(results)), 2)
        original.refresh_from_db()
        self.assertEqual(original.number_ordinal, 1)
        self.assertEqual(original.versions.count(), 2)

    def test_restored_backup_preserves_references_numbers_and_counters(self):
        req = create_request(self.a, data())
        letter = req.letters.get()

        def verify(db):
            self.assertEqual(
                db.execute(
                    "SELECT reference_number,reference_year,reference_ordinal FROM registry_request"
                ).fetchone(),
                (req.reference, req.reference_year, req.reference_ordinal),
            )
            self.assertEqual(
                db.execute("SELECT number,number_year,number_ordinal FROM registry_letter").fetchone(),
                (letter.number, letter.number_year, letter.number_ordinal),
            )
            self.assertEqual(db.execute("SELECT COUNT(*) FROM registry_numbersequence").fetchone()[0], 2)

        with tempfile.TemporaryDirectory() as temporary:
            backup = Path(temporary) / "snapshot.zip"
            target = Path(temporary) / "restored"
            call_command("backup_registry", output=str(backup), stdout=StringIO())
            if connection.vendor == "postgresql":
                import psycopg
                from psycopg import sql

                from .postgres_backup import connection_parameters

                name = "dytest_numbering_" + uuid.uuid4().hex
                try:
                    call_command(
                        "restore_registry",
                        str(backup),
                        target=str(target),
                        target_database=name,
                        stdout=StringIO(),
                    )
                    with psycopg.connect(**connection_parameters(name)) as db:
                        verify(db)
                finally:
                    # Wyłącznie nowa baza utworzona przez ten test; bez FORCE.
                    with psycopg.connect(**connection_parameters("postgres"), autocommit=True) as admin:
                        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
            else:
                call_command("restore_registry", str(backup), target=str(target), stdout=StringIO())
                with sqlite3.connect(target / "registry.sqlite3") as db:
                    verify(db)

    def test_backup_rejects_rewound_counter_and_inconsistent_reference(self):
        req = create_request(self.a, data())
        with tempfile.TemporaryDirectory() as temporary:
            NumberSequence.objects.filter(scope="REQUEST").update(last_value=0)
            with self.assertRaises(CommandError):
                call_command(
                    "backup_registry", output=str(Path(temporary) / "bad-counter.zip"), stdout=StringIO()
                )
            NumberSequence.objects.filter(scope="REQUEST").update(last_value=req.reference_ordinal)
            Request.objects.filter(pk=req.pk).update(reference_number="W/2099/00999")
            with self.assertRaises(CommandError):
                call_command(
                    "backup_registry", output=str(Path(temporary) / "bad-reference.zip"), stdout=StringIO()
                )


class NumberingMigrationTests(TransactionTestCase):
    def test_migration_preserves_legacy_references_and_signed_document_bytes(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        old_target = [("registry", "0004_letter_replaces")]
        new_target = [("registry", "0005_numbersequence_letter_number_ordinal_and_more")]
        executor = MigrationExecutor(connection)
        latest_target = executor.loader.graph.leaf_nodes("registry")
        executor.migrate(old_target)
        try:
            apps = executor.loader.project_state(old_target).apps
            OldOffice = apps.get_model("registry", "Office")
            OldUser = apps.get_model("registry", "User")
            OldRequest = apps.get_model("registry", "Request")
            OldLetter = apps.get_model("registry", "Letter")
            office = OldOffice.objects.create(id="a", name="Urząd historyczny", kind="COUNTY", city="A")
            user = OldUser.objects.create(
                username="a@test.invalid", email="a@test.invalid", role="COUNTY", office=office
            )
            req = OldRequest.objects.create(kind="III", office=office, author=user, case_number="HISTORY/1")
            stamp = datetime(2025, 12, 31, 23, 30, tzinfo=datetime_timezone.utc)
            OldRequest.objects.filter(pk=req.pk).update(created_at=stamp)
            original = b"%PDF-SYNTHETIC-LEGACY-ORIGINAL"
            signed = original + b"SYNTHETIC-LEGACY-SIGNATURE"
            report = {"synthetic_migration_fixture": True}
            letter = OldLetter.objects.create(
                number="DRT/2025/APPLICATION/ABCDEF123456",
                kind="APPLICATION",
                office=office,
                recipient=office,
                request=req,
                title="Historyczny dokument",
                body="Historia",
                pdf=original,
                sha256=hashlib.sha256(original).hexdigest(),
                signed_pdf=signed,
                signed_sha256=hashlib.sha256(signed).hexdigest(),
                signature_report=report,
                signature_status="UNVERIFIED",
                signed_by=user,
            )
            old_pk, req_pk = letter.pk, req.pk
            executor = MigrationExecutor(connection)
            executor.migrate(new_target)
            migrated = Request.objects.get(pk=req_pk)
            self.assertEqual(migrated.reference, f"W/2025/{req_pk:05d}")
            self.assertEqual(NumberSequence.objects.get(scope="REQUEST", year=2025).last_value, req_pk)
            # Model ze stanu migracji: żywy model ma kolumny dodane później.
            MigratedLetter = executor.loader.project_state(new_target).apps.get_model("registry", "Letter")
            archived = MigratedLetter.objects.get(pk=old_pk)
            self.assertEqual(archived.number, "DRT/2025/APPLICATION/ABCDEF123456")
            self.assertEqual(bytes(archived.pdf), original)
            self.assertEqual(bytes(archived.signed_pdf), signed)
            self.assertEqual(archived.signature_report, report)
            self.assertEqual(archived.signed_sha256, hashlib.sha256(signed).hexdigest())
            self.assertIsNone(archived.number_year)
            self.assertIsNone(archived.number_ordinal)
        finally:
            MigrationExecutor(connection).migrate(latest_target)
