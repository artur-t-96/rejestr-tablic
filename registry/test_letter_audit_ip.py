from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, Letter, Request
from .services import create_request, send_request
from .tests import data, fixtures


class LetterAuditIpTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.county, self.other = fixtures()

    def assert_letter_event(self, letter, actor, address):
        event = AuditLog.objects.get(
            action="letter.generated", object_type="Letter", object_id=str(letter.pk)
        )
        self.assertEqual(event.actor_id, actor.pk)
        self.assertEqual(event.ip, address)
        self.assertEqual(event.after, {"number": letter.number, "sha256": letter.sha256})

    def test_html_and_api_applications_keep_remote_address_not_forwarded_header(self):
        self.client.force_login(self.county)
        for index, address in enumerate(("192.0.2.10", "2001:db8::10")):
            with self.subTest(address=address):
                values = data(f"P{index}AUDYT")
                if index == 0:
                    response = self.client.post(
                        reverse("request_new"),
                        values,
                        REMOTE_ADDR=address,
                        HTTP_X_FORWARDED_FOR="198.51.100.99",
                    )
                    self.assertEqual(response.status_code, 302)
                    req = Request.objects.get(record__number=values["number"])
                else:
                    response = self.client.post(
                        "/api/requests/",
                        values,
                        content_type="application/json",
                        REMOTE_ADDR=address,
                        HTTP_X_FORWARDED_FOR="198.51.100.99",
                    )
                    self.assertEqual(response.status_code, 201, response.content)
                    req = Request.objects.get(uuid=response.json()["id"])
                self.assert_letter_event(req.letters.get(kind="APPLICATION"), self.county, address)

    def test_individual_approval_and_rejection_keep_deciding_address(self):
        for index, approve in enumerate((True, False)):
            with self.subTest(approve=approve):
                req = create_request(self.county, data(f"P{index}AUDYT"), ip="192.0.2.10")
                send_request(self.county, req.uuid)
                old_events = list(AuditLog.objects.order_by("pk").values())
                self.client.force_login(self.ump)
                response = self.client.post(
                    f"/api/requests/{req.uuid}/decide/",
                    {"approve": approve, "reason": "Odbiór audytu decyzji"},
                    content_type="application/json",
                    REMOTE_ADDR="2001:db8::20",
                )
                self.assertEqual(response.status_code, 200, response.content)
                self.assert_letter_event(
                    req.letters.get(kind="APPROVAL" if approve else "REJECTION"),
                    self.ump,
                    "2001:db8::20",
                )
                self.assertEqual(
                    list(
                        AuditLog.objects.filter(pk__in=[e["id"] for e in old_events]).order_by("pk").values()
                    ),
                    old_events,
                )

    def test_pool_decisions_keep_address_through_nested_allocation(self):
        for kind, prefix in (("II", "P"), ("III", "P0")):
            with self.subTest(kind=kind):
                req = create_request(
                    self.county,
                    {
                        "kind": kind,
                        "count": 2,
                        "case_number": "AUDYT/1",
                        "justification": "Odbiór audytu przydziału",
                    },
                )
                send_request(self.county, req.uuid)
                self.client.force_login(self.ump)
                response = self.client.post(
                    f"/api/requests/{req.uuid}/decide/",
                    {
                        "approve": True,
                        "pool": {
                            "prefix": prefix,
                            "start": 1,
                            "end": 2,
                            "valid_from": timezone.localdate().isoformat(),
                            "valid_until": timezone.localdate().isoformat(),
                        },
                    },
                    content_type="application/json",
                    REMOTE_ADDR="192.0.2.20",
                )
                self.assertEqual(response.status_code, 200, response.content)
                self.assert_letter_event(req.letters.get(kind="POOL"), self.ump, "192.0.2.20")

    def test_direct_pool_allocation_keeps_remote_address(self):
        self.client.force_login(self.ump)
        response = self.client.post(
            "/api/pools/",
            {
                "kind": "II",
                "office": self.county.office_id,
                "prefix": "P",
                "start": 1,
                "end": 2,
                "valid_from": timezone.localdate().isoformat(),
            },
            content_type="application/json",
            REMOTE_ADDR="192.0.2.30",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assert_letter_event(Letter.objects.get(pool__uuid=response.json()["id"]), self.ump, "192.0.2.30")

    def test_service_without_http_context_does_not_invent_an_address(self):
        req = create_request(self.county, data())
        self.assert_letter_event(req.letters.get(), self.county, None)

    def test_failed_otp_mail_keeps_request_address_without_claiming_login(self):
        with patch("registry.views.send_mail", side_effect=RuntimeError("Błąd testowego SMTP")):
            response = self.client.post(
                reverse("login_email"), {"email": self.county.email}, REMOTE_ADDR="192.0.2.60"
            )
        self.assertEqual(response.status_code, 302)
        event = AuditLog.objects.get(action="auth.mail_failed")
        self.assertEqual(event.ip, "192.0.2.60")
        self.assertIsNone(event.actor_id)
        self.assertFalse(AuditLog.objects.filter(action="auth.login").exists())
