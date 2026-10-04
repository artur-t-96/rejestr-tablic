from django.test import TestCase

from .forms import CheckForm
from .models import AuditLog, Letter, NumberSequence, PlateRecord, Request
from .services import availability
from .tests import fixtures
from .validation import display_number, validate_number


class FreeSuggestionTests(TestCase):
    def setUp(self):
        self.admin, self.main, self.county, self.other = fixtures()

    def snapshot(self):
        return {
            model.__name__: list(model.objects.order_by("pk").values())
            for model in (PlateRecord, Request, Letter, AuditLog, NumberSequence)
        }

    def test_selected_digit_offers_same_part_with_other_digits_then_other_letter(self):
        before = self.snapshot()
        suggestions = availability("URBAN", "M", 1)["suggestions"]
        expected = [f"M{d}URBAN" for d in range(10) if d != 1] + [f"P{d}URBAN" for d in range(10)]
        self.assertEqual(suggestions, expected)
        self.assertEqual(self.snapshot(), before)

    def test_no_digit_selection_offers_only_the_other_letter(self):
        result = availability("KOWA")
        self.assertEqual(result["suggestions"], [f"M{d}KOWA" for d in range(10)])
        self.assertFalse({item["number"] for item in result["digits"]} & set(result["suggestions"]))

    def test_individual_part_is_never_changed(self):
        for part in ("ABC", "KOWA", "KOWAL", "A12", "AB1C", "ABC12", "PPP"):
            for prefix in ("P", "M"):
                for digit in (None, 0, 7):
                    with self.subTest(part=part, prefix=prefix, digit=digit):
                        result = availability(part, prefix, digit)
                        suggestions = result["suggestions"]
                        self.assertEqual(len(suggestions), len(set(suggestions)))
                        self.assertGreater(len(suggestions), 0)
                        for number in suggestions:
                            self.assertEqual(validate_number(number), number)
                            self.assertEqual(number[2:], part)
                        self.assertFalse({item["number"] for item in result["digits"]} & set(suggestions))

    def test_occupied_variants_from_any_office_are_excluded_and_released_can_return(self):
        initial = availability("KOWA", "P", 7)["suggestions"]
        for index, number in enumerate(initial):
            PlateRecord.objects.create(
                number=number,
                office=self.county.office if index % 2 else self.other.office,
                owner="Właściciel wyłącznie testowy",
                status="ALLOCATED" if index % 2 else "SOLD",
            )
        # Zwolniona pozycja historyczna nie blokuje ponownego wykorzystania.
        released = PlateRecord.objects.get(number=initial[0])
        released.status = "RELEASED"
        released.save(update_fields=["status"])
        before = self.snapshot()
        self.assertEqual(availability("KOWA", "P", 7)["suggestions"], [initial[0]])
        self.assertEqual(self.snapshot(), before)

    def test_html_and_api_share_only_free_suggestions_without_owner_details(self):
        for part, prefix, digit in (("KOWA", "P", "7"), ("A12", "M", "0"), ("KOWAL", "P", "")):
            with self.subTest(part=part, prefix=prefix, digit=digit):
                values = {"part": part, "prefix": prefix, "digit": digit}
                response = self.client.get("/api/availability/", values)
                self.assertEqual(response.status_code, 200)
                page = self.client.post("/", values)
                self.assertEqual(page.status_code, 200)
                self.assertEqual(page.context["result"]["suggestions"], response.json()["suggestions"])
                for number in response.json()["suggestions"]:
                    self.assertContains(page, f"<span>{display_number(number)}</span>")
                self.assertNotContains(response, "Właściciel wyłącznie testowy")
                self.assertEqual(response["Cache-Control"], "no-store")


class PublicCheckerLayoutTests(TestCase):
    def test_fields_follow_the_order_on_the_plate(self):
        self.assertEqual(list(CheckForm().fields), ["prefix", "digit", "part"])
        html = self.client.get("/").content.decode()
        self.assertLess(html.index('id="id_prefix"'), html.index('id="id_digit"'))
        self.assertLess(html.index('id="id_digit"'), html.index('id="id_part"'))

    def test_numbers_are_shown_with_a_gap_and_api_keeps_plain_number(self):
        self.assertEqual(display_number("M1URBAN"), "M1 URBAN")
        page = self.client.post("/", {"prefix": "M", "digit": "1", "part": "urban"})
        self.assertContains(page, "<span>M1 URBAN</span>")
        self.assertNotContains(page, "<span>M1URBAN</span>")
        self.assertContains(page, "Ten sam wyróżnik z inną cyfrą lub literą województwa")
        # API zachowuje dotychczasowy kontrakt: numer bez odstępu.
        data = self.client.get("/api/availability/", {"prefix": "M", "digit": "1", "part": "URBAN"}).json()
        self.assertEqual(data["digits"], [{"number": "M1URBAN", "available": True}])
