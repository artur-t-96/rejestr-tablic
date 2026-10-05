"""Audit readability, saved facts, escaping and office/technical-role boundaries."""

from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .audit_presentation import present_event
from .models import AuditLog
from .services import audit, create_request, decide_request, send_request, update_record
from .tests import data, fixtures


class AuditPresentationTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        self.req = create_request(self.a, data())

    def test_real_correction_is_readable_and_does_not_rewrite_saved_history(self):
        send_request(self.a, self.req.uuid)
        decide_request(self.ump, self.req.uuid, True)
        self.req.record.refresh_from_db()
        update_record(
            self.ump,
            self.req.record.uuid,
            {"owner": "Fikcyjny właściciel po korekcie", "note": "Fikcyjna uwaga"},
            "Fikcyjna korekta danych",
            self.req.record.version,
        )
        before = list(AuditLog.objects.values())
        self.client.force_login(self.a)
        page = self.client.get(reverse("record_detail", args=[self.req.record.uuid]))
        self.assertContains(page, "Zmieniono dane wpisu")
        self.assertContains(page, '<th scope="row">Właściciel</th>', html=True)
        self.assertContains(page, "Fikcyjny właściciel po korekcie")
        self.assertContains(page, "Fikcyjna korekta danych")
        self.assertContains(page, "Szczegóły techniczne zdarzenia")
        self.assertContains(page, "plate.updated")
        self.assertContains(page, "Zarezerwowany")
        self.assertContains(page, "Wniosek w toku")
        self.assertContains(page, "Przydzielony")
        self.assertEqual(list(AuditLog.objects.values()), before)

    def test_request_and_record_statuses_have_their_own_meaning(self):
        send_request(self.a, self.req.uuid)
        self.client.force_login(self.a)
        page = self.client.get(reverse("request_detail", args=[self.req.uuid]))
        self.assertContains(page, "Złożono wniosek do UMP")
        self.assertContains(page, "Oczekuje na rozpatrzenie")
        self.assertContains(page, "Wniosek w toku")
        self.assertContains(page, 'scope="col"')
        self.assertContains(page, 'datetime="')

    def test_admin_never_receives_business_values_even_in_technical_details(self):
        audit(
            self.ump,
            "plate.updated",
            self.req.record,
            {"owner": "TAJNE-PRZED-TEST"},
            {"owner": "TAJNE-PO-TEST"},
            "Korekta testowa",
        )
        self.client.force_login(self.admin)
        page = self.client.get(reverse("audit_list"))
        self.assertContains(page, "Zmieniono dane wpisu")
        self.assertContains(page, "PlateRecord")
        self.assertNotContains(page, "TAJNE-PRZED-TEST")
        self.assertNotContains(page, "TAJNE-PO-TEST")
        self.assertNotContains(page, "Wartości przed i po")
        self.assertNotContains(page, "<pre>")
        self.assertEqual(
            self.client.get(reverse("record_detail", args=[self.req.record.uuid])).status_code, 403
        )

    def test_county_audit_is_own_actions_and_other_office_record_is_hidden(self):
        audit(self.a, "plate.updated", self.req.record, after={"note": "MOJE-TEST"})
        audit(self.b, "plate.updated", self.req.record, after={"note": "INNE-KONTO-TEST"})
        self.client.force_login(self.a)
        page = self.client.get(reverse("audit_list"))
        self.assertContains(page, "MOJE-TEST")
        self.assertNotContains(page, "INNE-KONTO-TEST")
        self.client.force_login(self.b)
        self.assertEqual(
            self.client.get(reverse("record_detail", args=[self.req.record.uuid])).status_code, 404
        )

    def test_html_nested_metadata_unknown_fields_and_action_are_escaped(self):
        event = audit(
            self.a,
            '<script>alert("action")</script>',
            self.req.record,
            after={
                "unknown_field": {"value": '<img src=x onerror="alert(1)">'},
                "note": "<script>danger</script>",
            },
            reason="<script>reason</script>",
        )
        html = render_to_string("registry/history.html", {"events": [event], "user": self.a})
        self.assertIn("Zdarzenie systemowe", html)
        self.assertIn("unknown_field", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img ", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;img", html)

    def test_empty_false_zero_and_missing_are_distinguished_without_inventing_deletion(self):
        event = audit(
            self.a,
            "plate.updated",
            self.req.record,
            before={"note": "Usunięta uwaga", "legacy": "Stary zapis", "same": "Bez zmian"},
            after={"note": "", "active": False, "count": 0, "case_number": "00001", "same": "Bez zmian"},
        )
        rows = present_event(event)["changes"]
        pairs = {row["label"]: (row["before"], row["after"]) for row in rows}
        self.assertEqual(pairs["Uwagi"], ("Usunięta uwaga", "Nie podano"))
        self.assertEqual(pairs["legacy"], ("Stary zapis", "Nie zapisano"))
        self.assertEqual(pairs["Aktywny urząd"], ("Nie zapisano", "Nie"))
        self.assertEqual(pairs["Liczba"], ("Nie zapisano", "0"))
        self.assertEqual(pairs["Znak sprawy"], ("Nie zapisano", "00001"))
        self.assertNotIn("same", pairs)
        event.before = {"count": 0, "legacy": {"value": False}}
        event.after = {"count": False, "legacy": {"value": 0}}
        self.assertEqual(len(present_event(event)["changes"]), 2)

    def test_saved_dates_timezone_and_legacy_payload_remain_inspectable(self):
        event = audit(
            None,
            "reservation.extended",
            self.req.record,
            before={"reservation_until": "2026-10-17T05:26:45+00:00"},
            after={
                "reservation_until": "2026-10-24T05:26:45+00:00",
                "sale_date": "2026-01-02",
                "bad": "not-date",
            },
        )
        with self.settings(TIME_ZONE="Europe/Warsaw"):
            rows = present_event(event)["changes"]
        self.assertEqual(rows[0]["before"], "17.10.2026 07:26:45 CEST")
        self.assertEqual(rows[0]["after"], "24.10.2026 07:26:45 CEST")
        self.assertEqual(rows[1]["after"], "02.01.2026")
        event.before = []
        event.after = ["Dawna lista", 0, False]
        html = render_to_string("registry/history.html", {"events": [event], "user": self.ump})
        self.assertIn("Dawna lista", html)
        self.assertIn("Dane zdarzenia", html)
        event.before = 0
        event.after = False
        self.assertEqual(len(present_event(event)["changes"]), 1)

    def test_actor_without_name_is_identified_and_rendering_does_not_query_per_event(self):
        self.a.first_name = ""
        self.a.last_name = ""
        self.a.save()
        for _ in range(20):
            audit(self.a, "plate.updated", self.req.record, after={"note": "Próba odczytu"})
        events = AuditLog.objects.select_related("actor", "office").all()
        with self.assertNumQueries(1):
            html = render_to_string("registry/history.html", {"events": events, "user": self.ump})
        self.assertIn(self.a.email, html)

    def test_transport_and_signature_states_use_event_meaning_instead_of_object_type(self):
        letter = self.req.letters.get()
        event = audit(None, "integration.result", letter, after={"status": "LOCAL_SAVED"})
        self.assertEqual(present_event(event)["changes"][0]["after"], "Zapisano w lokalnej skrzynce")
        event = audit(None, "account.invitation_state", self.a, after={"status": "QUEUED"})
        self.assertEqual(present_event(event)["changes"][0]["after"], "Oczekuje na wysyłkę")
        event = audit(None, "letter.signed", letter, after={"status": "TEST_SIGNED"})
        self.assertEqual(present_event(event)["changes"][0]["after"], "Podpis testowy")

    def test_pagination_reaches_old_events_and_keeps_office_and_actor_scope(self):
        for i in range(110):
            audit(self.a, "plate.updated", self.req.record, after={"note": f"HISTORIA-{i:03}"})
        other = create_request(self.b, data(number="P1OTHR"))
        audit(self.b, "plate.updated", other.record, after={"note": "INNY-URZAD-HISTORIA"})
        # An equal timestamp must not move entries between pages.
        AuditLog.objects.filter(action="plate.updated", actor=self.a).update(created_at=timezone.now())
        self.client.force_login(self.a)
        for url, expected in [
            (reverse("audit_list"), set(AuditLog.objects.filter(actor=self.a).values_list("pk", flat=True))),
            (
                reverse("record_detail", args=[self.req.record.uuid]),
                set(
                    AuditLog.objects.filter(
                        object_type="PlateRecord", object_id=str(self.req.record_id)
                    ).values_list("pk", flat=True)
                ),
            ),
            (
                reverse("request_detail", args=[self.req.uuid]),
                set(AuditLog.objects.filter(office=self.a.office).values_list("pk", flat=True)),
            ),
        ]:
            seen = []
            for number in [1, 2, 3]:
                page = self.client.get(url, {"history_page": number})
                self.assertEqual(page.context["history_page"].number, number)
                self.assertNotContains(page, "INNY-URZAD-HISTORIA")
                seen.extend(event.pk for event in page.context["events"])
            self.assertEqual(set(seen), expected)
            self.assertEqual(len(seen), len(set(seen)))
            self.assertContains(page, "HISTORIA-000")
            self.assertContains(page, "Nowsze zdarzenia")
            self.assertNotContains(page, "Starsze zdarzenia")
            first = self.client.get(url, {"history_page": "nie-liczba"})
            self.assertEqual(first.context["history_page"].number, 1)
