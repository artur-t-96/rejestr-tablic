from django.test import TestCase

from .models import AuditLog, Letter, NumberSequence, PlateRecord, Request
from .services import availability
from .tests import fixtures
from .validation import validate_number


class FreeSuggestionTests(TestCase):
    def setUp(self):
        self.admin, self.main, self.county, self.other = fixtures()

    def snapshot(self):
        return {
            model.__name__: list(model.objects.order_by("pk").values())
            for model in (PlateRecord, Request, Letter, AuditLog, NumberSequence)
        }

    def test_selected_digit_keeps_alternatives_and_all_three_text_variations(self):
        before = self.snapshot()
        result = availability("KOWA", digit=7)
        suggestions = result["suggestions"]
        for digit in range(10):
            if digit != 7:
                self.assertIn(f"P{digit}KOWA", suggestions)
        self.assertIn("P7KOW", suggestions)
        self.assertIn("P7KOWAS", suggestions)
        self.assertTrue(any(len(number[2:]) == 4 and number[2:] != "KOWA" for number in suggestions))
        self.assertNotIn("P7KOWA", suggestions)
        self.assertEqual(len(suggestions), 12)
        self.assertEqual(self.snapshot(), before)

    def test_no_digit_selection_does_not_repeat_displayed_numbers(self):
        result = availability("KOWA")
        self.assertFalse({item["number"] for item in result["digits"]} & set(result["suggestions"]))
        self.assertTrue(any(len(number[2:]) == 3 for number in result["suggestions"]))
        self.assertTrue(any(len(number[2:]) == 5 for number in result["suggestions"]))
        self.assertTrue(any(len(number[2:]) == 4 for number in result["suggestions"]))

    def test_minimum_maximum_length_numeric_suffix_and_both_prefixes(self):
        for part in ("ABC", "KOWA", "KOWAL", "A12", "AB1C", "ABC12", "PPP"):
            for prefix in ("P", "M"):
                for digit in (None, 0, 7):
                    with self.subTest(part=part, prefix=prefix, digit=digit):
                        result = availability(part, prefix, digit)
                        suggestions = result["suggestions"]
                        self.assertEqual(len(suggestions), len(set(suggestions)))
                        self.assertLessEqual(len(suggestions), 12)
                        self.assertGreater(len(suggestions), 0)
                        for number in suggestions:
                            self.assertEqual(validate_number(number), number)
                            self.assertTrue(number.startswith(prefix))
                            self.assertNotIn("Q", number)
                        self.assertFalse({item["number"] for item in result["digits"]} & set(suggestions))

    def test_occupied_variants_from_any_office_are_excluded_and_released_can_return(self):
        initial = availability("KOWA")["suggestions"]
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
        result = availability("KOWA")
        self.assertIn(initial[0], result["suggestions"])
        self.assertFalse(set(initial[1:]) & set(result["suggestions"]))
        self.assertEqual(len(result["suggestions"]), 12)
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
                    self.assertContains(page, f"<span>{number}</span>")
                self.assertNotContains(response, "Właściciel wyłącznie testowy")
                self.assertEqual(response["Cache-Control"], "no-store")
