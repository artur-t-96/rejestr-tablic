"""Izolacja aktualnej ewidencji od dokumentacji pierwotnego wnioskodawcy."""

from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog
from .services import create_request, decide_request, send_request, update_record
from .tests import data, fixtures


class OfficeTransferTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        self.req = create_request(self.a, data())
        self.record = self.req.record
        self.original_application_pdf = bytes(self.req.letters.get(kind="APPLICATION").pdf)

    def approve(self):
        send_request(self.a, self.req.uuid)
        decide_request(self.ump, self.req.uuid, True)
        self.record.refresh_from_db()

    def transfer(self):
        self.approve()
        self.record = update_record(
            self.ump,
            self.record.uuid,
            {
                "office_id": self.b.office_id,
                "owner": "Właściciel po przekazaniu TAJNY",
                "address": "Adres nowego właściciela TAJNY",
                "vin": "WVWZZZ1JZXW000001",
                "registration_date": timezone.localdate(),
                "status": "ISSUED",
            },
            "Zmiana urzędu i właściciela TAJNY",
            self.record.version,
        )

    def test_origin_request_keeps_history_without_current_foreign_personal_data(self):
        self.transfer()
        self.record = update_record(
            self.b,
            self.record.uuid,
            {"make": "Marka po przekazaniu TAJNY"},
            "Dane nowego urzędu TAJNY",
            self.record.version,
        )
        self.client.force_login(self.a)
        response = self.client.get(reverse("request_detail", args=[self.req.uuid]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.req.reference)
        for value in [
            "Właściciel po przekazaniu TAJNY",
            "Adres nowego właściciela TAJNY",
            "WVWZZZ1JZXW000001",
            "Zmiana urzędu i właściciela TAJNY",
            "Marka po przekazaniu TAJNY",
            "Dane nowego urzędu TAJNY",
        ]:
            self.assertNotContains(response, value)
        self.assertContains(response, "inny urząd")
        self.assertNotContains(response, reverse("record_detail", args=[self.record.uuid]))
        # Nadawca zachowuje niezmienne dokumenty swojej korespondencji.
        letter = self.req.letters.get(kind="APPLICATION")
        pdf = self.client.get(reverse("letter_pdf", args=[letter.uuid]))
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.content, self.original_application_pdf)
        self.req.refresh_from_db()
        self.assertEqual(self.req.office_id, self.a.office_id)
        self.assertEqual(self.req.author_id, self.a.pk)

    def test_previous_office_cannot_read_or_update_current_record(self):
        self.transfer()
        self.client.force_login(self.a)
        self.assertEqual(self.client.get(reverse("record_detail", args=[self.record.uuid])).status_code, 404)
        url = f"/api/records/{self.record.uuid}/"
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(
            self.client.patch(
                url,
                {"version": self.record.version, "reason": "Próba", "fields": {"make": "Zabronione"}},
                content_type="application/json",
            ).status_code,
            404,
        )
        self.record.refresh_from_db()
        self.assertEqual(self.record.make, "")
        exported = self.client.get(reverse("export_records"))
        self.assertEqual(exported.status_code, 200)
        self.assertNotContains(exported, self.record.number)
        self.assertNotContains(exported, "TAJNY")

    def test_current_office_and_ump_see_current_record_without_rewriting_origin_request(self):
        self.transfer()
        for user in (self.b, self.ump):
            self.client.force_login(user)
            detail = self.client.get(reverse("record_detail", args=[self.record.uuid]))
            self.assertContains(detail, "Właściciel po przekazaniu TAJNY")
            response = self.client.get(f"/api/records/{self.record.uuid}/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["office_id"], self.b.office_id)
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(reverse("request_detail", args=[self.req.uuid])).status_code, 404)
        self.client.force_login(self.ump)
        self.assertContains(
            self.client.get(reverse("request_detail", args=[self.req.uuid])),
            "Właściciel po przekazaniu TAJNY",
        )
        event = AuditLog.objects.get(action="plate.updated", object_id=str(self.record.pk))
        self.assertEqual(event.before["office_id"], self.a.office_id)
        self.assertEqual(event.after["office_id"], self.b.office_id)
        self.assertEqual(event.actor_id, self.ump.pk)

    def test_transfer_of_pending_request_is_rejected_without_mutation(self):
        for state in ("DRAFT", "SENT"):
            if state == "SENT":
                send_request(self.a, self.req.uuid)
            self.record.refresh_from_db()
            previous = self.record.version
            with self.assertRaisesMessage(ValidationError, "wniosek"):
                update_record(
                    self.ump,
                    self.record.uuid,
                    {"office_id": self.b.office_id, "owner": "Nie zapisuj"},
                    "Przekazanie w trakcie",
                    previous,
                )
            self.record.refresh_from_db()
            self.assertEqual(self.record.office_id, self.a.office_id)
            self.assertEqual(self.record.owner, "Osoba Fikcyjna")
            self.assertEqual(self.record.version, previous)
            self.assertFalse(AuditLog.objects.filter(action="plate.updated").exists())

    def test_inactive_target_is_rejected_for_service_and_api(self):
        self.approve()
        self.b.office.active = False
        self.b.office.save(update_fields=["active"])
        with self.assertRaisesMessage(ValidationError, "aktywny urząd"):
            update_record(
                self.ump,
                self.record.uuid,
                {"office_id": self.b.office_id},
                "Próba przekazania",
                self.record.version,
            )
        self.client.force_login(self.ump)
        response = self.client.patch(
            f"/api/records/{self.record.uuid}/",
            {"version": self.record.version, "reason": "Próba", "fields": {"office_id": self.b.office_id}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("aktywny urząd", response.json()["error"])
        self.record.refresh_from_db()
        self.assertEqual(self.record.office_id, self.a.office_id)

    def test_pending_transfer_via_api_is_rejected_without_changing_record(self):
        self.client.force_login(self.ump)
        response = self.client.patch(
            f"/api/records/{self.record.uuid}/",
            {
                "version": self.record.version,
                "reason": "Próba przekazania przed decyzją",
                "fields": {"office_id": self.b.office_id},
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("wniosek", response.json()["error"])
        self.record.refresh_from_db()
        self.assertEqual(self.record.office_id, self.a.office_id)
        self.assertFalse(AuditLog.objects.filter(action="plate.updated").exists())


class OfficeTransferConcurrencyTests(TransactionTestCase):
    # Prawdziwa kolejność dwóch transakcji: przekazanie trzyma blokadę,
    # zapis dawnego urzędu czeka, a po commit musi ponownie sprawdzić zakres.
    @skipUnlessDBFeature("has_select_for_update")
    def test_waiting_previous_office_cannot_save_after_transfer_commit(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from unittest.mock import patch

        from django.db import close_old_connections, connection

        from .models import PlateRecord, User
        from .services import audit as original_audit

        _, ump, a, b = fixtures()
        req = create_request(a, data())
        send_request(a, req.uuid)
        decide_request(ump, req.uuid, True)
        req.record.refresh_from_db()
        version = req.record.version
        transfer_locked, resume_transfer, previous_started = Event(), Event(), Event()
        worker_pid = []

        def pause_audit(actor, action, obj, *args, **kwargs):
            if action == "plate.updated" and actor.pk == ump.pk:
                transfer_locked.set()
                if not resume_transfer.wait(5):
                    raise TimeoutError("Nie wznowiono przekazania urzędu w teście.")
            return original_audit(actor, action, obj, *args, **kwargs)

        def transfer():
            close_old_connections()
            try:
                user = User.objects.get(pk=ump.pk)
                return update_record(
                    user, req.record.uuid, {"office_id": b.office_id}, "Przekazanie", version
                )
            finally:
                close_old_connections()

        def previous_save():
            close_old_connections()
            try:
                user = User.objects.get(pk=a.pk)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    worker_pid.append(cursor.fetchone()[0])
                previous_started.set()
                try:
                    update_record(user, req.record.uuid, {"make": "Zabronione"}, "Stary formularz", version)
                    return "saved"
                except PlateRecord.DoesNotExist:
                    return "not_found"
            finally:
                close_old_connections()

        with (
            patch("registry.services.audit", side_effect=pause_audit),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first = executor.submit(transfer)
            try:
                self.assertTrue(transfer_locked.wait(5))
                second = executor.submit(previous_save)
                self.assertTrue(previous_started.wait(5))
                waiting = False
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", worker_pid
                        )
                        result = cursor.fetchone()
                    if result and result[0] == "Lock":
                        waiting = True
                        break
                    time.sleep(0.02)
                self.assertTrue(waiting, "Nie potwierdzono oczekiwania na blokadę PostgreSQL.")
            finally:
                resume_transfer.set()
            first.result(timeout=5)
            self.assertEqual(second.result(timeout=5), "not_found")
        record = PlateRecord.objects.get(pk=req.record_id)
        self.assertEqual(record.office_id, b.office_id)
        self.assertEqual(record.make, "")
        self.assertEqual(record.version, version + 1)
