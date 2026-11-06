"""Pule tablic zmniejszonych i tymczasowych: kolejne wolne numery w liczbie 10–100 (uwagi UMP 06.11.2026)."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from .documents import letter_content
from .forms import PoolForm, RequestForm
from .models import AuditLog, NumberSequence, Office, Pool, PoolSlot, Request
from .services import (
    allocate_block,
    create_request,
    decide_request,
    preview_block,
    send_request,
)
from .tests import fixtures


def span(pool):
    return pool.slots.first().number, pool.slots.last().number


def pool_request(author, kind="II", count=30):
    return create_request(author, {"kind": kind, "count": count, "justification": "Fikcyjne zapotrzebowanie"})


class PoolBlockTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_pools_follow_one_counter_for_all_offices(self):
        pools = [allocate_block(self.ump, "II", office, count) for office, count in (("a", 10), ("b", 100), ("a", 20))]
        self.assertEqual(
            [span(pool) for pool in pools], [("M001", "M010"), ("M011", "M110"), ("M111", "M130")]
        )
        self.assertEqual([pool.total for pool in pools], [10, 100, 20])
        self.assertEqual(NumberSequence.objects.get(scope="POOL.II.M").last_value, 130)

    def test_temporary_pools_have_their_own_counter(self):
        allocate_block(self.ump, "II", "a", 50)
        first = allocate_block(self.ump, "III", "b", 10)
        second = allocate_block(self.ump, "III", "a", 40)
        self.assertEqual(span(first), ("M00001", "M00010"))
        self.assertEqual(span(second), ("M00011", "M00050"))
        self.assertEqual(span(allocate_block(self.ump, "II", "b", 10)), ("M051", "M060"))

    def test_count_outside_list_is_refused_without_writes(self):
        for count in (0, 5, 15, 110, 1000, "10", None):
            with self.subTest(count=count), self.assertRaises(ValidationError):
                allocate_block(self.ump, "II", "a", count)
        self.assertFalse(Pool.objects.exists())

    def test_new_pools_are_open_ended_and_dated_today(self):
        for kind in ("II", "III"):
            pool = allocate_block(self.ump, kind, "a", 10)
            self.assertIsNone(pool.valid_until)
            self.assertEqual(pool.valid_from, timezone.localdate())
            self.assertIsNone(pool.request)

    def historical(self, kind, prefix, ordinal, number):
        pool = Pool.objects.create(
            kind=kind, office_id="a", prefix=prefix, start=ordinal, end=ordinal, valid_from="2025-01-01"
        )
        PoolSlot.objects.create(pool=pool, number=number, ordinal=ordinal)

    def test_taken_numbers_are_skipped_and_pool_keeps_requested_count(self):
        self.historical("III", "M0", 5, "M00005")
        pool = allocate_block(self.ump, "III", "b", 10)
        self.assertEqual((span(pool), pool.total), (("M00001", "M00011"), 10))
        self.assertFalse(pool.slots.filter(number="M00005").exists())
        self.assertEqual(preview_block("III", 10), ("M00012", "M00021"))

    def test_historical_number_does_not_block_later_layouts(self):
        # Numer zajęty wcześniej nie zostawia luki, która zatrzymałaby przejście M999 → M01A.
        self.historical("II", "M", 50, "M050")
        self.historical("II", "M", 950, "M950")
        pools = [allocate_block(self.ump, "II", "a", 100) for _ in range(10)]
        self.assertEqual(span(pools[0]), ("M001", "M101"))
        self.assertEqual(pools[9].slots.last().ordinal, 1002)
        self.assertEqual(PoolSlot.objects.filter(pool__kind="II", ordinal__lte=999).count(), 999)

    def test_preview_shows_next_range_without_taking_it(self):
        self.assertEqual(preview_block("II", 20), ("M001", "M020"))
        self.assertEqual(preview_block("II", 20), ("M001", "M020"))
        self.assertFalse(Pool.objects.exists())
        allocate_block(self.ump, "II", "a", 20)
        self.assertEqual(preview_block("II", 100), ("M021", "M120"))

    def test_only_ump_allocates_and_inactive_office_is_refused(self):
        with self.assertRaises(PermissionDenied):
            allocate_block(self.a, "II", "a", 10)
        Office.objects.filter(pk="b").update(active=False)
        with self.assertRaises(Office.DoesNotExist):
            allocate_block(self.ump, "II", "b", 10)
        self.assertFalse(Pool.objects.exists())
        self.assertFalse(NumberSequence.objects.filter(scope="POOL.II.M", last_value__gt=0).exists())

    def test_audit_records_who_office_and_range(self):
        pool = allocate_block(self.ump, "II", "b", 30, ip="192.0.2.5")
        event = AuditLog.objects.get(action="pool.allocated", object_id=str(pool.pk))
        self.assertEqual(event.actor, self.ump)
        self.assertEqual(event.office_id, "b")
        self.assertEqual(event.ip, "192.0.2.5")
        self.assertEqual((event.after["first_number"], event.after["last_number"]), ("M001", "M030"))
        self.assertTrue(event.after["automatic"])

    def test_letter_states_open_ended_period_without_station(self):
        pool = allocate_block(self.ump, "II", "a", 40)
        _, body, _ = letter_content("POOL", None, pool, self.ump.office, pool.office)
        self.assertIn("Okres obowiązywania: bezterminowo", body)
        self.assertIn("Pula tablic zmniejszonych: M001 - M040 (40 numerów)", body)
        self.assertNotIn("Stacja", body)

    def test_request_approval_allocates_requested_count(self):
        allocate_block(self.ump, "II", "a", 10)
        req = pool_request(self.b, count=70)
        self.assertEqual(req.count, 70)
        send_request(self.b, req.uuid)
        decide_request(self.ump, req.uuid, True)
        pool = Pool.objects.get(request=req)
        self.assertEqual((span(pool), pool.total, pool.office_id), (("M011", "M080"), 70, "b"))

    def test_request_count_must_come_from_list(self):
        for count in (None, 0, 15, 110, 101):
            with self.subTest(count=count), self.assertRaises(ValidationError):
                create_request(self.a, {"kind": "II", "count": count, "justification": "Test"})
        for count in ("15", "110", ""):
            form = RequestForm({"kind": "III", "count": count, "justification": "Test"}, user=self.a)
            self.assertFalse(form.is_valid())
            self.assertIn("count", form.errors)
        form = RequestForm({"kind": "III", "count": "100", "justification": "Test"}, user=self.a)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["count"], 100)
        self.assertFalse(Request.objects.exists())

    def test_county_form_lists_counts_ten_to_hundred(self):
        self.client.force_login(self.a)
        page = self.client.get(reverse("request_new"))
        field = RequestForm(user=self.a).fields["count"]
        self.assertEqual([value for value, _ in field.widget.choices][1:], [str(n) for n in range(10, 101, 10)])
        self.assertContains(page, "Liczba tablic w puli")
        self.assertNotContains(page, "Stacja")
        self.assertNotIn("count", RequestForm(user=self.ump).fields)

    def test_forms_ask_for_kind_office_and_count(self):
        self.assertEqual(list(PoolForm().fields), ["kind", "office", "count"])
        self.assertEqual(PoolForm().fields["kind"].label, "Rodzaj puli")

    def test_pool_form_shows_preview_and_allocates_with_server_range(self):
        self.client.force_login(self.ump)
        page = self.client.get(reverse("pool_new"))
        self.assertContains(page, 'pula zacznie się od numeru <strong class="number">M001</strong>')
        self.assertContains(page, 'pula zacznie się od numeru <strong class="number">M00001</strong>')
        for name in ("prefix", "start", "end", "valid_from", "valid_until"):
            self.assertNotContains(page, f'name="{name}"')
        response = self.client.post(
            reverse("pool_new"), {"kind": "II", "office": "a", "count": "50", "start": 500}, follow=True
        )
        self.assertContains(response, "Przydzielono pulę M001 – M050.")
        self.assertEqual(span(Pool.objects.get()), ("M001", "M050"))
        self.assertContains(self.client.get(reverse("pools_list")), "bezterminowo")
        self.client.force_login(self.a)
        self.assertEqual(
            self.client.post(reverse("pool_new"), {"kind": "II", "office": "a", "count": "10"}).status_code, 403
        )

    def test_api_allocates_block_and_returns_range(self):
        self.client.force_login(self.ump)
        response = self.client.post(
            "/api/pools/", {"kind": "III", "office": "b"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            (response.json()["first_number"], response.json()["last_number"], response.json()["total"]),
            ("M00001", "M00100", 100),
        )
        response = self.client.post(
            "/api/pools/", {"kind": "III", "office": "b", "count": 20}, content_type="application/json"
        )
        self.assertEqual(response.json()["total"], 20)
        response = self.client.post(
            "/api/pools/", {"kind": "III", "office": "b", "count": 15}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_old_names_do_not_appear_in_labels_or_pages(self):
        allocate_block(self.ump, "II", "a", 10)
        allocate_block(self.ump, "III", "a", 10)
        self.assertEqual(dict(Request.Kind.choices)["II"], "Pula tablic zmniejszonych")
        self.assertEqual(dict(Request.Kind.choices)["III"], "Pula tablic tymczasowych")
        pages = []
        self.client.force_login(self.ump)
        pages += [self.client.get(reverse(name)) for name in ("pools_list", "pool_new", "requests_list")]
        self.client.force_login(self.a)
        pages += [self.client.get(reverse("request_new")), self.client.get(reverse("pools_list"))]
        for page in pages:
            text = page.content.decode().lower()
            for old in ("wąsk", "do badań", "stacja / przeznaczenie"):
                self.assertNotIn(old, text)
        self.assertContains(pages[0], "Pula tablic zmniejszonych")
        self.assertContains(pages[0], "Pula tablic tymczasowych")


class PoolBlockConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_parallel_allocations_never_share_a_range(self):
        _, ump, _, _ = fixtures()
        barrier = Barrier(4)

        def allocate(office):
            close_old_connections()
            try:
                barrier.wait()
                return span(allocate_block(ump, "II", office, 100))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=4) as executor:
            spans = list(executor.map(allocate, ["a", "b", "a", "b"]))
        self.assertEqual(
            sorted(spans), [("M001", "M100"), ("M101", "M200"), ("M201", "M300"), ("M301", "M400")]
        )
        self.assertEqual(PoolSlot.objects.count(), 400)
