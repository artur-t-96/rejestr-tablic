import csv
from io import StringIO
from urllib.parse import parse_qs, urlsplit

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .models import (
    AuditLog,
    DeliveryEvidence,
    EZDIncomingDocument,
    IntegrationJob,
    Letter,
    PlateRecord,
    Request,
)
from .tests import fixtures


class ListPaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.ump, cls.county, cls.other = fixtures()
        cls.records = PlateRecord.objects.bulk_create(
            [
                PlateRecord(
                    number="P0TEST", office=cls.county.office, owner=f"FIKCYJNY-{i:03}", status="RELEASED"
                )
                for i in range(305)
            ]
        )
        cls.requests = Request.objects.bulk_create(
            [
                Request(
                    kind="I",
                    office=cls.county.office,
                    author=cls.county,
                    record=record,
                    case_number=f"TEST-PAGE/{i:03}",
                    status="REJECTED",
                )
                for i, record in enumerate(cls.records)
            ]
        )
        # Archive list fixtures only: no PDF rendering, signing or dispatch.
        cls.letters = Letter.objects.bulk_create(
            [
                Letter(
                    number=f"TEST-PAGE/{i:03}",
                    office=cls.county.office,
                    recipient=cls.ump.office,
                    request=req,
                    title=f"Fikcyjne pismo listy {i:03}",
                    kind="APPLICATION",
                    body="Test listy",
                    pdf=b"list fixture, not a rendered PDF",
                    sha256="0" * 64,
                )
                for i, req in enumerate(cls.requests)
            ]
        )
        cls.jobs = IntegrationJob.objects.bulk_create(
            [
                IntegrationJob(
                    letter=letter,
                    provider="EDOR",
                    key=f"test-page-{i}",
                    remote_id=f"TEST-WYNIK-{i:03}",
                    status="LOCAL_SAVED",
                    payload=b"list fixture",
                )
                for i, letter in enumerate(cls.letters[:155])
            ]
        )
        DeliveryEvidence.objects.bulk_create(
            [
                DeliveryEvidence(
                    job=job,
                    remote_id=f"test-evidence-{i}",
                    kind="TEST",
                    content=b"list fixture",
                    sha256="0" * 64,
                )
                for i, job in enumerate(cls.jobs)
            ]
        )
        cls.incoming = EZDIncomingDocument.objects.bulk_create(
            [
                EZDIncomingDocument(
                    office=cls.county.office,
                    target_hash="0" * 64,
                    rpw_number=i + 1,
                    rpw_year=2026,
                    document_id=f"test-page-{i}",
                    version_id="1",
                    workspace_id="test",
                    letter=letter,
                    status="MATCHED",
                    sha256="0" * 64,
                    content=b"list fixture",
                )
                for i, letter in enumerate(cls.letters[:155])
            ]
        )
        cls.foreign_record = PlateRecord.objects.create(
            number="P1OTHER", office=cls.other.office, owner="CUDZY-WLASCICIEL-TEST", status="RELEASED"
        )
        cls.foreign_request = Request.objects.create(
            kind="I",
            office=cls.other.office,
            author=cls.other,
            record=cls.foreign_record,
            case_number="CUDZA-SPRAWA-TEST",
            status="REJECTED",
        )
        cls.foreign_letter = Letter.objects.create(
            number="CUDZE-PISMO-TEST",
            office=cls.other.office,
            recipient=cls.ump.office,
            request=cls.foreign_request,
            title="CUDZE-PISMO-TEST",
            kind="APPLICATION",
            body="Test",
            pdf=b"test",
            sha256="0" * 64,
        )
        cls.foreign_job = IntegrationJob.objects.create(
            letter=cls.foreign_letter,
            provider="EDOR",
            key="foreign-page",
            remote_id="CUDZY-WYNIK-TEST",
            status="LOCAL_SAVED",
        )
        cls.foreign_incoming = EZDIncomingDocument.objects.create(
            office=cls.other.office,
            target_hash="0" * 64,
            rpw_number=999,
            rpw_year=2026,
            document_id="foreign-page",
            version_id="1",
            workspace_id="test",
            error="CUDZY-WPLYW-TEST",
        )

    def lists(self):
        return (
            ("records_list", "records", self.records),
            ("requests_list", "requests", self.requests),
            ("letters_list", "letters", self.letters),
            ("integrations", "jobs", self.jobs),
            ("ezd_incoming", "incoming", self.incoming),
        )

    def test_oldest_records_and_requests_remain_reachable_after_300_rows(self):
        self.client.force_login(self.county)
        for route, key, expected in (
            ("records_list", "records", self.records[0].pk),
            ("requests_list", "requests", self.requests[0].pk),
        ):
            with self.subTest(route=route):
                response = self.client.get(reverse(route), {"page": 7})
                page = response.context["page_obj"]
                self.assertEqual(page.paginator.count, 305)
                self.assertEqual(page.number, 7)
                self.assertEqual(len(response.context[key]), 5)
                self.assertIn(expected, [row.pk for row in response.context[key]])
                self.assertContains(response, "Strona 7 z 7")

    def test_all_pages_cover_every_own_row_once_with_timestamp_ties(self):
        self.client.force_login(self.county)
        for route, key, objects in self.lists():
            model = type(objects[0])
            model.objects.update(created_at=timezone.now())
            expected = sorted((obj.pk for obj in objects), reverse=True)
            found = []
            for page in range(1, (len(expected) + 49) // 50 + 1):
                response = self.client.get(reverse(route), {"page": page})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["page_obj"].paginator.count, len(expected))
                rows = response.context[key]
                self.assertLessEqual(len(rows), 50)
                found.extend(row.pk for row in rows)
                for hidden in (
                    "CUDZY-WLASCICIEL-TEST",
                    "CUDZA-SPRAWA-TEST",
                    "CUDZE-PISMO-TEST",
                    "CUDZY-WYNIK-TEST",
                    "CUDZY-WPLYW-TEST",
                ):
                    self.assertNotContains(response, hidden)
            self.assertEqual(found, expected, route)

    def test_request_filters_are_preserved_by_navigation_and_new_filter_resets_page(self):
        self.client.force_login(self.county)
        response = self.client.get(
            reverse("requests_list"), {"q": "TEST-PAGE/", "status": "REJECTED", "page": 2}
        )
        self.assertContains(response, "Strona 2 z 7")
        self.assertContains(response, 'href="?q=TEST-PAGE%2F&amp;status=REJECTED&amp;page=3#list-results"')
        self.assertContains(response, 'href="?q=TEST-PAGE%2F&amp;status=REJECTED&amp;page=1#list-results"')
        self.assertNotContains(response, 'name="page"')
        filtered = self.client.get(reverse("requests_list"), {"q": "TEST-PAGE/000", "status": "REJECTED"})
        self.assertEqual(filtered.context["page_obj"].paginator.count, 1)
        self.assertEqual(filtered.context["page_obj"].number, 1)
        self.assertEqual(filtered.context["requests"][0].pk, self.requests[0].pk)

    def test_record_filters_and_csv_export_cover_full_filtered_result(self):
        self.client.force_login(self.ump)
        filters = {"q": "FIKCYJNY-", "status": "RELEASED", "office": self.county.office_id, "page": 2}
        response = self.client.get(reverse("records_list"), filters)
        self.assertEqual(response.context["page_obj"].paginator.count, 305)
        self.assertContains(response, "office=a&amp;page=3#list-results")
        self.assertContains(response, "q=FIKCYJNY-&amp;status=RELEASED")
        exported = self.client.get(reverse("export_records"), filters)
        self.assertEqual(exported.status_code, 200)
        rows = list(csv.DictReader(StringIO(exported.content.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(len(rows), 305)
        self.assertEqual({row["owner"] for row in rows}, {obj.owner for obj in self.records})
        self.assertNotContains(exported, "CUDZY-WLASCICIEL-TEST")

    def test_empty_and_invalid_page_parameters_are_safe(self):
        self.client.force_login(self.county)
        for route, key, objects in self.lists():
            last = (len(objects) + 49) // 50
            for raw, expected in (("brak", 1), ("", 1), ("0", last), ("-1", last), ("99999999", last)):
                with self.subTest(route=route, page=raw):
                    response = self.client.get(reverse(route), {"page": raw})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.context["page_obj"].number, expected)
                    self.assertLessEqual(len(response.context[key]), 50)
        response = self.client.get(reverse("requests_list"), {"q": "NIE-ISTNIEJE", "page": 99})
        self.assertContains(response, "Liczba wyników: 0")
        self.assertNotContains(response, "Następna strona")
        self.assertEqual(response.context["page_obj"].number, 1)

    def test_api_navigation_and_filters_do_not_truncate_or_leak_foreign_requests(self):
        self.client.force_login(self.county)
        Request.objects.update(created_at=timezone.now())
        url = "/api/requests/?q=TEST-PAGE%2F&status=REJECTED"
        found = []
        pages = 0
        while url:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertEqual(result["count"], 305)
            self.assertEqual(result["pages"], 7)
            self.assertEqual(result["page_size"], 50)
            self.assertLessEqual(len(result["items"]), 50)
            self.assertTrue(all(row["office"] == self.county.office_id for row in result["items"]))
            found.extend(row["id"] for row in result["items"])
            for link in (result["next"], result["previous"]):
                if link:
                    self.assertEqual(urlsplit(link).path, "/api/requests/")
                    self.assertEqual(parse_qs(urlsplit(link).query)["q"], ["TEST-PAGE/"])
                    self.assertEqual(parse_qs(urlsplit(link).query)["status"], ["REJECTED"])
            pages += 1
            url = result["next"]
            self.assertLessEqual(pages, 7)
        self.assertEqual(set(found), {str(obj.uuid) for obj in self.requests})
        self.assertEqual(len(found), 305)
        self.assertEqual(found, [str(obj.uuid) for obj in reversed(self.requests)])

    def test_recipient_letter_and_its_operation_are_visible_without_sender_actions(self):
        letter = self.letters[0]
        Letter.objects.filter(pk=letter.pk).update(office=self.ump.office, recipient=self.county.office)
        self.client.force_login(self.county)
        response = self.client.get(reverse("letters_list"), {"page": 7})
        self.assertContains(response, letter.title)
        self.assertNotContains(response, f'id="provider-{letter.pk}"')
        self.assertEqual(response.context["page_obj"].paginator.count, 305)
        response = self.client.get(reverse("integrations"), {"page": 4})
        self.assertContains(response, self.jobs[0].remote_id)
        self.assertEqual(response.context["page_obj"].paginator.count, 155)

    def test_query_parameters_cannot_override_office_scope(self):
        self.client.force_login(self.county)
        response = self.client.get(reverse("records_list"), {"office": self.other.office_id, "page": 7})
        self.assertEqual(response.context["page_obj"].paginator.count, 0)
        self.assertNotContains(response, "CUDZY-WLASCICIEL-TEST")
        response = self.client.get("/api/requests/", {"q": "CUDZA-SPRAWA-TEST", "page": 7})
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(response.json()["count"], 0)
        self.assertIsNone(response.json()["next"])

    def test_scopes_include_recipient_documents_and_admin_only_diagnostics(self):
        self.client.force_login(self.other)
        for route, key, _ in self.lists():
            response = self.client.get(reverse(route))
            self.assertEqual(response.context["page_obj"].paginator.count, 1)
            self.assertEqual(len(response.context[key]), 1)
        self.client.force_login(self.ump)
        for route in ("records_list", "requests_list", "letters_list"):
            self.assertEqual(self.client.get(reverse(route)).context["page_obj"].paginator.count, 306)
        self.assertEqual(self.client.get(reverse("ezd_incoming")).context["page_obj"].paginator.count, 0)
        self.client.force_login(self.admin)
        for route in ("records_list", "requests_list", "letters_list", "ezd_incoming"):
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)
        self.assertEqual(self.client.get("/api/requests/").status_code, 403)
        self.assertEqual(self.client.get(reverse("integrations")).context["page_obj"].paginator.count, 156)

    def test_list_navigation_does_not_mutate_business_data(self):
        models = (
            Request,
            PlateRecord,
            Letter,
            IntegrationJob,
            DeliveryEvidence,
            EZDIncomingDocument,
            AuditLog,
        )
        before = [list(model.objects.order_by("pk").values()) for model in models]
        self.client.force_login(self.county)
        for route, _, _ in self.lists():
            self.assertEqual(self.client.get(reverse(route), {"page": 7}).status_code, 200)
        self.assertEqual([list(model.objects.order_by("pk").values()) for model in models], before)

    def test_list_queries_are_bounded_and_do_not_fetch_document_bytes(self):
        self.client.force_login(self.county)
        for route, key in (
            ("letters_list", "letters"),
            ("integrations", "jobs"),
            ("ezd_incoming", "incoming"),
        ):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse(route), {"page": 2})
            self.assertEqual(response.status_code, 200)
            self.assertLessEqual(len(queries), 12, route)
            self.assertEqual(len(response.context[key]), 50)
            sql = " ".join(query["sql"] for query in queries)
            for column in ('"pdf"', '"signed_pdf"', '"content"', '"payload"'):
                self.assertNotIn(column, sql, route)
            self.assertIn("LIMIT 50 OFFSET 50", sql)
