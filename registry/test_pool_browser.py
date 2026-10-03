from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation

from .forms import DecisionForm, PoolForm
from .models import AuditLog
from .services import allocate_pool
from .tests import fixtures


class PoolBrowserTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        self.pool = allocate_pool(
            self.ump,
            {
                "kind": "II",
                "office": "a",
                "prefix": "P",
                "start": 1,
                "end": 501,
                "valid_from": timezone.localdate(),
            },
        )
        self.url = reverse("pool_detail", args=[self.pool.uuid])
        self.client.force_login(self.a)

    def test_all_slots_are_reachable_beyond_old_500_limit(self):
        first = self.client.get(self.url)
        self.assertEqual(len(first.context["slots"]), 100)
        self.assertContains(first, 'aria-label="Strony numerów puli"')
        self.assertContains(first, 'href="?page=6"')
        self.assertContains(first, "Numer sprawy wydania P001")
        self.assertNotContains(first, "Numer sprawy wydania P501")
        last = self.client.get(self.url, {"page": "6"})
        self.assertEqual([slot.number for slot in last.context["slots"]], ["P501"])
        self.assertContains(last, "Numer sprawy wydania P501")
        self.assertContains(last, "Numery 501–501 z 501")

    def test_issue_and_error_preserve_page_and_duplicate_is_rejected(self):
        slot = self.pool.slots.last()
        error = self.client.post(self.url + "?page=6", {"slot": slot.pk, "case_number": ""})
        self.assertContains(error, "Podaj numer sprawy wydania.")
        self.assertEqual(error.context["slots"].number, 6)
        result = self.client.post(self.url + "?page=6", {"slot": slot.pk, "case_number": "TEST/501"})
        self.assertRedirects(result, self.url + "?page=6")
        slot.refresh_from_db()
        self.assertEqual(slot.case_number, "TEST/501")
        self.assertEqual(slot.issued_by, self.a)
        duplicate = self.client.post(self.url + "?page=6", {"slot": slot.pk, "case_number": "TEST/DUP"})
        self.assertContains(duplicate, "Ten numer został już wydany.")
        self.assertEqual(duplicate.context["slots"].number, 6)
        slot.refresh_from_db()
        self.assertEqual(slot.case_number, "TEST/501")
        self.assertEqual(AuditLog.objects.filter(action="pool.number_issued").count(), 1)

    def test_foreign_office_cannot_read_or_issue_last_page(self):
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(self.url, {"page": "6"}).status_code, 404)
        slot = self.pool.slots.last()
        response = self.client.post(self.url + "?page=6", {"slot": slot.pk, "case_number": "TEST/FOREIGN"})
        self.assertEqual(response.status_code, 404)
        slot.refresh_from_db()
        self.assertIsNone(slot.issued_at)

    def test_invalid_page_values_are_safe_and_bounded(self):
        for value, expected in (("bad", 1), ("99999999999999", 6), ("0", 6)):
            with self.subTest(value=value):
                response = self.client.get(self.url, {"page": value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["slots"].number, expected)
                self.assertLessEqual(len(response.context["slots"]), 100)

    def test_native_date_widgets_use_iso_even_in_polish_locale(self):
        with translation.override("pl"):
            for form in (PoolForm, DecisionForm):
                page = form(initial={"valid_from": date(2026, 10, 3), "valid_until": date(2026, 12, 31)})
                self.assertIn('value="2026-10-03"', str(page["valid_from"]))
                self.assertIn('value="2026-12-31"', str(page["valid_until"]))

    def test_outside_validity_cannot_issue(self):
        self.pool.valid_from = timezone.localdate() + timedelta(days=1)
        self.pool.save(update_fields=["valid_from"])
        slot = self.pool.slots.last()
        result = self.client.post(self.url + "?page=6", {"slot": slot.pk, "case_number": "TEST/FUTURE"})
        self.assertContains(result, "Pula nie obowiązuje w dniu wydania.")
        self.assertEqual(result.context["slots"].number, 6)
        slot.refresh_from_db()
        self.assertIsNone(slot.issued_at)
