from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import close_old_connections, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, IntegrationJob, Letter, NumberSequence, Pool, PoolSlot, User
from .pool_capacity import require_capacity_order
from .services import allocate_pool, create_request, decide_request, issue_slot, send_request
from .tests import fixtures
from .validation import SMALL_SUFFIXES


class SmallLayoutOrderTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.author, self.other = fixtures()

    def historical_pool(self, prefix="P", kind="II", end=17379):
        return Pool.objects.create(
            kind=kind,
            office=self.author.office,
            prefix=prefix,
            start=1,
            end=end,
            valid_from=timezone.localdate() - timedelta(days=30),
            valid_until=timezone.localdate() + timedelta(days=30),
        )

    def insert(self, pool, numbers):
        PoolSlot.objects.bulk_create(
            [PoolSlot(pool=pool, number=number, ordinal=position) for position, number in numbers],
            batch_size=1000,
        )

    def proposal(self, start, end=None, prefix="P"):
        return {
            "kind": "II",
            "office": self.author.office_id,
            "prefix": prefix,
            "start": start,
            "end": start if end is None else end,
            "valid_from": timezone.localdate(),
        }

    def snapshot(self):
        return {
            model.__name__: list(model.objects.order_by("pk").values())
            for model in (Pool, PoolSlot, Letter, NumberSequence, IntegrationJob, AuditLog)
        }

    def test_declared_end_invalid_numbers_wrong_module_and_prefix_do_not_fill_previous_layout(self):
        old = self.historical_pool(end=999)
        self.insert(old, [(998, "P998"), (999, "P999"), (1, "P000"), (2, "M001")])
        other_module = self.historical_pool(kind="III")
        self.insert(other_module, [(1, "P001")])
        before = self.snapshot()
        with self.assertRaisesMessage(ValidationError, "2 z 999"):
            allocate_pool(self.ump, self.proposal(1000))
        self.assertEqual(self.snapshot(), before)

    def test_all_six_layout_boundaries_require_actual_previous_numbers(self):
        # Jeden kompletny fikcyjny wykaz; każda podpróba używa savepointu.
        old = self.historical_pool()
        self.insert(old, enumerate(("P" + suffix for suffix in SMALL_SUFFIXES), 1))
        # Pozycje wynikają z siedmiu układów § 30 ust. 2 pkt 2.
        for boundary, expected in [
            (1000, "P01A"),
            (2980, "P1A1"),
            (4600, "PA01"),
            (6580, "P1AA"),
            (10180, "PAA1"),
            (13780, "PA1A"),
        ]:
            with self.subTest(boundary=boundary), transaction.atomic():
                previous = PoolSlot.objects.get(pool=old, ordinal=boundary - 1)
                previous_number = previous.number
                previous.delete()
                old.slots.get(ordinal=boundary).delete()
                before = self.snapshot()
                with self.assertRaisesMessage(ValidationError, "wcześniejszy układ"):
                    allocate_pool(self.ump, self.proposal(boundary))
                self.assertEqual(self.snapshot(), before)
                PoolSlot.objects.create(pool=old, number=previous_number, ordinal=boundary - 1)
                new = allocate_pool(self.ump, self.proposal(boundary))
                self.assertEqual(new.slots.get().number, expected)
                self.assertEqual(new.letters.count(), 1)
                transaction.set_rollback(True)

    def test_one_allocation_can_finish_numeric_layout_and_start_letter_layout(self):
        old = self.historical_pool(end=998)
        old.office = self.other.office
        old.save(update_fields=["office"])
        self.insert(old, ((i, f"P{i:03d}") for i in range(1, 999)))
        new = allocate_pool(self.ump, self.proposal(999, 1001))
        self.assertEqual(list(new.slots.values_list("number", flat=True)), ["P999", "P01A", "P01C"])
        self.assertIn("P999 - P01C (3 numerów)", new.letters.get().body)

    def test_m_layout_counts_its_own_numbers_after_p_capacity_is_exhausted(self):
        old_p = self.historical_pool()
        self.insert(old_p, enumerate(("P" + suffix for suffix in SMALL_SUFFIXES), 1))
        old_m = self.historical_pool(prefix="M", end=998)
        self.insert(old_m, ((i, f"M{i:03d}") for i in range(1, 999)))
        with self.assertRaisesMessage(ValidationError, "998 z 999"):
            allocate_pool(self.ump, self.proposal(1000, prefix="M"))
        new = allocate_pool(self.ump, self.proposal(999, 1000, prefix="M"))
        self.assertEqual(list(new.slots.values_list("number", flat=True)), ["M999", "M01A"])

    def test_one_range_can_finish_multiple_prior_layouts(self):
        new = allocate_pool(self.ump, self.proposal(1, 6580))
        self.assertEqual(new.slots.count(), 6580)
        self.assertEqual(new.slots.last().number, "P1AA")

    def test_late_hole_in_first_layout_is_not_hidden_by_complete_second_layout(self):
        old = self.historical_pool()
        self.insert(old, ((i, "P" + SMALL_SUFFIXES[i - 1]) for i in range(1, 2980) if i != 7))
        with self.assertRaisesMessage(ValidationError, "998 z 999"):
            allocate_pool(self.ump, self.proposal(2980))

    def test_failed_request_decision_keeps_request_letter_queue_and_sequence_unchanged(self):
        req = create_request(
            self.author,
            {"kind": "II", "count": 1, "case_number": "FIKCYJNE/II/01", "justification": "Fikcyjna pula"},
        )
        send_request(self.author, req.uuid)
        before = self.snapshot()
        with self.assertRaisesMessage(ValidationError, "wcześniejszy układ"):
            decide_request(self.ump, req.uuid, True, pool_data=self.proposal(1000))
        req.refresh_from_db()
        self.assertEqual(req.status, "SENT")
        self.assertEqual(self.snapshot(), before)

    def test_api_and_html_reject_jump_with_field_error_without_saving(self):
        self.client.force_login(self.ump)
        proposal = self.proposal(1000)
        before = self.snapshot()
        response = self.client.post("/api/pools/", proposal, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("wcześniejszy układ", response.json()["error"])
        response = self.client.post(reverse("pool_new"), proposal)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "wcześniejszy układ")
        self.assertEqual(self.snapshot(), before)

    def test_historical_letter_number_remains_issuable_without_reallocating_or_filling_gaps(self):
        old = self.historical_pool()
        self.insert(old, [(1000, "P01A")])
        slot = old.slots.get()
        issue_slot(self.author, old.uuid, slot.pk, "FIKCYJNE/WYDANIE/01")
        slot.refresh_from_db()
        self.assertIsNotNone(slot.issued_at)
        self.assertEqual(slot.case_number, "FIKCYJNE/WYDANIE/01")
        self.assertEqual(PoolSlot.objects.count(), 1)


class SmallLayoutConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_two_allocations_crossing_layout_boundary_have_one_complete_winner(self):
        _, ump, author, _ = fixtures()
        old = Pool.objects.create(
            kind="II",
            office=author.office,
            prefix="P",
            start=1,
            end=998,
            valid_from=timezone.localdate(),
        )
        PoolSlot.objects.bulk_create(
            [PoolSlot(pool=old, number=f"P{i:03d}", ordinal=i) for i in range(1, 999)], batch_size=1000
        )
        proposal = {
            "kind": "II",
            "office": author.office_id,
            "prefix": "P",
            "start": 999,
            "end": 1001,
            "valid_from": timezone.localdate(),
        }
        checked = Barrier(2, timeout=5)

        def synchronized_check(*args):
            require_capacity_order(*args)
            checked.wait()

        def allocate():
            close_old_connections()
            try:
                try:
                    pool = allocate_pool(User.objects.get(pk=ump.pk), proposal)
                    return ("allocated", pool.pk)
                except ValidationError as exc:
                    return ("conflict", str(exc))
            finally:
                close_old_connections()

        with patch("registry.pool_capacity.require_capacity_order", side_effect=synchronized_check):
            with ThreadPoolExecutor(max_workers=2) as workers:
                results = list(workers.map(lambda _: allocate(), range(2)))
        self.assertEqual(sorted(result[0] for result in results), ["allocated", "conflict"])
        self.assertEqual(Pool.objects.count(), 2)
        self.assertEqual(PoolSlot.objects.count(), 1001)
        new = Pool.objects.exclude(pk=old.pk).get()
        self.assertEqual(list(new.slots.values_list("number", flat=True)), ["P999", "P01A", "P01C"])
        self.assertEqual(Letter.objects.count(), 1)
        self.assertEqual(NumberSequence.objects.get().last_value, 1)
        self.assertEqual(AuditLog.objects.filter(action="pool.allocated").count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="letter.generated").count(), 1)
        self.assertFalse(IntegrationJob.objects.exists())
