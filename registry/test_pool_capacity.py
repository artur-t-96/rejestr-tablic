import json
import re
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from .models import AuditLog, IntegrationJob, Letter, Pool, PoolSlot
from .pool_capacity import capacity_pattern, occupied_capacity
from .services import allocate_pool, create_request, decide_request, send_request
from .tests import fixtures
from .validation import SMALL_SUFFIXES, TEMPORARY_CAPACITY, pool_numbers, temporary_suffix


class PoolNumberSequenceTests(SimpleTestCase):
    def test_temporary_boundaries_and_letter_order(self):
        self.assertEqual(pool_numbers("III", "P0", 9998, 10001), ["P09998", "P09999", "P0001A", "P0002A"])
        self.assertEqual(pool_numbers("III", "P9", 10998, 10999), ["P9999A", "P9001C"])
        self.assertEqual(pool_numbers("III", "M9", 29979, 29979), ["M9999Y"])

    def test_all_generated_suffixes_are_unique_and_match_capacity_query(self):
        small = re.compile(capacity_pattern("II", "P"))
        self.assertEqual(len(SMALL_SUFFIXES), 17379)
        self.assertEqual(len(set(SMALL_SUFFIXES)), 17379)
        self.assertTrue(all(small.fullmatch("P" + s) for s in SMALL_SUFFIXES))
        temporary = re.compile(capacity_pattern("III", "P[0-9]"))
        suffixes = [temporary_suffix(i) for i in range(1, TEMPORARY_CAPACITY + 1)]
        self.assertEqual(TEMPORARY_CAPACITY, 29979)
        self.assertEqual(len(set(suffixes)), 29979)
        for digit in range(10):
            self.assertTrue(all(temporary.fullmatch(f"P{digit}" + s) for s in suffixes))

    def test_invalid_zero_numbers_letters_and_shapes_do_not_count(self):
        small = re.compile(capacity_pattern("II", "P"))
        for number in ["P000", "P00A", "PA00", "P0AA", "PAA0", "PA0A", "P01B", "P01Q", "P1234"]:
            with self.subTest(number=number):
                self.assertIsNone(small.fullmatch(number))
        temporary = re.compile(capacity_pattern("III", "P[0-9]"))
        for number in [
            "P00000",
            "P0000A",
            "P0001B",
            "P0001D",
            "P0001I",
            "P0001O",
            "P0001Q",
            "P0001Z",
            "P0001AA",
            "M00001",
        ]:
            with self.subTest(number=number):
                self.assertIsNone(temporary.fullmatch(number))

    def test_out_of_capacity_batch_and_scheme_are_rejected(self):
        for start, end in [(0, 1), (True, 2), (1, 10001), (29979, 29980)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValidationError):
                pool_numbers("III", "P0", start, end)
        with self.assertRaisesMessage(ValidationError, "schemat"):
            pool_numbers("III", "P0", 1, 2, scheme="UNKNOWN")


class PoolCapacityTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.author, self.other = fixtures()

    def raw_pool(self, kind="III", prefix="P0", end=9999):
        # Jawna historyczna ewidencja tylko w odrębnej bazie testowej.
        return Pool.objects.create(
            kind=kind,
            office=self.other.office,
            prefix=prefix,
            start=1,
            end=end,
            valid_from=timezone.localdate() - timedelta(days=60),
            valid_until=timezone.localdate() - timedelta(days=30),
        )

    def insert_numbers(self, pool, numbers):
        PoolSlot.objects.bulk_create(
            [PoolSlot(pool=pool, number=n, ordinal=i) for i, n in enumerate(numbers, 1)],
            batch_size=1000,
        )

    def pending(self, count=1):
        req = create_request(
            self.author,
            {
                "kind": "III",
                "case_number": "TEST/CAPACITY/1",
                "count": count,
                "justification": "Fikcyjne zapotrzebowanie",
            },
        )
        send_request(self.author, req.uuid)
        return req

    def decision_data(self, prefix="P0", start=10000, end=10000):
        return {
            "prefix": prefix,
            "start": start,
            "end": end,
            "valid_from": timezone.localdate(),
            "valid_until": timezone.localdate() + timedelta(days=30),
        }

    def counts(self):
        return tuple(m.objects.count() for m in (Pool, PoolSlot, Letter, IntegrationJob, AuditLog))

    def test_range_end_without_actual_numbers_does_not_exhaust_capacity(self):
        old = self.raw_pool()
        self.insert_numbers(old, ["P09999", "P00000", "P0001B", "P0000A"])
        self.assertEqual(occupied_capacity("III", "P0"), 1)
        req = self.pending()
        before = self.counts()
        with self.assertRaisesMessage(ValidationError, "Najpierw przydziel całą serię"):
            decide_request(self.ump, req.uuid, True, pool_data=self.decision_data())
        req.refresh_from_db()
        self.assertEqual(req.status, "SENT")
        self.assertEqual(self.counts(), before)

    def test_last_numeric_and_first_letter_numbers_can_be_allocated_together(self):
        old = self.raw_pool(end=9997)
        self.insert_numbers(old, (f"P0{i:04d}" for i in range(1, 9998)))
        req = self.pending(4)
        decide_request(self.ump, req.uuid, True, pool_data=self.decision_data(start=9998, end=10001))
        pool = Pool.objects.get(request=req)
        self.assertEqual(
            list(pool.slots.values_list("number", flat=True)), ["P09998", "P09999", "P0001A", "P0002A"]
        )
        self.assertEqual(occupied_capacity("III", "P0"), 10001)
        self.assertEqual(IntegrationJob.objects.filter(operation="DECISION_NOTICE").count(), 1)
        letter = Letter.objects.get(pool=pool)
        self.assertIn("P09998 - P0002A (4 numerów)", letter.body)
        self.assertEqual(json.loads(bytes(IntegrationJob.objects.get().payload))["to"], self.author.email)
        second = self.pending()
        before = self.counts()
        with self.assertRaisesMessage(ValidationError, "Kolizja numeru P0001A"):
            decide_request(self.ump, second.uuid, True, pool_data=self.decision_data())
        self.assertEqual(self.counts(), before)
        next_request = self.pending()
        decide_request(
            self.ump,
            next_request.uuid,
            True,
            pool_data=self.decision_data(start=10002, end=10002),
        )
        self.assertEqual(Pool.objects.get(request=next_request).slots.get().number, "P0003A")

    def test_continuation_with_missing_old_number_is_blocked_even_if_maximum_is_present(self):
        old = self.raw_pool()
        self.insert_numbers(old, ["P09997", "P09998", "P09999"])
        req = self.pending(2)
        before = self.counts()
        with self.assertRaisesMessage(ValidationError, "3 z 9999"):
            decide_request(self.ump, req.uuid, True, pool_data=self.decision_data(start=10000, end=10001))
        self.assertEqual(self.counts(), before)

    def test_m_small_needs_every_p_number_including_expired_pools(self):
        old = self.raw_pool("II", "P", len(SMALL_SUFFIXES))
        self.insert_numbers(old, ("P" + s for s in SMALL_SUFFIXES[:-1]))
        proposal = {
            "kind": "II",
            "office": self.author.office_id,
            "prefix": "M",
            "start": 1,
            "end": 1,
            "valid_from": timezone.localdate(),
        }
        before = self.counts()
        with self.assertRaisesMessage(ValidationError, "17378 z 17379"):
            allocate_pool(self.ump, proposal)
        self.assertEqual(self.counts(), before)
        PoolSlot.objects.create(pool=old, number="P" + SMALL_SUFFIXES[-1], ordinal=17379)
        pool = allocate_pool(self.ump, proposal)
        self.assertEqual(list(pool.slots.values_list("number", flat=True)), ["M001"])

    def test_m_temporary_requires_all_p_digits_and_both_series(self):
        self.raw_pool(end=TEMPORARY_CAPACITY)
        req = self.pending()
        before = self.counts()
        with self.assertRaisesMessage(ValidationError, "0 z 299790"):
            decide_request(
                self.ump, req.uuid, True, pool_data=self.decision_data(prefix="M0", start=1, end=1)
            )
        req.refresh_from_db()
        self.assertEqual(req.status, "SENT")
        self.assertEqual(self.counts(), before)

    def test_other_module_and_foreign_prefix_do_not_count_for_current_series(self):
        small = self.raw_pool("II", "P", 1)
        self.insert_numbers(small, ["P00001"])
        temporary = self.raw_pool()
        self.insert_numbers(temporary, ["P10001", "M00001"])
        self.assertEqual(occupied_capacity("III", "P0"), 0)
        self.assertEqual(occupied_capacity("III", "P[0-9]"), 1)

    def test_http_api_enforces_m_gate_without_creating_pool_or_letter(self):
        self.client.force_login(self.ump)
        before = self.counts()
        response = self.client.post(
            "/api/pools/",
            {
                "kind": "II",
                "office": self.author.office_id,
                "prefix": "M",
                "start": 1,
                "end": 1,
                "valid_from": "2026-10-03",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("pojemność P", response.json()["error"])
        self.assertEqual(self.counts(), before)
