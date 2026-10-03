import hashlib
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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

    def test_county_readonly_states_preserve_data_and_reject_direct_posts(self):
        self.client.force_login(self.a)
        for status in ("RESERVED", "SENT", "RELEASED"):
            self.record.status = status
            self.record.save(update_fields=["status"])
            before = PlateRecord.objects.values().get(pk=self.record.pk)
            response = self.client.get(self.url)
            self.assertContains(response, "Dawna historia")
            self.assertContains(response, "WVWZZZ1JZXW000001")
            self.assertContains(response, "01.02.2025")
            self.assertNotContains(response, "Zapisz zmianę")
            self.assertNotContains(response, 'name="vin"')
            self.assertContains(
                response, "pozostają historią" if status == "RELEASED" else "po przydziale numeru"
            )
            self.assertEqual(
                self.client.post(
                    self.url, {"vin": "WVWZZZ1JZXW000002", "reason": "Próba", "version": 1}
                ).status_code,
                403,
            )
            self.assertEqual(PlateRecord.objects.values().get(pk=self.record.pk), before)
        self.assertFalse(AuditLog.objects.exists())

    def test_county_vehicle_fields_remain_available_after_allocation(self):
        self.client.force_login(self.a)
        for status in ("ALLOCATED", "ISSUED", "SOLD"):
            self.record.status = status
            self.record.save(update_fields=["status"])
            response = self.client.get(self.url)
            self.assertContains(response, "Zapisz zmianę")
            self.assertContains(response, 'name="vin"')
            self.assertNotContains(response, 'name="owner"')
            self.assertNotContains(response, 'name="status"')

    def test_main_can_correct_every_status_but_extend_only_live_reservations(self):
        self.client.force_login(self.ump)
        for status in PlateRecord.Status.values:
            self.record.status = status
            self.record.reservation_until = timezone.now() + timedelta(days=1)
            self.record.save(update_fields=["status", "reservation_until"])
            response = self.client.get(self.url)
            self.assertContains(response, "Zapisz zmianę")
            self.assertContains(response, 'name="owner"')
            if status in ("RESERVED", "SENT"):
                self.assertContains(response, "Przedłuż rezerwację")
            else:
                self.assertNotContains(response, "Przedłuż rezerwację")
        self.record.status = "SENT"
        self.record.reservation_until = timezone.now() - timedelta(seconds=1)
        self.record.save(update_fields=["status", "reservation_until"])
        self.assertNotContains(self.client.get(self.url), "Przedłuż rezerwację")

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
