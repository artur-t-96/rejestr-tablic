import csv
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, close_old_connections
from django.test import Client, TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from .imports import FIELDS, apply_import, apply_source_import, preview_import
from .models import AuditLog, IntegrationJob, Letter, NumberSequence, PlateRecord, Request, User
from .record_import_views import SESSION_KEY
from .tests import fixtures


def row(number="P2HIST", **changes):
    return {
        **{field: "" for field in FIELDS},
        "number": number,
        "owner": "Osoba Fikcyjna",
        "office_id": "a",
        "status": "ALLOCATED",
        **changes,
    }


def csv_text(rows):
    stream = StringIO()
    writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


class RecordImportTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def counts(self):
        return tuple(
            model.objects.count()
            for model in (PlateRecord, AuditLog, Request, Letter, NumberSequence, IntegrationJob)
        )

    def apply(self, text):
        return apply_source_import(
            self.ump,
            text,
            hashlib.sha256(text.encode()).hexdigest(),
            "TEST: uzgodniony wykaz z pisma HISTORY/01",
            filename="historia.csv",
        )

    def test_preview_and_import_preserve_all_data_and_original_bom_hash(self):
        original = row(
            "M9HIST",
            status="SOLD",
            address="Fikcyjna 1",
            vin="WVWZZZ1JZXW000001",
            make="Fikcyjna marka",
            model="Fikcyjny model",
            registration_date="2025-01-01",
            sale_date="2025-02-01",
            buyer="Fikcyjny nabywca",
            letter_number="FIKCYJNE/2025/01",
            note="Historyczny wykaz",
        )
        text = "\ufeff" + csv_text([original, row("P2PAST", status="RELEASED")])
        before = self.counts()
        checked = preview_import(text)
        self.assertEqual(checked["errors"], [])
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.apply(text), 2)
        record = PlateRecord.objects.get(number="M9HIST")
        for field, value in original.items():
            actual = getattr(record, field)
            self.assertEqual(actual.isoformat() if hasattr(actual, "isoformat") else actual, value)
        self.assertIsNone(record.allocated_at)
        self.assertIsNone(record.reservation_until)
        event = AuditLog.objects.get(object_id=str(record.pk), action="plate.imported")
        self.assertEqual(event.after["source_sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(event.after["source_filename"], "historia.csv")
        self.assertEqual(event.actor, self.ump)
        self.assertEqual(event.office, self.a.office)
        self.assertIn("HISTORY/01", event.reason)
        self.assertEqual(self.counts()[2:], before[2:])

    def test_strict_structure_utf8_bom_empty_and_limits(self):
        for text in (
            '"unfinished',
            "number;number;owner;office_id\nP2HIST;P2OTHER;X;a",
            "number;owner;office_id;unknown\nP2HIST;X;a;ignored",
            "number;owner;office_id\nP2HIST;X;a;extra",
            "number;owner;office_id\nP2HIST;X",
            csv_text([row()]) + '"unfinished',
        ):
            with self.subTest(text=text):
                try:
                    checked = preview_import(text)
                except ValidationError:
                    continue
                self.assertTrue(checked["errors"])
        self.assertTrue(preview_import(csv_text([]))["errors"])
        self.assertIn(
            "Maksymalnie 500",
            " ".join(preview_import(csv_text([row(status="RELEASED") for _ in range(501)]))["errors"]),
        )
        with self.assertRaises(ValidationError):
            preview_import("ą" * 1_000_001)
        with self.assertRaises(ValidationError):
            preview_import(None)

    def test_dates_status_lengths_office_and_vin_are_consistent(self):
        invalid = [
            {"registration_date": "2025-1-1"},
            {"registration_date": "2025-02-30"},
            {"registration_date": "2030-01-01"},
            {"status": "SOLD", "vin": "WVWZZZ1JZXW000001", "registration_date": "2025-01-01"},
            {"sale_date": "2025-02-01", "registration_date": "2025-01-01", "buyer": "X"},
            {"status": "ISSUED"},
            {"vin": "INVALID"},
            {"status": "SENT"},
            {"owner": "x" * 181},
            {"address": "x" * 301},
            {"office_id": "missing"},
            {
                "status": "SOLD",
                "vin": "WVWZZZ1JZXW000001",
                "registration_date": "2025-02-01",
                "sale_date": "2025-01-01",
                "buyer": "X",
            },
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                checked = preview_import(csv_text([row(**changes)]))
                self.assertTrue(checked["errors"])
        self.a.office.active = False
        self.a.office.save(update_fields=["active"])
        self.assertTrue(preview_import(csv_text([row()]))["errors"])
        self.assertEqual(PlateRecord.objects.count(), 0)

    def test_collision_after_preview_hash_reason_and_access_rejections_do_not_write(self):
        text = csv_text([row(), row("P2OTHER")])
        self.assertEqual(preview_import(text)["errors"], [])
        self.apply(csv_text([row("P2OTHER")]))
        before = self.counts()
        with self.assertRaises(ValidationError):
            self.apply(text)
        self.assertEqual(self.counts(), before)
        clean = csv_text([row()])
        for digest, reason in (("0" * 64, "Powód"), (hashlib.sha256(clean.encode()).hexdigest(), " ")):
            with self.assertRaises(ValidationError):
                apply_source_import(self.ump, clean, digest, reason)
            self.assertEqual(self.counts(), before)
        for actor in (self.admin, self.a, self.b):
            with self.assertRaises(PermissionDenied):
                apply_source_import(actor, clean, hashlib.sha256(clean.encode()).hexdigest(), "Powód")
        self.assertEqual(self.counts(), before)

    def test_exact_source_replay_of_only_released_history_is_rejected(self):
        text = csv_text([row(status="RELEASED"), row(status="RELEASED", note="Inny dawny okres")])
        self.assertEqual(self.apply(text), 2)
        before = self.counts()
        with self.assertRaisesMessage(ValidationError, "już zaimportowany"):
            self.apply(text)
        self.assertEqual(self.counts(), before)
        # Dawna zwolniona historia nie blokuje nowego aktywnego numeru.
        self.assertEqual(self.apply(csv_text([row()])), 1)
        self.assertEqual(PlateRecord.objects.filter(number="P2HIST").count(), 3)

    def test_partial_insert_failure_rolls_back_every_record_and_audit(self):
        text = csv_text([row(), row("P2OTHER")])
        original = PlateRecord.objects.create
        calls = 0

        def failing(**values):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise IntegrityError("Fikcyjna kolizja po pierwszym wpisie")
            return original(**values)

        before = self.counts()
        with (
            patch.object(PlateRecord.objects, "create", side_effect=failing),
            self.assertRaisesMessage(ValidationError, "żadnego wpisu"),
        ):
            self.apply(text)
        self.assertEqual(self.counts(), before)


class RecordImportBrowserTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        self.url = reverse("import_records")
        self.client.force_login(self.ump)

    def upload(self, text):
        return self.client.post(
            self.url,
            {
                "action": "preview",
                "file": SimpleUploadedFile("historia.csv", text.encode(), content_type="text/csv"),
            },
        )

    def confirm(self, token, **extra):
        return self.client.post(
            self.url,
            {
                "action": "confirm",
                "preview_token": token,
                "reason": "TEST: historyczny wykaz z pisma HISTORY/01",
                "acknowledged": "on",
                **extra,
            },
        )

    def test_preview_has_all_fields_and_confirmation_requires_reason_and_acknowledgment(self):
        item = row(
            note="Ważna uwaga", address="Fikcyjna 1", make="Marka", model="Model", letter_number="FIKCYJNE/01"
        )
        response = self.upload(csv_text([item]))
        for value in ("Podgląd wykazu · wpisy: 1", "Ważna uwaga", "Fikcyjna 1", "Marka Model", "FIKCYJNE/01"):
            self.assertContains(response, value)
        token = self.client.session[SESSION_KEY]["token"]
        for extra in ({"acknowledged": ""}, {"reason": ""}):
            self.assertContains(self.confirm(token, **extra), "To pole jest wymagane")
            self.assertFalse(PlateRecord.objects.exists())
        self.assertRedirects(self.confirm(token), reverse("records_list"))
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(PlateRecord.objects.get().note, "Ważna uwaga")
        self.assertEqual(Letter.objects.count(), 0)

    def test_old_card_cannot_confirm_replaced_preview_and_unicode_token_does_not_crash(self):
        self.upload(csv_text([row()]))
        old = self.client.session[SESSION_KEY]["token"]
        self.upload(csv_text([row("P2OTHER")]))
        for token in (old, "ą" * 48):
            self.assertContains(self.confirm(token), "został zastąpiony")
            self.assertFalse(PlateRecord.objects.exists())
        current = self.client.session[SESSION_KEY]["token"]
        self.confirm(current)
        self.assertEqual(list(PlateRecord.objects.values_list("number", flat=True)), ["P2OTHER"])
        self.assertContains(self.confirm(current), "wygasł")
        self.assertEqual(PlateRecord.objects.count(), 1)

    def test_expiry_invalid_upload_and_legacy_confirmation_invalidate_preview(self):
        self.upload(csv_text([row()]))
        session = self.client.session
        saved = session[SESSION_KEY]
        saved["created"] = (timezone.now() - timedelta(minutes=16)).isoformat()
        session[SESSION_KEY] = saved
        session.save()
        self.assertContains(self.confirm(saved["token"]), "wygasł")
        self.upload(csv_text([row()]))
        token = self.client.session[SESSION_KEY]["token"]
        self.upload('"unfinished')
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertContains(self.confirm(token), "wygasł")
        session = self.client.session
        session["import_preview"] = [row()]
        session.save()
        response = self.client.post(self.url, {"confirm": "1"})
        self.assertContains(response, "To pole jest wymagane")
        self.assertNotIn("import_preview", self.client.session)
        self.assertFalse(PlateRecord.objects.exists())

    def test_pagination_and_escaped_markup(self):
        self.upload(
            csv_text(
                [row(f"P2A{i:02d}", note='<script>alert("TEST")</script>') for i in range(100)]
                + [row("P2LAST")]
            )
        )
        first = self.client.get(self.url)
        self.assertContains(first, "Wpisy 1–100 z 101")
        self.assertContains(first, "&lt;script&gt;")
        self.assertNotContains(first, '<script>alert("TEST")</script>')
        second = self.client.get(self.url, {"page": 2})
        self.assertContains(second, "P2LAST")
        self.assertContains(second, "Wpisy 101–101 z 101")
        self.assertEqual(PlateRecord.objects.count(), 0)

    def test_roles_csrf_utf8_and_changed_destination_are_rejected(self):
        response = self.client.get(self.url + "?template=1")
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.ump)
        self.assertEqual(strict.post(self.url, {"action": "confirm"}).status_code, 403)
        response = self.client.post(self.url, {"file": SimpleUploadedFile("bad.csv", b"\xff")})
        self.assertContains(response, "CSV UTF-8")
        self.upload(csv_text([row()]))
        token = self.client.session[SESSION_KEY]["token"]
        self.a.office.active = False
        self.a.office.save(update_fields=["active"])
        self.assertContains(self.confirm(token), "aktywny urząd")
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.client.force_login(self.a)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.a.office.active = True
        self.a.office.save(update_fields=["active"])
        for actor in (self.admin, self.a, self.b):
            self.client.force_login(actor)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.upload(csv_text([row()])).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertFalse(PlateRecord.objects.exists())


class RecordImportConcurrencyTests(TransactionTestCase):
    def parallel(self, operation):
        barrier = Barrier(2)
        original = preview_import

        def checked(text):
            result = original(text)
            barrier.wait(timeout=5)
            return result

        def run():
            close_old_connections()
            try:
                user = User.objects.get(role="MAIN")
                try:
                    operation(user)
                    return "committed"
                except ValidationError:
                    return "conflict"
            finally:
                close_old_connections()

        with patch("registry.imports.preview_import", side_effect=checked):
            with ThreadPoolExecutor(max_workers=2) as workers:
                futures = [workers.submit(run) for _ in range(2)]
                return [future.result(timeout=10) for future in futures]

    @skipUnlessDBFeature("has_select_for_update")
    def test_active_number_unique_constraint_commits_one_of_two_completed_previews(self):
        fixtures()
        results = self.parallel(lambda user: apply_import(user, [row(), row("P2OTHER")]))
        self.assertCountEqual(results, ["committed", "conflict"])
        self.assertEqual(PlateRecord.objects.count(), 2)
        self.assertEqual(AuditLog.objects.filter(action="plate.imported").count(), 2)
        self.assertFalse(Letter.objects.exists())

    @skipUnlessDBFeature("has_select_for_update")
    def test_same_released_source_serializes_and_does_not_duplicate_history(self):
        fixtures()
        text = csv_text([row(status="RELEASED")])
        digest = hashlib.sha256(text.encode()).hexdigest()
        barrier = Barrier(2)
        original = preview_import

        def run():
            close_old_connections()
            try:
                actor = User.objects.get(role="MAIN")
                try:
                    apply_source_import(actor, text, digest, "TEST: historyczne źródło")
                    return "committed"
                except ValidationError:
                    return "conflict"
            finally:
                close_old_connections()

        # Druga walidacja rekonstruuje identyczne CSV; rozróżniamy wywołania per wątek.
        from threading import local

        state = local()

        def preview_once(text):
            checked = original(text)
            if not getattr(state, "seen", False):
                state.seen = True
                barrier.wait(timeout=5)
            return checked

        with patch("registry.imports.preview_import", side_effect=preview_once):
            with ThreadPoolExecutor(max_workers=2) as workers:
                futures = [workers.submit(run) for _ in range(2)]
                results = [future.result(timeout=10) for future in futures]
        self.assertCountEqual(results, ["committed", "conflict"])
        self.assertEqual(PlateRecord.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="plate.imported").count(), 1)
        self.assertFalse(Letter.objects.exists())
