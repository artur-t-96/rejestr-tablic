"""Interleaving rzeczywistych transakcji; bez kontenerów i zewnętrznych usług."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from .documents import lock_letter
from .integrations import enqueue, process_job
from .models import AuditLog, IntegrationJob, LoginCode, PlateRecord, User
from .services import (
    allocate_pool,
    create_request,
    decide_request,
    expire_reservations,
    extend_reservation,
    issue_slot,
    send_request,
    withdraw_request,
)
from .tests import data, fixtures


class ReservationDeadlineTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_expired_reservation_cannot_be_extended_sent_or_decided(self):
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        past = timezone.now() - timedelta(seconds=1)
        PlateRecord.objects.filter(pk=req.record_id).update(reservation_until=past)
        with self.assertRaises(ValidationError):
            extend_reservation(self.ump, req.record.uuid, 14, "Za późno")
        with self.assertRaises(ValidationError):
            decide_request(self.ump, req.uuid, True)
        with self.assertRaises(ValidationError):
            withdraw_request(self.a, req.uuid, "Za późno")
        second = create_request(self.a, data("P1TEST"))
        PlateRecord.objects.filter(pk=second.record_id).update(reservation_until=past)
        with self.assertRaises(ValidationError):
            send_request(self.a, second.uuid)
        self.assertEqual(expire_reservations(), 1)
        for request in (req, second):
            request.refresh_from_db()
            request.record.refresh_from_db()
            self.assertEqual(request.status, "EXPIRED")
            self.assertEqual(request.record.status, "RELEASED")
            self.assertEqual(request.record.reservation_until, past)
        self.assertFalse(AuditLog.objects.filter(action="reservation.extended").exists())

    def test_otp_for_administrator_without_office(self):
        token = LoginCode.objects.create(
            user=self.admin,
            digest=make_password("123456"),
            expires_at=timezone.now() + timedelta(minutes=1),
        )
        session = self.client.session
        session["login_code_id"] = token.pk
        session.save()
        self.assertEqual(self.client.post("/logowanie/kod/", {"code": "123456"}).status_code, 302)
        token.refresh_from_db()
        self.assertTrue(token.used)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.admin.pk)


class DatabaseConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    @skipUnlessDBFeature("has_select_for_update")
    def test_office_document_lock_allows_unrelated_new_document_foreign_keys(self):
        old = create_request(self.a, data()).letters.get()
        locked, resume = Event(), Event()

        def hold_document():
            close_old_connections()
            try:
                with transaction.atomic():
                    lock_letter(old)
                    locked.set()
                    if not resume.wait(5):
                        raise TimeoutError("Nie zwolniono blokady pisma testowego.")
            finally:
                close_old_connections()

        def generate():
            close_old_connections()
            try:
                return create_request(User.objects.get(pk=self.a.pk), data("P1TEST")).reference_ordinal
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(hold_document)
            try:
                self.assertTrue(locked.wait(5))
                self.assertEqual(executor.submit(generate).result(timeout=3), 2)
            finally:
                resume.set()
            first.result(timeout=5)

    @skipUnlessDBFeature("has_select_for_update")
    def test_expiry_with_waiting_withdrawal_has_no_deadlock(self):
        # Wygaszanie zatrzymane po blokadzie tablicy, przed UPDATE wniosku.
        # Drugi proces musi już czekać na bazie. Stara kolejność wniosek →
        # tablica powodowała wtedy rzeczywisty deadlock PostgreSQL.
        req = create_request(self.a, data())
        PlateRecord.objects.filter(pk=req.record_id).update(
            reservation_until=timezone.now() - timedelta(seconds=1)
        )
        expiry_locked, resume_expiry, withdrawal_started = Event(), Event(), Event()
        worker_pid = []

        def expire():
            close_old_connections()

            def pause(execute, sql, params, many, context):
                if sql.startswith('UPDATE "registry_request"'):
                    expiry_locked.set()
                    if not resume_expiry.wait(5):
                        raise TimeoutError("Nie wznowiono wygaszania w teście.")
                return execute(sql, params, many, context)

            try:
                with connection.execute_wrapper(pause):
                    return expire_reservations()
            finally:
                close_old_connections()

        def withdraw():
            close_old_connections()
            try:
                user = User.objects.get(pk=self.a.pk)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    worker_pid.append(cursor.fetchone()[0])
                withdrawal_started.set()
                try:
                    withdraw_request(user, req.uuid, "Test współbieżności")
                    return "withdrawn"
                except ValidationError:
                    return "expired"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(expire)
            try:
                self.assertTrue(expiry_locked.wait(5))
                second = executor.submit(withdraw)
                self.assertTrue(withdrawal_started.wait(5))
                waiting = False
                until = time.monotonic() + 3
                while time.monotonic() < until:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", worker_pid
                        )
                        state = cursor.fetchone()
                    if state and state[0] == "Lock":
                        waiting = True
                        break
                    time.sleep(0.02)
                self.assertTrue(waiting, "Nie potwierdzono oczekiwania na blokadę PostgreSQL.")
            finally:
                resume_expiry.set()
            self.assertEqual(first.result(timeout=5), 1)
            self.assertEqual(second.result(timeout=5), "expired")
        req.refresh_from_db()
        req.record.refresh_from_db()
        self.assertEqual((req.status, req.record.status), ("EXPIRED", "RELEASED"))
        self.assertEqual(AuditLog.objects.filter(action="reservation.expired").count(), 1)
        self.assertFalse(AuditLog.objects.filter(action="request.withdrawn").exists())

    def test_decision_and_withdrawal_leave_consistent_request_and_plate(self):
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        barrier = Barrier(2)

        def operation(approve):
            close_old_connections()
            try:
                user = User.objects.get(pk=self.ump.pk if approve else self.a.pk)
                barrier.wait(timeout=5)
                try:
                    if approve:
                        decide_request(user, req.uuid, True)
                        return "approved"
                    withdraw_request(user, req.uuid, "Wycofanie testowe")
                    return "withdrawn"
                except ValidationError:
                    return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(operation, [True, False]))
        self.assertEqual(results.count("conflict"), 1)
        req.refresh_from_db()
        req.record.refresh_from_db()
        self.assertIn((req.status, req.record.status), [("APPROVED", "ALLOCATED"), ("WITHDRAWN", "RELEASED")])

    def test_same_pool_number_can_only_be_issued_once(self):
        pool = allocate_pool(
            self.ump,
            {
                "kind": "II",
                "office": self.a.office_id,
                "prefix": "P",
                "start": 1,
                "end": 2,
                "valid_from": timezone.localdate(),
            },
        )
        slot = pool.slots.first()
        barrier = Barrier(2)

        def issue(case):
            close_old_connections()
            try:
                user = User.objects.get(pk=self.a.pk)
                barrier.wait(timeout=5)
                try:
                    issue_slot(user, pool.uuid, slot.pk, case)
                    return "issued"
                except ValidationError:
                    return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(issue, ["TEST/1", "TEST/2"]))
        self.assertEqual(sorted(results), ["conflict", "issued"])
        slot.refresh_from_db()
        self.assertIsNotNone(slot.issued_at)
        self.assertEqual(AuditLog.objects.filter(action="pool.number_issued").count(), 1)

    def test_two_workers_claim_one_job_without_duplicate_send(self):
        req = create_request(self.a, data())
        job = enqueue(self.a, req.letters.get(), "SMTP")
        network_started, network_resume = Event(), Event()

        def send(job):
            network_started.set()
            if not network_resume.wait(5):
                raise TimeoutError("Nie wznowiono fikcyjnego transportu testowego.")
            return "LOCAL_SAVED"

        def process():
            close_old_connections()
            try:
                return process_job(IntegrationJob.objects.get(pk=job.pk)).status
            finally:
                close_old_connections()

        with patch("registry.integrations.send_email", side_effect=send) as transport:
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(process)
                try:
                    self.assertTrue(network_started.wait(5))
                    self.assertEqual(executor.submit(process).result(timeout=5), "PROCESSING")
                finally:
                    network_resume.set()
                self.assertEqual(first.result(timeout=5), "LOCAL_SAVED")
            self.assertEqual(transport.call_count, 1)
        job.refresh_from_db()
        self.assertEqual(job.attempts, 1)
        self.assertEqual(job.status, "LOCAL_SAVED")
