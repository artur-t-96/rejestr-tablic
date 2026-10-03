"""Odbiór terminów rezerwacji: bezpośredni odczyt, historia i stały proces."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, Letter, PlateRecord, Request
from .services import audit, create_request, expire_reservations, send_request
from .tests import data, fixtures


class ReservationCompletionTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def overdue(self, sent=True):
        req = create_request(self.a, data())
        if sent:
            send_request(self.a, req.uuid)
        PlateRecord.objects.filter(pk=req.record_id).update(
            reservation_until=timezone.now() - timedelta(seconds=1)
        )
        return req

    def test_direct_request_page_expires_before_render_and_preserves_letters(self):
        req = self.overdue()
        original = bytes(req.letters.get().pdf)
        self.client.force_login(self.ump)
        page = self.client.get(reverse("request_detail", args=[req.uuid]))
        self.assertEqual(page.context["req"].status, "EXPIRED")
        self.assertNotContains(page, "Zapisz decyzję")
        self.assertNotContains(page, "Wycofaj wniosek")
        self.assertContains(page, "Termin rezerwacji upłynął")
        self.assertEqual(Letter.objects.count(), 1)
        self.assertEqual(bytes(req.letters.get().pdf), original)
        event = AuditLog.objects.get(action="request.expired")
        self.assertEqual(event.before["status"], "SENT")
        self.assertEqual(event.after["status"], "EXPIRED")
        self.assertEqual(event.office_id, self.a.office_id)
        self.assertIsNone(event.actor_id)
        self.assertEqual(event.reason, "Upłynął termin rezerwacji")
        self.client.get(reverse("request_detail", args=[req.uuid]))
        self.assertEqual(AuditLog.objects.filter(action="request.expired").count(), 1)

    def test_direct_record_page_removes_expired_reservation_actions(self):
        req = self.overdue()
        self.client.force_login(self.ump)
        page = self.client.get(reverse("record_detail", args=[req.record.uuid]))
        self.assertEqual(page.context["record"].status, "RELEASED")
        self.assertFalse(page.context["can_extend"])
        self.assertNotContains(page, "Przedłuż rezerwację")

    def test_request_list_and_api_do_not_keep_overdue_request_pending(self):
        req = self.overdue(False)
        self.client.force_login(self.a)
        page = self.client.get(reverse("requests_list"), {"status": "EXPIRED"})
        self.assertContains(page, req.reference)
        self.assertEqual(self.client.get("/api/requests/").json()["items"][0]["status"], "EXPIRED")

    def test_record_api_expires_before_read_without_prior_panel_visit(self):
        req = self.overdue()
        self.client.force_login(self.a)
        response = self.client.get(f"/api/records/{req.record.uuid}/")
        self.assertEqual(response.json()["status"], "RELEASED")
        req.refresh_from_db()
        self.assertEqual(req.status, "EXPIRED")

    def test_request_api_expires_without_prior_panel_visit(self):
        self.overdue()
        self.client.force_login(self.a)
        self.assertEqual(self.client.get("/api/requests/").json()["items"][0]["status"], "EXPIRED")

    def test_admin_is_denied_before_expiry_and_unknown_extension_target_is_404(self):
        req = self.overdue()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("request_detail", args=[req.uuid])).status_code, 403)
        self.assertEqual(self.client.get(reverse("record_detail", args=[req.record.uuid])).status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, "SENT")
        self.assertFalse(AuditLog.objects.filter(action="request.expired").exists())
        self.client.force_login(self.ump)
        self.assertEqual(
            self.client.post(
                reverse("reservation_extend", args=[uuid4()]), {"days": 7, "reason": "Fikcyjne"}
            ).status_code,
            404,
        )

    def test_expiry_audit_failure_rolls_back_both_states_and_history(self):
        req = self.overdue()
        before = AuditLog.objects.count()

        def fail_request_event(actor, action, *args, **kwargs):
            if action == "request.expired":
                raise RuntimeError("Fikcyjna awaria audytu")
            return audit(actor, action, *args, **kwargs)

        with patch("registry.services.audit", side_effect=fail_request_event):
            with self.assertRaises(RuntimeError):
                expire_reservations()
        req.refresh_from_db()
        req.record.refresh_from_db()
        self.assertEqual((req.status, req.record.status), ("SENT", "SENT"))
        self.assertEqual(AuditLog.objects.count(), before)

    def test_expiry_never_releases_allocated_issued_or_sold_records(self):
        for i, status in enumerate(["ALLOCATED", "ISSUED", "SOLD"]):
            PlateRecord.objects.create(
                number=f"P{i}SAFE",
                office=self.a.office,
                owner="Fikcyjne",
                status=status,
                reservation_until=timezone.now() - timedelta(days=1),
            )
        self.assertEqual(expire_reservations(), 0)
        self.assertEqual(
            list(PlateRecord.objects.order_by("number").values_list("status", flat=True)),
            ["ALLOCATED", "ISSUED", "SOLD"],
        )


class ReservationWatcherTests(TransactionTestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_watcher_expires_without_read_request_and_stops_on_interrupt(self):
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        PlateRecord.objects.filter(pk=req.record_id).update(
            reservation_until=timezone.now() - timedelta(seconds=1)
        )
        output = StringIO()
        with patch(
            "registry.management.commands.expire_reservations.time.sleep", side_effect=KeyboardInterrupt
        ):
            call_command("expire_reservations", watch=True, interval=1, stdout=output)
        req.refresh_from_db()
        self.assertEqual(req.status, "EXPIRED")
        self.assertEqual(AuditLog.objects.filter(action="request.expired").count(), 1)
        self.assertIn("Zwolniono 1 rezerwacji", output.getvalue())
        self.assertIn("zatrzymany", output.getvalue())
        call_command("expire_reservations", stdout=StringIO())
        self.assertEqual(AuditLog.objects.filter(action="request.expired").count(), 1)

    def test_invalid_interval_fails_before_processing(self):
        for value in [0, -1, 3601]:
            with self.subTest(value=value), self.assertRaises(CommandError):
                call_command("expire_reservations", watch=True, interval=value, stdout=StringIO())
        self.assertFalse(Request.objects.exists())


class ReservationExpiryConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_two_expiry_workers_write_each_status_and_audit_once(self):
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        PlateRecord.objects.filter(pk=req.record_id).update(
            reservation_until=timezone.now() - timedelta(seconds=1)
        )
        ready = Barrier(2)

        def expire():
            close_old_connections()
            try:
                ready.wait(timeout=5)
                return expire_reservations()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [f.result(timeout=5) for f in [executor.submit(expire), executor.submit(expire)]]
        self.assertEqual(sorted(results), [0, 1])
        req.refresh_from_db()
        req.record.refresh_from_db()
        self.assertEqual((req.status, req.record.status), ("EXPIRED", "RELEASED"))
        self.assertEqual(AuditLog.objects.filter(action="reservation.expired").count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="request.expired").count(), 1)
        self.assertEqual(Letter.objects.count(), 1)
