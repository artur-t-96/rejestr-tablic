import json

from django.test import TestCase

from .models import AuditLog, IntegrationJob, Letter, NumberSequence, PlateRecord, Pool, PoolSlot, Request
from .tests import fixtures


class RecordApiValidationTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.county, self.other = fixtures()
        self.record = PlateRecord.objects.create(
            number="P0TEST",
            office=self.county.office,
            owner="Osoba Fikcyjna",
            status="SOLD",
            vin="WVWZZZ1JZXW000001",
            registration_date="2025-01-01",
            sale_date="2025-02-01",
            buyer="Nabywca Fikcyjny",
        )
        self.url = f"/api/records/{self.record.uuid}/"
        self.client.force_login(self.county)

    def patch(self, payload):
        return self.client.patch(self.url, json.dumps(payload), content_type="application/json")

    def assert_rejected_without_changes(self, payload):
        before = PlateRecord.objects.values().get(pk=self.record.pk)
        audits = list(AuditLog.objects.values())
        response = self.patch(payload)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("error", response.json())
        self.assertEqual(PlateRecord.objects.values().get(pk=self.record.pk), before)
        self.assertEqual(list(AuditLog.objects.values()), audits)

    def test_invalid_sale_date_cannot_clear_existing_date_or_change_status(self):
        self.assert_rejected_without_changes(
            {"fields": {"sale_date": "niepoprawna data"}, "reason": "Korekta", "version": 1}
        )

    def test_json_body_must_be_an_object(self):
        for payload in (None, [], "tekst", 1, True):
            with self.subTest(payload=payload):
                self.assert_rejected_without_changes(payload)

    def test_invalid_calendar_dates_and_non_string_values_are_rejected_atomically(self):
        for field in ("sale_date", "registration_date"):
            for value in (
                "2025-02-30",
                "0000-01-01",
                "2025-13-01",
                "20250101",
                "2025-1-1",
                "2025-01-01T00:00:00",
                " 2025-01-01",
                "2025-W01-1",
                [],
                {},
                0,
                1,
                False,
                True,
            ):
                with self.subTest(field=field, value=value):
                    self.assert_rejected_without_changes(
                        {"fields": {field: value, "make": "Nowa marka"}, "reason": "Korekta", "version": 1}
                    )

    def test_fields_and_reason_have_explicit_types(self):
        for fields in (None, [], "sale_date", 1, True, {}):
            with self.subTest(fields=fields):
                self.assert_rejected_without_changes({"fields": fields, "reason": "Korekta", "version": 1})
        for reason in (None, [], {}, 0, False, "", "   "):
            with self.subTest(reason=reason):
                self.assert_rejected_without_changes(
                    {"fields": {"make": "Marka"}, "reason": reason, "version": 1}
                )

    def test_version_cannot_be_coerced_from_boolean_float_or_text(self):
        for version in (None, True, False, 1.0, "1", "1.0", 0, -1, [], {}):
            with self.subTest(version=version):
                self.assert_rejected_without_changes(
                    {"fields": {"make": "Marka"}, "reason": "Korekta", "version": version}
                )

    def test_missing_keys_are_rejected(self):
        payload = {"fields": {"make": "Marka"}, "reason": "Korekta", "version": 1}
        for key in payload:
            with self.subTest(key=key):
                self.assert_rejected_without_changes({k: v for k, v in payload.items() if k != key})

    def test_text_fields_cannot_silently_store_json_structures(self):
        self.client.force_login(self.ump)
        for field in (
            "owner",
            "address",
            "office_id",
            "status",
            "vin",
            "make",
            "model",
            "buyer",
            "letter_number",
            "note",
        ):
            for value in (None, [], {}, True, 1):
                with self.subTest(field=field, value=value):
                    self.assert_rejected_without_changes(
                        {"fields": {field: value}, "reason": "Korekta", "version": 1}
                    )

    def test_valid_date_correction_records_exact_before_and_after(self):
        response = self.patch({"fields": {"sale_date": "2025-02-28"}, "reason": "Poprawa daty", "version": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sale_date"], "2025-02-28")
        self.assertEqual(response.json()["status"], "SOLD")
        self.assertEqual(response.json()["version"], 2)
        audit = AuditLog.objects.get(action="plate.updated")
        self.assertEqual(audit.before["sale_date"], "2025-02-01")
        self.assertEqual(audit.after["sale_date"], "2025-02-28")
        self.assertEqual(audit.reason, "Poprawa daty")
        self.assertEqual(audit.actor_id, self.county.pk)

    def test_explicit_sale_date_clear_remains_available_with_reason(self):
        for value in (None, ""):
            with self.subTest(value=value):
                self.record.refresh_from_db()
                response = self.patch(
                    {
                        "fields": {"sale_date": value},
                        "reason": "Usunięcie błędnie odnotowanej sprzedaży",
                        "version": self.record.version,
                    }
                )
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.json()["sale_date"])
                self.assertEqual(response.json()["status"], "ISSUED")
        self.assertEqual(AuditLog.objects.filter(action="plate.updated").count(), 2)

    def test_invalid_business_chronology_and_stale_version_preserve_state(self):
        for fields, version in (
            ({"sale_date": "2024-12-31"}, 1),
            ({"registration_date": None}, 1),
            ({"make": "Zmiana"}, 2),
        ):
            with self.subTest(fields=fields, version=version):
                self.assert_rejected_without_changes(
                    {"fields": fields, "reason": "Korekta", "version": version}
                )

    def test_partial_patch_preserves_dates(self):
        response = self.patch(
            {"fields": {"make": "Marka poprawiona"}, "reason": "Korekta marki", "version": 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["registration_date"], "2025-01-01")
        self.assertEqual(response.json()["sale_date"], "2025-02-01")
        self.assertEqual(response.json()["status"], "SOLD")

    def test_access_and_field_permissions_still_apply(self):
        before = PlateRecord.objects.values().get(pk=self.record.pk)
        payload = {"fields": {"make": "Zmiana"}, "reason": "Korekta", "version": 1}
        for user, status in ((self.other, 404), (self.admin, 403)):
            self.client.force_login(user)
            self.assertEqual(self.patch(payload).status_code, status)
        self.client.logout()
        self.assertEqual(self.patch(payload).status_code, 401)
        self.client.force_login(self.county)
        for field in ("number", "owner", "office_id", "status", "unknown"):
            self.assertEqual(self.patch({**payload, "fields": {field: "Zmiana"}}).status_code, 403)
        self.assertEqual(PlateRecord.objects.values().get(pk=self.record.pk), before)
        self.assertFalse(AuditLog.objects.exists())

    def test_non_object_bodies_are_rejected_by_other_write_endpoints(self):
        models = (Request, PlateRecord, Letter, Pool, PoolSlot, NumberSequence, IntegrationJob, AuditLog)
        before = [list(model.objects.order_by("pk").values()) for model in models]
        for url in (
            "/api/requests/",
            "/api/pools/",
            f"/api/requests/{self.record.uuid}/withdraw/",
            f"/api/pools/{self.record.uuid}/issue/",
        ):
            for payload in (None, [], [1], "tekst", True, 1):
                with self.subTest(url=url, payload=payload):
                    response = self.client.post(url, json.dumps(payload), content_type="application/json")
                    self.assertEqual(response.status_code, 400, response.content)
                    self.assertIn("obiektem JSON", response.json()["error"])
        self.assertEqual([list(model.objects.order_by("pk").values()) for model in models], before)

    def test_malformed_json_is_rejected_without_changes(self):
        before = PlateRecord.objects.values().get(pk=self.record.pk)
        response = self.client.patch(self.url, '{"fields":', content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PlateRecord.objects.values().get(pk=self.record.pk), before)
        self.assertFalse(AuditLog.objects.exists())
