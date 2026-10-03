from datetime import timedelta
from uuid import uuid4

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, PlateRecord, Request
from .services import availability, create_request, decide_request, send_request, withdraw_request
from .tests import data, fixtures


class AvailabilitySelectionTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_selected_digit_zero_and_seven_on_html_and_api(self):
        for digit in (0, 7):
            with self.subTest(digit=digit):
                number = f"P{digit}TEST"
                api = self.client.get("/api/availability/", {"part": "TEST", "digit": str(digit)})
                self.assertEqual(api.status_code, 200)
                self.assertEqual(api.json()["digits"], [{"number": number, "available": True}])
                page = self.client.post("/", {"part": "TEST", "prefix": "P", "digit": str(digit)})
                self.assertEqual(page.status_code, 200)
                self.assertEqual(page.context["result"]["digits"], api.json()["digits"])
                self.assertContains(page, 'class="digit-result available"', count=1)
                self.assertNotIn(number, api.json()["suggestions"])

    def test_no_selection_keeps_all_ten_digits(self):
        expected = [{"number": f"P{d}TEST", "available": True} for d in range(10)]
        self.assertEqual(availability("TEST")["digits"], expected)
        api = self.client.get("/api/availability/", {"part": "TEST"})
        self.assertEqual(api.json()["digits"], expected)
        page = self.client.post("/", {"part": "TEST", "prefix": "P", "digit": ""})
        self.assertEqual(page.context["result"]["digits"], expected)
        self.assertContains(page, 'class="digit-result available"', count=10)

    def test_reserved_selected_number_is_unavailable_with_free_alternatives_only(self):
        req = create_request(self.a, data("P7TEST"))
        api = self.client.get("/api/availability/", {"part": "TEST", "digit": "7"})
        self.assertEqual(api.json()["digits"], [{"number": "P7TEST", "available": False}])
        self.assertNotIn("P7TEST", api.json()["suggestions"])
        self.assertIn("P0TEST", api.json()["suggestions"])
        self.assertNotContains(api, "Osoba Fikcyjna")
        self.assertNotContains(api, str(req.uuid))
        page = self.client.post("/", {"part": "TEST", "prefix": "P", "digit": "7"})
        self.assertContains(page, 'class="digit-result unavailable"', count=1)
        self.assertContains(page, "Niedostępny")
        self.assertNotContains(page, "Osoba Fikcyjna")

    def test_selection_preserves_prefix_and_does_not_reserve(self):
        api = self.client.get("/api/availability/", {"part": "TEST", "prefix": "M", "digit": "7"})
        self.assertEqual(api.json()["digits"], [{"number": "M7TEST", "available": True}])
        self.assertFalse(PlateRecord.objects.exists())

    def test_invalid_digit_is_rejected(self):
        for digit in ("-1", "10", "abc"):
            with self.subTest(digit=digit):
                response = self.client.get("/api/availability/", {"part": "TEST", "digit": digit})
                self.assertEqual(response.status_code, 400)

    @override_settings(DEBUG=False)
    def test_missing_and_foreign_request_have_same_safe_polish_message(self):
        req = create_request(self.a, data())
        self.client.force_login(self.b)
        for uuid in (req.uuid, uuid4()):
            with self.subTest(uuid=uuid):
                page = self.client.get(reverse("request_detail", args=[uuid]))
                self.assertContains(page, "Nie znaleziono strony", status_code=404)
                self.assertContains(page, 'lang="pl"', status_code=404)
                self.assertContains(page, "Wróć do panelu", status_code=404)
                self.assertNotContains(page, "Osoba Fikcyjna", status_code=404)
                self.assertNotContains(page, req.reference, status_code=404)
                self.assertEqual(page["Cache-Control"], "no-store")

    @override_settings(DEBUG=False)
    def test_public_missing_page_has_recovery_link(self):
        page = self.client.get("/nieistniejacy-ekran/")
        self.assertContains(page, "Nie znaleziono strony", status_code=404)
        self.assertContains(page, "Sprawdź dostępność tablicy", status_code=404)


class AvailabilityReservationTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        self.draft = create_request(self.a, data("P0TEST"))
        self.sent = create_request(self.a, data("P1TEST"))
        send_request(self.a, self.sent.uuid)
        self.allocated = create_request(self.a, data("P2TEST"))
        send_request(self.a, self.allocated.uuid)
        decide_request(self.ump, self.allocated.uuid, True)
        self.foreign = create_request(self.b, data("P3TEST"))

    def business_snapshot(self):
        return {
            model.__name__: list(model.objects.order_by("pk").values())
            for model in (PlateRecord, Request, AuditLog)
        }

    def test_html_and_api_scope_pending_status_to_office_and_ump(self):
        before = self.business_snapshot()
        for user, pending in (
            (self.a, {"P0TEST", "P1TEST"}),
            (self.b, {"P3TEST"}),
            (self.ump, {"P0TEST", "P1TEST", "P3TEST"}),
        ):
            with self.subTest(role=user.role, office=user.office_id):
                self.client.force_login(user)
                api = self.client.get("/api/availability/", {"part": "TEST"})
                self.assertEqual(api.status_code, 200)
                digits = api.json()["digits"]
                self.assertEqual({item["number"] for item in digits if item["reservation_pending"]}, pending)
                self.assertEqual(
                    {item["number"] for item in digits if not item["available"]},
                    {"P0TEST", "P1TEST", "P2TEST", "P3TEST"},
                )
                page = self.client.post("/", {"part": "TEST", "prefix": "P"})
                self.assertEqual(page.context["result"]["digits"], digits)
                self.assertContains(page, "Zarezerwowany – wniosek w toku", count=len(pending))
                for response in (page, api):
                    self.assertNotContains(response, "Osoba Fikcyjna")
                    for req in (self.draft, self.sent, self.allocated, self.foreign):
                        self.assertNotContains(response, str(req.uuid))
                        self.assertNotContains(response, str(req.record.uuid))
                        self.assertNotContains(response, req.reference)
                self.assertEqual(self.business_snapshot(), before)

    def test_anonymous_and_admin_keep_public_contract(self):
        for user in (None, self.admin):
            with self.subTest(role=user.role if user else "PUBLIC"):
                if user:
                    self.client.force_login(user)
                else:
                    self.client.logout()
                api = self.client.get("/api/availability/", {"part": "TEST"})
                self.assertEqual(api.status_code, 200)
                self.assertTrue(all(set(item) == {"number", "available"} for item in api.json()["digits"]))
                page = self.client.post("/", {"part": "TEST", "prefix": "P"})
                self.assertNotContains(page, "Zarezerwowany – wniosek w toku")
                self.assertNotContains(api, "reservation_pending")

    def test_other_county_does_not_distinguish_foreign_reservation_and_allocation(self):
        self.client.force_login(self.b)
        for digit in (0, 1, 2):
            with self.subTest(digit=digit):
                response = self.client.get("/api/availability/", {"part": "TEST", "digit": digit})
                self.assertEqual(
                    response.json()["digits"],
                    [{"number": f"P{digit}TEST", "available": False, "reservation_pending": False}],
                )

    def test_withdrawn_and_expired_reservations_become_available(self):
        withdraw_request(self.a, self.draft.uuid, "Wycofanie testowe")
        PlateRecord.objects.filter(pk=self.sent.record_id).update(
            reservation_until=timezone.now() - timedelta(seconds=1)
        )
        self.client.force_login(self.a)
        response = self.client.get("/api/availability/", {"part": "TEST"})
        self.assertEqual(response.status_code, 200)
        for item in response.json()["digits"][:2]:
            self.assertTrue(item["available"])
            self.assertFalse(item["reservation_pending"])
        self.sent.refresh_from_db()
        self.assertEqual(self.sent.status, "EXPIRED")
        self.assertNotIn("P2TEST", response.json()["suggestions"])

    def test_service_does_not_enrich_inactive_accounts_or_offices(self):
        for inactive_office in (False, True):
            with self.subTest(inactive_office=inactive_office):
                self.a.is_active = inactive_office
                self.a.office.active = not inactive_office
                self.assertTrue(
                    all(
                        set(item) == {"number", "available"}
                        for item in availability("TEST", viewer=self.a)["digits"]
                    )
                )
