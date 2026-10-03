"""Rzeczywiste podpisy kryptograficzne na syntetycznej CA; nie podpisy kwalifikowane."""

import hashlib
import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from io import BytesIO
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from pyhanko.pdf_utils import generic
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

from .backup_integrity import verify_document_hashes
from .documents import document_payload
from .integrations import enqueue
from .models import AuditLog, Letter
from .services import create_letter_revision, create_request, decide_request, send_request
from .signatures import load_profile, local_sign, sign_letter, verify_signed_pdf
from .tests import data, fixtures


class SignatureTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(dt_timezone.utc)
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Dyna FIKCYJNA CA TESTOWA")])
        cls.ca = (
            x509.CertificateBuilder()
            .subject_name(ca_name)
            .issuer_name(ca_name)
            .public_key(cls.ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=False,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(cls.ca_key.public_key()), critical=False)
            .sign(cls.ca_key, hashes.SHA256())
        )
        cls.cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Podpis TESTOWY Urząd A")]))
            .issuer_name(ca_name)
            .public_key(cls.key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=True,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(cls.ca_key.public_key()), critical=False
            )
            .add_extension(
                x509.CRLDistributionPoints(
                    [
                        x509.DistributionPoint(
                            full_name=[
                                x509.UniformResourceIdentifier("https://test.invalid/not-fetched.crl")
                            ],
                            relative_name=None,
                            reasons=None,
                            crl_issuer=None,
                        )
                    ]
                ),
                critical=False,
            )
            .sign(cls.ca_key, hashes.SHA256())
        )
        cls.crl = (
            x509.CertificateRevocationListBuilder()
            .issuer_name(ca_name)
            .last_update(now - timedelta(minutes=1))
            .next_update(now + timedelta(days=1))
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(cls.ca_key.public_key()), critical=False
            )
            .sign(cls.ca_key, hashes.SHA256())
        )

    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        self.letter = create_request(self.a, data()).letters.get()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        self.files = {}
        for name, content in {
            "key": self.key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            ),
            "cert": self.cert.public_bytes(serialization.Encoding.PEM),
            "ca": self.ca.public_bytes(serialization.Encoding.PEM),
            "crl": self.crl.public_bytes(serialization.Encoding.PEM),
        }.items():
            path = directory / f"{name}.pem"
            path.write_bytes(content)
            path.chmod(0o600)
            self.files[name] = str(path)
        self.config = {
            "mode": "DEMO",
            "authorized_users": [self.a.email],
            "allowed_certificate_fingerprints": [
                hashlib.sha256(self.cert.public_bytes(serialization.Encoding.DER)).hexdigest()
            ],
            "trust_root_files": [self.files["ca"]],
            "chain_files": [self.files["ca"]],
            "seal": {"key_file": self.files["key"], "certificate_file": self.files["cert"]},
        }
        self.config_file = directory / "config.json"
        self.write_config()
        setting = self.settings(SIGNING_CONFIG_FILE=str(self.config_file))
        setting.enable()
        self.addCleanup(setting.disable)

    def write_config(self):
        self.config_file.write_text(json.dumps({"offices": {"a": self.config}}))
        self.config_file.chmod(0o600)

    def signed_bytes(self):
        return local_sign(bytes(self.letter.pdf), load_profile("a"), reason="Test zgodności")

    def test_real_pades_signature_and_archive_preserves_original(self):
        original = bytes(self.letter.pdf)
        letter = sign_letter(self.a, self.letter, reason="Test podpisania pisma")
        self.assertEqual(letter.signature_status, "TEST_SIGNED")
        self.assertEqual(bytes(letter.pdf), original)
        self.assertTrue(bytes(letter.signed_pdf).startswith(original))
        self.assertEqual(letter.signed_sha256, hashlib.sha256(bytes(letter.signed_pdf)).hexdigest())
        self.assertEqual(letter.signature_report["qualification"], "NOT_ASSESSED")
        result = letter.signature_report["signatures"][0]
        self.assertTrue(result["valid"])
        self.assertTrue(result["intact"])
        self.assertEqual(result["coverage"], "ENTIRE_FILE")
        self.assertTrue(letter.signature_report["original_content_unchanged"])
        self.assertTrue(AuditLog.objects.filter(action="letter.signed").exists())

    def test_decision_notice_does_not_prevent_signing_the_official_reply(self):
        from .integrations import process_job
        from .models import IntegrationJob

        req = create_request(
            self.a,
            {
                "kind": "III",
                "case_number": "TEST/SIGN/III",
                "count": 2,
                "justification": "Fikcyjne zapotrzebowanie",
            },
        )
        send_request(self.a, req.uuid)
        decide_request(self.ump, req.uuid, False, reason="Fikcyjna odmowa")
        job = IntegrationJob.objects.get(operation="DECISION_NOTICE")
        original_snapshot = bytes(job.payload)
        self.config["authorized_users"] = [self.ump.email]
        self.config_file.write_text(json.dumps({"offices": {"ump": self.config}}))
        self.client.force_login(self.ump)
        page = self.client.get(reverse("letter_sign", args=[job.letter.uuid]))
        self.assertFalse(page.context["locked"])
        signed = sign_letter(self.ump, job.letter, reason="Test pisma po powiadomieniu")
        self.assertEqual(signed.signature_status, "TEST_SIGNED")
        with self.settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            self.assertEqual(process_job(job).status, "ACCEPTED")
        job.refresh_from_db()
        self.assertEqual(bytes(job.payload), original_snapshot)

    def test_import_valid_signed_original_without_private_key(self):
        signed = self.signed_bytes()
        self.config.pop("seal")
        self.write_config()
        letter = sign_letter(self.a, self.letter, uploaded=signed, reason="Import podpisanego oryginału")
        self.assertEqual(bytes(letter.signed_pdf), signed)

    def test_offline_hard_fail_with_valid_ca_and_crl(self):
        self.config.update(mode="LOCAL_PEM", crl_files=[self.files["crl"]])
        self.write_config()
        letter = sign_letter(self.a, self.letter, reason="Kontrola certyfikatu i CRL")
        self.assertEqual(letter.signature_status, "VERIFIED_SIGNED")
        self.assertEqual(letter.signature_report["revocation_policy"], "OFFLINE_HARD_FAIL")
        self.assertEqual(letter.signature_report["qualification"], "NOT_ASSESSED")

    def test_offline_hard_fail_without_revocation_data_rejects(self):
        self.config["mode"] = "LOCAL_PEM"
        self.write_config()
        with self.assertRaises(ValidationError):
            sign_letter(self.a, self.letter, reason="Brak danych unieważnienia")
        self.letter.refresh_from_db()
        self.assertIsNone(self.letter.signed_pdf)

    def test_changed_bytes_uncovered_tail_and_unsigned_file_reject(self):
        signed = self.signed_bytes()
        for payload in [
            signed + b"\nUNSIGNED TAIL",
            signed.replace(b"%PDF-1.4", b"%PDF-1.5", 1),
            bytes(self.letter.pdf),
        ]:
            with self.subTest(length=len(payload)):
                with self.assertRaises(ValidationError):
                    verify_signed_pdf(payload, bytes(self.letter.pdf), load_profile("a"))

    def test_original_with_modified_title_signed_validly_is_rejected(self):
        original = bytes(self.letter.pdf)
        writer = IncrementalPdfFileWriter(BytesIO(original))
        writer.root[generic.pdf_name("/PageMode")] = generic.pdf_name("/FullScreen")
        writer.update_root()
        output = BytesIO()
        writer.write(output)
        modified_signed = local_sign(output.getvalue(), load_profile("a"), reason="Podmieniona rewizja")
        self.assertTrue(modified_signed.startswith(original))
        with self.assertRaises(ValidationError):
            verify_signed_pdf(modified_signed, original, load_profile("a"))

    def test_unauthorized_certificate_and_users_cannot_sign(self):
        signed = self.signed_bytes()
        self.config["allowed_certificate_fingerprints"] = ["0" * 64]
        self.write_config()
        with self.assertRaises(ValidationError):
            verify_signed_pdf(signed, bytes(self.letter.pdf), load_profile("a"))
        for user in [self.b, self.ump, self.admin]:
            with self.assertRaises(PermissionDenied):
                sign_letter(user, self.letter, uploaded=signed, reason="Niedozwolone")

    def test_resigning_and_signing_queued_letter_are_blocked(self):
        signed = sign_letter(self.a, self.letter, reason="Pierwszy podpis")
        with self.assertRaises(ValidationError):
            sign_letter(self.a, signed, reason="Drugi podpis")
        other = create_request(self.a, data("P1TEST")).letters.get()
        enqueue(self.a, other, "SMTP")
        with self.assertRaises(ValidationError):
            sign_letter(self.a, other, reason="Podpis po wysyłce")

    def test_public_config_and_demo_in_production_are_rejected(self):
        self.config_file.chmod(0o644)
        with self.assertRaises(ValidationError):
            load_profile("a")
        self.write_config()
        with self.settings(LOCAL=False):
            with self.assertRaises(ValidationError):
                load_profile("a")

    def test_valid_signature_over_changed_page_contents_is_rejected(self):
        original = bytes(self.letter.pdf)
        writer = IncrementalPdfFileWriter(BytesIO(original))
        page_ref, _ = writer.find_page_for_modification(0)
        page = page_ref.get_object()
        page[generic.pdf_name("/Contents")] = writer.add_object(
            generic.StreamObject(stream_data=b"BT /F1 12 Tf 40 400 Td (CHANGED CONTENT) Tj ET")
        )
        writer.mark_update(page_ref)
        output = BytesIO()
        writer.write(output)
        payload = local_sign(output.getvalue(), load_profile("a"), reason="Zmiana treści")
        with self.assertRaises(ValidationError):
            verify_signed_pdf(payload, original, load_profile("a"))

    def test_revoked_certificate_is_rejected_with_real_crl(self):
        now = datetime.now(dt_timezone.utc)
        revoked = (
            x509.RevokedCertificateBuilder()
            .serial_number(self.cert.serial_number)
            .revocation_date(now - timedelta(minutes=2))
            .build()
        )
        response = (
            x509.CertificateRevocationListBuilder()
            .issuer_name(self.ca.subject)
            .last_update(now - timedelta(minutes=1))
            .next_update(now + timedelta(days=1))
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(self.ca_key.public_key()), critical=False
            )
            .add_revoked_certificate(revoked)
            .sign(self.ca_key, hashes.SHA256())
        )
        Path(self.files["crl"]).write_bytes(response.public_bytes(serialization.Encoding.PEM))
        self.config.update(mode="LOCAL_PEM", crl_files=[self.files["crl"]])
        self.write_config()
        with self.assertRaises(ValidationError):
            sign_letter(self.a, self.letter, reason="Certyfikat unieważniony")
        self.letter.refresh_from_db()
        self.assertIsNone(self.letter.signed_pdf)

    def test_stale_letter_queue_uses_latest_signed_document(self):
        stale = Letter.objects.get(pk=self.letter.pk)
        signed = sign_letter(self.a, self.letter, reason="Podpis przed kolejką")
        job = enqueue(self.a, stale, "SMTP")
        self.assertEqual(bytes(job.payload), bytes(signed.signed_pdf))
        self.assertEqual(job.payload_sha256, signed.signed_sha256)
        Letter.objects.filter(pk=signed.pk).update(signed_pdf=b"%PDF-TAMPERED")
        signed.refresh_from_db()
        with self.assertRaises(ValidationError):
            document_payload(signed)
        self.assertTrue(bytes(job.payload).startswith(bytes(signed.pdf)))

    def test_http_import_report_download_and_role_isolation(self):
        self.client.force_login(self.a)
        url = reverse("letter_sign", args=[self.letter.uuid])
        self.assertEqual(self.client.get(url).status_code, 200)
        payload = self.signed_bytes()
        response = self.client.post(
            url,
            {
                "method": "IMPORT",
                "reason": "Import testowy HTTP",
                "file": SimpleUploadedFile("signed.pdf", payload, content_type="application/pdf"),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(url), "Podpis testowy")
        pdf_url = reverse("letter_pdf", args=[self.letter.uuid])
        self.assertEqual(self.client.get(pdf_url).content, payload)
        self.assertEqual(self.client.get(pdf_url + "?original=1").content, bytes(self.letter.pdf))
        for user in [self.b, self.admin]:
            self.client.force_login(user)
            self.assertIn(self.client.get(url).status_code, [403, 404])
            self.assertIn(self.client.get(pdf_url).status_code, [403, 404])
        self.client.force_login(self.ump)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(pdf_url).status_code, 200)
        Letter.objects.filter(pk=self.letter.pk).update(signed_pdf=b"CORRUPTED")
        self.assertEqual(self.client.get(pdf_url).status_code, 409)

    def test_new_revision_preserves_signed_original_and_queue(self):
        signed = sign_letter(self.a, self.letter, reason="Archiwum")
        job = enqueue(self.a, signed, "SMTP")
        new = create_letter_revision(self.a, signed, "Nowa wersja")
        self.assertEqual(new.replaces, signed)
        self.assertEqual(new.body, signed.body)
        self.assertNotEqual(new.number, signed.number)
        self.assertIsNone(new.signed_pdf)
        signed.refresh_from_db()
        self.assertEqual(bytes(job.payload), bytes(signed.signed_pdf))
        with self.assertRaises(PermissionDenied):
            create_letter_revision(self.b, signed, "Obcy urząd")

    def test_demo_command_private_files_and_no_overwrite(self):
        from io import StringIO

        target = Path(self.temp.name) / "new-profile"
        call_command("create_demo_signing", email=self.a.email, directory=str(target), stdout=StringIO())
        self.assertEqual(target.stat().st_mode & 0o777, 0o700)
        for path in target.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.settings(SIGNING_CONFIG_FILE=str(target / "profile.json")):
            signed = sign_letter(self.a, self.letter, reason="Nowy profil DEMO")
            self.assertEqual(signed.signature_status, "TEST_SIGNED")
        with self.assertRaises(CommandError):
            call_command("create_demo_signing", email=self.a.email, directory=str(target), stdout=StringIO())

    def test_backup_integrity_rejects_tampered_signed_document(self):
        payload = self.signed_bytes()
        with sqlite3.connect(":memory:") as db:
            db.execute(
                "CREATE TABLE registry_letter (pdf BLOB,sha256 TEXT,signed_pdf BLOB,signed_sha256 TEXT)"
            )
            db.execute(
                "INSERT INTO registry_letter VALUES (?,?,?,?)",
                (
                    bytes(self.letter.pdf),
                    self.letter.sha256,
                    payload,
                    hashlib.sha256(payload).hexdigest(),
                ),
            )
            verify_document_hashes(db)
            db.execute("UPDATE registry_letter SET signed_pdf=?", (payload + b"tampered",))
            with self.assertRaises(CommandError):
                verify_document_hashes(db)
