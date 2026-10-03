"""Method contract at every URL, including rejection before PDF audit/body parsing."""

import re

from django.test import TestCase

from config.urls import urlpatterns

from .models import AuditLog, IntegrationJob, Letter, NumberSequence, PlateRecord, Pool, PoolSlot, Request
from .services import create_request
from .tests import data, fixtures

METHODS = {
    "public": ("GET", "POST"),
    "login_email": ("GET", "POST"),
    "login_code": ("GET", "POST"),
    "logout_view": ("POST",),
    "dashboard": ("GET",),
    "requests_list": ("GET",),
    "request_new": ("GET", "POST"),
    "request_detail": ("GET", "POST"),
    "request_action": ("POST",),
    "records_list": ("GET",),
    "record_detail": ("GET", "POST"),
    "reservation_extend": ("POST",),
    "export_records": ("GET",),
    "import_records": ("GET", "POST"),
    "import_pools": ("GET", "POST"),
    "pools_list": ("GET",),
    "pool_new": ("GET", "POST"),
    "pool_detail": ("GET", "POST"),
    "letters_list": ("GET",),
    "letter_pdf": ("GET",),
    "letter_sign": ("GET", "POST"),
    "letter_revision": ("GET", "POST"),
    "letter_send": ("POST",),
    "letter_ezd": ("GET", "POST"),
    "audit_list": ("GET",),
    "integrations": ("GET",),
    "ezd_incoming": ("GET", "POST"),
    "ezd_incoming_publish": ("POST",),
    "ezd_incoming_pdf": ("GET",),
    "edor_search": ("GET", "POST"),
    "edor_resume": ("GET", "POST"),
    "delivery_evidence": ("GET",),
    "admin_panel": ("GET",),
    "account_invitations": ("GET", "POST"),
    "admin_edit": ("GET", "POST"),
    "health": ("GET",),
    "session_status": ("GET",),
    "session_extend": ("POST",),
    "api_availability": ("GET",),
    "public_challenge": ("GET",),
    "api_requests": ("GET", "POST"),
    "api_request_action": ("POST",),
    "api_record": ("GET", "PATCH"),
    "api_pools": ("GET", "POST"),
    "api_slot": ("POST",),
}


class HttpMethodContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.ump, cls.county, cls.other = fixtures()
        cls.request = create_request(cls.county, data())
        cls.letter = cls.request.letters.get()

    def snapshot(self):
        return [
            list(model.objects.order_by("pk").values())
            for model in (
                Request,
                PlateRecord,
                Letter,
                Pool,
                PoolSlot,
                NumberSequence,
                IntegrationJob,
                AuditLog,
            )
        ]

    def test_delete_cannot_download_pdf_or_append_download_audit(self):
        self.client.force_login(self.county)
        before = self.snapshot()
        response = self.client.delete(f"/panel/pisma/{self.letter.uuid}/pdf/")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "GET")
        self.assertEqual(self.snapshot(), before)
        response = self.client.get(f"/panel/pisma/{self.letter.uuid}/pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, bytes(self.letter.pdf))
        self.assertEqual(AuditLog.objects.filter(action="letter.downloaded").count(), 1)

    def test_unsupported_api_method_is_rejected_before_reading_invalid_json(self):
        self.client.force_login(self.county)
        before = self.snapshot()
        for body in ("", "not-json", "[]", '{"owner":NaN}'):
            with self.subTest(body=body):
                response = self.client.delete("/api/requests/", body, content_type="application/json")
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response["Allow"], "GET, POST")
        self.assertEqual(self.snapshot(), before)

    def test_method_control_preserves_api_authentication_and_role_checks(self):
        response = self.client.delete("/api/requests/", "not-json", content_type="application/json")
        self.assertEqual(response.status_code, 401)
        self.client.force_login(self.admin)
        response = self.client.delete("/api/requests/", "not-json", content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_every_configured_url_rejects_methods_outside_its_contract_without_business_writes(self):
        self.assertEqual({pattern.callback.__name__ for pattern in urlpatterns}, set(METHODS))
        self.client.force_login(self.ump)
        before = self.snapshot()
        all_methods = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE")
        checked = 0
        for pattern in urlpatterns:
            allowed = METHODS[pattern.callback.__name__]
            values = {
                "uuid": str(self.letter.uuid),
                "action": "withdraw",
                "kind": "user",
                "pk": str(self.county.pk),
                "user_pk": str(self.county.pk),
                "evidence_pk": "1",
            }
            path = "/" + re.sub(r"<[^:>]+:([^>]+)>", lambda m: values[m[1]], pattern.pattern._route)
            for method in all_methods:
                if method in allowed:
                    continue
                with self.subTest(path=path, method=method):
                    response = self.client.generic(
                        method, path, data="not-json", content_type="application/json"
                    )
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response["Allow"], ", ".join(allowed))
                checked += 1
        self.assertGreater(checked, 250)
        self.assertEqual(self.snapshot(), before)
