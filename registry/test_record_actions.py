import hashlib

from django.test import TestCase
from django.urls import reverse

from .imports import apply_source_import
from .models import AuditLog, PlateRecord
from .test_record_imports import csv_text, row
from .tests import fixtures


class RecordActionTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        self.record = PlateRecord.objects.create(
            number="P0TEST",
            owner="Osoba Fikcyjna",
            office=self.a.office,
            status="RELEASED",
            vin="WVWZZZ1JZXW000001",
            make="Marka",
            model="Model",
            registration_date="2025-01-01",
            sale_date="2025-02-01",
            buyer="Nabywca Fikcyjny",
            note="Dawna historia",
        )
        self.url = reverse("record_detail", args=[self.record.uuid])

    def test_county_sees_number_without_vehicle_data_and_cannot_post(self):
        # Uwagi UMP z 15.11.2026: ewidencja dotyczy przyznanych numerów, nie właścicieli i pojazdów.
        self.client.force_login(self.a)
        for status in PlateRecord.Status.values:
            self.record.status = status
            self.record.save(update_fields=["status"])
            before = PlateRecord.objects.values().get(pk=self.record.pk)
            response = self.client.get(self.url)
            self.assertContains(response, "P0 TEST")
            self.assertContains(response, "Dawna historia")
            for hidden in ("WVWZZZ1JZXW000001", "Osoba Fikcyjna", "Nabywca Fikcyjny", "01.02.2025"):
                self.assertNotContains(response, hidden)
            self.assertNotContains(response, "Zapisz zmianę")
            self.assertEqual(
                self.client.post(
                    self.url, {"vin": "WVWZZZ1JZXW000002", "reason": "Próba", "version": 1}
                ).status_code,
                403,
            )
            self.assertEqual(PlateRecord.objects.values().get(pk=self.record.pk), before)
        self.assertFalse(AuditLog.objects.exists())

    def test_main_corrects_office_letter_and_note_only(self):
        self.client.force_login(self.ump)
        for status in PlateRecord.Status.values:
            self.record.status = status
            self.record.save(update_fields=["status"])
            response = self.client.get(self.url)
            self.assertContains(response, "Zapisz zmianę")
            self.assertContains(response, 'name="note"')
            hidden = ("owner", "address", "vin", "make", "registration_date", "sale_date", "buyer", "status")
            for field in hidden:
                self.assertNotContains(response, f'name="{field}"')
            self.assertNotContains(response, "WVWZZZ1JZXW000001")
            self.assertNotContains(response, "rezerwac")
        response = self.client.post(
            self.url,
            {"office": "a", "letter_number": "", "note": "Nowa uwaga", "reason": "Korekta", "version": 1},
        )
        self.assertEqual(response.status_code, 302)
        self.record.refresh_from_db()
        # Dane pojazdu zostają w bazie bez zmian.
        self.assertEqual((self.record.note, self.record.vin), ("Nowa uwaga", "WVWZZZ1JZXW000001"))

    def test_import_source_is_readable_for_own_county_without_editing_released_history(self):
        text = csv_text([row("M9HIST", status="RELEASED", office_id="a", note="Historyczny wpis")])
        digest = hashlib.sha256(text.encode()).hexdigest()
        apply_source_import(self.ump, text, digest, "TEST: źródło HISTORY/01", filename="historia.csv")
        record = PlateRecord.objects.get(number="M9HIST")
        url = reverse("record_detail", args=[record.uuid])
        self.client.force_login(self.a)
        response = self.client.get(url)
        for text in (
            "Źródło historycznego wpisu",
            digest,
            "historia.csv",
            "HISTORY/01",
            "Data dawnego przydziału nie jest ustalona",
        ):
            self.assertContains(response, text)
        self.assertNotContains(response, "Zapisz zmianę")
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 403)
