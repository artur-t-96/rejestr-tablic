"""Regresja reguł numeracji z § 30 i nowelizacji Dz.U. 2025 poz. 939."""

from datetime import date

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from .forms import CheckForm, RequestForm
from .imports import apply_import, preview_import
from .models import AuditLog, Letter, NumberSequence, PlateRecord, Request
from .services import create_request, decide_request, send_request, update_record
from .tests import data, fixtures
from .validation import validate_number, validate_part


class IndividualAlphabetTests(SimpleTestCase):
    def test_all_25_statutory_letters_are_accepted(self):
        # B D I O Z są wyłączone z automatycznej numeracji, nie z indywidualnej.
        for letter in "ABCDEFGHIJKLMNOPRSTUVWXYZ":
            with self.subTest(letter=letter):
                self.assertEqual(validate_part(letter * 3), letter * 3)

    def test_q_is_rejected_at_every_position_in_all_lengths(self):
        for length in (3, 4, 5):
            for index in range(length):
                part = "A" * index + "Q" + "A" * (length - index - 1)
                with self.subTest(part=part), self.assertRaisesMessage(ValidationError, "wyjątkiem Q"):
                    validate_part(part)

    def test_normalization_and_digits_keep_valid_individual_formats(self):
        for raw, expected in [(" m9 bioz ", "M9BIOZ"), ("p0 a12", "P0A12"), ("P7 AB1C", "P7AB1C")]:
            with self.subTest(raw=raw):
                self.assertEqual(validate_number(raw), expected)
        with self.assertRaisesMessage(ValidationError, "wyjątkiem Q"):
            validate_number(" m9 abq ")

    def test_both_forms_apply_same_alphabet(self):
        form = CheckForm({"part": "ABQ", "prefix": "M", "digit": "9"})
        self.assertFalse(form.is_valid())
        self.assertIn("wyjątkiem Q", form.errors["part"][0])
        request = RequestForm(data("M9ABQ"))
        self.assertFalse(request.is_valid())
        self.assertIn("wyjątkiem Q", request.errors["number"][0])


class IndividualAlphabetEntryTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.county, self.other = fixtures()

    def counts(self):
        return tuple(
            model.objects.count() for model in (PlateRecord, Request, Letter, AuditLog, NumberSequence)
        )

    def test_public_html_and_api_reject_q_without_availability_result(self):
        values = {"part": "ABQ", "prefix": "M", "digit": "9"}
        before = self.counts()
        html = self.client.post("/", values)
        self.assertContains(html, "wyjątkiem Q")
        self.assertNotContains(html, 'id="availability-result"')
        api = self.client.get("/api/availability/", values)
        self.assertEqual(api.status_code, 400)
        self.assertIn("wyjątkiem Q", api.json()["error"])
        self.assertEqual(self.counts(), before)

    def test_request_service_rejects_q_before_any_business_write(self):
        before = self.counts()
        with self.assertRaisesMessage(ValidationError, "wyjątkiem Q"):
            create_request(self.county, data("P0ABQ"))
        self.assertEqual(self.counts(), before)

    def test_import_preview_and_commit_both_reject_q(self):
        row = {"number": "M9ABQ", "owner": "Osoba Fikcyjna", "office_id": self.county.office_id}
        preview = preview_import("number;owner;office_id\nM9ABQ;Osoba Fikcyjna;a\n")
        self.assertEqual(preview["rows"], [])
        self.assertIn("wyjątkiem Q", preview["errors"][0])
        before = self.counts()
        # Podgląd sporządzony przed aktualizacją też podlega ponownej walidacji.
        with self.assertRaisesMessage(ValidationError, "wyjątkiem Q"):
            apply_import(self.ump, [row])
        self.assertEqual(self.counts(), before)

    def test_m_can_be_chosen_before_p_is_exhausted(self):
        req = create_request(self.county, data("M9BIOZ"))
        self.assertEqual(req.record.number, "M9BIOZ")
        self.assertEqual(req.record.status, "RESERVED")
        api = self.client.get("/api/availability/", {"part": "BIOZ", "prefix": "M", "digit": "9"})
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.json()["digits"], [{"number": "M9BIOZ", "available": False}])

    def test_legacy_q_draft_cannot_be_submitted(self):
        req = create_request(self.county, data())
        PlateRecord.objects.filter(pk=req.record_id).update(number="P0ABQ")
        before = self.counts()
        with self.assertRaisesMessage(ValidationError, "wyjątkiem Q"):
            send_request(self.county, req.uuid)
        req.refresh_from_db()
        self.assertEqual(req.status, "DRAFT")
        self.assertEqual(req.record.status, "RESERVED")
        self.assertEqual(self.counts(), before)

    def test_legacy_q_sent_request_can_be_rejected_but_not_approved(self):
        req = create_request(self.county, data())
        send_request(self.county, req.uuid)
        PlateRecord.objects.filter(pk=req.record_id).update(number="P0ABQ")
        before = self.counts()
        with self.assertRaisesMessage(ValidationError, "wyjątkiem Q"):
            decide_request(self.ump, req.uuid, True)
        req.refresh_from_db()
        self.assertEqual(req.status, "SENT")
        self.assertEqual(self.counts(), before)
        decide_request(self.ump, req.uuid, False, "Nieprawidłowy alfabet wyróżnika.")
        req.refresh_from_db()
        self.assertEqual(req.status, "REJECTED")
        self.assertEqual(req.record.status, "RELEASED")

    def test_legacy_q_allocation_cannot_be_issued_but_can_be_released(self):
        req = create_request(self.county, data())
        send_request(self.county, req.uuid)
        decide_request(self.ump, req.uuid, True)
        PlateRecord.objects.filter(pk=req.record_id).update(number="P0ABQ")
        req.refresh_from_db()
        record = req.record
        before = self.counts()
        with self.assertRaisesMessage(ValidationError, "wyjątkiem Q"):
            update_record(
                self.county,
                record.uuid,
                {"vin": "WVWZZZ1JZXW000001", "registration_date": date(2026, 10, 3)},
                "Rejestracja",
                record.version,
            )
        record.refresh_from_db()
        self.assertEqual(record.status, "ALLOCATED")
        self.assertEqual(record.vin, "")
        self.assertEqual(self.counts(), before)
        update_record(self.ump, record.uuid, {"status": "RELEASED"}, "Niepoprawny numer", record.version)
        record.refresh_from_db()
        self.assertEqual(record.status, "RELEASED")
        with self.assertRaisesMessage(ValidationError, "wyjątkiem Q"):
            update_record(self.ump, record.uuid, {"status": "ALLOCATED"}, "Przywrócenie", record.version)
