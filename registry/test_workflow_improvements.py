"""Kolejka decyzji, powiadomienia, pisma papierowe, pomoc przy decyzji i ochrona logowania."""

import re
from datetime import timedelta

from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import RecordForm
from .integrations import enqueue
from .models import (
    AuditLog,
    FlaggedWord,
    IntegrationJob,
    LoginCode,
    Office,
    PlateRecord,
    Pool,
    Request,
    User,
)
from .notifications import send_reservation_reminders
from .number_checks import content_warnings, suggest_pool_range
from .services import (
    allocate_pool,
    create_request,
    decide_request,
    expire_reservations,
    extend_reservation,
    issue_slot,
    record_postal_dispatch,
    restore_expired_request,
    revoke_slot_issue,
    send_request,
    update_record,
)
from .tests import data, fixtures

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


def pool_request(author, kind="II", count=3):
    return create_request(
        author,
        {"kind": kind, "case_number": "PULA/1", "count": count, "justification": "Fikcyjne zapotrzebowanie"},
    )


class Base(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        Office.objects.filter(pk="ump").update(email="ump-kontakt@test.invalid")
        Office.objects.filter(pk="a").update(email="a-kontakt@test.invalid")

    def sent(self, user=None, number="P0TEST"):
        user = user or self.a
        req = create_request(user, data(number))
        send_request(user, req.uuid)
        req.refresh_from_db()
        return req

    def small_pool(self, end=5):
        return allocate_pool(
            self.ump,
            {
                "kind": "II",
                "office": "a",
                "prefix": "P",
                "start": 1,
                "end": end,
                "valid_from": timezone.localdate(),
            },
        )


class StatusGuardTests(Base):
    def test_correction_cannot_replace_decision_while_request_is_open(self):
        req = self.sent()
        with self.assertRaisesRegex(ValidationError, "decyzja albo wycofanie"):
            update_record(self.ump, req.record.uuid, {"status": "ALLOCATED"}, "Skrót", req.record.version)
        req.refresh_from_db()
        self.assertEqual((req.status, req.record.status), ("SENT", "SENT"))
        self.assertFalse(req.letters.filter(kind="APPROVAL").exists())
        # Pozostałe pola UMP nadal poprawia, a decyzja działa po korekcie.
        update_record(
            self.ump, req.record.uuid, {"owner": "Osoba Poprawiona"}, "Literówka", req.record.version
        )
        decide_request(self.ump, req.uuid, True)
        self.assertEqual(Request.objects.get(pk=req.pk).status, "APPROVED")

    def test_form_hides_status_only_while_request_is_open(self):
        req = self.sent()
        self.assertNotIn("status", RecordForm(instance=req.record, user=self.ump).fields)
        decide_request(self.ump, req.uuid, True)
        req.record.refresh_from_db()
        self.assertIn("status", RecordForm(instance=req.record, user=self.ump).fields)

    def test_entry_that_never_was_an_allocation_cannot_be_reactivated(self):
        req = self.sent()
        decide_request(self.ump, req.uuid, False, "Fikcyjna odmowa")
        record = PlateRecord.objects.get(pk=req.record_id)
        with self.assertRaisesRegex(ValidationError, "nie był przydziałem"):
            update_record(self.ump, record.uuid, {"status": "ALLOCATED"}, "Obejście", record.version)
        self.assertEqual(PlateRecord.objects.get(pk=record.pk).status, "RELEASED")

    def test_released_allocation_can_still_be_restored(self):
        req = self.sent()
        decide_request(self.ump, req.uuid, True)
        record = PlateRecord.objects.get(pk=req.record_id)
        record = update_record(self.ump, record.uuid, {"status": "RELEASED"}, "Pomyłka", record.version)
        record = update_record(self.ump, record.uuid, {"status": "ALLOCATED"}, "Cofnięcie", record.version)
        self.assertEqual(record.status, "ALLOCATED")


class RestoreExpiredTests(Base):
    def expired(self, submit=True):
        req = create_request(self.a, data())
        if submit:
            send_request(self.a, req.uuid)
        PlateRecord.objects.filter(pk=req.record_id).update(
            reservation_until=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(expire_reservations(), 1)
        return Request.objects.get(pk=req.pk)

    def test_ump_restores_submitted_request_and_can_decide(self):
        req = self.expired()
        self.assertEqual(req.status, "EXPIRED")
        restore_expired_request(self.ump, req.uuid, 7, "Opóźnienie po stronie UMP")
        req.refresh_from_db()
        self.assertEqual((req.status, req.record.status), ("SENT", "SENT"))
        self.assertGreater(req.record.reservation_until, timezone.now() + timedelta(days=6))
        decide_request(self.ump, req.uuid, True)
        self.assertTrue(AuditLog.objects.filter(action="request.restored", reason__contains="UMP").exists())

    def test_draft_returns_as_draft(self):
        req = self.expired(submit=False)
        restore_expired_request(self.ump, req.uuid, 3, "Szkic na prośbę urzędu")
        req.refresh_from_db()
        self.assertEqual((req.status, req.record.status), ("DRAFT", "RESERVED"))

    def test_number_taken_meanwhile_is_not_restored(self):
        req = self.expired()
        create_request(self.b, data())
        with self.assertRaisesRegex(ValidationError, "Numer zajął"):
            restore_expired_request(self.ump, req.uuid, 7, "Za późno")
        req.refresh_from_db()
        self.assertEqual((req.status, req.record.status), ("EXPIRED", "RELEASED"))

    def test_entry_moved_to_another_office_is_not_restored(self):
        req = self.expired()
        update_record(self.ump, req.record.uuid, {"office_id": "b"}, "Przeniesienie", req.record.version)
        with self.assertRaisesRegex(ValidationError, "inny urząd"):
            restore_expired_request(self.ump, req.uuid, 7, "Po przeniesieniu")
        req.refresh_from_db()
        self.assertEqual((req.status, req.record.status), ("EXPIRED", "RELEASED"))

    def test_only_ump_with_reason_and_bounded_days(self):
        req = self.expired()
        with self.assertRaises(PermissionDenied):
            restore_expired_request(self.a, req.uuid, 7, "Powiat")
        for days, reason in ((0, "x"), (91, "x"), (7, " ")):
            with self.subTest(days=days, reason=reason), self.assertRaises(ValidationError):
                restore_expired_request(self.ump, req.uuid, days, reason)
        active = self.sent(number="P1TEST")
        with self.assertRaisesRegex(ValidationError, "wygasłą rezerwacją"):
            restore_expired_request(self.ump, active.uuid, 7, "Nie wygasł")

    def test_view_action_and_form(self):
        req = self.expired()
        self.client.force_login(self.a)
        page = self.client.get(reverse("request_detail", args=[req.uuid]))
        self.assertNotContains(page, "Przywróć wygasły wniosek")
        response = self.client.post(
            reverse("request_action", args=[req.uuid, "restore"]), {"days": 7, "reason": "Powiat"}
        )
        self.assertEqual(response.status_code, 403)
        self.client.force_login(self.ump)
        self.assertContains(
            self.client.get(reverse("request_detail", args=[req.uuid])), "Przywróć wygasły wniosek"
        )
        response = self.client.post(
            reverse("request_action", args=[req.uuid, "restore"]),
            {"days": "", "reason": "Brak dni"},
            follow=True,
        )
        self.assertContains(response, "nowy termin rezerwacji 1–90 dni")
        self.client.post(
            reverse("request_action", args=[req.uuid, "restore"]), {"days": 7, "reason": "Zgoda"}
        )
        self.assertEqual(Request.objects.get(pk=req.pk).status, "SENT")


@override_settings(EMAIL_BACKEND=LOCMEM)
class NotificationTests(Base):
    def test_author_is_notified_about_decisions_in_modules_one_and_two(self):
        individual = self.sent()
        decide_request(self.ump, individual.uuid, True)
        rejected = self.sent(number="P1TEST")
        decide_request(self.ump, rejected.uuid, False, "Fikcyjna odmowa")
        pool = pool_request(self.a)
        send_request(self.a, pool.uuid)
        decide_request(
            self.ump,
            pool.uuid,
            True,
            pool_data={"prefix": "P", "start": 1, "end": 3, "valid_from": timezone.localdate()},
        )
        kinds = set(
            IntegrationJob.objects.filter(operation="DECISION_NOTICE").values_list("letter__kind", flat=True)
        )
        self.assertEqual(kinds, {"APPROVAL", "REJECTION", "POOL"})
        self.assertEqual(IntegrationJob.objects.filter(operation="DECISION_NOTICE").count(), 3)

    def test_reminder_goes_once_per_deadline_without_personal_data(self):
        req = create_request(self.a, data())
        self.assertEqual(send_reservation_reminders(), 0)
        PlateRecord.objects.filter(pk=req.record_id).update(
            reservation_until=timezone.now() + timedelta(days=2)
        )
        self.assertEqual(send_reservation_reminders(), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.a.email])
        self.assertIn(req.reference, message.body)
        self.assertIn("szkicem", message.body)
        self.assertNotIn("Osoba Fikcyjna", message.body)
        self.assertEqual(send_reservation_reminders(), 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(AuditLog.objects.filter(action="reservation.reminder").exists())

    def test_extension_allows_new_reminder_and_submitted_request_reaches_ump(self):
        req = self.sent()
        PlateRecord.objects.filter(pk=req.record_id).update(
            reservation_until=timezone.now() + timedelta(days=1)
        )
        self.assertEqual(send_reservation_reminders(), 1)
        self.assertEqual(sorted(mail.outbox[0].to), sorted([self.a.email, "ump-kontakt@test.invalid"]))
        extend_reservation(self.ump, req.record.uuid, 30, "Analiza")
        self.assertEqual(send_reservation_reminders(), 0)
        PlateRecord.objects.filter(pk=req.record_id).update(
            reservation_until=timezone.now() + timedelta(hours=5)
        )
        self.assertEqual(send_reservation_reminders(), 1)

    def test_unsent_reminder_is_not_counted_as_sent(self):
        req = create_request(self.a, data())
        User.objects.filter(pk=self.a.pk).update(is_active=False)
        PlateRecord.objects.filter(pk=req.record_id).update(
            reservation_until=timezone.now() + timedelta(days=1)
        )
        self.assertEqual(send_reservation_reminders(), 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(AuditLog.objects.filter(action="reservation.reminder_skipped").exists())

    def test_expired_and_decided_reservations_get_no_reminder(self):
        req = self.sent()
        decide_request(self.ump, req.uuid, True)
        self.assertEqual(send_reservation_reminders(), 0)

    def test_pool_alert_is_sent_once_when_threshold_is_crossed(self):
        pool = self.small_pool()
        slots = list(pool.slots.all())
        with self.captureOnCommitCallbacks(execute=True):
            for slot in slots[:3]:
                issue_slot(self.a, pool.uuid, slot.pk, "S/1")
        self.assertEqual(len(mail.outbox), 0)
        # Każde wydanie to osobne żądanie i osobny commit.
        for slot, case in ((slots[3], "S/4"), (slots[4], "S/5")):
            with self.captureOnCommitCallbacks(execute=True):
                issue_slot(self.a, pool.uuid, slot.pk, case)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(sorted(mail.outbox[0].to), ["a-kontakt@test.invalid", "ump-kontakt@test.invalid"])
        self.assertIn("80%", mail.outbox[0].subject)
        self.assertTrue(AuditLog.objects.filter(action="pool.alert", object_id=str(pool.pk)).exists())

    def test_missing_contact_address_is_recorded_not_hidden(self):
        Office.objects.update(email="")
        pool = self.small_pool(end=1)
        with self.captureOnCommitCallbacks(execute=True):
            issue_slot(self.a, pool.uuid, pool.slots.get().pk, "S/1")
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(AuditLog.objects.filter(action="pool.alert_skipped").exists())


@override_settings(EMAIL_BACKEND=LOCMEM)
class MailRetryTests(Base):
    def test_failed_mail_is_requeued_on_explicit_resend_only(self):
        letter = self.sent().letters.get(kind="APPLICATION")
        job = enqueue(self.a, letter, "SMTP")
        IntegrationJob.objects.filter(pk=job.pk).update(status="ACCEPTED", attempts=1)
        self.assertEqual(enqueue(self.a, letter, "SMTP").status, "ACCEPTED")
        IntegrationJob.objects.filter(pk=job.pk).update(status="REVIEW_REQUIRED", attempts=1, error="Timeout")
        again = enqueue(self.a, letter, "SMTP")
        self.assertEqual((again.pk, again.status, again.attempts, again.error), (job.pk, "QUEUED", 0, ""))
        self.assertEqual(IntegrationJob.objects.filter(letter=letter).count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="integration.requeued").exists())

    def test_screen_reports_real_state_instead_of_queueing_success(self):
        letter = self.sent().letters.get(kind="APPLICATION")
        job = enqueue(self.a, letter, "SMTP")
        IntegrationJob.objects.filter(pk=job.pk).update(status="ACCEPTED")
        self.client.force_login(self.a)
        response = self.client.post(
            reverse("letter_send", args=[letter.uuid]), {"provider": "SMTP"}, follow=True
        )
        self.assertContains(response, "ma już operację w tym kanale")
        self.assertNotContains(response, "Operacja zapisana w kolejce integracji.")

    def test_ump_can_requeue_failed_decision_notice(self):
        req = self.sent()
        decide_request(self.ump, req.uuid, True)
        job = IntegrationJob.objects.get(operation="DECISION_NOTICE")
        url = reverse("request_action", args=[req.uuid, "renotify"])
        self.client.force_login(self.ump)
        self.assertContains(self.client.post(url, follow=True), "Ponowić można tylko nieudaną wysyłkę")
        IntegrationJob.objects.filter(pk=job.pk).update(status="REVIEW_REQUIRED", attempts=1)
        self.assertContains(
            self.client.get(reverse("request_detail", args=[req.uuid])), "Ponów powiadomienie"
        )
        self.client.post(url)
        self.assertEqual(IntegrationJob.objects.get(pk=job.pk).status, "QUEUED")
        self.client.force_login(self.a)
        self.assertEqual(self.client.post(url).status_code, 403)


class PostalDispatchTests(Base):
    def setUp(self):
        super().setUp()
        self.letter = self.sent().letters.get(kind="APPLICATION")
        self.url = reverse("letter_send", args=[self.letter.uuid])

    def test_sender_records_and_corrects_postal_dispatch(self):
        today = timezone.localdate()
        self.client.force_login(self.a)
        response = self.client.post(
            self.url, {"provider": "POST", "posted_at": today.isoformat(), "posted_reference": "RR123PL"}
        )
        self.assertRedirects(response, reverse("letters_list"))
        self.letter.refresh_from_db()
        self.assertEqual((self.letter.posted_at, self.letter.posted_reference), (today, "RR123PL"))
        self.assertEqual(self.letter.posted_by, self.a)
        self.assertContains(self.client.get(reverse("letters_list")), "nr nadania RR123PL")
        record_postal_dispatch(self.a, self.letter, today, "RR999PL")
        event = AuditLog.objects.filter(action="letter.posted").first()
        self.assertEqual(event.before["posted_reference"], "RR123PL")
        self.assertEqual(IntegrationJob.objects.count(), 0)

    def test_invalid_dates_and_foreign_offices_are_rejected(self):
        self.client.force_login(self.a)
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        for value in (tomorrow, "2020-01-01", "", "wczoraj"):
            with self.subTest(value=value):
                self.client.post(self.url, {"provider": "POST", "posted_at": value})
                self.letter.refresh_from_db()
                self.assertIsNone(self.letter.posted_at)
        payload = {"provider": "POST", "posted_at": timezone.localdate().isoformat()}
        self.client.force_login(self.ump)
        self.assertEqual(self.client.post(self.url, payload).status_code, 403)
        self.client.force_login(self.b)
        self.assertEqual(self.client.post(self.url, payload).status_code, 404)
        self.letter.refresh_from_db()
        self.assertIsNone(self.letter.posted_at)


class DecisionAidTests(Base):
    def test_ump_sees_number_history_and_verification_but_county_does_not(self):
        first = self.sent()
        decide_request(self.ump, first.uuid, True)
        record = PlateRecord.objects.get(pk=first.record_id)
        update_record(self.ump, record.uuid, {"status": "RELEASED"}, "Zwolnienie", record.version)
        second = self.sent(self.b)
        self.client.force_login(self.ump)
        page = self.client.get(reverse("request_detail", args=[second.uuid]))
        self.assertContains(page, "Ten numer wcześniej")
        self.assertContains(page, "Unikalny w województwie")
        self.assertEqual([item.pk for item in page.context["check"]["earlier"]], [record.pk])
        self.assertContains(page, "Urząd A")
        self.client.force_login(self.b)
        page = self.client.get(reverse("request_detail", args=[second.uuid]))
        self.assertIsNone(page.context["check"])
        self.assertNotContains(page, "Ten numer wcześniej")
        self.assertNotContains(page, "Urząd A")

    def test_content_warning_reads_digits_as_letters_and_never_blocks(self):
        FlaggedWord.objects.create(word="TEST", note="Fikcyjny wpis słownika")
        self.assertEqual([w.word for w in content_warnings("P0TE5T")], ["TEST"])
        self.assertEqual(content_warnings("P0KOWAL"), [])
        req = self.sent(number="P0TE5T")
        self.client.force_login(self.ump)
        page = self.client.get(reverse("request_detail", args=[req.uuid]))
        self.assertContains(page, "Ostrzeżenie o treści")
        self.assertContains(page, "Fikcyjny wpis słownika")
        decide_request(self.ump, req.uuid, True)

    def test_first_free_range_is_suggested_for_pool_decision(self):
        self.assertEqual(suggest_pool_range("II", "P", 4), (1, 4))
        self.small_pool()
        req = pool_request(self.b, count=3)
        send_request(self.b, req.uuid)
        self.client.force_login(self.ump)
        page = self.client.get(reverse("request_detail", args=[req.uuid]))
        self.assertEqual(page.context["suggested"], (6, 8))
        self.assertEqual((page.context["form"]["start"].value(), page.context["form"]["end"].value()), (6, 8))
        self.assertContains(page, "pierwsze wolne pozycje tego prefiksu to 6–8")
        decide_request(
            self.ump,
            req.uuid,
            True,
            pool_data={"prefix": "P", "start": 6, "end": 8, "valid_from": timezone.localdate()},
        )
        self.assertIsNone(suggest_pool_range("III", "P0", 30000))


class ListsAndExportsTests(Base):
    def test_decision_queue_lists_longest_waiting_first_and_filters_by_module(self):
        older, newer = self.sent(), self.sent(self.b, "P1TEST")
        Request.objects.filter(pk=newer.pk).update(sent_at=timezone.now() - timedelta(days=5))
        pool = pool_request(self.a)
        send_request(self.a, pool.uuid)
        self.client.force_login(self.ump)
        page = self.client.get(reverse("requests_list"), {"status": "SENT"})
        self.assertEqual([r.pk for r in page.context["requests"]][:2], [newer.pk, older.pk])
        self.assertContains(page, "czeka")
        page = self.client.get(reverse("requests_list"), {"kind": "II"})
        self.assertEqual([r.pk for r in page.context["requests"]], [pool.pk])
        page = self.client.get(reverse("requests_list"), {"office": "b"})
        self.assertEqual([r.pk for r in page.context["requests"]], [newer.pk])
        dashboard = self.client.get(reverse("dashboard"))
        self.assertTrue(dashboard.context["queue"])
        self.assertEqual(dashboard.context["requests"][0].pk, newer.pk)

    def test_county_filter_cannot_reach_other_office(self):
        self.sent(self.b, "P1TEST")
        self.client.force_login(self.a)
        page = self.client.get(reverse("requests_list"), {"office": "b"})
        self.assertEqual(list(page.context["requests"]), [])

    def test_pool_list_filters_sorts_and_marks_threshold(self):
        pool = self.small_pool()
        for slot in pool.slots.all()[:4]:
            issue_slot(self.a, pool.uuid, slot.pk, "S")
        other = allocate_pool(
            self.ump,
            {
                "kind": "II",
                "office": "b",
                "prefix": "P",
                "start": 6,
                "end": 9,
                "valid_from": timezone.localdate(),
            },
        )
        self.client.force_login(self.ump)
        page = self.client.get(reverse("pools_list"), {"sort": "usage"})
        self.assertEqual([p.pk for p in page.context["pools"]], [pool.pk, other.pk])
        self.assertEqual(page.context["pools"][0].usage_percent, 80)
        self.assertContains(page, "czas na kolejną pulę")
        page = self.client.get(reverse("pools_list"), {"office": "b"})
        self.assertEqual([p.pk for p in page.context["pools"]], [other.pk])
        self.assertEqual(
            (page.context["pools"][0].first_number, page.context["pools"][0].last_number), ("P006", "P009")
        )

    def test_exports_follow_scope_and_role(self):
        mine, foreign = self.sent(), self.sent(self.b, "P1TEST")
        self.small_pool()
        self.client.force_login(self.a)
        body = self.client.get(reverse("export_records"), {"co": "wnioski"}).content.decode()
        self.assertIn(mine.reference, body)
        self.assertNotIn(foreign.reference, body)
        self.assertNotIn("Osoba Fikcyjna", body)
        body = self.client.get(reverse("export_records"), {"co": "pule"}).content.decode()
        self.assertIn("II;a;P001;P005;5;0;0", body)
        self.assertEqual(self.client.get(reverse("export_records"), {"co": "urzedy"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("export_records"), {"co": "inne"}).status_code, 404)
        self.client.force_login(self.ump)
        body = self.client.get(reverse("export_records"), {"co": "urzedy"}).content.decode()
        self.assertIn("a;Urząd A;1;1;0;5;0;0;0", body)
        self.assertEqual(
            AuditLog.objects.filter(action="registry.exported", after__scope="urzedy").count(), 1
        )

    def test_offices_overview_counts_and_access(self):
        req = self.sent()
        decide_request(self.ump, req.uuid, True)
        self.sent(number="P2TEST")
        self.client.force_login(self.ump)
        page = self.client.get(reverse("offices_overview"))
        office = next(o for o in page.context["offices"] if o.pk == "a")
        self.assertEqual((office.active_plates, office.pending_requests, office.sold_vehicles), (2, 1, 0))
        self.assertNotIn("ump", [o.pk for o in page.context["offices"]])
        for user in (self.a, self.admin):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("offices_overview")).status_code, 403)

    def test_ump_dashboard_counts_sold_vehicles_waiting_for_release(self):
        req = self.sent()
        decide_request(self.ump, req.uuid, True)
        record = PlateRecord.objects.get(pk=req.record_id)
        today = timezone.localdate()
        update_record(
            self.a,
            record.uuid,
            {"vin": "WVWZZZ1KZ8W123456", "registration_date": today, "sale_date": today, "buyer": "Nabywca"},
            "Zbycie",
            record.version,
        )
        self.client.force_login(self.ump)
        page = self.client.get(reverse("dashboard"))
        self.assertEqual(page.context["sold_count"], 1)
        self.assertContains(page, "Pojazdy zbyte")
        self.client.force_login(self.a)
        self.assertNotContains(self.client.get(reverse("dashboard")), "Pojazdy zbyte")


class SlotRevokeTests(Base):
    def test_office_revokes_mistaken_issue_with_reason(self):
        pool = self.small_pool()
        slots = list(pool.slots.all())
        for slot in slots[:4]:
            issue_slot(self.a, pool.uuid, slot.pk, "S/1")
        self.assertIsNotNone(Pool.objects.get(pk=pool.pk).alerted_at)
        url = reverse("pool_detail", args=[pool.uuid])
        self.client.force_login(self.a)
        response = self.client.post(
            url, {"action": "revoke", "slot": slots[0].pk, "reason": " "}, follow=True
        )
        self.assertContains(response, "Podaj powód cofnięcia wydania")
        self.client.post(url, {"action": "revoke", "slot": slots[0].pk, "reason": "Pomyłka numeru"})
        slot = pool.slots.get(pk=slots[0].pk)
        self.assertEqual((slot.issued_at, slot.issued_by, slot.case_number), (None, None, ""))
        self.assertIsNone(Pool.objects.get(pk=pool.pk).alerted_at)
        event = AuditLog.objects.get(action="pool.number_issue_revoked")
        self.assertEqual((event.before["case_number"], event.reason), ("S/1", "Pomyłka numeru"))
        issue_slot(self.a, pool.uuid, slot.pk, "S/2")

    def test_unissued_and_foreign_slots_are_refused(self):
        pool = self.small_pool()
        slot = pool.slots.first()
        with self.assertRaisesRegex(ValidationError, "nie jest oznaczony jako wydany"):
            revoke_slot_issue(self.a, pool.uuid, slot.pk, "Powód")
        issue_slot(self.a, pool.uuid, slot.pk, "S/1")
        self.client.force_login(self.b)
        response = self.client.post(
            reverse("pool_detail", args=[pool.uuid]), {"action": "revoke", "slot": slot.pk, "reason": "Obcy"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertIsNotNone(pool.slots.get(pk=slot.pk).issued_at)


@override_settings(EMAIL_BACKEND=LOCMEM)
class LoginAvailabilityTests(Base):
    def order(self, client, email):
        response = client.post(reverse("login_email"), {"email": email})
        return response, (re.search(r"Kod: (\d{8})", mail.outbox[-1].body).group(1) if mail.outbox else "")

    def test_foreign_requests_neither_invalidate_code_nor_lock_out_owner(self):
        response, code = self.order(self.client, self.a.email)
        self.assertRedirects(response, reverse("login_code"))
        stranger = Client(REMOTE_ADDR="203.0.113.9")
        statuses = [self.order(stranger, self.a.email)[0].status_code for _ in range(6)]
        self.assertEqual(statuses, [302] * 5 + [429])
        response = self.client.post(reverse("login_code"), {"code": code})
        self.assertRedirects(response, reverse("dashboard"))
        # Po udanym logowaniu pozostałe kody tego konta przestają działać.
        self.assertFalse(LoginCode.objects.filter(user=self.a, used=False).exists())

    def test_owner_can_still_order_code_after_foreign_flood(self):
        stranger = Client(REMOTE_ADDR="203.0.113.9")
        for _ in range(6):
            self.order(stranger, self.a.email)
        response, code = self.order(self.client, self.a.email)
        self.assertRedirects(response, reverse("login_code"))
        self.assertRedirects(self.client.post(reverse("login_code"), {"code": code}), reverse("dashboard"))

    def test_ipv6_hosts_of_one_network_share_the_limit_and_code_has_eight_digits(self):
        statuses = []
        for host in range(1, 7):
            client = Client(REMOTE_ADDR=f"2001:db8:1:2::{host}")
            statuses.append(self.order(client, self.a.email)[0].status_code)
        self.assertEqual(statuses, [302] * 5 + [429])
        self.assertRegex(mail.outbox[-1].body, r"Kod: \d{8}\n")
        response = self.client.post(reverse("login_code"), {"code": "123456"})
        self.assertFalse(response.context["form"].is_valid())

    def test_same_session_reorder_still_replaces_its_previous_code(self):
        _, first = self.order(self.client, self.a.email)
        _, second = self.order(self.client, self.a.email)
        self.assertEqual(LoginCode.objects.filter(user=self.a, used=False).count(), 1)
        response = self.client.post(reverse("login_code"), {"code": second})
        self.assertRedirects(response, reverse("dashboard"))


class AdministrationTests(Base):
    def account_form(self, user, **changes):
        page = self.client.get(reverse("admin_edit", args=["user", user.pk]))
        values = {
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "office": user.office_id or "",
            "is_active": "on",
            "reason": "Fikcyjna zmiana",
            "account_version": page.context["form"].initial["account_version"],
        }
        return {**values, **changes}

    def test_administrator_cannot_grant_himself_a_substantive_role(self):
        self.client.force_login(self.admin)
        url = reverse("admin_edit", args=["user", self.admin.pk])
        response = self.client.post(url, self.account_form(self.admin, role="MAIN", office="ump"))
        self.assertContains(response, "Zmianę wykonuje inny administrator")
        self.admin.refresh_from_db()
        self.assertEqual((self.admin.role, self.admin.office_id), ("ADMIN", None))
        # Własne imię i nazwisko nadal można poprawić, także przy dawnym zapisie adresu.
        User.objects.filter(pk=self.admin.pk).update(email="Admin@test.invalid")
        self.admin.refresh_from_db()
        response = self.client.post(url, self.account_form(self.admin, first_name="Ada"))
        self.assertRedirects(response, reverse("admin_panel"))

    def test_second_administrator_changes_the_account(self):
        other = User.objects.create_user(
            username="admin2@test.invalid", email="admin2@test.invalid", role="ADMIN"
        )
        self.client.force_login(other)
        response = self.client.post(
            reverse("admin_edit", args=["user", self.admin.pk]), self.account_form(self.admin, is_active="")
        )
        self.assertRedirects(response, reverse("admin_panel"))
        self.assertFalse(User.objects.get(pk=self.admin.pk).is_active)

    def test_warning_dictionary_is_admin_only_and_normalized(self):
        url = reverse("admin_new", args=["flag"])
        self.client.force_login(self.ump)
        self.assertEqual(self.client.post(url, {"word": "abc"}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertContains(self.client.post(url, {"word": "a1"}), "2–5 liter")
        self.assertRedirects(self.client.post(url, {"word": "abc", "note": "Opis"}), reverse("admin_panel"))
        self.assertEqual(FlaggedWord.objects.get().word, "ABC")
        self.assertContains(self.client.get(reverse("admin_panel")), "Słownik ostrzeżeń")
