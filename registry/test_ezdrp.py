"""Testy kontraktowe: MockTransport NIE jest dowodem działania piaskownicy EZD."""

import base64
import hashlib
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .connectors.ezdrp import ConnectorError, EZDProfile, EZDRPClient, load_profile
from .integrations import enqueue, enqueue_ezd, process_job, reconcile_ezd_job, recover_stale_jobs
from .models import AuditLog, EZDCaseLink, IntegrationJob
from .services import create_request
from .tests import data, fixtures


class EZDRPTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        self.req = create_request(self.a, data())
        self.letter = self.req.letters.get()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        self.key_file = directory / "key"
        self.key_file.write_text("synthetic-api-key")
        self.key_file.chmod(0o600)
        self.config_file = directory / "ezd.json"
        profile = {
            "api_url": "https://api.ezd.test.invalid",
            "token_url": "https://sso.ezd.test.invalid/connect/token",
            "web_host": "web.ezd.test.invalid",
            "pid": "podmiot-test",
            "aki": "key-test",
            "sid": "sid-test",
            "api_key_file": str(self.key_file),
            "jrwa_id": "jrwa-test",
            "archival_category": "B10",
            "metadata": {
                "request_id": {"key": "Dyna.RequestId", "name": "Wniosek Dyna"},
                "request_url": {"key": "Dyna.RequestUrl", "name": "Link do wniosku"},
            },
        }
        self.config_file.write_text(json.dumps({"offices": {"a": profile, "ump": profile}}))
        self.config_file.chmod(0o600)
        self.setting = self.settings(EZDRP_CONFIG_FILE=str(self.config_file))
        self.setting.enable()
        self.addCleanup(self.setting.disable)
        self.calls = []

    def mock(self, request):
        self.calls.append(request)
        path = request.url.path
        if path == "/download/doc-test":
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(200, content=bytes(self.letter.pdf))
        if path == "/connect/token":
            return httpx.Response(
                200, json={"access_token": "synthetic-token", "token_type": "Bearer", "expires_in": 300}
            )
        self.assertEqual(request.headers["authorization"], "Bearer synthetic-token")
        self.assertEqual(request.headers["sid"], "sid-test")
        if path.endswith("/sprawy/case-test"):
            return httpx.Response(
                200,
                json={
                    "idSprawa": "case-test",
                    "tytul": "Sprawa testowa",
                    "idPodmiotWlascicielBiznesowy": "podmiot-test",
                    "znak": "TEST.1.2026",
                    "idPrzestrzenRobocza": "space-test",
                },
            )
        if path.endswith("/sprawy") and request.method == "POST":
            values = json.loads(request.content)
            self.assertEqual(values["idWykaz"], "jrwa-test")
            self.assertEqual(values["numer"], 17)
            self.assertEqual(values["kategoriaArchiwalna"], "B10")
            return httpx.Response(
                201,
                json={
                    "idSprawa": "case-test",
                    "tytul": values["tytul"],
                    "idPodmiotWlascicielBiznesowy": "podmiot-test",
                    "znak": "TEST.17.2026",
                },
            )
        if path.endswith("/sprawy/case-test/dokumenty"):
            self.assertIn(b'name="files"', request.content)
            self.assertIn(f"DRT-{self.letter.uuid}.pdf".encode(), request.content)
            self.assertIn(bytes(self.letter.pdf), request.content)
            return httpx.Response(
                201,
                json={
                    "lista": [
                        {
                            "idDokumentPrzestrzeni": "doc-test",
                            "idDokument": "d-test",
                            "idDokumentWersja": "v-test",
                            "idPrzestrzenRobocza": "space-test",
                        }
                    ]
                },
            )
        if path.endswith("/dokumenty/doc-test/metadane"):
            values = json.loads(request.content)
            self.assertIn(str(self.req.uuid), request.content.decode())
            self.assertIn(f"/panel/wnioski/{self.req.uuid}/", request.content.decode())
            return httpx.Response(200, json=values)
        if path.endswith("/dokumenty/doc-test/link"):
            return httpx.Response(200, json={"link": "https://api.ezd.test.invalid/download/doc-test"})
        if path.endswith("/dokumenty/doc-test"):
            return httpx.Response(
                200, json={"idDokumentPrzestrzeni": "doc-test", "idPrzestrzenRobocza": "space-test"}
            )
        raise AssertionError(f"Nieoczekiwane żądanie {request.method} {path}")

    def queue(self, **kwargs):
        return enqueue_ezd(
            self.a, self.letter, reason="Test powiązania", **({"case_id": "case-test"} | kwargs)
        )

    def process(self, job, handler=None):
        return process_job(job, transport=httpx.MockTransport(handler or self.mock))

    def test_auth_matches_official_hash_protocol_and_keeps_key_off_wire(self):
        profile = load_profile("a")
        with EZDRPClient(profile, transport=httpx.MockTransport(self.mock)) as client:
            client.get_case("case-test")
            client.get_case("case-test")
        auth = self.calls[0]
        fields = parse_qs(auth.content.decode())
        expected = base64.b64encode(
            hashlib.sha256((fields["rt"][0] + "synthetic-api-key").encode()).digest()
        ).decode()
        self.assertEqual(fields["akh"], [expected])
        expected_id = "api_" + base64.b64encode(hashlib.sha256(b"web.ezd.test.invalid").digest()).decode()
        self.assertEqual(fields["client_id"], [expected_id])
        self.assertEqual(fields["grant_type"], ["api_credentials"])
        self.assertNotIn(b"synthetic-api-key", auth.content)
        self.assertEqual(sum(call.url.path == "/connect/token" for call in self.calls), 1)
        self.assertNotIn("synthetic-api-key", repr(profile))

    def test_register_freezes_pdf_and_is_not_a_delivery(self):
        job = self.queue()
        self.assertEqual(self.queue().pk, job.pk)
        result = self.process(job)
        self.assertEqual(result.status, "REGISTERED")
        self.assertFalse(result.result["delivery_confirmed"])
        self.assertEqual(result.result["case_symbol"], "TEST.1.2026")
        self.assertEqual(result.remote_id, "doc-test")
        self.letter.refresh_from_db()
        self.assertEqual(self.letter.ezd_id, "doc-test")
        self.assertEqual(result.payload_sha256, self.letter.sha256)
        count = len(self.calls)
        self.process(result)
        self.assertEqual(len(self.calls), count)
        self.assertEqual(IntegrationJob.objects.count(), 1)
        self.assertNotIn("synthetic-token", json.dumps(result.result))
        self.assertNotIn("synthetic-api-key", str(list(AuditLog.objects.values())))

    def test_create_case_then_add_pdf_once(self):
        job = enqueue_ezd(self.a, self.letter, case_number=17, reason="Nowa sprawa testowa")
        result = self.process(job)
        self.assertEqual(result.status, "REGISTERED")
        link = EZDCaseLink.objects.get()
        self.assertEqual(link.remote_id, "case-test")
        self.assertEqual(link.state, "LINKED")
        self.assertEqual(result.result["steps"]["create_case"]["state"], "COMPLETED")
        self.assertEqual(
            sum(call.method == "POST" and call.url.path.endswith("/sprawy") for call in self.calls), 1
        )

    def test_no_profile_no_foreign_sender_no_invalid_case_no_implicit_creation(self):
        with self.assertRaises(ValidationError):
            enqueue_ezd(self.b, self.letter, case_id="case-test", reason="Test")
        with self.assertRaises(ValidationError):
            enqueue_ezd(self.a, self.letter)
        with self.assertRaises(ValidationError):
            self.queue(case_id="../foreign")
        with self.settings(EZDRP_CONFIG_FILE=""):
            with self.assertRaises(ValidationError):
                self.queue()
        self.assertEqual(IntegrationJob.objects.count(), 0)
        self.assertEqual(EZDCaseLink.objects.count(), 0)

    def test_case_belongs_to_configured_office(self):
        def foreign(request):
            if request.url.path.endswith("/sprawy/case-test"):
                return httpx.Response(
                    200,
                    json={
                        "idSprawa": "case-test",
                        "tytul": "Inny podmiot",
                        "idPodmiotWlascicielBiznesowy": "foreign",
                    },
                )
            return self.mock(request)

        result = self.process(self.queue(), foreign)
        self.assertEqual(result.status, "REVIEW_REQUIRED")
        self.assertFalse(any("/dokumenty" in call.url.path for call in self.calls))

    def test_timeout_after_upload_is_never_automatically_repeated(self):
        def broken(request):
            if request.url.path.endswith("/dokumenty"):
                self.calls.append(request)
                raise httpx.ReadTimeout("response lost; synthetic-token", request=request)
            return self.mock(request)

        job = self.process(self.queue(), broken)
        self.assertEqual(job.status, "REVIEW_REQUIRED")
        self.assertEqual(job.result["steps"]["add_document"]["state"], "IN_FLIGHT")
        self.assertNotIn("synthetic-token", job.error)
        count = len(self.calls)
        self.process(job)
        self.assertEqual(len(self.calls), count)

    def test_safe_retry_only_resumes_missing_metadata_without_second_upload(self):
        def limited(request):
            if request.url.path.endswith("/metadane"):
                self.calls.append(request)
                return httpx.Response(429, headers={"Retry-After": "120"}, json={})
            return self.mock(request)

        job = self.process(self.queue(), limited)
        self.assertEqual(job.status, "RETRY")
        self.assertEqual(job.result["steps"]["add_document"]["state"], "COMPLETED")
        self.assertGreater(job.next_attempt_at, timezone.now() + timedelta(seconds=100))
        before = len(self.calls)
        self.process(job)
        self.assertEqual(len(self.calls), before)
        IntegrationJob.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        job = self.process(job)
        self.assertEqual(job.status, "REGISTERED")
        self.assertEqual(sum(call.url.path.endswith("/dokumenty") for call in self.calls), 1)

    def test_unconfirmed_creation_blocks_other_letters_from_creating_case(self):
        def lost(request):
            if request.method == "POST" and request.url.path.endswith("/sprawy"):
                raise httpx.ReadTimeout("response lost", request=request)
            return self.mock(request)

        job = enqueue_ezd(self.a, self.letter, case_number=17, reason="Test")
        result = self.process(job, lost)
        self.assertEqual(result.status, "REVIEW_REQUIRED")
        self.assertEqual(EZDCaseLink.objects.get().state, "REVIEW_REQUIRED")

    def test_connect_failure_can_retry_and_wrong_target_cannot(self):
        def unreachable(request):
            raise httpx.ConnectError("synthetic-secret", request=request)

        job = self.process(self.queue(), unreachable)
        self.assertEqual(job.status, "RETRY")
        self.assertNotIn("synthetic-secret", job.error)
        conf = json.loads(self.config_file.read_text())
        conf["offices"]["a"]["api_url"] = "https://other.ezd.test.invalid"
        self.config_file.write_text(json.dumps(conf))
        IntegrationJob.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        result = self.process(job)
        self.assertEqual(result.status, "REVIEW_REQUIRED")
        self.assertEqual(len(self.calls), 0)

    def test_stale_worker_is_reported_and_does_not_resend(self):
        job = self.queue()
        IntegrationJob.objects.filter(pk=job.pk).update(
            status="PROCESSING", claimed_until=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(recover_stale_jobs(), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, "REVIEW_REQUIRED")
        self.process(job)
        self.assertEqual(len(self.calls), 0)

    def test_reconcile_verifies_remote_pdf_before_resuming_without_upload(self):
        def lost(request):
            if request.url.path.endswith("/dokumenty"):
                self.calls.append(request)
                raise httpx.ReadTimeout("response lost", request=request)
            return self.mock(request)

        job = self.process(self.queue(), lost)
        self.assertEqual(job.status, "REVIEW_REQUIRED")
        with self.assertRaises(ValidationError):
            reconcile_ezd_job(self.admin, job.uuid, reason="Test", transport=httpx.MockTransport(self.mock))
        job = reconcile_ezd_job(
            self.admin,
            job.uuid,
            document_id="doc-test",
            reason="Potwierdzono w API",
            transport=httpx.MockTransport(self.mock),
        )
        self.assertEqual(job.status, "QUEUED")
        result = self.process(job)
        self.assertEqual(result.status, "REGISTERED")
        self.assertEqual(sum(call.url.path.endswith("/sprawy/case-test/dokumenty") for call in self.calls), 1)
        self.assertTrue(AuditLog.objects.filter(action="integration.reconciled", actor=self.admin).exists())

    def test_reconcile_refuses_changed_remote_pdf_and_foreign_workspace(self):
        job = self.queue()
        IntegrationJob.objects.filter(pk=job.pk).update(status="REVIEW_REQUIRED")

        def altered(request):
            if request.url.path == "/download/doc-test":
                return httpx.Response(200, content=b"a different PDF")
            return self.mock(request)

        with self.assertRaises(ValidationError):
            reconcile_ezd_job(
                self.admin,
                job.uuid,
                document_id="doc-test",
                reason="Test",
                transport=httpx.MockTransport(altered),
            )

        def foreign(request):
            if request.url.path.endswith("/dokumenty/doc-test"):
                return httpx.Response(
                    200, json={"idDokumentPrzestrzeni": "doc-test", "idPrzestrzenRobocza": "foreign"}
                )
            return self.mock(request)

        with self.assertRaises(ValidationError):
            reconcile_ezd_job(
                self.admin,
                job.uuid,
                document_id="doc-test",
                reason="Test",
                transport=httpx.MockTransport(foreign),
            )
        job.refresh_from_db()
        self.assertEqual(job.status, "REVIEW_REQUIRED")

    def test_ambiguous_server_response_and_untrusted_download_are_blocked(self):
        def failed(request):
            if request.url.path.endswith("/dokumenty"):
                return httpx.Response(500, json={"detail": "synthetic-secret"})
            return self.mock(request)

        job = self.process(self.queue(), failed)
        self.assertEqual(job.status, "REVIEW_REQUIRED")
        self.assertNotIn("synthetic-secret", job.error)

        def untrusted(request):
            if request.url.path.endswith("/dokumenty/doc-test/link"):
                return httpx.Response(200, json={"link": "https://other.test.invalid/private?token=secret"})
            return self.mock(request)

        with EZDRPClient(load_profile("a"), transport=httpx.MockTransport(untrusted)) as client:
            with self.assertRaises(ConnectorError):
                client.document_sha256("doc-test")
        self.assertFalse(any(call.url.host == "other.test.invalid" for call in self.calls))

    def test_secret_permissions_and_tls_are_required(self):
        self.key_file.chmod(0o644)
        with self.assertRaises(ConnectorError):
            load_profile("a")
        self.key_file.chmod(0o600)
        conf = json.loads(self.config_file.read_text())
        conf["offices"]["a"]["api_url"] = "http://api.ezd.test.invalid"
        self.config_file.write_text(json.dumps(conf))
        with self.assertRaises(ConnectorError):
            load_profile("a")

    def test_ezd_page_scope_and_csrf(self):
        url = reverse("letter_ezd", args=[self.letter.uuid])
        self.client.force_login(self.a)
        self.assertContains(self.client.get(url), "Zapis dokumentu w EZD RP")
        self.assertEqual(self.client.post(url, {"case_id": "case-test", "reason": "Test"}).status_code, 302)
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_smtp_uses_frozen_payload_and_deduplicates(self):
        self.letter.recipient.email = "office@test.invalid"
        self.letter.recipient.save()
        with self.settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            job = enqueue(self.a, self.letter, "SMTP")
            self.letter.signed_pdf = b"changed-after-queue"
            self.letter.save(update_fields=["signed_pdf"])
            self.assertEqual(process_job(job).status, "ACCEPTED")
            from django.core import mail

            self.assertEqual(mail.outbox[-1].attachments[0].content, bytes(self.letter.pdf))
            self.assertEqual(enqueue(self.a, self.letter, "SMTP").pk, job.pk)
            process_job(job)
            self.assertEqual(len(mail.outbox), 1)


class EZDConcurrentQueueTests(TransactionTestCase):
    def test_concurrent_double_click_queues_only_one_document_and_case(self):
        _, _, county, _ = fixtures()
        letter = create_request(county, data()).letters.get()
        barrier = Barrier(2)
        profile = EZDProfile(
            api_url="https://api.test.invalid",
            token_url="https://sso.test.invalid/connect/token",
            web_host="web.test.invalid",
            pid="pid-test",
            aki="aki-test",
            sid="sid-test",
            api_key="synthetic",
        )

        def queue():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return enqueue_ezd(county, letter, case_id="case-test", reason="Test współbieżności").pk
            finally:
                close_old_connections()

        with (
            patch("registry.integrations.load_profile", return_value=profile),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            results = list(executor.map(lambda _: queue(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(EZDCaseLink.objects.count(), 1)
        self.assertEqual(IntegrationJob.objects.count(), 1)
