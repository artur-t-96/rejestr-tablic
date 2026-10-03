from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import AuditLog
from .services import create_request, send_request, withdraw_request
from .tests import data, fixtures


class PlateLifecycleHistoryTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        self.req = create_request(self.a, data())

    def events(self):
        return AuditLog.objects.filter(object_type="PlateRecord", object_id=str(self.req.record_id))

    def test_submission_and_withdrawal_are_visible_in_plate_history(self):
        send_request(self.a, self.req.uuid, "192.0.2.1")
        submitted = self.events().get(action="plate.submitted")
        self.assertEqual(submitted.before, {"status": "RESERVED"})
        self.assertEqual(submitted.after, {"status": "SENT"})
        self.assertEqual(submitted.actor, self.a)
        self.assertEqual(submitted.ip, "192.0.2.1")
        with self.assertRaises(ValidationError):
            send_request(self.a, self.req.uuid)
        self.assertEqual(self.events().filter(action="plate.submitted").count(), 1)

        withdraw_request(self.a, self.req.uuid, "Rezygnacja testowa", "192.0.2.1")
        withdrawn = self.events().get(action="plate.withdrawn")
        self.assertEqual(withdrawn.before, {"status": "SENT"})
        self.assertEqual(withdrawn.after, {"status": "RELEASED"})
        self.assertEqual(withdrawn.reason, "Rezygnacja testowa")
        self.client.force_login(self.a)
        page = self.client.get(reverse("record_detail", args=[self.req.record.uuid]))
        self.assertContains(page, "plate.submitted")
        self.assertContains(page, "plate.withdrawn")
        self.assertContains(page, "Rezygnacja testowa")

    def test_draft_withdrawal_records_reserved_to_released_and_requires_reason(self):
        with self.assertRaises(ValidationError):
            withdraw_request(self.a, self.req.uuid, "")
        self.assertFalse(self.events().filter(action="plate.withdrawn").exists())
        withdraw_request(self.a, self.req.uuid, "Rezygnacja ze szkicu")
        event = self.events().get(action="plate.withdrawn")
        self.assertEqual(event.before, {"status": "RESERVED"})
        self.assertEqual(event.after, {"status": "RELEASED"})

    def test_audit_failure_rolls_back_both_statuses_and_version(self):
        initial_version = self.req.record.version
        initial_audits = AuditLog.objects.count()
        with patch("registry.services.audit", side_effect=RuntimeError("Testowa awaria audytu")):
            with self.assertRaises(RuntimeError):
                send_request(self.a, self.req.uuid)
        self.req.refresh_from_db()
        self.req.record.refresh_from_db()
        self.assertEqual(self.req.status, "DRAFT")
        self.assertEqual(self.req.record.status, "RESERVED")
        self.assertEqual(self.req.record.version, initial_version)
        self.assertEqual(AuditLog.objects.count(), initial_audits)
