from datetime import date

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
        self.assertContains(first, '<li class="number">P001</li>', html=True)
        self.assertNotContains(first, ">P501<")
        last = self.client.get(self.url, {"page": "6"})
        self.assertEqual([slot.number for slot in last.context["slots"]], ["P501"])
        self.assertContains(last, '<li class="number">P501</li>', html=True)
        self.assertContains(last, "Numery 501–501 z 501")

    def test_pool_shows_allocated_range_and_date_without_usage_tracking(self):
        page = self.client.get(self.url)
        self.assertContains(page, "501 numerów")
        self.assertContains(page, "Data przydziału")
        self.assertContains(page, timezone.localdate().strftime("%d.%m.%Y"))
        for usage in ("wydanych", "Wydaj", "Numer sprawy wydania", "Cofnij", "wykorzyst"):
            self.assertNotContains(page, usage)
        listing = self.client.get(reverse("pools_list"))
        self.assertContains(listing, "Liczba numerów")
        self.assertContains(listing, "Data przydziału")
        self.assertNotContains(listing, "<progress")
        self.assertNotContains(listing, "Wykorzystanie")
        self.assertNotContains(listing, "Najbardziej wykorzystane")

    def test_pool_page_does_not_record_issuance(self):
        slot = self.pool.slots.last()
        response = self.client.post(self.url + "?page=6", {"slot": slot.pk, "case_number": "TEST/501"})
        self.assertEqual(response.status_code, 405)
        slot.refresh_from_db()
        self.assertIsNone(slot.issued_at)
        self.assertFalse(AuditLog.objects.filter(action="pool.number_issued").exists())

    def test_foreign_office_cannot_read_last_page(self):
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(self.url, {"page": "6"}).status_code, 404)

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
