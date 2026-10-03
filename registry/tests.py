import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier

from django.contrib.auth.hashers import make_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from .imports import apply_import, preview_import
from .models import AuditLog, LoginCode, Office, PlateRecord, Pool, PoolSlot, User
from .services import (
    allocate_pool,
    availability,
    create_request,
    decide_request,
    expire_reservations,
    extend_reservation,
    issue_slot,
    send_request,
    update_record,
    withdraw_request,
)
from .validation import pool_numbers, validate_number, validate_part


def fixtures():
    main = Office.objects.create(id="ump", name="UMP test", kind="MAIN", city="Poznań")
    county = Office.objects.create(id="a", name="Urząd A", kind="COUNTY", city="A")
    other = Office.objects.create(id="b", name="Urząd B", kind="COUNTY", city="B")
    admin = User.objects.create_user(username="admin@test.invalid", email="admin@test.invalid", role="ADMIN")
    ump = User.objects.create_user(
        username="ump@test.invalid", email="ump@test.invalid", role="MAIN", office=main
    )
    a = User.objects.create_user(
        username="a@test.invalid", email="a@test.invalid", role="COUNTY", office=county
    )
    b = User.objects.create_user(
        username="b@test.invalid", email="b@test.invalid", role="COUNTY", office=other
    )
    return admin, ump, a, b


def data(number="P0TEST"):
    return {"kind": "I", "number": number, "owner": "Osoba Fikcyjna", "case_number": "TEST/1", "count": 1}


class CoreTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def allocated(self):
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        decide_request(self.ump, req.uuid, True)
        req.refresh_from_db()
        return req

    def test_formats(self):
        self.assertEqual(validate_number("p0 kowal"), "P0KOWAL")
        for value in ["ABC", "AB1", "A12", "AB1C", "KOWAL", "AUTO1"]:
            self.assertEqual(validate_part(value), value)
        for value in ["12A", "A1BCD", "KOWAL1", "ĄBC", "AB", "<A>"]:
            with self.assertRaises(ValidationError):
                validate_part(value)
        self.assertEqual(pool_numbers("II", "P", 999, 1000), ["P999", "P01A"])

    def test_public_never_exposes_personal_data(self):
        req = create_request(self.a, data())
        response = self.client.get("/api/availability/", {"part": "TEST"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Osoba Fikcyjna")
        self.assertNotContains(response, str(req.uuid))
        self.assertFalse(response.json()["digits"][0]["available"])

    def test_lifecycle_and_sale_does_not_release(self):
        req = self.allocated()
        rec = req.record
        rec.refresh_from_db()
        rec = update_record(
            self.a,
            rec.uuid,
            {"vin": "WVWZZZ1JZXW000001", "make": "Test", "registration_date": timezone.localdate()},
            "Rejestracja",
            rec.version,
        )
        self.assertEqual(rec.status, "ISSUED")
        rec = update_record(
            self.a,
            rec.uuid,
            {"sale_date": timezone.localdate(), "buyer": "Nabywca Fikcyjny"},
            "Zbycie",
            rec.version,
        )
        self.assertEqual(rec.status, "SOLD")
        self.assertFalse(availability("TEST")["digits"][0]["available"])
        rec = update_record(self.ump, rec.uuid, {"status": "RELEASED"}, "Zwolnienie przez UMP", rec.version)
        self.assertTrue(availability("TEST")["digits"][0]["available"])
        self.assertTrue(PlateRecord.objects.filter(pk=rec.pk).exists())

    def test_duplicate_reservation_is_blocked_by_service_and_database(self):
        req = create_request(self.a, data())
        with self.assertRaises(ValidationError):
            create_request(self.b, data())
        with self.assertRaises(IntegrityError), transaction.atomic():
            PlateRecord.objects.create(number=req.record.number, office=self.b.office, owner="Inny")

    def test_county_cannot_decide_or_override_owner(self):
        req = self.allocated()
        with self.assertRaises(PermissionDenied):
            decide_request(self.a, req.uuid, True)
        with self.assertRaises(PermissionDenied):
            update_record(self.a, req.record.uuid, {"owner": "Inny"}, "Próba", req.record.version)

    def test_admin_cannot_access_business_records(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/api/requests/").status_code, 403)
        self.assertEqual(self.client.get("/panel/ewidencja/").status_code, 403)

    def test_other_county_cannot_read_or_mutate_foreign_record(self):
        req = self.allocated()
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(f"/api/records/{req.record.uuid}/").status_code, 404)
        self.assertEqual(self.client.get(reverse("request_detail", args=[req.uuid])).status_code, 404)
        response = self.client.patch(
            f"/api/records/{req.record.uuid}/",
            data=json.dumps({"fields": {"buyer": "Inny"}, "reason": "Próba", "version": req.record.version}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_rejection_requires_reason_and_releases_number(self):
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        with self.assertRaises(ValidationError):
            decide_request(self.ump, req.uuid, False)
        decide_request(self.ump, req.uuid, False, "Treść niedopuszczalna")
        self.assertTrue(availability("TEST")["digits"][0]["available"])

    def test_stale_version_is_rejected(self):
        req = self.allocated()
        rec = req.record
        version = rec.version
        update_record(self.ump, rec.uuid, {"note": "Pierwsza zmiana"}, "Korekta", version)
        with self.assertRaises(ValidationError):
            update_record(self.ump, rec.uuid, {"note": "Druga zmiana"}, "Korekta", version)

    def test_expiry_releases_reservation_and_expires_request(self):
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        PlateRecord.objects.filter(pk=req.record_id).update(
            reservation_until=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(expire_reservations(), 1)
        req.refresh_from_db()
        self.assertEqual(req.status, "EXPIRED")
        self.assertTrue(availability("TEST")["digits"][0]["available"])
        with self.assertRaises(ValidationError):
            decide_request(self.ump, req.uuid, True)

    def test_ump_can_extend_and_county_cannot(self):
        req = create_request(self.a, data())
        until = req.record.reservation_until
        with self.assertRaises(PermissionDenied):
            extend_reservation(self.a, req.record.uuid, 14, "Przedłużenie")
        rec = extend_reservation(self.ump, req.record.uuid, 14, "Przedłużenie")
        self.assertEqual(rec.reservation_until, until + timedelta(days=14))

    def test_withdrawal_releases_and_retains_history(self):
        req = create_request(self.a, data())
        withdraw_request(self.a, req.uuid, "Wycofanie")
        self.assertTrue(availability("TEST")["digits"][0]["available"])
        self.assertTrue(AuditLog.objects.filter(action="request.withdrawn").exists())

    def test_pool_overlap_and_duplicate_issue(self):
        p = allocate_pool(
            self.ump,
            {
                "kind": "II",
                "office": "a",
                "prefix": "P",
                "start": 1,
                "end": 10,
                "valid_from": timezone.localdate(),
            },
        )
        with self.assertRaises(ValidationError):
            allocate_pool(
                self.ump,
                {
                    "kind": "II",
                    "office": "b",
                    "prefix": "P",
                    "start": 10,
                    "end": 20,
                    "valid_from": timezone.localdate(),
                },
            )
        slot = p.slots.first()
        issue_slot(self.a, p.uuid, slot.pk, "CASE/1")
        with self.assertRaises(ValidationError):
            issue_slot(self.a, p.uuid, slot.pk, "CASE/2")
        self.assertEqual(p.used, 1)
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(reverse("pool_detail", args=[p.uuid])).status_code, 404)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PoolSlot.objects.create(pool=p, number=slot.number, ordinal=99)

    def test_module_three_requires_request_and_matches_count(self):
        with self.assertRaises(ValidationError):
            allocate_pool(
                self.ump,
                {
                    "kind": "III",
                    "office": "a",
                    "prefix": "P0",
                    "start": 1,
                    "end": 2,
                    "valid_from": timezone.localdate(),
                },
            )
        req = create_request(
            self.a,
            {
                "kind": "III",
                "case_number": "III/1",
                "count": 2,
                "justification": "Potrzeba testowa",
                "station": "Stacja Testowa",
            },
        )
        send_request(self.a, req.uuid)
        decide_request(
            self.ump,
            req.uuid,
            True,
            pool_data={
                "prefix": "P0",
                "start": 1,
                "end": 2,
                "valid_from": timezone.localdate(),
                "valid_until": timezone.localdate() + timedelta(days=90),
            },
        )
        self.assertEqual(Pool.objects.get(request=req).total, 2)

    def test_actual_pdf_contains_polish_text_and_reference(self):
        req = create_request(self.a, data())
        letter = req.letters.first()
        self.assertTrue(bytes(letter.pdf).startswith(b"%PDF"))
        text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(bytes(letter.pdf))).pages)
        self.assertIn("Wniosek o przydział", text)
        self.assertIn(str(req.uuid), text)
        self.assertIn("Podpis sprawdź w czytniku PDF", text)

    def test_import_preview_and_atomic_apply(self):
        text = "number;owner;office_id\nP2IMPORT;Fikcyjny;a\n"
        preview = preview_import(text)
        self.assertTrue(preview["errors"])  # zbyt długa część indywidualna
        preview = preview_import("number;owner;office_id\nP2IMPRT;Fikcyjny;a\n")
        self.assertEqual(preview["errors"], [])
        self.assertEqual(apply_import(self.ump, preview["rows"]), 1)
        with self.assertRaises(ValidationError):
            apply_import(self.ump, preview["rows"])
        self.assertEqual(PlateRecord.objects.filter(number="P2IMPRT").count(), 1)

    def test_csv_export_filters_scope_and_escapes_formulas(self):
        create_request(self.a, data())
        create_request(self.b, {**data("P1TEST"), "owner": '=HYPERLINK("bad")'})
        self.client.force_login(self.a)
        response = self.client.get("/panel/eksport/")
        self.assertContains(response, "P0TEST")
        self.assertNotContains(response, "P1TEST")
        self.client.force_login(self.ump)
        self.assertContains(self.client.get("/panel/eksport/"), "'=HYPERLINK")

    def test_csrf_is_required_for_mutations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.a)
        self.assertEqual(
            client.post(
                "/api/requests/", data=json.dumps(data()), content_type="application/json"
            ).status_code,
            403,
        )

    def test_single_use_otp_and_disabled_office(self):
        token = LoginCode.objects.create(
            user=self.a, digest=make_password("123456"), expires_at=timezone.now() + timedelta(minutes=1)
        )
        session = self.client.session
        session["login_code_id"] = token.pk
        session.save()
        response = self.client.post("/logowanie/kod/", {"code": "123456"})
        self.assertEqual(response.status_code, 302)
        token.refresh_from_db()
        self.assertTrue(token.used)
        self.a.office.active = False
        self.a.office.save()
        self.assertEqual(self.client.get("/api/requests/").status_code, 401)

    def test_audit_is_immutable(self):
        create_request(self.a, data())
        event = AuditLog.objects.first()
        with self.assertRaises(ValidationError):
            event.delete()
        event.reason = "Podmiana"
        with self.assertRaises(ValidationError):
            event.save()

    def test_all_panel_pages_render_for_their_roles(self):
        req = self.allocated()
        for role in [self.ump, self.a]:
            self.client.force_login(role)
            for path in [
                "/panel/",
                "/panel/wnioski/",
                "/panel/ewidencja/",
                "/panel/pule/",
                "/panel/pisma/",
                "/panel/audyt/",
                "/panel/integracje/",
                reverse("request_detail", args=[req.uuid]),
                reverse("record_detail", args=[req.record.uuid]),
            ]:
                with self.subTest(user=role.role, path=path):
                    self.assertEqual(self.client.get(path).status_code, 200)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/panel/administracja/").status_code, 200)


class ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_two_offices_only_one_reservation(self):
        barrier = Barrier(2)

        def submit(user_pk):
            close_old_connections()
            user = User.objects.get(pk=user_pk)
            barrier.wait(timeout=10)
            try:
                req = create_request(user, data())
                return ("created", str(req.uuid))
            except ValidationError:
                return ("conflict", None)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(submit, [self.a.pk, self.b.pk]))
        self.assertEqual(sorted(r[0] for r in results), ["conflict", "created"])
        self.assertEqual(PlateRecord.objects.exclude(status="RELEASED").count(), 1)

    def test_overlapping_pools_concurrently(self):
        barrier = Barrier(2)

        def allocate(start):
            close_old_connections()
            user = User.objects.get(pk=self.ump.pk)
            barrier.wait(timeout=10)
            try:
                allocate_pool(
                    user,
                    {
                        "kind": "II",
                        "office": "a",
                        "prefix": "P",
                        "start": start,
                        "end": start + 9,
                        "valid_from": timezone.localdate(),
                    },
                )
                return "created"
            except ValidationError:
                return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(allocate, [1, 5]))
        self.assertEqual(sorted(results), ["conflict", "created"])
        self.assertEqual(PoolSlot.objects.count(), 10)
