from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, IntegrationJob, Letter, NumberSequence, PlateRecord, Pool, PoolSlot, Request
from .services import allocate_pool, create_request, issue_slot, send_request
from .tests import data, fixtures


class ApiOperationValidationTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.county, self.other = fixtures()
        self.client.force_login(self.county)

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

    def rejected(self, url, payload):
        before = self.snapshot()
        response = self.client.post(url, payload, content_type="application/json")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self.snapshot(), before)

    def pool(self):
        return allocate_pool(
            self.ump,
            {
                "office": self.county.office_id,
                "kind": "II",
                "prefix": "P",
                "start": 1,
                "end": 2,
                "valid_from": timezone.localdate(),
            },
        )

    def test_case_number_null_returns_validation_error_without_issuing(self):
        pool = self.pool()
        self.rejected(f"/api/pools/{pool.uuid}/issue/", {"slot": pool.slots.first().pk, "case_number": None})

    def test_fractional_slot_id_cannot_issue_a_different_number(self):
        pool = self.pool()
        self.rejected(
            f"/api/pools/{pool.uuid}/issue/", {"slot": pool.slots.first().pk + 0.75, "case_number": "TEST/1"}
        )

    def test_case_number_length_matches_database_on_all_backends(self):
        pool = self.pool()
        self.rejected(
            f"/api/pools/{pool.uuid}/issue/", {"slot": pool.slots.first().pk, "case_number": "X" * 101}
        )

    def test_owner_object_cannot_be_silently_saved_as_text(self):
        self.rejected("/api/requests/", {**data(), "owner": {"name": "Fikcyjny"}})

    def test_fractional_pool_decision_cannot_truncate_positions(self):
        req = create_request(
            self.county, {"kind": "II", "count": 2, "case_number": "TEST/II", "justification": "Test"}
        )
        send_request(self.county, req.uuid)
        self.client.force_login(self.ump)
        self.rejected(
            f"/api/requests/{req.uuid}/decide/",
            {
                "approve": True,
                "pool": {
                    "prefix": "P",
                    "start": 1.75,
                    "end": 2.75,
                    "valid_from": timezone.localdate().isoformat(),
                },
            },
        )

    def test_slot_types_missing_fields_and_unknown_fields_preserve_all_tables(self):
        pool = self.pool()
        url = f"/api/pools/{pool.uuid}/issue/"
        good = {"slot": pool.slots.first().pk, "case_number": "TEST/1"}
        for slot in (True, False, 1.0, "1", None, [], {}, 0, -1):
            with self.subTest(slot=slot):
                self.rejected(url, {**good, "slot": slot})
        for case in (True, False, 1, None, [], {}, "", "   "):
            with self.subTest(case=case):
                self.rejected(url, {**good, "case_number": case})
        for payload in (
            {},
            {"slot": good["slot"]},
            {"case_number": "TEST"},
            {**good, "issued_by": self.other.pk},
        ):
            self.rejected(url, payload)

    def test_service_and_html_share_case_number_limit_and_service_rejects_coercion(self):
        pool = self.pool()
        slot = pool.slots.first()
        for slot_id, case in (
            (slot.pk, "X" * 101),
            (slot.pk, None),
            (slot.pk + 0.75, "TEST"),
            (True, "TEST"),
        ):
            before = self.snapshot()
            with self.assertRaises(ValidationError):
                issue_slot(self.county, pool.uuid, slot_id, case)
            self.assertEqual(self.snapshot(), before)
        before = self.snapshot()
        response = self.client.post(
            reverse("pool_detail", args=[pool.uuid]), {"slot": slot.pk, "case_number": "X" * 101}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "najwyżej 100 znaków")
        self.assertEqual(self.snapshot(), before)

    def test_request_field_types_and_identity_overrides_are_rejected(self):
        for field in ("kind", "number", "owner", "address", "vin", "case_number", "station", "justification"):
            for value in (None, [], {}, True, 1):
                with self.subTest(field=field, value=value):
                    self.rejected("/api/requests/", {**data(), field: value})
        for count in (True, 1.0, "1", None, {}, [], 0, -1, 10001):
            self.rejected("/api/requests/", {**data(), "count": count})
        for field in ("office", "office_id", "author", "status", "unknown"):
            self.rejected("/api/requests/", {**data(), field: "b"})

    def test_direct_pool_and_decision_share_strict_types_and_iso_dates(self):
        req = create_request(
            self.county, {"kind": "II", "count": 2, "case_number": "TEST/II", "justification": "Test"}
        )
        send_request(self.county, req.uuid)
        self.client.force_login(self.ump)
        pool = {"prefix": "P", "start": 1, "end": 2, "valid_from": timezone.localdate().isoformat()}
        for field, values in (
            ("start", (True, 1.0, "1", None, [], {}, 0)),
            ("end", (True, 2.0, "2", None, [], {}, 0)),
            ("prefix", (True, 1, None, [], {})),
            ("valid_from", (True, 0, None, [], {}, "20261003", "2026-2-1", "2026-02-30", "03.10.2026")),
            ("valid_until", (False, 0, [], {}, "2026-02-30")),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    invalid = {**pool, field: value}
                    self.rejected("/api/pools/", {**invalid, "kind": "II", "office": self.county.office_id})
                    self.rejected(f"/api/requests/{req.uuid}/decide/", {"approve": True, "pool": invalid})
        for key in pool:
            self.rejected(
                f"/api/requests/{req.uuid}/decide/",
                {"approve": True, "pool": {k: v for k, v in pool.items() if k != key}},
            )
        for extra in ("office", "kind", "station", "unknown"):
            self.rejected(
                f"/api/requests/{req.uuid}/decide/", {"approve": True, "pool": {**pool, extra: "b"}}
            )

    def test_duplicate_fields_nonfinite_values_and_excessive_nesting_are_rejected(self):
        raw_bodies = (
            '{"kind":"I","kind":"III"}',
            '{"owner":NaN}',
            '{"count":Infinity}',
            '{"count":-Infinity}',
            '{"pool":{"start":1,"start":2}}',
            '{"owner":' + "[" * 1500 + "0" + "]" * 1500 + "}",
        )
        for raw in raw_bodies:
            before = self.snapshot()
            response = self.client.post("/api/requests/", raw, content_type="application/json")
            self.assertEqual(response.status_code, 400, response.content)
            self.assertEqual(self.snapshot(), before)

    def test_decision_and_submit_shapes_are_not_silently_ignored(self):
        req = create_request(self.county, data())
        self.rejected(f"/api/requests/{req.uuid}/submit/", {"approve": True})
        self.rejected(f"/api/requests/{req.uuid}/withdraw/", {"reason": "Test", "status": "APPROVED"})
        send_request(self.county, req.uuid)
        self.client.force_login(self.ump)
        for value in (None, [], {}, 1, "true"):
            self.rejected(f"/api/requests/{req.uuid}/decide/", {"approve": value})
        for payload in (
            {},
            {"approve": True, "pool": {}},
            {"approve": False, "pool": {}},
            {"approve": False},
            {"approve": True, "office": "b"},
        ):
            self.rejected(f"/api/requests/{req.uuid}/decide/", payload)

    def test_correct_individual_api_flow_and_record_corrections_still_work(self):
        response = self.client.post("/api/requests/", data(), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        req = Request.objects.get(uuid=response.json()["id"])
        self.assertEqual(req.office_id, self.county.office_id)
        self.assertEqual(req.author_id, self.county.pk)
        self.assertEqual(
            self.client.post(f"/api/requests/{req.uuid}/submit/", {}, content_type="application/json").json()[
                "status"
            ],
            "SENT",
        )
        self.client.force_login(self.ump)
        self.assertEqual(
            self.client.post(
                f"/api/requests/{req.uuid}/decide/", {"approve": True}, content_type="application/json"
            ).json()["status"],
            "APPROVED",
        )
        req.record.refresh_from_db()
        self.client.force_login(self.county)
        response = self.client.patch(
            f"/api/records/{req.record.uuid}/",
            {
                "fields": {"vin": "WVWZZZ1JZXW000001", "registration_date": "2026-01-01"},
                "reason": "Test wydania",
                "version": req.record.version,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ISSUED")
        response = self.client.patch(
            f"/api/records/{req.record.uuid}/",
            {
                "fields": {"sale_date": "2026-02-01", "buyer": "Nabywca Fikcyjny"},
                "reason": "Test zbycia",
                "version": response.json()["version"],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "SOLD")
        self.assertEqual(Letter.objects.filter(request=req).count(), 2)

    def test_correct_pool_decisions_both_modules_and_slot_issue(self):
        for kind, prefix in (("II", "P"), ("III", "P1")):
            self.client.force_login(self.county)
            response = self.client.post(
                "/api/requests/",
                {
                    "kind": kind,
                    "count": 2,
                    "case_number": f"TEST/{kind}",
                    "justification": "Test",
                    "station": "Fikcyjna stacja",
                },
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 201)
            req = Request.objects.get(uuid=response.json()["id"])
            self.assertEqual(
                self.client.post(
                    f"/api/requests/{req.uuid}/submit/", {}, content_type="application/json"
                ).status_code,
                200,
            )
            self.client.force_login(self.ump)
            pool = {
                "prefix": prefix,
                "start": 1,
                "end": 2,
                "valid_from": timezone.localdate().isoformat(),
                "valid_until": (timezone.localdate() + timedelta(days=30)).isoformat(),
            }
            self.assertEqual(
                self.client.post(
                    f"/api/requests/{req.uuid}/decide/",
                    {"approve": True, "pool": pool},
                    content_type="application/json",
                ).status_code,
                200,
            )
            allocated = Pool.objects.get(request=req)
            self.assertEqual(allocated.station, "Fikcyjna stacja")
            self.client.force_login(self.county)
            slot = allocated.slots.first()
            response = self.client.post(
                f"/api/pools/{allocated.uuid}/issue/",
                {"slot": slot.pk, "case_number": "X" * 100},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            slot.refresh_from_db()
            self.assertEqual(slot.issued_by_id, self.county.pk)
            self.assertEqual(slot.case_number, "X" * 100)
            self.rejected(f"/api/pools/{allocated.uuid}/issue/", {"slot": slot.pk, "case_number": "Ponownie"})
        # Autor dostaje powiadomienie o decyzji w każdym module, tutaj II i III.
        self.assertEqual(IntegrationJob.objects.filter(operation="DECISION_NOTICE").count(), 2)

    def test_other_office_and_admin_cannot_issue_or_decide_and_unknown_objects_are_404(self):
        pool = self.pool()
        slot = pool.slots.first()
        req = create_request(self.county, data())
        send_request(self.county, req.uuid)
        for user, issue_status in ((self.other, 404), (self.admin, 403)):
            self.client.force_login(user)
            before = self.snapshot()
            self.assertEqual(
                self.client.post(
                    f"/api/pools/{pool.uuid}/issue/",
                    {"slot": slot.pk, "case_number": "Test"},
                    content_type="application/json",
                ).status_code,
                issue_status,
            )
            self.assertEqual(
                self.client.post(
                    f"/api/requests/{req.uuid}/decide/", {"approve": True}, content_type="application/json"
                ).status_code,
                403,
            )
            self.assertEqual(self.snapshot(), before)
        self.client.force_login(self.county)
        before = self.snapshot()
        self.assertEqual(
            self.client.post("/api/pools/", {"kind": "II"}, content_type="application/json").status_code, 403
        )
        self.assertEqual(
            self.client.post(
                f"/api/pools/{pool.uuid}/issue/",
                {"slot": slot.pk + 999, "case_number": "Test"},
                content_type="application/json",
            ).status_code,
            404,
        )
        self.assertEqual(self.snapshot(), before)

    def test_domain_pool_service_rejects_fractional_positions_without_artifacts(self):
        for value in (True, 1.0, "1"):
            before = self.snapshot()
            with self.assertRaises(ValidationError):
                allocate_pool(
                    self.ump,
                    {
                        "office": self.county.office_id,
                        "kind": "II",
                        "prefix": "P",
                        "start": value,
                        "end": 2,
                        "valid_from": timezone.localdate(),
                    },
                )
            self.assertEqual(self.snapshot(), before)
