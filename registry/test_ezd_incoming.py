"""HTTP jest MockTransport; import, uprawnienia, transakcje i PDF są rzeczywiste."""

import hashlib
import json
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from io import StringIO
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import httpx
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from .connectors.ezdrp import ConnectorError, EZDProfile, EZDRPClient
from .ezd_incoming import attachment_ids, publish_incoming_link, receive_rpw
from .models import AuditLog, EZDIncomingDocument, Letter
from .services import create_request
from .tests import data, fixtures


class IncomingTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.county, self.other = fixtures()
        self.req = create_request(self.county, data())
        self.letter = self.req.letters.get()
        self.profile = EZDProfile(
            api_url="https://ezd.test.invalid",
            token_url="https://sso.test.invalid/connect/token",
            web_host="web.test.invalid",
            pid="test-pid",
            aki="test-aki",
            sid="test-sid",
            api_key="test-only",
            metadata={
                "request_id": {"key": "Dyna.Id", "name": "Wniosek"},
                "request_url": {"key": "Dyna.Url", "name": "Link"},
            },
        )
        self.payload = bytes(self.letter.pdf)
        self.doc_version = "v1"
        self.workspace = "space1"
        self.request_id = str(self.req.uuid)
        self.calls = []
        self.put_failure = False
        self.page_count = 2
        self.patch = patch("registry.ezd_incoming.load_profile", return_value=self.profile)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.transport = httpx.MockTransport(self.mock)

    def mock(self, request):
        self.calls.append(request)
        path = request.url.path
        if path == "/connect/token":
            return httpx.Response(200, json={"access_token": "test-only", "expires_in": 300})
        if path == "/download/doc1":
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(200, content=self.payload)
        self.assertEqual(request.headers["authorization"], "Bearer test-only")
        self.assertEqual(request.headers["sid"], "test-sid")
        if path.endswith("/rpw/17/2026/metadane"):
            return httpx.Response(
                200,
                json={
                    "numerRPW": "RPW/17/2026",
                    "status": 2,
                    "idPrzestrzenRobocza": "space1",
                    "zalaczniki": [
                        {
                            "idDokumentPrzestrzeni": "doc1",
                            "idDokumentWersja": "v1",
                            "zalaczniki": [],
                        }
                    ],
                },
            )
        if path.endswith("/dokumenty/doc1/link"):
            return httpx.Response(200, json={"link": "https://ezd.test.invalid/download/doc1"})
        if path.endswith("/dokumenty/doc1/metadane"):
            if request.method == "PUT":
                if self.put_failure:
                    raise httpx.ReadTimeout("test-only timeout", request=request)
                values = json.loads(request.content)
                self.assertEqual({x["klucz"] for x in values["metadane"]}, {"Dyna.Id", "Dyna.Url"})
                return httpx.Response(200, json=values)
            return httpx.Response(
                200,
                json={
                    "idDokumentPrzestrzeni": "doc1",
                    "listaKonfiguracji": [
                        {"kluczSystemowy": "Dyna.Id", "wartosc": self.request_id},
                        {"kluczSystemowy": "Dyna.Url", "wartosc": "https://untrusted.test.invalid/"},
                    ],
                },
            )
        if path.endswith("/dokumenty/doc1"):
            return httpx.Response(
                200,
                json={
                    "idDokumentPrzestrzeni": "doc1",
                    "idDokumentWersja": self.doc_version,
                    "idPrzestrzenRobocza": self.workspace,
                    "rozszerzenie": "pdf",
                },
            )
        if path.endswith("/rpw/_search"):
            value = json.loads(request.content)
            self.assertEqual(value["dataOd"], "2026-10-01")
            self.assertEqual(value["pageSize"], 25)
            return httpx.Response(
                200,
                json={
                    "lista": [
                        {
                            "numerRPW": "RPW/17/2026",
                            "idPodmiotWlascicielBiznesowy": "test-pid",
                            "czyUsuniety": False,
                        }
                    ],
                    "pageInfo": {
                        "pageNumber": value["page"],
                        "pageSize": 25,
                        "pagesCount": self.page_count,
                        "isNextPageExists": value["page"] + 1 < self.page_count,
                    },
                },
            )
        raise AssertionError(f"Unexpected mock request {request.method} {path}")

    def receive(self, user=None):
        return receive_rpw(user or self.ump, 17, 2026, reason="Fikcyjny test", transport=self.transport)

    def test_receive_deduplicates_exact_pdf_and_never_changes_request(self):
        row = self.receive()[0]
        again = self.receive()[0]
        self.assertEqual(row.pk, again.pk)
        self.assertEqual(row.letter_id, self.letter.pk)
        self.assertEqual(bytes(row.content), self.payload)
        self.assertEqual(row.status, "MATCHED")
        self.assertIn(str(self.req.uuid), row.request_url)
        self.assertNotIn("untrusted", row.request_url)
        self.assertEqual(AuditLog.objects.filter(action="ezd.incoming.received").count(), 1)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, "DRAFT")
        self.assertFalse(any(r.method == "PUT" for r in self.calls))

    def test_unknown_pdf_is_not_archived_or_assigned_by_claimed_uuid(self):
        self.payload = b"%PDF-1.7\nTEST UNKNOWN DOCUMENT"
        row = self.receive()[0]
        self.assertEqual(row.status, "UNMATCHED")
        self.assertIsNone(row.letter_id)
        self.assertIsNone(row.content)
        self.assertEqual(row.sha256, hashlib.sha256(self.payload).hexdigest())
        with self.assertRaises(ValidationError):
            publish_incoming_link(self.ump, row.uuid, reason="Test", transport=self.transport)

    def test_wrong_recipient_and_conflicting_uuid_do_not_match(self):
        row = self.receive(self.other)[0]
        self.assertIsNone(row.content)
        self.request_id = str(uuid.uuid4())
        row = self.receive()[0]
        self.assertIsNone(row.content)
        self.assertIn("Identyfikator", row.error)

    def test_corrupt_local_pdf_is_not_accepted(self):
        Letter.objects.filter(pk=self.letter.pk).update(pdf=b"corrupt")
        row = self.receive()[0]
        self.assertIsNone(row.content)
        self.assertIn("integralności", row.error)

    def test_non_pdf_and_changed_remote_version_or_workspace_are_rejected(self):
        for change in ("payload", "doc_version", "workspace"):
            with self.subTest(change=change):
                old = getattr(self, change)
                setattr(self, change, b"not PDF" if change == "payload" else "wrong")
                with self.assertRaises(ConnectorError):
                    self.receive()
                setattr(self, change, old)
        self.assertFalse(EZDIncomingDocument.objects.exists())

    def test_same_version_with_different_bytes_never_overwrites_archive(self):
        row = self.receive()[0]
        self.payload = b"%PDF-1.7\nchanged"
        with self.assertRaises(ValidationError):
            self.receive()
        row.refresh_from_db()
        self.assertEqual(bytes(row.content), bytes(self.letter.pdf))

    def test_publish_link_validates_archive_and_only_sets_configured_attributes(self):
        row = self.receive()[0]
        result = publish_incoming_link(self.ump, row.uuid, reason="Test link", transport=self.transport)
        self.assertEqual(result.link_status, "PUBLISHED")
        self.assertEqual(result.link_attempts, 1)
        put = next(r for r in self.calls if r.method == "PUT")
        values = {x["klucz"]: x["wartosc"] for x in json.loads(put.content)["metadane"]}
        self.assertEqual(values, {"Dyna.Id": str(self.req.uuid), "Dyna.Url": row.request_url})
        self.assertTrue(AuditLog.objects.filter(action="ezd.incoming.link.published").exists())

    def test_custom_metadata_attribute_id_also_detects_conflicting_request(self):
        def by_id(request):
            response = self.mock(request)
            if request.method == "GET" and request.url.path.endswith("/dokumenty/doc1/metadane"):
                value = response.json()
                value["listaKonfiguracji"] = [
                    {"id": "Dyna.Id", "kluczSystemowy": "", "wartosc": str(uuid.uuid4())}
                ]
                return httpx.Response(200, json=value)
            return response

        row = receive_rpw(self.ump, 17, 2026, reason="Test", transport=httpx.MockTransport(by_id))[0]
        self.assertIsNone(row.letter_id)
        self.assertIn("Identyfikator", row.error)

    def test_timeout_is_audited_and_safe_repeat_does_not_create_document(self):
        row = self.receive()[0]
        self.put_failure = True
        with self.assertRaises(ConnectorError):
            publish_incoming_link(self.ump, row.uuid, reason="Test timeout", transport=self.transport)
        row.refresh_from_db()
        self.assertEqual(row.link_status, "REVIEW_REQUIRED")
        self.assertTrue(row.link_error)
        self.put_failure = False
        result = publish_incoming_link(
            self.ump, row.uuid, reason="Sprawdzenie po timeout", transport=self.transport
        )
        self.assertEqual(result.link_attempts, 2)
        self.assertEqual(EZDIncomingDocument.objects.count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="ezd.incoming.link.error").exists())
        self.assertTrue(all(r.method != "POST" or r.url.path == "/connect/token" for r in self.calls))

    def test_publish_refuses_changed_remote_version_content_and_claim(self):
        row = self.receive()[0]
        for change in ("doc_version", "payload", "request_id"):
            with self.subTest(change=change):
                old = getattr(self, change)
                setattr(self, change, b"%PDF-1.7\nwrong" if change == "payload" else str(uuid.uuid4()))
                with self.assertRaises(ValidationError):
                    publish_incoming_link(self.ump, row.uuid, reason="Test", transport=self.transport)
                setattr(self, change, old)
        self.assertFalse(any(r.method == "PUT" for r in self.calls))

    def test_roles_and_reason_are_checked_before_network(self):
        with self.assertRaises(PermissionDenied):
            self.receive(self.admin)
        with self.assertRaises(ValidationError):
            receive_rpw(self.ump, 17, 2026, reason="", transport=self.transport)
        self.assertEqual(self.calls, [])

    def test_document_changes_during_download_before_archive(self):
        def changing(request):
            response = self.mock(request)
            if request.url.path == "/download/doc1":
                self.doc_version = "v2"
            return response

        with self.assertRaises(ConnectorError):
            receive_rpw(self.ump, 17, 2026, reason="Test", transport=httpx.MockTransport(changing))
        self.assertFalse(EZDIncomingDocument.objects.exists())
        self.assertTrue(AuditLog.objects.filter(action="ezd.incoming.read.error").exists())

    def test_deleted_or_unconfirmed_rpw_is_rejected_before_download(self):
        for status in (1, 4, 74, None, True):

            def deleted(request):
                response = self.mock(request)
                if request.url.path.endswith("/rpw/17/2026/metadane"):
                    value = response.json()
                    value["status"] = status
                    return httpx.Response(200, json=value)
                return response

            with self.subTest(status=status), self.assertRaises(ConnectorError):
                receive_rpw(self.ump, 17, 2026, reason="Test", transport=httpx.MockTransport(deleted))
        self.assertFalse(any(r.url.path == "/download/doc1" for r in self.calls))

    def test_search_refuses_foreign_tenant_and_missing_pagination_proof(self):
        for issue in ("tenant", "pagination", "deleted_state"):

            def wrong(request):
                response = self.mock(request)
                if request.url.path.endswith("/rpw/_search"):
                    value = response.json()
                    if issue == "tenant":
                        value["lista"][0]["idPodmiotWlascicielBiznesowy"] = "other"
                    elif issue == "pagination":
                        value["pageInfo"] = {"pageNumber": 0, "pageSize": 25}
                    else:
                        value["lista"][0].pop("czyUsuniety")
                    return httpx.Response(200, json=value)
                return response

            with (
                self.subTest(issue=issue),
                EZDRPClient(self.profile, transport=httpx.MockTransport(wrong)) as client,
            ):
                with self.assertRaises(ConnectorError):
                    client.search_incoming(date(2026, 10, 1), date(2026, 10, 3))

    def test_profile_change_and_corrupted_archive_block_put(self):
        row = self.receive()[0]
        with patch(
            "registry.ezd_incoming.load_profile",
            return_value=EZDProfile(
                api_url="https://other.test.invalid",
                token_url=self.profile.token_url,
                web_host=self.profile.web_host,
                pid=self.profile.pid,
                aki=self.profile.aki,
                sid=self.profile.sid,
                api_key=self.profile.api_key,
                metadata=self.profile.metadata,
            ),
        ):
            with self.assertRaises(ValidationError):
                publish_incoming_link(self.ump, row.uuid, reason="Test", transport=self.transport)
        row.content = b"corrupt"
        row.save()
        with self.assertRaises(ValidationError):
            publish_incoming_link(self.ump, row.uuid, reason="Test", transport=self.transport)
        self.assertFalse(any(r.method == "PUT" for r in self.calls))

    def test_nested_attachments_are_bounded_and_duplicates_are_rejected(self):
        base = {"idDokumentPrzestrzeni": "doc1", "idDokumentWersja": "v1"}
        self.assertEqual(attachment_ids({"zalaczniki": [base]}), [("doc1", "v1")])
        for value in ([base, base], [None], "invalid", [{**base, "zalaczniki": [base]}]):
            with self.assertRaises(ConnectorError):
                attachment_ids({"zalaczniki": value})

    def test_search_pagination_and_dates_match_official_contract(self):
        with EZDRPClient(self.profile, transport=self.transport) as client:
            self.assertEqual(
                client.search_incoming(date(2026, 10, 1), date(2026, 10, 3)), ([(17, 2026)], True)
            )
            self.assertEqual(
                client.search_incoming(date(2026, 10, 1), date(2026, 10, 3), 1), ([(17, 2026)], False)
            )
            for start, end in ((date(2026, 10, 3), date(2026, 10, 1)), (date(2026, 1, 1), date(2026, 10, 3))):
                with self.assertRaises(ConnectorError):
                    client.search_incoming(start, end)

    def test_cli_pages_deduplicate_repeated_rpw_and_report_incomplete_scan(self):
        factory = lambda profile, **kw: EZDRPClient(profile, transport=self.transport)
        with (
            patch("registry.ezd_incoming.EZDRPClient", side_effect=factory),
            patch("registry.management.commands.sync_ezd_incoming.EZDRPClient", side_effect=factory),
            patch("registry.management.commands.sync_ezd_incoming.load_profile", return_value=self.profile),
        ):
            output = StringIO()
            call_command(
                "sync_ezd_incoming",
                actor=self.ump.email,
                date_from=date(2026, 10, 1),
                date_to=date(2026, 10, 3),
                reason="Test",
                stdout=output,
            )
            self.assertIn("Odczyt zakończony: 1 RPW", output.getvalue())
            with self.assertRaisesMessage(CommandError, "Odczyt jest niepełny"):
                call_command(
                    "sync_ezd_incoming",
                    actor=self.ump.email,
                    date_from=date(2026, 10, 1),
                    date_to=date(2026, 10, 3),
                    reason="Test",
                    max_pages=1,
                    stdout=StringIO(),
                )
        self.assertEqual(EZDIncomingDocument.objects.count(), 1)

    def test_ui_get_does_not_call_api_post_requires_csrf_and_documents_are_isolated(self):
        self.client.force_login(self.ump)
        url = reverse("ezd_incoming")
        self.assertContains(self.client.get(url), "Pobierz i sprawdź RPW")
        self.assertEqual(self.calls, [])
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.ump)
        self.assertEqual(csrf.post(url, {"number": 17, "year": 2026, "reason": "Test"}).status_code, 403)
        with patch(
            "registry.ezd_incoming.EZDRPClient",
            side_effect=lambda p, **kw: EZDRPClient(p, transport=self.transport),
        ):
            self.assertRedirects(self.client.post(url, {"number": 17, "year": 2026, "reason": "Test"}), url)
        row = EZDIncomingDocument.objects.get()
        self.assertContains(self.client.get(url), str(self.letter.number))
        detail_url = reverse("request_detail", args=[self.req.uuid])
        self.assertContains(self.client.get(detail_url), "Wpływy z EZD do Twojego urzędu")
        self.assertContains(self.client.get(detail_url), "ezd.incoming.received")
        pdf_url = reverse("ezd_incoming_pdf", args=[row.uuid])
        response = self.client.get(pdf_url)
        self.assertEqual(response.content, self.payload)
        self.assertIn("no-store", response["Cache-Control"])
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(url), str(self.letter.number))
        self.assertEqual(self.client.get(pdf_url).status_code, 404)
        self.client.force_login(self.county)
        self.assertNotContains(self.client.get(detail_url), "ezd.incoming.received")
        self.assertNotContains(self.client.get(detail_url), "Wpływy z EZD do Twojego urzędu")
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.post(
                reverse("ezd_incoming_publish", args=[row.uuid]), {"reason": "Test"}
            ).status_code,
            404,
        )
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(pdf_url).status_code, 403)


class IncomingConcurrencyTests(TransactionTestCase):
    setUp = IncomingTests.setUp
    mock = IncomingTests.mock

    @skipUnlessDBFeature("has_select_for_update")
    def test_two_real_database_connections_receive_one_version_once(self):
        start = Barrier(2)

        def synchronized(request):
            if request.url.path == "/connect/token":
                start.wait(timeout=5)
            return self.mock(request)

        transport = httpx.MockTransport(synchronized)

        def worker():
            close_old_connections()
            try:
                return receive_rpw(self.ump, 17, 2026, reason="Równoczesny odczyt", transport=transport)[0].pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker) for _ in range(2)]
            ids = [future.result(timeout=10) for future in futures]
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(EZDIncomingDocument.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="ezd.incoming.received").count(), 1)


class IncomingBackupTests(TransactionTestCase):
    def test_snapshot_and_restore_preserve_incoming_pdf_and_reject_corruption(self):
        _, ump, county, _ = fixtures()
        letter = create_request(county, data()).letters.get()
        row = EZDIncomingDocument.objects.create(
            office=ump.office,
            target_hash="a" * 64,
            rpw_number=17,
            rpw_year=2026,
            document_id="doc1",
            version_id="v1",
            workspace_id="space1",
            letter=letter,
            content=bytes(letter.pdf),
            sha256=letter.sha256,
            status="MATCHED",
        )
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "backup.zip"
            target = Path(temp) / "restore"
            call_command("backup_registry", output=str(archive), stdout=StringIO())
            from ._backup_test_helpers import restored_database

            with restored_database(archive, target) as (db, _):
                content, digest = db.execute(
                    "SELECT content,sha256 FROM registry_ezdincomingdocument"
                ).fetchone()
                self.assertEqual(content, bytes(letter.pdf))
                self.assertEqual(digest, letter.sha256)
            row.content = b"corrupt"
            row.save()
            with self.assertRaisesMessage(CommandError, "Uszkodzony dokument wpływu"):
                call_command("backup_registry", output=str(Path(temp) / "bad.zip"), stdout=StringIO())
