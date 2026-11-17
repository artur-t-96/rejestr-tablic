"""Uwagi z testów Starostwa w Gnieźnie i UMP z 15.11.2026: podpis przed złożeniem, wycofanie
tylko przez urząd wnioskujący, wniosek o serię numerów, tylko wolny numer, menu i filtry wniosków."""

from io import BytesIO

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from pypdf import PdfReader

from .demo_setup import prepare
from .forms import RequestForm
from .models import Letter, PlateRecord, Request
from .services import create_request, decide_request, send_request, update_record, withdraw_request
from .test_demo_mode import DemoBase
from .tests import data, fixtures
from .validation import series_numbers


def sign(req):
    """Pismo wniosku oznaczone jako podpisane (właściwy podpis sprawdzają testy podpisów)."""
    letter = req.letters.get(kind="APPLICATION")
    Letter.objects.filter(pk=letter.pk).update(signed_pdf=b"%PDF-podpisany", signature_status="TEST_SIGNED")


def series(first="P1MAJA1", last="P1MAJA9"):
    return {"kind": "I", "number": first, "number_to": last, "count": 1}


@override_settings(SIGNED_APPLICATION_REQUIRED=True)
class SignatureBeforeSubmitTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_unsigned_request_cannot_be_sent_to_ump(self):
        req = create_request(self.a, data())
        with self.assertRaisesMessage(ValidationError, "Najpierw podpisz wniosek"):
            send_request(self.a, req.uuid)
        req.refresh_from_db()
        self.assertEqual((req.status, req.record.status), ("DRAFT", "RESERVED"))
        sign(req)
        send_request(self.a, req.uuid)
        req.refresh_from_db()
        self.assertEqual((req.status, req.record.status), ("SENT", "SENT"))

    def test_only_latest_application_version_counts(self):
        req = create_request(self.a, data())
        sign(req)
        letter = req.letters.get(kind="APPLICATION")
        from .services import create_letter_revision

        create_letter_revision(self.a, letter, "Poprawka treści")
        with self.assertRaisesMessage(ValidationError, "Najpierw podpisz wniosek"):
            send_request(self.a, req.uuid)

    def test_detail_offers_signing_and_blocks_submit_button(self):
        req = create_request(self.a, data())
        self.client.force_login(self.a)
        page = self.client.get(reverse("request_detail", args=[req.uuid]))
        letter = req.letters.get(kind="APPLICATION")
        self.assertContains(page, reverse("letter_sign", args=[letter.uuid]))
        self.assertContains(page, "Podpisz wniosek")
        self.assertContains(page, "Niepodpisanego wniosku nie można wysłać")
        self.assertNotContains(page, reverse("request_action", args=[req.uuid, "submit"]))
        # Bezpośredni POST też nie przechodzi.
        response = self.client.post(reverse("request_action", args=[req.uuid, "submit"]), follow=True)
        self.assertContains(response, "Najpierw podpisz wniosek")
        self.assertEqual(Request.objects.get(pk=req.pk).status, "DRAFT")
        sign(req)
        page = self.client.get(reverse("request_detail", args=[req.uuid]))
        self.assertContains(page, "Pismo wniosku podpisane")
        self.assertContains(page, reverse("request_action", args=[req.uuid, "submit"]))

    def test_unsigned_application_letter_cannot_be_sent_by_any_channel(self):
        from .integrations import enqueue

        req = create_request(self.a, data())
        letter = req.letters.get(kind="APPLICATION")
        for provider in ("EDOR", "SMTP"):
            with self.subTest(provider=provider), self.assertRaisesMessage(ValidationError, "Niepodpisanego"):
                enqueue(self.a, letter, provider)
        self.assertFalse(letter.jobs.exists())

    def test_api_submit_requires_signature(self):
        req = create_request(self.a, data())
        self.client.force_login(self.a)
        response = self.client.post(
            f"/api/requests/{req.uuid}/submit/", data="{}", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("podpisz", response.json()["error"])


class WithdrawalByApplicantTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_ump_cannot_withdraw_county_request(self):
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        with self.assertRaises(PermissionDenied):
            withdraw_request(self.ump, req.uuid, "Próba UMP")
        self.assertEqual(Request.objects.get(pk=req.pk).status, "SENT")
        self.client.force_login(self.ump)
        page = self.client.get(reverse("request_detail", args=[req.uuid]))
        self.assertNotContains(page, "Wycofaj wniosek")
        withdraw_request(self.a, req.uuid, "Rezygnacja starostwa")
        self.assertEqual(PlateRecord.objects.get(pk=req.record_id).status, "RELEASED")

    def test_ump_withdraws_own_request_and_county_sees_button(self):
        own = create_request(self.ump, data("P0UMPW"))
        withdraw_request(self.ump, own.uuid, "Rezygnacja UMP")
        self.assertEqual(Request.objects.get(pk=own.pk).status, "WITHDRAWN")
        req = create_request(self.a, data())
        self.client.force_login(self.a)
        self.assertContains(self.client.get(reverse("request_detail", args=[req.uuid])), "Wycofaj wniosek")

    def test_ump_cannot_submit_county_draft(self):
        req = create_request(self.a, data())
        with self.assertRaises(PermissionDenied):
            send_request(self.ump, req.uuid)

    def test_no_withdrawal_after_approval(self):
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        decide_request(self.ump, req.uuid, True)
        with self.assertRaisesMessage(ValidationError, "nie jest już zajęty"):
            withdraw_request(self.a, req.uuid, "Po przydziale")


class SeriesTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_series_numbers_rules(self):
        self.assertEqual(len(series_numbers("P1MAJA1", "P1 maja9")), 9)
        self.assertEqual(series_numbers("P0MAJ08", "P0MAJ11"), ["P0MAJ08", "P0MAJ09", "P0MAJ10", "P0MAJ11"])
        for first, last in (
            ("P1MAJA1", "P1MAJB9"),  # różny wyróżnik
            ("P1MAJA9", "P1MAJA1"),  # malejąco
            ("P1MAJAB", "P1MAJAC"),  # bez cyfr
            ("P1MAJ1", "P1MAJ12"),  # różna liczba cyfr
            ("P1MAJA1", "P2MAJA9"),  # różna cyfra województwa
        ):
            with self.subTest(first=first, last=last), self.assertRaises(ValidationError):
                series_numbers(first, last)

    def test_one_request_reserves_whole_series_and_ump_decides_it_at_once(self):
        req = create_request(self.a, series())
        records = req.plate_records
        self.assertEqual([r.number for r in records], [f"P1MAJA{n}" for n in range(1, 10)])
        self.assertEqual(
            (req.count, req.record.number, req.subject_numbers), (9, "P1MAJA1", "P1 MAJA1 – P1 MAJA9")
        )
        self.assertTrue(all(r.status == "RESERVED" for r in records))
        text = "".join(page.extract_text() for page in PdfReader(BytesIO(bytes(req.letters.get().pdf))).pages)
        self.assertIn("P1 MAJA1 – P1 MAJA9", text)
        # Żaden numer serii nie trafi do innego wniosku.
        with self.assertRaisesMessage(ValidationError, "Numer zajęty: P1 MAJA5"):
            create_request(self.b, data("P1MAJA5"))
        send_request(self.a, req.uuid)
        self.assertEqual(
            set(PlateRecord.objects.filter(series_request=req).values_list("status", flat=True)), {"SENT"}
        )
        decide_request(self.ump, req.uuid, True)
        req.refresh_from_db()
        letter = req.letters.get(kind="APPROVAL")
        allocated = PlateRecord.objects.filter(series_request=req)
        self.assertEqual(set(allocated.values_list("status", flat=True)), {"ALLOCATED"})
        self.assertEqual(set(allocated.values_list("letter_number", flat=True)), {letter.number})

    def test_series_rejection_and_withdrawal_release_every_number(self):
        rejected = create_request(self.a, series())
        send_request(self.a, rejected.uuid)
        decide_request(self.ump, rejected.uuid, False, "Odmowa testowa")
        self.assertEqual(
            set(PlateRecord.objects.filter(series_request=rejected).values_list("status", flat=True)),
            {"RELEASED"},
        )
        withdrawn = create_request(self.b, series())
        withdraw_request(self.b, withdrawn.uuid, "Rezygnacja")
        self.assertEqual(
            set(PlateRecord.objects.filter(series_request=withdrawn).values_list("status", flat=True)),
            {"RELEASED"},
        )

    def test_series_with_one_taken_number_is_refused_whole(self):
        create_request(self.b, data("P1MAJA4"))
        with self.assertRaisesMessage(ValidationError, "P1 MAJA4"):
            create_request(self.a, series())
        self.assertEqual(PlateRecord.objects.filter(number__startswith="P1MAJA").count(), 1)

    def test_record_of_series_keeps_open_request_guard(self):
        req = create_request(self.a, series())
        middle = PlateRecord.objects.get(number="P1MAJA5")
        with self.assertRaisesMessage(ValidationError, "Nie można zmienić urzędu"):
            update_record(self.ump, middle.uuid, {"office_id": "b"}, "Próba", middle.version)
        self.assertEqual(Request.objects.get(pk=req.pk).status, "DRAFT")

    def test_form_list_search_and_detail_show_series(self):
        self.client.force_login(self.a)
        response = self.client.post(
            reverse("request_new"), {"kind": "I", "number": "P1MAJA1", "number_to": "P1MAJA9"}, follow=True
        )
        req = Request.objects.get()
        self.assertContains(response, "Seria numerów")
        self.assertContains(response, "P1 MAJA5")
        listing = self.client.get(reverse("requests_list"), {"q": "P1MAJA5"})
        self.assertContains(listing, req.reference)
        self.assertContains(listing, "P1 MAJA1 – P1 MAJA9")
        self.assertContains(listing, "seria · 9 numerów")
        self.client.force_login(self.ump)
        send_request(self.a, req.uuid)
        page = self.client.get(reverse("request_detail", args=[req.uuid]))
        self.assertEqual(len(page.context["checks"]), 9)
        export = self.client.get(reverse("export_records"), {"co": "wnioski"}).content.decode()
        self.assertIn("P1MAJA1-P1MAJA9", export)

    def test_form_rejects_bad_series(self):
        form = RequestForm(series("P1MAJA1", "P1MAJB9"))
        self.assertFalse(form.is_valid())
        self.assertIn("number_to", form.errors)


class FreeNumberOnlyTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_form_refuses_taken_number_with_hint(self):
        create_request(self.b, data())
        self.client.force_login(self.a)
        response = self.client.post(reverse("request_new"), {"kind": "I", "number": "P0 TEST"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Numer zajęty: P0 TEST")
        self.assertContains(response, "Sprawdź tablicę")
        self.assertEqual(Request.objects.count(), 1)

    def test_live_check_endpoint(self):
        create_request(self.b, data())
        self.client.force_login(self.a)
        url = reverse("request_number_check")
        self.assertEqual(self.client.get(url, {"number": "P0TEST"}).json()["ok"], False)
        self.assertIn("Numer zajęty", self.client.get(url, {"number": "P0TEST"}).json()["message"])
        self.assertEqual(
            self.client.get(url, {"number": "P0WOLNYX"}).json()["ok"], False
        )  # 6 liter: niepoprawny
        free = self.client.get(url, {"number": "P0WOLN"}).json()
        self.assertEqual((free["ok"], free["message"].startswith("Numer wolny")), (True, True))
        whole = self.client.get(url, {"number": "P1MAJA1", "number_to": "P1MAJA9"}).json()
        self.assertTrue(whole["ok"])
        self.assertIn("Seria wolna (9)", whole["message"])
        # Sprawdzenie nie zajmuje numeru.
        self.assertFalse(PlateRecord.objects.filter(number="P0WOLN").exists())
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url, {"number": "P0WOLN"}).status_code, 403)

    def test_form_fields_follow_kind(self):
        self.client.force_login(self.a)
        page = self.client.get(reverse("request_new"))
        for name in ("kind", "number", "number_to", "count"):
            self.assertContains(page, f'name="{name}"')
        self.assertContains(page, "data-number-check")


class MenuAndFiltersTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_menu_without_search_and_records_but_with_check(self):
        for user in (self.a, self.ump):
            self.client.force_login(user)
            page = self.client.get(reverse("dashboard"))
            sidebar = page.content.decode().split('aria-label="Menu panelu"')[1].split("</nav>")[0]
            self.assertNotIn(reverse("number_search"), sidebar)
            self.assertNotIn(reverse("records_list") + '"', sidebar)
            self.assertIn('class="nav-check" href="/"', sidebar)
            self.assertContains(page, 'class="button check-plate"')

    def test_record_detail_hides_owner_and_vehicle_data(self):
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        decide_request(self.ump, req.uuid, True)
        PlateRecord.objects.filter(pk=req.record_id).update(owner="Osoba Ukryta", vin="WVWZZZ1JZXW000009")
        for user in (self.a, self.ump):
            self.client.force_login(user)
            page = self.client.get(reverse("record_detail", args=[req.record.uuid]))
            self.assertContains(page, "P0 TEST")
            self.assertContains(page, req.reference)
            self.assertNotContains(page, "Osoba Ukryta")
            self.assertNotContains(page, "WVWZZZ1JZXW000009")

    def test_request_filters_by_date_and_signature(self):
        signed = create_request(self.a, data("P0PODP"))
        sign(signed)
        unsigned = create_request(self.a, data("P0BRAK"))
        self.client.force_login(self.a)
        url = reverse("requests_list")
        page = self.client.get(url, {"podpis": "tak"})
        self.assertContains(page, signed.reference)
        self.assertNotContains(page, unsigned.reference)
        page = self.client.get(url, {"podpis": "nie"})
        self.assertContains(page, unsigned.reference)
        self.assertNotContains(page, signed.reference)
        self.assertNotContains(self.client.get(url, {"od": "2999-01-01"}), signed.reference)
        self.assertContains(self.client.get(url, {"do": "2999-01-01"}), signed.reference)
        self.assertContains(self.client.get(url, {"q": signed.reference}), signed.reference)
        page = self.client.get(url)
        self.assertContains(page, "data-auto-filter")
        self.assertContains(page, 'name="od"')


class DemoDataSignedTests(DemoBase):
    @override_settings(SIGNED_APPLICATION_REQUIRED=True)
    def test_demo_cases_are_signed_before_reaching_ump(self):
        prepare()
        sent = Request.objects.exclude(status="DRAFT").filter(
            record__number__in=["P0DEMO", "P1URBAN", "P7ZBYT"]
        )
        self.assertEqual(sent.count(), 3)
        for req in sent:
            self.assertEqual(req.letters.get(kind="APPLICATION").signature_status, "TEST_SIGNED")
