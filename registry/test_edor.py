"""Kontrakt i awarie z MockTransport; NIE test rzeczywistego środowiska INT."""

import base64
import hashlib
import json
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from .connectors.edor import TOKEN_CACHE, EDorClient, load_profile
from .connectors.ezdrp import ConnectorError
from .edor_delivery import edor_resume_mode, resume_edor_observation, resume_edor_unsent
from .integrations import enqueue, process_job, recover_stale_jobs
from .models import AuditLog, DeliveryEvidence, IntegrationJob
from .services import create_request
from .tests import data, fixtures

SENDER = "AE:PL-11111-11111-AAAAA-11"
RECIPIENT = "AE:PL-22222-22222-BBBBB-22"


class EDorTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "FIKCYJNY TEST — NIE KWALIFIKOWANY")])
        now = datetime.now(dt_timezone.utc)
        cls.cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(cls.key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .sign(cls.key, hashes.SHA256())
        )

    def setUp(self):
        TOKEN_CACHE.clear()
        self.addCleanup(TOKEN_CACHE.clear)
        self.admin, self.ump, self.a, self.b = fixtures()
        self.a.office.ade = SENDER
        self.a.office.save()
        self.ump.office.ade = RECIPIENT
        self.ump.office.save()
        self.letter = create_request(self.a, data()).letters.get()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        key_file, cert_file = directory / "key.pem", directory / "cert.pem"
        key_file.write_bytes(
            self.key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        cert_file.write_bytes(self.cert.public_bytes(serialization.Encoding.PEM))
        key_file.chmod(0o600)
        cert_file.chmod(0o600)
        self.profile_config = {
            "environment": "INT",
            "sender_ade": SENDER,
            "system_name": "DYNA.TEST",
            "ua_url": "https://ua.test.invalid/api/v3",
            "se_url": "https://se.test.invalid/api/se/v4",
            "token_url": "https://iam.test.invalid/auth/realms/EDOR/protocol/openid-connect/token",
            "audience": "https://iam.test.invalid/auth/realms/EDOR",
            "private_key_file": str(key_file),
            "certificate_file": str(cert_file),
        }
        self.config_file = directory / "edor.json"
        self.write_config()
        setting = self.settings(EDOR_CONFIG_FILE=str(self.config_file))
        setting.enable()
        self.addCleanup(setting.disable)
        self.calls = []
        self.pending = False
        self.remote_status = "Nadana"
        self.evidence_available = True
        self.transport = httpx.MockTransport(self.mock)

    def write_config(self):
        self.config_file.write_text(json.dumps({"offices": {"a": self.profile_config}}))
        self.config_file.chmod(0o600)

    def mock(self, request):
        self.calls.append(request)
        path = request.url.path
        if path.endswith("/openid-connect/token"):
            params = parse_qs(request.content.decode())
            assertion = params["client_assertion"][0]
            claims = jwt.decode(
                assertion,
                self.key.public_key(),
                algorithms=["RS256"],
                audience=self.profile_config["audience"],
            )
            self.assertEqual(claims["iss"], f"{SENDER}.SYSTEM.DYNA.TEST")
            self.assertEqual(claims["iss"], claims["sub"])
            self.assertEqual(claims["exp"] - claims["iat"], 300)
            self.assertEqual(params["grant_type"], ["client_credentials"])
            self.assertEqual(request.url.params["login_hint"], f"ADE.{SENDER}")
            return httpx.Response(
                200, json={"access_token": "synthetic-token", "expires_in": 300, "token_type": "Bearer"}
            )
        self.assertEqual(request.headers["authorization"], "Bearer synthetic-token")
        if path.endswith("/eda-confirmation"):
            self.assertEqual(json.loads(request.content), {"senderEda": SENDER, "recipientEda": RECIPIENT})
            return httpx.Response(
                200,
                json={
                    "recipientEda": {
                        "recipientEda": RECIPIENT,
                        "edaStatus": "ACTIVE",
                        "assignmentDegree": 3,
                        "designatedOperator": True,
                    },
                    "recipient": {"isPublic": True, "entityName": "UMP test"},
                },
            )
        if path.endswith("/bae_search"):
            self.assertEqual(json.loads(request.content)["searchCategory"], ["PUBLIC_INSTITUTION"])
            return httpx.Response(
                200,
                json={
                    "totalResults": 1,
                    "baeSearchResponses": [
                        {
                            "recipientEda": {
                                "recipientEda": RECIPIENT,
                                "edaStatus": "ACTIVE",
                                "assignmentDegree": 3,
                                "isMainEda": True,
                            },
                            "baeSearchData": [
                                {"index": 1, "isPublic": True, "entityName": "UMP test"},
                                {"index": 2, "isPublic": True, "entityName": "Stara nazwa"},
                            ],
                        }
                    ],
                },
            )
        if path.endswith("/messages") and request.method == "POST":
            message = json.loads(request.content)
            self.assertEqual(message["messageMetadata"]["to"], [{"eDeliveryAddress": RECIPIENT}])
            self.assertEqual(message["messageMetadata"]["shippingService"], "electronic")
            self.assertNotIn("messageControlData", message)
            file = message["attachments"][0]["file"]
            self.assertEqual(base64.b64decode(file["file"]), bytes(self.letter.pdf))
            self.assertEqual(file["fileMetadata"]["contentType"], "application/pdf")
            return httpx.Response(202, json={"messageTaskId": "task-test"})
        if path.endswith("/tasks/task-test/status"):
            return httpx.Response(200, json={"messageTaskStatus": "PENDING" if self.pending else "FINISHED"})
        if path.endswith("/tasks/task-test"):
            return httpx.Response(
                200, json=[{"messageId": "message-test", "addressee": {"eDeliveryAddress": RECIPIENT}}]
            )
        if path.endswith("/messages/message-test"):
            self.assertEqual(request.url.params["format"], "metadata")
            return httpx.Response(
                200,
                json=[
                    {
                        "messageMetadata": {
                            "messageId": "message-test",
                            "from": {"eDeliveryAddress": SENDER},
                            "to": [{"eDeliveryAddress": RECIPIENT, "contributor": {"companyName": "UMP"}}],
                            "shippingService": "electronic",
                            "submissionDate": "2026-10-03T12:00:00Z",
                        },
                        "messageControlData": {"status": self.remote_status},
                    }
                ],
            )
        if path.endswith("/messages/message-test/evidences"):
            proofs = [
                {
                    "evidenceId": "submission-test",
                    "messageId": "message-test",
                    "type": "A.1",
                    "externalData": "https://untrusted.invalid/secret",
                }
            ]
            if self.remote_status in {"Doręczona", "Uznana za doręczoną"} and self.evidence_available:
                proofs.append(
                    {
                        "evidenceId": "receipt-test",
                        "messageId": "message-test",
                        "type": "E.1" if self.remote_status == "Doręczona" else "BP.OX",
                    }
                )
            return httpx.Response(200, json={"evidences": proofs})
        if "/evidences/purde/" in path:
            return httpx.Response(
                200, content=b"<FikcyjnyDowodTestowy/>", headers={"Content-Type": "application/octet-stream"}
            )
        self.fail(f"Nieoczekiwane wywołanie: {request.method} {path}")

    def run_job(self, job):
        IntegrationJob.objects.filter(pk=job.pk).update(next_attempt_at=None)
        return process_job(job, transport=self.transport)

    def send_count(self):
        return sum(
            request.method == "POST" and request.url.path.endswith("/messages") for request in self.calls
        )

    def test_signed_authentication_and_token_reuse_across_clients(self):
        profile = load_profile("a")
        self.assertNotIn("private_key=", repr(profile))
        for _ in range(2):
            with EDorClient(profile, transport=self.transport) as client:
                self.assertEqual(client.confirm_address(RECIPIENT)["ade"], RECIPIENT)
        self.assertEqual(sum(r.url.path.endswith("/token") for r in self.calls), 1)
        with EDorClient(
            replace(profile, certificate_expires_at=datetime.now(dt_timezone.utc) - timedelta(seconds=1)),
            transport=self.transport,
        ) as client:
            with self.assertRaises(ConnectorError):
                client.authenticate()

    def test_public_search_filters_old_versions_and_never_updates_offices(self):
        with EDorClient(load_profile("a"), transport=self.transport) as client:
            result = client.search_public("UMP")
        self.assertEqual(
            result["rows"], [{"ade": RECIPIENT, "name": "UMP test", "active": True, "main": True}]
        )
        self.assertEqual(self.ump.office.ade, RECIPIENT)

    def test_queue_freezes_addresses_and_document_and_deduplicates(self):
        job = enqueue(self.a, self.letter, "EDOR")
        self.assertEqual(enqueue(self.a, self.letter, "EDOR").pk, job.pk)
        original = bytes(job.payload)
        self.letter.signed_pdf = b"%PDF-CHANGED"
        self.letter.save(update_fields=["signed_pdf"])
        self.ump.office.ade = "AE:PL-33333-33333-CCCCC-33"
        self.ump.office.save()
        result = self.run_job(job)
        self.assertEqual(result.status, "MONITORING")
        self.assertEqual(bytes(result.payload), original)
        self.assertEqual(result.result["recipient_ade"], RECIPIENT)
        self.assertFalse(result.result["delivery_confirmed"])
        self.assertEqual(self.send_count(), 1)

    def test_async_pending_then_submission_and_delivery_archives_proofs_once(self):
        job = self.run_job(enqueue(self.a, self.letter, "EDOR"))
        self.pending = True
        job = self.run_job(job)
        self.assertEqual(job.remote_id, "")
        self.assertEqual(job.status, "MONITORING")
        self.pending = False
        job = self.run_job(job)
        self.assertEqual(job.remote_id, "message-test")
        self.assertEqual(job.status, "MONITORING")
        self.assertTrue(job.result["submission_evidence_archived"])
        self.remote_status = "Doręczona"
        job = self.run_job(job)
        self.assertEqual(job.status, "EDOR_DELIVERED")
        self.assertTrue(job.result["delivery_confirmed"])
        self.assertFalse(job.result["evidence_signature_verified"])
        self.assertEqual(job.evidence.count(), 2)
        self.assertEqual(self.send_count(), 1)
        self.assertEqual(sum(r.url.path.endswith("/purde/submission-test") for r in self.calls), 1)
        self.assertFalse(any(r.url.host == "untrusted.invalid" for r in self.calls))
        for evidence in job.evidence.all():
            self.assertEqual(evidence.sha256, hashlib.sha256(bytes(evidence.content)).hexdigest())

    def test_delivery_without_proof_remains_observed_and_deemed_is_distinct(self):
        job = self.run_job(enqueue(self.a, self.letter, "EDOR"))
        self.remote_status = "Doręczona"
        self.evidence_available = False
        job = self.run_job(job)
        self.assertEqual(job.status, "MONITORING")
        self.assertFalse(job.result["delivery_confirmed"])
        self.remote_status = "Uznana za doręczoną"
        self.evidence_available = True
        job = self.run_job(job)
        self.assertEqual(job.status, "EDOR_DEEMED")
        self.assertFalse(job.result["delivery_confirmed"])

    def test_ambiguous_send_and_worker_restart_never_repeat_post(self):
        job = enqueue(self.a, self.letter, "EDOR")

        def broken(request):
            if request.url.path.endswith("/messages"):
                self.calls.append(request)
                raise httpx.ReadTimeout("secret server response", request=request)
            return self.mock(request)

        job = process_job(job, transport=httpx.MockTransport(broken))
        self.assertEqual(job.status, "REVIEW_REQUIRED")
        self.assertEqual(job.result["steps"]["send"]["state"], "IN_FLIGHT")
        self.assertNotIn("secret", job.error)
        IntegrationJob.objects.filter(pk=job.pk).update(status="RETRY", next_attempt_at=None)
        job = self.run_job(job)
        self.assertEqual(job.status, "REVIEW_REQUIRED")
        self.assertEqual(self.send_count(), 1)
        with self.assertRaises(ValidationError):
            resume_edor_observation(self.admin, job.uuid, reason="Weryfikacja", transport=self.transport)

    def test_429_can_retry_but_500_cannot_repeat_send(self):
        for status, expected in [(429, "RETRY"), (500, "REVIEW_REQUIRED")]:
            with self.subTest(status=status):
                IntegrationJob.objects.all().delete()
                job = enqueue(self.a, self.letter, "EDOR")

                def failure(request):
                    if request.url.path.endswith("/messages"):
                        return httpx.Response(
                            status, headers={"Retry-After": "90"}, json={"error": "sensitive"}
                        )
                    return self.mock(request)

                job = process_job(job, transport=httpx.MockTransport(failure))
                self.assertEqual(job.status, expected)
                self.assertNotIn("sensitive", job.error)
                if status == 429:
                    job = self.run_job(job)
                    self.assertEqual(job.status, "MONITORING")

    def test_read_failures_retry_without_resending_and_can_resume_after_limit(self):
        job = self.run_job(enqueue(self.a, self.letter, "EDOR"))

        def broken(request):
            if request.method == "GET":
                raise httpx.ReadTimeout("synthetic", request=request)
            return self.mock(request)

        for _ in range(5):
            IntegrationJob.objects.filter(pk=job.pk).update(next_attempt_at=None)
            job = process_job(job, transport=httpx.MockTransport(broken))
        self.assertEqual(job.status, "RETRY_EXHAUSTED")
        job = resume_edor_observation(
            self.admin,
            job.uuid,
            reason="Przywrócono połączenie",
            transport=self.transport,
            ip="2001:db8::40",
        )
        self.assertEqual(AuditLog.objects.get(action="edor.observation.resumed").ip, "2001:db8::40")
        job = self.run_job(job)
        self.assertEqual(job.status, "MONITORING")
        self.assertEqual(self.send_count(), 1)
        self.assertEqual(job.result["consecutive_errors"], 0)

    def test_poll_error_budget_resets_after_success(self):
        job = self.run_job(enqueue(self.a, self.letter, "EDOR"))
        for _ in range(6):

            def busy(request):
                if request.method == "GET":
                    return httpx.Response(503)
                return self.mock(request)

            IntegrationJob.objects.filter(pk=job.pk).update(next_attempt_at=None)
            job = process_job(job, transport=httpx.MockTransport(busy))
            self.assertEqual(job.status, "RETRY")
            job = self.run_job(job)
            self.assertEqual(job.status, "MONITORING")
        self.assertEqual(self.send_count(), 1)

    def test_wrong_task_recipient_blocks_observation(self):
        job = self.run_job(enqueue(self.a, self.letter, "EDOR"))

        def wrong(request):
            if request.url.path.endswith("/tasks/task-test"):
                return httpx.Response(
                    200, json=[{"messageId": "foreign", "addressee": {"eDeliveryAddress": SENDER}}]
                )
            return self.mock(request)

        IntegrationJob.objects.filter(pk=job.pk).update(next_attempt_at=None)
        job = process_job(job, transport=httpx.MockTransport(wrong))
        self.assertEqual(job.status, "REVIEW_REQUIRED")
        self.assertEqual(job.evidence.count(), 0)
        self.assertEqual(self.send_count(), 1)

    def test_foreign_proof_and_json_error_are_not_archived(self):
        job = self.run_job(enqueue(self.a, self.letter, "EDOR"))
        for mode in ["foreign", "json"]:

            def wrong(request):
                if mode == "foreign" and request.url.path.endswith("/messages/message-test/evidences"):
                    return httpx.Response(
                        200,
                        json={"evidences": [{"evidenceId": "wrong", "type": "E.1", "messageId": "foreign"}]},
                    )
                if mode == "json" and "/evidences/purde/" in request.url.path:
                    return httpx.Response(200, json={"error": "should not count as evidence"})
                return self.mock(request)

            IntegrationJob.objects.filter(pk=job.pk).update(status="MONITORING", next_attempt_at=None)
            job = process_job(job, transport=httpx.MockTransport(wrong))
            self.assertEqual(job.status, "REVIEW_REQUIRED" if mode == "foreign" else "RETRY")
            self.assertEqual(job.evidence.count(), 0)

    def test_inactive_or_nonpublic_address_prevents_send(self):
        for public in [True, False]:
            with EDorClient(
                load_profile("a"),
                transport=httpx.MockTransport(
                    lambda r: (
                        self.mock(r)
                        if r.url.path.endswith("/token")
                        else httpx.Response(
                            200,
                            json={
                                "recipientEda": {
                                    "recipientEda": RECIPIENT,
                                    "edaStatus": "STRUCK_OFF",
                                    "assignmentDegree": 3,
                                },
                                "recipient": {"isPublic": public},
                            },
                        )
                    )
                ),
            ) as client:
                with self.assertRaises(ConnectorError):
                    client.confirm_address(RECIPIENT)
        self.assertEqual(self.send_count(), 0)

    def test_config_target_change_and_stale_worker_stop(self):
        job = enqueue(self.a, self.letter, "EDOR")
        self.profile_config["ua_url"] = "https://other.test.invalid/api/v3"
        self.write_config()
        job = self.run_job(job)
        self.assertEqual(job.status, "REVIEW_REQUIRED")
        self.assertEqual(self.calls, [])
        IntegrationJob.objects.filter(pk=job.pk).update(
            status="PROCESSING", claimed_until=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(recover_stale_jobs(), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, "REVIEW_REQUIRED")

    def test_configuration_rejects_public_key_files_http_and_old_api(self):
        self.config_file.chmod(0o644)
        with self.assertRaises(ConnectorError):
            load_profile("a")
        self.write_config()
        for value in ["http://ua.test.invalid/api/v3", "https://ua.test.invalid/api/v1"]:
            self.profile_config["ua_url"] = value
            self.write_config()
            with self.assertRaises(ConnectorError):
                load_profile("a")

    def test_roles_ui_and_download_integrity(self):
        with self.assertRaises(ValidationError):
            enqueue(self.b, self.letter, "EDOR")
        with self.assertRaises(PermissionDenied):
            enqueue(self.admin, self.letter, "EDOR")
        job = enqueue(self.a, self.letter, "EDOR")
        proof = DeliveryEvidence.objects.create(
            job=job,
            remote_id="synthetic",
            kind="A.1",
            content=b"%PDF-TEST",
            sha256=hashlib.sha256(b"%PDF-TEST").hexdigest(),
        )
        url = reverse("delivery_evidence", args=[self.letter.uuid, proof.pk])
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.a)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"%PDF-TEST")
        self.assertEqual(response.headers["X-Content-SHA256"], proof.sha256)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertTrue(AuditLog.objects.filter(action="edor.evidence.downloaded").exists())
        proof.content = b"tampered"
        proof.save()
        self.assertEqual(self.client.get(url).status_code, 409)
        self.client.force_login(self.ump)
        self.assertContains(self.client.get(reverse("edor_search")), "Nie skonfigurowano")

    def test_lookup_csrf_and_live_profile_unavailable_does_not_call_network(self):
        self.client.force_login(self.a)
        with patch(
            "registry.connectors.edor.EDorClient.search_public", return_value={"rows": [], "total": 0}
        ) as search:
            response = self.client.post(reverse("edor_search"), {"entity_name": "UMP", "offset": 0})
            self.assertEqual(response.status_code, 200)
            search.assert_called_once_with(entity_name="UMP", offset=0)
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.a)
        self.assertEqual(
            client.post(reverse("edor_search"), {"entity_name": "UMP", "offset": 0}).status_code, 403
        )
        with self.settings(EDOR_CONFIG_FILE=""):
            response = self.client.post(
                reverse("letter_send", args=[self.letter.uuid]), {"provider": "EDOR"}, follow=True
            )
            self.assertContains(response, "Nie skonfigurowano e-Doręczeń dla tego urzędu.")
            self.assertNotContains(response, "['Nie skonfigurowano")
            self.assertFalse(IntegrationJob.objects.filter(provider="EDOR").exists())

    def test_token_unauthorized_has_safe_error_and_invalidates_cache(self):
        with EDorClient(
            load_profile("a"),
            transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "secret"})),
        ) as client:
            with self.assertRaises(ConnectorError) as error:
                client.authenticate()
        self.assertNotIn("secret", str(error.exception))
        self.assertEqual(TOKEN_CACHE, {})

    def test_missing_task_id_after_success_requires_review(self):
        def missing(request):
            if request.url.path.endswith("/messages"):
                return httpx.Response(202, json={"messageId": "not-a-task-id"})
            return self.mock(request)

        job = process_job(enqueue(self.a, self.letter, "EDOR"), transport=httpx.MockTransport(missing))
        self.assertEqual(job.status, "REVIEW_REQUIRED")
        self.assertEqual(job.result["steps"]["send"]["state"], "IN_FLIGHT")
        self.assertNotIn("EZD", job.error)

    def test_remote_message_of_other_sender_does_not_archive_proofs(self):
        job = self.run_job(enqueue(self.a, self.letter, "EDOR"))

        def foreign(request):
            if request.url.path.endswith("/messages/message-test"):
                result = self.mock(request).json()
                result[0]["messageMetadata"]["from"]["eDeliveryAddress"] = RECIPIENT
                return httpx.Response(200, json=result)
            return self.mock(request)

        IntegrationJob.objects.filter(pk=job.pk).update(next_attempt_at=None)
        job = process_job(job, transport=httpx.MockTransport(foreign))
        self.assertEqual(job.status, "REVIEW_REQUIRED")
        self.assertEqual(job.evidence.count(), 0)

    def test_lookup_rate_limit_and_missing_profile_do_not_call_api(self):
        self.client.force_login(self.a)
        with (
            patch("registry.views.rate_limit", return_value=False),
            patch("registry.connectors.edor.EDorClient.search_public") as search,
        ):
            self.assertContains(
                self.client.post(reverse("edor_search"), {"entity_name": "UMP", "offset": 0}),
                "Limit wyszukiwań",
            )
            search.assert_not_called()
        self.client.force_login(self.b)
        with patch("registry.connectors.edor.EDorClient.search_public") as search:
            self.assertContains(
                self.client.post(reverse("edor_search"), {"entity_name": "UMP", "offset": 0}),
                "Nie skonfigurowano",
            )
            search.assert_not_called()

    def unsent_job(self):
        job = enqueue(self.a, self.letter, "EDOR")
        with self.settings(EDOR_CONFIG_FILE=""):
            job = process_job(job, transport=self.transport)
        self.assertEqual(job.status, "CONFIG_ERROR")
        return job

    def test_resume_unsent_after_config_repair_preserves_job_and_sends_once(self):
        job = self.unsent_job()
        original = (job.pk, bytes(job.payload), job.payload_sha256, job.result.copy())
        self.letter.signed_pdf = b"%PDF-LATER-VERSION"
        self.letter.save(update_fields=["signed_pdf"])
        resumed = resume_edor_unsent(
            self.admin,
            job.uuid,
            reason="Naprawiono profil",
            transport=self.transport,
            ip="192.0.2.40",
        )
        self.assertEqual(AuditLog.objects.get(action="edor.unsent.resumed").ip, "192.0.2.40")
        self.assertEqual((resumed.pk, bytes(resumed.payload), resumed.payload_sha256), original[:3])
        self.assertEqual(resumed.result["recipient_ade"], original[3]["recipient_ade"])
        self.assertEqual(resumed.attempts, 1)
        self.assertEqual(resumed.status, "QUEUED")
        self.assertEqual(self.send_count(), 0)
        self.assertEqual(IntegrationJob.objects.count(), 1)
        self.assertTrue(
            AuditLog.objects.filter(action="edor.unsent.resumed", reason="Naprawiono profil").exists()
        )
        resumed = self.run_job(resumed)
        self.assertEqual(resumed.status, "MONITORING")
        self.assertEqual(self.send_count(), 1)

    def test_definite_http_rejection_has_proof_and_can_resume_same_job(self):
        for status in (400, 401, 403):
            with self.subTest(status=status):
                IntegrationJob.objects.all().delete()
                self.calls.clear()
                job = enqueue(self.a, self.letter, "EDOR")

                def rejected(request):
                    if request.url.path.endswith("/messages"):
                        self.calls.append(request)
                        return httpx.Response(status, json={"error": "private operator text"})
                    return self.mock(request)

                job = process_job(job, transport=httpx.MockTransport(rejected))
                self.assertEqual(job.result["steps"]["send"]["state"], "NOT_ACCEPTED")
                self.assertEqual(edor_resume_mode(job), "UNSENT")
                self.assertNotIn("private operator text", job.error)
                job = resume_edor_unsent(self.admin, job.uuid, reason="Naprawa", transport=self.transport)
                self.assertEqual(self.send_count(), 1)  # odmowa; wznowienie nie wykonało drugiego POST
                self.assertEqual(self.run_job(job).status, "MONITORING")
                self.assertEqual(self.send_count(), 2)

    def test_uncertain_transport_http_and_success_without_id_cannot_resume_send(self):
        cases = ["read-timeout", "write-timeout", 408, 409, 500, 404, "missing-id"]
        for failure in cases:
            with self.subTest(failure=failure):
                IntegrationJob.objects.all().delete()
                job = enqueue(self.a, self.letter, "EDOR")

                def uncertain(request):
                    if request.url.path.endswith("/messages"):
                        if failure == "read-timeout":
                            raise httpx.ReadTimeout("synthetic", request=request)
                        if failure == "write-timeout":
                            raise httpx.WriteTimeout("synthetic", request=request)
                        if failure == "missing-id":
                            return httpx.Response(202, json={})
                        return httpx.Response(failure)
                    return self.mock(request)

                job = process_job(job, transport=httpx.MockTransport(uncertain))
                self.assertEqual(job.result["steps"]["send"]["state"], "IN_FLIGHT")
                self.assertEqual(edor_resume_mode(job), "")
                before_calls = len(self.calls)
                with self.assertRaises(ValidationError):
                    resume_edor_unsent(self.admin, job.uuid, reason="Naprawa", transport=self.transport)
                self.assertEqual(len(self.calls), before_calls)

    def test_connection_failure_is_definite_but_legacy_checkpoint_is_not(self):
        job = enqueue(self.a, self.letter, "EDOR")

        def disconnected(request):
            if request.url.path.endswith("/messages"):
                raise httpx.ConnectError("synthetic", request=request)
            return self.mock(request)

        job = process_job(job, transport=httpx.MockTransport(disconnected))
        self.assertEqual(job.result["steps"]["send"]["state"], "NOT_ACCEPTED")
        job.status = "RETRY_EXHAUSTED"
        job.result["steps"]["send"] = {"state": "NOT_COMPLETED", "output": {}}
        job.save()
        with self.assertRaises(ValidationError):
            resume_edor_unsent(self.admin, job.uuid, reason="Stary zapis", transport=self.transport)
        job.status = "RETRY"
        job.next_attempt_at = None
        job.save()
        self.calls.clear()
        job = process_job(job, transport=self.transport)
        self.assertEqual(job.status, "REVIEW_REQUIRED")
        self.assertEqual(self.calls, [])

    def test_unsent_resume_rejects_restore_marker_remote_evidence_and_corrupt_pdf(self):
        job = self.unsent_job()
        original = job.result.copy()
        for extra in (
            {"restore_requires_reconciliation": True},
            {"submission_guard_version": None},
            {"task_id": "known-task"},
            {"steps": {"send": {"state": "NOT_ACCEPTED", "output": {}}}},
            {"steps": {"send": {}}},
            {"steps": {"send": []}},
        ):
            with self.subTest(extra=extra):
                job.result = {**original, **extra}
                job.save()
                with self.assertRaises(ValidationError):
                    resume_edor_unsent(self.admin, job.uuid, reason="Kontrola", transport=self.transport)
        job.result = original
        job.payload = b"%PDF-TAMPERED"
        job.save()
        with self.assertRaises(ValidationError):
            resume_edor_unsent(self.admin, job.uuid, reason="Kontrola", transport=self.transport)
        job.payload = bytes(self.letter.pdf)
        job.save()
        DeliveryEvidence.objects.create(
            job=job,
            remote_id="known-evidence",
            kind="A.1",
            content=b"test",
            sha256=hashlib.sha256(b"test").hexdigest(),
        )
        with self.assertRaises(ValidationError):
            resume_edor_unsent(self.admin, job.uuid, reason="Kontrola", transport=self.transport)
        self.assertEqual(self.calls, [])

    def test_resume_does_not_retarget_or_send_from_disabled_office(self):
        job = self.unsent_job()
        self.ump.office.ade = "AE:PL-33333-33333-CCCCC-33"
        self.ump.office.save()
        with self.assertRaises(ValidationError):
            resume_edor_unsent(self.admin, job.uuid, reason="Zmiana odbiorcy", transport=self.transport)
        self.ump.office.ade = RECIPIENT
        self.ump.office.save()
        self.profile_config["environment"] = "PROD"
        self.write_config()
        with self.assertRaises(ValidationError):
            resume_edor_unsent(self.admin, job.uuid, reason="Inny profil", transport=self.transport)
        self.profile_config["environment"] = "INT"
        self.write_config()
        self.a.office.active = False
        self.a.office.save()
        with self.assertRaises(ValidationError):
            resume_edor_unsent(self.admin, job.uuid, reason="Wyłączony urząd", transport=self.transport)
        self.assertEqual(self.calls, [])

    def test_resume_detects_job_and_office_change_during_preflight(self):
        job = self.unsent_job()
        for mutation in ("job", "office"):
            with self.subTest(mutation=mutation):

                def changed(request):
                    response = self.mock(request)
                    if request.url.path.endswith("/eda-confirmation"):
                        if mutation == "job":
                            IntegrationJob.objects.filter(pk=job.pk).update(updated_at=timezone.now())
                        else:
                            self.ump.office.active = False
                            self.ump.office.save()
                    return response

                with self.assertRaises(ValidationError):
                    resume_edor_unsent(
                        self.admin, job.uuid, reason="Naprawa", transport=httpx.MockTransport(changed)
                    )
        job.refresh_from_db()
        self.assertEqual(job.status, "CONFIG_ERROR")
        self.assertFalse(AuditLog.objects.filter(action="edor.unsent.resumed").exists())
        self.assertEqual(self.send_count(), 0)

    def test_admin_form_requires_csrf_reason_and_current_version(self):
        job = self.unsent_job()
        url = reverse("edor_resume", args=[job.uuid])
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        page = client.get(url)
        self.assertContains(page, "Przywróć zlecenie do kolejki")
        self.assertNotContains(page, self.letter.body)
        self.assertEqual(self.calls, [])
        values = {"mode": "UNSENT", "expected_updated_at": job.updated_at.isoformat(), "reason": "Naprawa"}
        self.assertEqual(client.post(url, values).status_code, 403)
        values["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
        values["reason"] = "   "
        self.assertContains(client.post(url, values), "To pole jest wymagane")
        values["reason"] = "Naprawa"
        IntegrationJob.objects.filter(pk=job.pk).update(updated_at=timezone.now())
        self.assertContains(client.post(url, values), "Stan operacji zmienił się")
        job.refresh_from_db()
        values["expected_updated_at"] = job.updated_at.isoformat()
        with patch(
            "registry.edor_delivery.EDorClient",
            side_effect=lambda p, **kw: EDorClient(p, transport=self.transport),
        ):
            self.assertRedirects(
                client.post(url, values, REMOTE_ADDR="2001:db8::50"), reverse("integrations")
            )
        job.refresh_from_db()
        self.assertEqual(job.status, "QUEUED")
        self.assertEqual(self.send_count(), 0)
        self.assertEqual(AuditLog.objects.get(action="edor.unsent.resumed").ip, "2001:db8::50")

    def test_admin_observation_form_keeps_ip_without_sending_again(self):
        job = self.run_job(enqueue(self.a, self.letter, "EDOR"))
        IntegrationJob.objects.filter(pk=job.pk).update(status="RETRY_EXHAUSTED")
        job.refresh_from_db()
        url = reverse("edor_resume", args=[job.uuid])
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.get(url).status_code, 200)
        values = {
            "mode": "OBSERVATION",
            "expected_updated_at": job.updated_at.isoformat(),
            "reason": "Odbiór audytu obserwacji",
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        }
        with patch(
            "registry.edor_delivery.EDorClient",
            side_effect=lambda p, **kw: EDorClient(p, transport=self.transport),
        ):
            self.assertRedirects(client.post(url, values, REMOTE_ADDR="192.0.2.50"), reverse("integrations"))
        job.refresh_from_db()
        self.assertEqual(job.status, "MONITORING")
        self.assertEqual(self.send_count(), 1)
        self.assertEqual(AuditLog.objects.get(action="edor.observation.resumed").ip, "192.0.2.50")

    def test_maintenance_roles_cannot_requeue_and_unknown_job_is_not_found(self):
        job = self.unsent_job()
        url = reverse("edor_resume", args=[job.uuid])
        for actor in (self.a, self.ump, self.b):
            self.client.force_login(actor)
            denied = self.client.get(url)
            self.assertContains(denied, "Brak uprawnień", status_code=403)
            # The session extension form may echo the caller's URL. It must
            # not turn the denied business page into a view of the job.
            main = re.search(r"<main\b[^>]*>(.*?)</main>", denied.content.decode(), re.S).group(1)
            self.assertNotIn(str(job.uuid), main)
            self.assertIsNone(denied.context.get("job"))
            self.assertNotContains(denied, self.letter.body, status_code=403)
            self.assertEqual(self.client.post(url, {"reason": "Naprawa"}).status_code, 403)
            with self.assertRaises(PermissionDenied):
                resume_edor_unsent(actor, job.uuid, reason="Naprawa", transport=self.transport)
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(
                reverse("edor_resume", args=["00000000-0000-0000-0000-000000000000"])
            ).status_code,
            404,
        )
        self.assertEqual(self.calls, [])

    def test_observation_rejects_malformed_or_busy_state_before_io(self):
        job = self.unsent_job()
        for result in ([], {"steps": []}, {"steps": {"send": {"state": "COMPLETED", "output": []}}}):
            with self.subTest(result=result):
                job.result = result
                job.save()
                with self.assertRaises(ValidationError):
                    resume_edor_observation(self.admin, job.uuid, reason="Odczyt", transport=self.transport)
        job.result = {"steps": {"send": {"state": "COMPLETED", "output": {"task_id": "known-task"}}}}
        job.claimed_until = timezone.now() + timedelta(minutes=1)
        job.save()
        with self.assertRaises(ValidationError):
            resume_edor_observation(self.admin, job.uuid, reason="Odczyt", transport=self.transport)
        self.assertEqual(self.calls, [])

    def test_uncertain_job_has_no_action_and_observation_mode_never_resends(self):
        job = self.run_job(enqueue(self.a, self.letter, "EDOR"))
        job.status = "REVIEW_REQUIRED"
        job.result["restore_requires_reconciliation"] = True
        job.save()
        self.client.force_login(self.admin)
        url = reverse("edor_resume", args=[job.uuid])
        page = self.client.get(url)
        self.assertContains(page, "Wznów obserwację")
        self.assertNotContains(page, "Przywróć zlecenie do kolejki")
        values = {
            "mode": "OBSERVATION",
            "expected_updated_at": job.updated_at.isoformat(),
            "reason": "Odczyt",
        }
        with patch(
            "registry.edor_delivery.EDorClient",
            side_effect=lambda p, **kw: EDorClient(p, transport=self.transport),
        ):
            self.assertRedirects(self.client.post(url, values), reverse("integrations"))
        self.assertEqual(self.send_count(), 1)
        job.refresh_from_db()
        job.status = "REVIEW_REQUIRED"
        job.result["steps"]["send"] = {"state": "IN_FLIGHT", "output": {}}
        job.save()
        page = self.client.get(url)
        self.assertContains(page, "Brak podstaw do bezpiecznego wznowienia")
        self.assertEqual(page.context["mode"], "")
        main = re.search(r"<main\b[^>]*>(.*?)</main>", page.content.decode(), re.S).group(1)
        self.assertNotIn("<form", main)
        before = (job.status, job.result, job.updated_at, AuditLog.objects.count())
        values.update(mode="UNSENT", expected_updated_at=job.updated_at.isoformat())
        self.assertContains(self.client.post(url, values), "Stan operacji nie pozwala")
        job.refresh_from_db()
        self.assertEqual((job.status, job.result, job.updated_at, AuditLog.objects.count()), before)
        self.assertEqual(self.send_count(), 1)

    def test_cli_requeues_same_job_without_submission_and_rejects_wrong_actor(self):
        from io import StringIO

        job = self.unsent_job()
        with self.assertRaises(CommandError):
            call_command("resume_edor_unsent", str(job.uuid), actor=self.a.email, reason="Naprawa")
        with patch(
            "registry.edor_delivery.EDorClient",
            side_effect=lambda p, **kw: EDorClient(p, transport=self.transport),
        ):
            output = StringIO()
            call_command(
                "resume_edor_unsent", str(job.uuid), actor=self.admin.email, reason="Naprawa", stdout=output
            )
        self.assertIn(str(job.uuid), output.getvalue())
        self.assertEqual(self.send_count(), 0)
        job.refresh_from_db()
        self.assertEqual(job.status, "QUEUED")

    def test_expired_worker_cannot_submit_or_overwrite_a_resumed_attempt(self):
        job = enqueue(self.a, self.letter, "EDOR")

        def paused(request):
            response = self.mock(request)
            if request.url.path.endswith("/eda-confirmation"):
                IntegrationJob.objects.filter(pk=job.pk).update(
                    claimed_until=timezone.now() - timedelta(seconds=1)
                )
                self.assertEqual(recover_stale_jobs(), 1)
                resumed = resume_edor_unsent(
                    self.admin, job.uuid, reason="Po przerwaniu", transport=self.transport
                )
                self.assertEqual(self.run_job(resumed).status, "MONITORING")
            return response

        returned = process_job(job, transport=httpx.MockTransport(paused))
        self.assertEqual(returned.status, "MONITORING")
        self.assertEqual(returned.result["steps"]["send"]["state"], "COMPLETED")
        self.assertEqual(returned.result["steps"]["send"]["output"]["task_id"], "task-test")
        self.assertEqual(returned.attempts, 2)
        self.assertEqual(self.send_count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="integration.worker.superseded").exists())


class EDorWorkerConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_parked_worker_loses_submission_right_after_recovery_and_new_claim(self):
        admin, ump, county, _ = fixtures()
        county.office.ade, ump.office.ade = SENDER, RECIPIENT
        county.office.save()
        ump.office.save()
        letter = create_request(county, data()).letters.get()
        profile = SimpleNamespace(target_hash="a" * 64, sender_ade=SENDER, environment="INT")
        with patch("registry.edor_delivery.load_profile", return_value=profile):
            job = enqueue(county, letter, "EDOR")
        parked, release = Event(), Event()
        confirmations, submissions = [], []

        class ControlledClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def authenticate(self):
                pass

            def confirm_address(self, address):
                confirmations.append(address)
                if len(confirmations) == 1:
                    parked.set()
                    if not release.wait(timeout=10):
                        raise AssertionError("Nie wznowiono zaparkowanego pracownika.")
                return {"ade": address}

            def send_message(self, **kwargs):
                submissions.append(kwargs["payload"])
                return {"task_id": "new-attempt-task"}

        def old_worker():
            close_old_connections()
            try:
                return process_job(job).status
            finally:
                close_old_connections()

        with (
            patch("registry.edor_delivery.load_profile", return_value=profile),
            patch("registry.edor_delivery.EDorClient", ControlledClient),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            future = executor.submit(old_worker)
            try:
                self.assertTrue(parked.wait(timeout=5))
                IntegrationJob.objects.filter(pk=job.pk).update(
                    claimed_until=timezone.now() - timedelta(seconds=1)
                )
                self.assertEqual(recover_stale_jobs(), 1)
                resumed = resume_edor_unsent(admin, job.uuid, reason="Po przerwaniu")
                self.assertEqual(process_job(resumed).status, "MONITORING")
            finally:
                release.set()
            self.assertEqual(future.result(timeout=5), "MONITORING")
        job.refresh_from_db()
        self.assertEqual(job.status, "MONITORING")
        self.assertEqual(job.result["steps"]["send"]["output"]["task_id"], "new-attempt-task")
        self.assertEqual(job.attempts, 2)
        self.assertEqual(submissions, [bytes(letter.pdf)])

    @skipUnlessDBFeature("has_select_for_update")
    def test_two_administrators_resume_one_unsent_job_once(self):
        admin, ump, county, _ = fixtures()
        county.office.ade, ump.office.ade = SENDER, RECIPIENT
        county.office.save()
        ump.office.save()
        letter = create_request(county, data()).letters.get()
        profile = SimpleNamespace(target_hash="a" * 64, sender_ade=SENDER, environment="INT")
        with patch("registry.edor_delivery.load_profile", return_value=profile):
            job = enqueue(county, letter, "EDOR")
        job.status = "CONFIG_ERROR"
        job.save()
        preflight = Barrier(2)

        class ReadOnlyClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def authenticate(self):
                pass

            def confirm_address(self, address):
                preflight.wait(timeout=5)
                return {"ade": address}

            def send_message(self, **kwargs):
                raise AssertionError("Wznowienie nie może wysyłać wiadomości.")

        def resume():
            close_old_connections()
            try:
                try:
                    result = resume_edor_unsent(admin, job.uuid, reason="Równoczesna naprawa")
                    return result.status
                except ValidationError:
                    return "STALE"
            finally:
                close_old_connections()

        with (
            patch("registry.edor_delivery.load_profile", return_value=profile),
            patch("registry.edor_delivery.EDorClient", ReadOnlyClient),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            futures = [executor.submit(resume) for _ in range(2)]
            results = [future.result(timeout=10) for future in futures]
        self.assertCountEqual(results, ["QUEUED", "STALE"])
        job.refresh_from_db()
        self.assertEqual(job.status, "QUEUED")
        self.assertEqual(job.attempts, 0)
        self.assertEqual(AuditLog.objects.filter(action="edor.unsent.resumed").count(), 1)

    def test_two_workers_claim_one_job_once(self):
        _, _, county, _ = fixtures()
        letter = create_request(county, data()).letters.get()
        job = IntegrationJob.objects.create(
            letter=letter,
            provider="EDOR",
            key="EDOR:concurrency:SEND",
            payload=bytes(letter.pdf),
            payload_sha256=hashlib.sha256(bytes(letter.pdf)).hexdigest(),
        )
        start, active, second_done = Barrier(2), Event(), Event()
        executions = []

        def external_operation(current, **kwargs):
            executions.append(current.pk)
            active.set()
            if not second_done.wait(timeout=5):
                raise AssertionError("Drugi pracownik nie odczytał zajętego zadania.")
            return "MONITORING"

        def worker():
            close_old_connections()
            try:
                start.wait(timeout=5)
                result = process_job(job)
                if result.status == "PROCESSING":
                    second_done.set()
                return result.status
            finally:
                close_old_connections()

        with patch("registry.edor_delivery.process_edor", side_effect=external_operation):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(worker) for _ in range(2)]
                results = [future.result(timeout=10) for future in futures]
        self.assertTrue(active.is_set())
        self.assertEqual(executions, [job.pk])
        self.assertCountEqual(results, ["PROCESSING", "MONITORING"])
        job.refresh_from_db()
        self.assertEqual(job.attempts, 1)
