"""Automatyczne pule tablic wąskich i tymczasowych (uwagi UMP z 29.10.2026)."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from .documents import letter_content
from .forms import PoolForm, RequestForm
from .models import AuditLog, NumberSequence, Office, Pool, PoolSlot, Request
from .services import (
    allocate_block,
    allocate_pool,
    create_request,
    decide_request,
    preview_block,
    send_request,
)
from .tests import fixtures


def span(pool):
    return pool.slots.first().number, pool.slots.last().number


class PoolBlockTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_narrow_blocks_follow_one_counter_for_all_offices(self):
        pools = [allocate_block(self.ump, "II", office) for office in ("a", "b", "a")]
        self.assertEqual(
            [span(pool) for pool in pools], [("M001", "M099"), ("M100", "M199"), ("M200", "M299")]
        )
        self.assertEqual([pool.total for pool in pools], [99, 100, 100])
        self.assertEqual(NumberSequence.objects.get(scope="POOL.II.M").last_value, 3)

    def test_temporary_blocks_have_their_own_counter(self):
        allocate_block(self.ump, "II", "a")
        allocate_block(self.ump, "II", "a")
        first = allocate_block(self.ump, "III", "b")
        second = allocate_block(self.ump, "III", "a")
        self.assertEqual(span(first), ("M00001", "M00099"))
        self.assertEqual(span(second), ("M00100", "M00199"))
        self.assertEqual(span(allocate_block(self.ump, "II", "b")), ("M200", "M299"))

    def test_new_pools_are_open_ended_and_dated_today(self):
        for kind in ("II", "III"):
            pool = allocate_block(self.ump, kind, "a")
            self.assertIsNone(pool.valid_until)
            self.assertEqual(pool.valid_from, timezone.localdate())
            self.assertIsNone(pool.request)

    def test_block_skips_numbers_already_taken_by_earlier_pools(self):
        allocate_pool(
            self.ump,
            {
                "kind": "III",
                "office": "a",
                "prefix": "M0",
                "start": 150,
                "end": 160,
                "valid_from": "2026-01-01",
            },
            automatic=True,
        )
        self.assertEqual(preview_block("III"), ("M00200", "M00299"))
        self.assertEqual(span(allocate_block(self.ump, "III", "b")), ("M00200", "M00299"))

    def test_preview_shows_next_block_without_reserving_it(self):
        self.assertEqual(preview_block("II"), ("M001", "M099"))
        self.assertEqual(preview_block("II"), ("M001", "M099"))
        self.assertFalse(Pool.objects.exists())
        allocate_block(self.ump, "II", "a")
        self.assertEqual(preview_block("II"), ("M100", "M199"))

    @override_settings(POOL_BLOCKS={"II": {"prefix": "M", "size": 50}, "III": {"prefix": "P0", "size": 20}})
    def test_prefix_and_block_size_come_from_configuration(self):
        self.assertEqual(span(allocate_block(self.ump, "II", "a")), ("M001", "M049"))
        self.assertEqual(span(allocate_block(self.ump, "II", "a")), ("M050", "M099"))
        self.assertEqual(span(allocate_block(self.ump, "III", "a")), ("P00001", "P00019"))

    def test_only_ump_allocates_and_inactive_office_is_refused(self):
        with self.assertRaises(PermissionDenied):
            allocate_block(self.a, "II", "a")
        Office.objects.filter(pk="b").update(active=False)
        with self.assertRaises(Office.DoesNotExist):
            allocate_block(self.ump, "II", "b")
        self.assertFalse(Pool.objects.exists())
        self.assertFalse(NumberSequence.objects.filter(scope="POOL.II.M", last_value__gt=0).exists())

    def test_audit_records_who_office_and_range(self):
        pool = allocate_block(self.ump, "II", "b", ip="192.0.2.5")
        event = AuditLog.objects.get(action="pool.allocated", object_id=str(pool.pk))
        self.assertEqual(event.actor, self.ump)
        self.assertEqual(event.office_id, "b")
        self.assertEqual(event.ip, "192.0.2.5")
        self.assertEqual((event.after["first_number"], event.after["last_number"]), ("M001", "M099"))
        self.assertTrue(event.after["automatic"])

    def test_letter_states_open_ended_period(self):
        pool = allocate_block(self.ump, "II", "a")
        _, body, _ = letter_content("POOL", None, pool, self.ump.office, pool.office)
        self.assertIn("Okres obowiązywania: bezterminowo", body)
        self.assertIn("Pula tablic wąskich: M001 - M099 (99 numerów)", body)

    def test_request_approval_allocates_next_block(self):
        allocate_block(self.ump, "II", "a")
        req = create_request(self.b, {"kind": "II", "case_number": "PULA/1", "justification": "Test"})
        self.assertEqual(req.count, 100)
        send_request(self.b, req.uuid)
        decide_request(self.ump, req.uuid, True)
        pool = Pool.objects.get(request=req)
        self.assertEqual((span(pool), pool.office_id), (("M100", "M199"), "b"))
        req.refresh_from_db()
        self.assertEqual(req.count, 100)

    def test_forms_ask_only_for_kind_and_office(self):
        self.assertEqual(list(PoolForm().fields), ["kind", "office"])
        self.assertEqual(PoolForm().fields["kind"].label, "Rodzaj puli")
        self.assertNotIn("count", RequestForm().fields)

    def test_pool_form_shows_preview_and_allocates_with_server_range(self):
        self.client.force_login(self.ump)
        page = self.client.get(reverse("pool_new"))
        self.assertContains(page, 'zostanie przydzielona pula <strong class="number">M001 – M099</strong>')
        self.assertContains(
            page, 'zostanie przydzielona pula <strong class="number">M00001 – M00099</strong>'
        )
        for name in ("prefix", "start", "end", "valid_from", "valid_until"):
            self.assertNotContains(page, f'name="{name}"')
        response = self.client.post(
            reverse("pool_new"), {"kind": "II", "office": "a", "start": 500, "end": 900}, follow=True
        )
        self.assertContains(response, "Przydzielono pulę M001 – M099.")
        self.assertEqual(span(Pool.objects.get()), ("M001", "M099"))
        self.assertContains(self.client.get(reverse("pools_list")), "bezterminowo")
        self.client.force_login(self.a)
        self.assertEqual(
            self.client.post(reverse("pool_new"), {"kind": "II", "office": "a"}).status_code, 403
        )

    def test_api_allocates_block_and_returns_range(self):
        self.client.force_login(self.ump)
        response = self.client.post(
            "/api/pools/", {"kind": "III", "office": "b"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            (response.json()["first_number"], response.json()["last_number"], response.json()["total"]),
            ("M00001", "M00099", 99),
        )

    def test_old_names_do_not_appear_in_labels_or_pages(self):
        allocate_block(self.ump, "II", "a")
        allocate_block(self.ump, "III", "a")
        self.assertEqual(dict(Request.Kind.choices)["II"], "Pula tablic wąskich")
        self.assertEqual(dict(Request.Kind.choices)["III"], "Pula tablic tymczasowych")
        pages = []
        self.client.force_login(self.ump)
        pages += [self.client.get(reverse(name)) for name in ("pools_list", "pool_new", "requests_list")]
        self.client.force_login(self.a)
        pages += [self.client.get(reverse("request_new")), self.client.get(reverse("pools_list"))]
        for page in pages:
            text = page.content.decode().lower()
            for old in ("zmniejsz", "do badań"):
                self.assertNotIn(old, text)
        self.assertContains(pages[0], "Pula tablic wąskich")
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
                return span(allocate_block(ump, "II", office))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=4) as executor:
            spans = list(executor.map(allocate, ["a", "b", "a", "b"]))
        self.assertEqual(
            sorted(spans), [("M001", "M099"), ("M100", "M199"), ("M200", "M299"), ("M300", "M399")]
        )
        self.assertEqual(PoolSlot.objects.count(), 99 + 300)
