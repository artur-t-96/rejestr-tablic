"""Zbycie pojazdu: przeniesienie wpisu do innego urzędu jest czymś innym niż zwolnienie numeru."""

from importlib import import_module

from django.apps import apps
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, LetterTemplate, Office, PlateRecord
from .services import create_request, decide_request, send_request, transfer_record, update_record
from .tests import data, fixtures

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


def taken(number):
    return PlateRecord.objects.exclude(status="RELEASED").filter(number=number).exists()


@override_settings(EMAIL_BACKEND=LOCMEM)
class RecordTransferTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        Office.objects.filter(pk="b").update(email="b-kontakt@test.invalid")
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        decide_request(self.ump, req.uuid, True)
        self.record = PlateRecord.objects.get(pk=req.record_id)
        self.url = reverse("record_detail", args=[self.record.uuid])

    def sell(self):
        today = timezone.localdate()
        self.record = update_record(
            self.a,
            self.record.uuid,
            {
                "vin": "WVWZZZ1JZXW000001",
                "registration_date": today,
                "sale_date": today,
                "buyer": "Nabywca Fikcyjny",
            },
            "Zbycie pojazdu",
            self.record.version,
        )
        self.assertEqual(self.record.status, "SOLD")

    def post_transfer(self, **overrides):
        payload = {
            "transfer-office": "b",
            "transfer-owner": "Nabywca Fikcyjny",
            "transfer-address": "Adres w B",
            "transfer-reason": "Pojazd zarejestrowany w urzędzie B",
            "transfer-version": self.record.version,
            **overrides,
        }
        return self.client.post(reverse("record_transfer", args=[self.record.uuid]), payload, follow=True)

    def test_sold_vehicle_page_offers_transfer_and_release_as_separate_actions(self):
        self.sell()
        self.client.force_login(self.ump)
        page = self.client.get(self.url)
        self.assertContains(page, "Pojazd zbyty — co dalej z numerem?")
        self.assertContains(page, "Przenieś do innego urzędu")
        self.assertContains(page, "numer pozostaje zajęty")
        self.assertContains(page, "Zwolnij numer")
        self.assertContains(page, reverse("record_transfer", args=[self.record.uuid]))
        self.assertContains(page, reverse("record_release", args=[self.record.uuid]))
        # Nabywca jest podpowiedzią nowego właściciela; obecny urząd nie jest celem przeniesienia.
        self.assertContains(page, 'value="Nabywca Fikcyjny"')
        offices = list(page.context["transfer_form"].fields["office"].queryset.values_list("pk", flat=True))
        self.assertEqual(offices, ["b"])
        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard, "Pojazdy zbyte — do przeniesienia lub zwolnienia numeru")
        self.client.force_login(self.a)
        page = self.client.get(self.url)
        self.assertNotContains(page, "Przenieś do innego urzędu")
        self.assertNotContains(page, "Zwolnij numer")

    def test_transfer_moves_record_to_new_office_and_keeps_number_taken(self):
        self.sell()
        self.client.force_login(self.ump)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post_transfer()
        self.assertContains(response, "Wpis przeniesiony do urzędu Urząd B. Numer pozostaje zajęty.")
        self.record.refresh_from_db()
        self.assertEqual(
            (self.record.office_id, self.record.status, self.record.owner, self.record.address),
            ("b", "ISSUED", "Nabywca Fikcyjny", "Adres w B"),
        )
        self.assertEqual((self.record.sale_date, self.record.buyer), (None, ""))
        self.assertEqual(self.record.vin, "WVWZZZ1JZXW000001")
        self.assertTrue(taken(self.record.number))
        event = AuditLog.objects.get(action="plate.transferred", object_id=str(self.record.pk))
        self.assertEqual((event.before["office_id"], event.after["office_id"]), ("a", "b"))
        self.assertEqual((event.before["status"], event.after["status"]), ("SOLD", "ISSUED"))
        self.assertEqual(event.before["buyer"], "Nabywca Fikcyjny")
        self.assertEqual(event.reason, "Pojazd zarejestrowany w urzędzie B")
        self.assertFalse(AuditLog.objects.filter(action="plate.released").exists())
        # Nowy urząd dostaje informację bez danych właściciela i pojazdu.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["b-kontakt@test.invalid"])
        self.assertIn("Numer pozostaje zajęty", mail.outbox[0].body)
        self.assertNotIn("Nabywca Fikcyjny", mail.outbox[0].body)
        self.assertNotIn("WVWZZZ1JZXW000001", mail.outbox[0].body)
        # Nowy urząd prowadzi wpis dalej, poprzedni traci dostęp do aktualnych danych.
        self.client.force_login(self.b)
        self.assertContains(self.client.get(self.url), "Nabywca Fikcyjny")
        self.client.force_login(self.a)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_transfer_without_contact_address_is_recorded(self):
        self.sell()
        Office.objects.filter(pk="b").update(email="")
        with self.captureOnCommitCallbacks(execute=True):
            transfer_record(
                self.ump, self.record.uuid, {"office_id": "b"}, "Przeniesienie", self.record.version
            )
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(AuditLog.objects.filter(action="plate.transfer_notice_skipped").exists())
        # Bez wpisanego właściciela nowym właścicielem zostaje nabywca ze zbycia.
        self.assertEqual(PlateRecord.objects.get(pk=self.record.pk).owner, "Nabywca Fikcyjny")

    def test_transfer_is_refused_without_changes(self):
        self.sell()
        before = PlateRecord.objects.filter(pk=self.record.pk).values().get()
        cases = (
            ({"office_id": "a"}, "inny niż obecny"),
            ({"office_id": "ump"}, "aktywny urząd wnioskujący"),
            ({"office_id": "brak"}, "aktywny urząd wnioskujący"),
        )
        for values, message in cases:
            with self.subTest(values=values), self.assertRaisesRegex(ValidationError, message):
                transfer_record(self.ump, self.record.uuid, values, "Powód", self.record.version)
        with self.assertRaisesRegex(ValidationError, "zmienił się"):
            transfer_record(self.ump, self.record.uuid, {"office_id": "b"}, "Powód", self.record.version - 1)
        with self.assertRaisesRegex(ValidationError, "powód"):
            transfer_record(self.ump, self.record.uuid, {"office_id": "b"}, " ", self.record.version)
        with self.assertRaises(PermissionDenied):
            transfer_record(self.a, self.record.uuid, {"office_id": "b"}, "Powód", self.record.version)
        PlateRecord.objects.filter(pk=self.record.pk).update(buyer="")
        with self.assertRaisesRegex(ValidationError, "nowego właściciela"):
            transfer_record(self.ump, self.record.uuid, {"office_id": "b"}, "Powód", self.record.version)
        PlateRecord.objects.filter(pk=self.record.pk).update(buyer=before["buyer"])
        self.assertEqual(PlateRecord.objects.filter(pk=self.record.pk).values().get(), before)
        self.assertFalse(AuditLog.objects.filter(action="plate.transferred").exists())

    def test_reserved_number_cannot_be_transferred_or_released(self):
        req = create_request(self.a, data("P1TEST"))
        record = req.record
        with self.assertRaisesRegex(ValidationError, "przydzielony, wydany albo"):
            transfer_record(self.ump, record.uuid, {"office_id": "b", "owner": "X"}, "Powód", record.version)
        self.client.force_login(self.ump)
        page = self.client.get(reverse("record_detail", args=[record.uuid]))
        self.assertNotContains(page, "Przenieś do innego urzędu")
        response = self.client.post(
            reverse("record_release", args=[record.uuid]),
            {"release-reason": "Powód", "release-version": record.version},
            follow=True,
        )
        self.assertContains(response, "Zwolnić można tylko wpis przydzielony")
        self.assertEqual(PlateRecord.objects.get(pk=record.pk).status, "RESERVED")

    def test_county_cannot_use_transfer_or_release(self):
        self.sell()
        self.client.force_login(self.a)
        self.assertEqual(self.post_transfer().status_code, 403)
        response = self.client.post(
            reverse("record_release", args=[self.record.uuid]),
            {"release-reason": "Powód", "release-version": self.record.version},
        )
        self.assertEqual(response.status_code, 403)
        self.record.refresh_from_db()
        self.assertEqual((self.record.office_id, self.record.status), ("a", "SOLD"))

    def test_release_returns_number_to_free_pool(self):
        self.sell()
        self.client.force_login(self.ump)
        response = self.client.post(
            reverse("record_release", args=[self.record.uuid]),
            {"release-reason": "Właściciel zrezygnował z numeru", "release-version": self.record.version},
            follow=True,
        )
        self.assertContains(response, "Numer zwolniony i wrócił do puli wolnych numerów.")
        self.record.refresh_from_db()
        self.assertEqual((self.record.status, self.record.office_id), ("RELEASED", "a"))
        event = AuditLog.objects.get(action="plate.released")
        self.assertEqual((event.before["status"], event.after["status"]), ("SOLD", "RELEASED"))
        self.assertFalse(taken(self.record.number))
        missing = self.client.post(
            reverse("record_release", args=[self.record.uuid]),
            {"release-reason": "", "release-version": self.record.version},
            follow=True,
        )
        self.assertContains(missing, "Podaj powód zwolnienia numeru.")


class NeutralWordingTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_ump_screens_do_not_call_the_answer_a_decision(self):
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        for user in (self.a, self.ump):
            self.client.force_login(user)
            for url in (
                reverse("dashboard"),
                reverse("requests_list"),
                reverse("requests_list") + "?status=SENT",
                reverse("request_detail", args=[req.uuid]),
            ):
                with self.subTest(user=user.email, url=url):
                    page = self.client.get(url).content.decode()
                    self.assertNotRegex(page.lower(), r"decyzj|decyzę")
        page = self.client.get(reverse("request_detail", args=[req.uuid]))
        self.assertContains(page, "Oczekuje na rozpatrzenie")
        self.assertContains(page, "Zapisz uzasadnienie")
        self.assertContains(page, "Stanowisko UMP")
        self.client.force_login(self.a)
        self.assertContains(self.client.get(reverse("requests_list")), "Oczekuje na rozpatrzenie")

    def test_migration_updates_only_unchanged_approval_template(self):
        migration = import_module("registry.migrations.0014_neutral_wording")
        template = LetterTemplate.objects.create(
            kind="APPROVAL", title=migration.APPROVAL_TITLE, body=migration.PREVIOUS_BODY, revision=2
        )
        own = LetterTemplate.objects.create(
            kind="REJECTION", title="Własny", body="Uzasadnienie decyzji: ${reason}"
        )
        migration.update_defaults(apps, None)
        migration.update_defaults(apps, None)
        template.refresh_from_db()
        self.assertEqual((template.body, template.revision), (migration.NEUTRAL_BODY, 3))
        self.assertNotIn("decyzji", template.body)
        own.refresh_from_db()
        self.assertEqual(own.body, "Uzasadnienie decyzji: ${reason}")
        self.assertEqual(AuditLog.objects.filter(action="template.default.updated").count(), 1)
        migration.restore_defaults(apps, None)
        template.refresh_from_db()
        self.assertEqual((template.body, template.revision), (migration.PREVIOUS_BODY, 2))

    def test_approval_letter_has_no_decision_wording(self):
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        decide_request(self.ump, req.uuid, True, "Numer zgodny z zasadami")
        letter = req.letters.get(kind="APPROVAL")
        self.assertIn("Uzasadnienie: Numer zgodny z zasadami", letter.body)
        self.assertNotIn("decyzj", letter.body.lower())
