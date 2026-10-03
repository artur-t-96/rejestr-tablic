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

from .models import AuditLog, IntegrationJob, Letter, NumberSequence, Pool, PoolSlot, Request, User
from .pool_import_views import SESSION_KEY
from .pool_imports import FIELDS, apply_pool_import, preview_pool_import
from .services import create_request, decide_request, send_request
from .tests import fixtures


def row(number="P001", **changes):
    return {
        "pool_ref": "TEST/HISTORY/01",
        "kind": "II",
        "office_id": "a",
        "prefix": "P",
        "number": number,
        "valid_from": "2025-01-01",
        "valid_until": "2025-12-31",
        "station": "",
        "issued_on": "",
        "case_number": "",
        "source_reference": "FIKCYJNE/PISMO/2025/01",
        **changes,
    }


def csv_text(rows):
    stream = StringIO()
    writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


class PoolImportTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def counts(self):
        return tuple(
            model.objects.count()
            for model in (Pool, PoolSlot, AuditLog, Request, Letter, IntegrationJob, NumberSequence)
        )

    def apply(self, text, actor=None):
        return apply_pool_import(
            actor or self.ump,
            text,
            hashlib.sha256(text.encode()).hexdigest(),
            "Uzgodniony fikcyjny wykaz",
            filename="historia.csv",
        )

    def test_preview_does_not_write_and_import_preserves_holes_issue_dates_and_source(self):
        text = "\ufeff" + csv_text(
            [row("P001", issued_on="2025-02-01", case_number="TEST/WYDANIE/01"), row("P003")]
        )
        before = self.counts()
        preview = preview_pool_import(text)
        self.assertEqual(preview["errors"], [])
        self.assertEqual(preview["groups"][0]["count"], 2)
        self.assertEqual(self.counts(), before)
        pool = self.apply(text)[0]
        self.assertIsNone(pool.request_id)
        self.assertEqual((pool.start, pool.end), (1, 3))
        self.assertEqual(list(pool.slots.values_list("number", flat=True)), ["P001", "P003"])
        self.assertFalse(PoolSlot.objects.filter(number="P002").exists())
        issued = pool.slots.get(number="P001")
        self.assertEqual(timezone.localdate(issued.issued_at).isoformat(), "2025-02-01")
        self.assertIsNone(issued.issued_by_id)
        self.assertEqual(pool.used, 1)
        event = AuditLog.objects.get(action="pool.imported")
        self.assertEqual(event.actor, self.ump)
        self.assertEqual(event.office, self.a.office)
        self.assertEqual(event.after["source_sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(event.after["source_reference"], "FIKCYJNE/PISMO/2025/01")
        self.assertEqual(event.after["source_filename"], "historia.csv")
        self.assertEqual(event.reason, "Uzgodniony fikcyjny wykaz")
        self.assertEqual(self.counts()[3:], before[3:])

    def test_historical_incomplete_letter_and_m_pools_can_be_recorded_without_new_allocation(self):
        text = csv_text(
            [row("P0001A", kind="III", prefix="P0"), row("M001", pool_ref="TEST/M/HISTORY", prefix="M")]
        )
        pools = self.apply(text)
        self.assertEqual(len(pools), 2)
        self.assertEqual(PoolSlot.objects.get(number="P0001A").ordinal, 10000)
        self.assertEqual(Letter.objects.count(), 0)
        self.assertEqual(IntegrationJob.objects.count(), 0)

    def test_historical_numbers_finish_numeric_capacity_for_a_new_decision(self):
        # Odrębna baza testowa: wcześniejsza fikcyjna historia 9997 numerów.
        old = Pool.objects.create(
            kind="III",
            office=self.a.office,
            prefix="P0",
            start=1,
            end=9997,
            valid_from="2025-01-01",
            valid_until="2025-12-31",
        )
        PoolSlot.objects.bulk_create(
            [PoolSlot(pool=old, number=f"P0{i:04d}", ordinal=i) for i in range(1, 9998)], batch_size=1000
        )
        self.apply(csv_text([row("P09998", kind="III", prefix="P0"), row("P09999", kind="III", prefix="P0")]))
        req = create_request(
            self.a, {"kind": "III", "count": 1, "case_number": "TEST/NOWA", "justification": "Fikcyjne"}
        )
        send_request(self.a, req.uuid)
        decide_request(
            self.ump,
            req.uuid,
            True,
            pool_data={
                "prefix": "P0",
                "start": 10000,
                "end": 10000,
                "valid_from": timezone.localdate(),
                "valid_until": timezone.localdate() + timedelta(days=30),
            },
        )
        self.assertEqual(Pool.objects.get(request=req).slots.get().number, "P0001A")

    def test_duplicate_in_file_across_pools_and_conflicting_metadata_are_blocked(self):
        for rows in (
            [row(), row(pool_ref="INNA")],
            [row(), row("P002", office_id="b")],
            [row(), row("P002", source_reference="INNE")],
        ):
            with self.subTest(rows=rows):
                text = csv_text(rows)
                before = self.counts()
                self.assertTrue(preview_pool_import(text)["errors"])
                with self.assertRaises(ValidationError):
                    self.apply(text)
                self.assertEqual(self.counts(), before)

    def test_invalid_formats_dates_and_missing_provenance_are_blocked(self):
        changes = [
            {"number": "P000"},
            {"number": "P01B"},
            {"number": "P01Q"},
            {"kind": "III", "prefix": "P0", "number": "P0000A"},
            {"kind": "III", "prefix": "P0", "number": "P0001Q"},
            {"kind": "III", "prefix": "P0", "number": "P00001", "valid_until": ""},
            {"kind": "I"},
            {"prefix": "M"},
            {"office_id": "unknown"},
            {"source_reference": ""},
            {"pool_ref": ""},
            {"valid_from": "2025-1-1"},
            {"valid_from": "2030-01-01"},
            {"valid_from": "2025-02-30"},
            {"valid_until": "2024-12-31"},
            {"issued_on": "2025-03-01"},
            {"case_number": "BEZ DATY"},
            {"issued_on": "2024-12-31", "case_number": "ZA WCZEŚNIE"},
            {"issued_on": "2026-01-01", "case_number": "PO KOŃCU"},
            {"station": "x" * 181},
            {"source_reference": "x" * 201},
        ]
        for change in changes:
            with self.subTest(change=change):
                self.assertTrue(preview_pool_import(csv_text([row(**change)]))["errors"])
        self.assertEqual(Pool.objects.count(), 0)

    def test_strict_csv_structure_empty_file_and_limits(self):
        for text in (
            '"unterminated',
            "number;number\nP001;P002",
            csv_text([row()]).replace("number;", "unexpected;"),
            csv_text([row()]) + '"unterminated',
        ):
            with self.subTest(text=text):
                try:
                    result = preview_pool_import(text)
                except ValidationError:
                    continue
                self.assertTrue(result["errors"])
        self.assertTrue(preview_pool_import(csv_text([]))["errors"])
        with self.assertRaises(ValidationError):
            preview_pool_import("x" * 2_000_001)
        too_many = csv_text([row() for _ in range(5001)])
        self.assertIn("Maksymalnie 5000 numerów", " ".join(preview_pool_import(too_many)["errors"]))

    def test_collision_after_preview_different_hash_and_missing_reason_leave_all_rows_unchanged(self):
        text = csv_text([row(), row("P002")])
        self.assertEqual(preview_pool_import(text)["errors"], [])
        self.apply(csv_text([row("P002")]))
        before = self.counts()
        with self.assertRaises(ValidationError):
            self.apply(text)
        self.assertEqual(self.counts(), before)
        for digest, reason in (("0" * 64, "Powód"), (hashlib.sha256(text.encode()).hexdigest(), " ")):
            with self.assertRaises(ValidationError):
                apply_pool_import(self.ump, text, digest, reason)
            self.assertEqual(self.counts(), before)

    def test_failure_after_first_slot_rolls_back_all_pools_and_their_audits(self):
        text = csv_text([row(), row("P002", pool_ref="DRUGA")])
        create = PoolSlot.objects.bulk_create

        def failing(*args, **kwargs):
            create(args[0][:1], **kwargs)
            raise IntegrityError("Fikcyjny błąd ograniczenia po zapisaniu pierwszego numeru")

        before = self.counts()
        with (
            patch.object(PoolSlot.objects, "bulk_create", side_effect=failing),
            self.assertRaisesMessage(ValidationError, "Nie zapisano żadnej puli"),
        ):
            self.apply(text)
        self.assertEqual(self.counts(), before)

    def test_only_ump_can_import_but_inactive_historical_destination_is_supported(self):
        text = csv_text([row()])
        for actor in (self.admin, self.a, self.b):
            with self.assertRaises(PermissionDenied):
                self.apply(text, actor)
        self.a.office.active = False
        self.a.office.save(update_fields=["active"])
        self.assertEqual(self.apply(text)[0].office, self.a.office)


class PoolImportBrowserTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        self.url = reverse("import_pools")
        self.client.force_login(self.ump)

    def upload(self, text, name="historia.csv"):
        return self.client.post(
            self.url,
            {"action": "preview", "file": SimpleUploadedFile(name, text.encode(), content_type="text/csv")},
        )

    def confirm(self, token):
        return self.client.post(
            self.url,
            {
                "action": "confirm",
                "preview_token": token,
                "reason": "Uzgodniony fikcyjny wykaz",
                "acknowledged": "on",
            },
        )

    def test_preview_explicit_confirmation_history_and_office_isolation(self):
        response = self.upload(
            csv_text([row(), row("P003", issued_on="2025-02-01", case_number="TEST/STARE")])
        )
        self.assertContains(response, "Podgląd wykazu · numery: 2 · pule: 1")
        self.assertContains(response, self.a.office.name)
        self.assertEqual(Pool.objects.count(), 0)
        token = self.client.session[SESSION_KEY]["token"]
        missing_ack = self.client.post(
            self.url, {"action": "confirm", "preview_token": token, "reason": "Powód"}
        )
        self.assertContains(missing_ack, "To pole jest wymagane")
        self.assertEqual(Pool.objects.count(), 0)
        self.assertRedirects(self.confirm(token), reverse("pools_list"))
        self.assertNotIn(SESSION_KEY, self.client.session)
        pool = Pool.objects.get()
        self.assertContains(
            self.client.get(reverse("pool_detail", args=[pool.uuid])), "FIKCYJNE/PISMO/2025/01"
        )
        self.client.force_login(self.a)
        detail = self.client.get(reverse("pool_detail", args=[pool.uuid]))
        self.assertContains(detail, "Historyczny przydział")
        self.assertContains(detail, "Nie wydano · poza okresem puli")
        self.assertContains(detail, "Poza okresem puli")
        self.assertNotContains(detail, "<td>Dostępny</td>")
        self.assertNotContains(detail, 'class="inline issue-form"')
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(reverse("pool_detail", args=[pool.uuid])).status_code, 404)

    def test_old_token_expiry_failed_upload_and_replay_do_not_write(self):
        text = csv_text([row()])
        self.upload(text)
        old_token = self.client.session[SESSION_KEY]["token"]
        for malformed in ("x" * 48, "ą" * 48):
            self.assertContains(self.confirm(malformed), "został zastąpiony")
            self.assertEqual(Pool.objects.count(), 0)
        self.upload(csv_text([row("P002")]))
        self.assertContains(self.confirm(old_token), "został zastąpiony")
        self.assertEqual(Pool.objects.count(), 0)
        session = self.client.session
        saved = session[SESSION_KEY]
        saved["created"] = (timezone.now() - timedelta(minutes=16)).isoformat()
        session[SESSION_KEY] = saved
        session.save()
        self.assertContains(self.confirm(saved["token"]), "wygasł")
        self.upload(text)
        token = self.client.session[SESSION_KEY]["token"]
        self.upload("złe nagłówki")
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertContains(self.confirm(token), "wygasł")
        self.upload(text)
        token = self.client.session[SESSION_KEY]["token"]
        self.confirm(token)
        self.assertContains(self.confirm(token), "wygasł")
        self.assertEqual(Pool.objects.count(), 1)
        self.assertEqual(PoolSlot.objects.count(), 1)

    def test_all_rows_are_reviewable_and_source_markup_is_escaped(self):
        self.upload(
            csv_text(
                [row(f"P{i:03d}", source_reference='<script>alert("TEST")</script>') for i in range(1, 102)]
            )
        )
        response = self.client.get(self.url, {"page": 2})
        self.assertContains(response, "Numery 101–101 z 101")
        self.assertContains(response, "P101")
        self.assertNotContains(response, '<script>alert("TEST")</script>')
        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(response, 'aria-label="Strony numerów importu"')

    def test_role_csrf_and_utf8_failures_are_rejected(self):
        self.assertEqual(self.client.get(self.url + "?template=1")["Content-Type"], "text/csv; charset=utf-8")
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.ump)
        self.assertEqual(strict.post(self.url, {"action": "confirm"}).status_code, 403)
        response = self.client.post(self.url, {"file": SimpleUploadedFile("bad.csv", b"\xff")})
        self.assertContains(response, "CSV UTF-8")
        response = self.upload('"unterminated')
        self.assertContains(response, "Niepoprawny nagłówek CSV")
        self.assertNotIn(SESSION_KEY, self.client.session)
        for actor in (self.admin, self.a, self.b):
            self.client.force_login(actor)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.upload(csv_text([row()])).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(Pool.objects.count(), 0)


class PoolImportConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_two_imports_checked_before_insert_only_one_commits(self):
        _, ump, _, _ = fixtures()
        text = csv_text([row(), row("P002")])
        digest = hashlib.sha256(text.encode()).hexdigest()
        barrier = Barrier(2)
        original = preview_pool_import

        def synchronized(value):
            result = original(value)
            barrier.wait(timeout=5)
            return result

        def run():
            close_old_connections()
            try:
                actor = User.objects.get(pk=ump.pk)
                try:
                    apply_pool_import(actor, text, digest, "Fikcyjny wyścig")
                    return "committed"
                except ValidationError:
                    return "conflict"
            finally:
                close_old_connections()

        with patch("registry.pool_imports.preview_pool_import", side_effect=synchronized):
            with ThreadPoolExecutor(max_workers=2) as workers:
                futures = [workers.submit(run) for _ in range(2)]
                results = [future.result(timeout=10) for future in futures]
        self.assertCountEqual(results, ["committed", "conflict"])
        self.assertEqual(Pool.objects.count(), 1)
        self.assertEqual(PoolSlot.objects.count(), 2)
        self.assertEqual(AuditLog.objects.filter(action="pool.imported").count(), 1)
        self.assertFalse(Letter.objects.exists())
