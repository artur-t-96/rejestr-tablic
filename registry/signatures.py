"""PAdES: podpis lokalnym kluczem albo import podpisanej rewizji PDF.

Nie przypisujemy kwalifikowanego statusu na podstawie samego X.509/PAdES.
Certyfikaty i dane unieważnienia są konfigurowane jawnie, bez pobierania URL
z niezaufanego dokumentu i bez używania systemowych korzeni TLS.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone as datetime_timezone
from io import BytesIO

from asn1crypto import crl, keys, ocsp, pem
from asn1crypto import x509 as asn1x509
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from pyhanko.pdf_utils import generic
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.diff_analysis import DEFAULT_DIFF_POLICY, ModificationLevel
from pyhanko.sign.fields import SigSeedSubFilter
from pyhanko.sign.signers import PdfSignatureMetadata, PdfSigner, SimpleSigner
from pyhanko.sign.validation import KeyUsageConstraints, validate_pdf_signature
from pyhanko.sign.validation.status import SignatureCoverageLevel
from pyhanko_certvalidator import ValidationContext
from pyhanko_certvalidator.registry import SimpleCertificateStore
from pypdf import PdfReader

from .connectors.ezdrp import ConnectorError, private_text
from .documents import lock_letter
from .models import IntegrationJob
from .services import audit, require_role

MAX_SIGNED_PDF = 10 * 1024 * 1024


def secret_text(path):
    try:
        return private_text(path)
    except ConnectorError as exc:
        raise ValidationError(
            "Nie można odczytać prywatnej konfiguracji podpisu. Sprawdź ścieżki i uprawnienia plików."
        ) from exc


def certificates(paths):
    if not isinstance(paths, list) or len(paths) > 20:
        raise ValidationError("Lista certyfikatów podpisu musi zawierać do 20 plików PEM.")
    values = []
    for path in paths:
        for certificate in x509.load_pem_x509_certificates(secret_text(path).encode()):
            values.append(asn1x509.Certificate.load(certificate.public_bytes(serialization.Encoding.DER)))
    return values


@dataclass(frozen=True)
class SignatureProfile:
    mode: str
    allowed_users: tuple
    allowed_fingerprints: tuple
    roots: tuple = field(repr=False)
    chain: tuple = field(repr=False)
    crls: tuple = field(repr=False)
    ocsps: tuple = field(repr=False)
    seal: dict = field(default_factory=dict, repr=False)

    def validation_context(self):
        return ValidationContext(
            trust_roots=self.roots,
            other_certs=self.chain,
            crls=self.crls,
            ocsps=self.ocsps,
            allow_fetching=False,
            revocation_mode="soft-fail" if self.mode == "DEMO" else "hard-fail",
        )


def load_profile(office_id):
    if not settings.SIGNING_CONFIG_FILE:
        raise ValidationError("Nie skonfigurowano podpisywania dokumentów dla tego urzędu.")
    try:
        config = json.loads(secret_text(settings.SIGNING_CONFIG_FILE))["offices"].get(office_id)
        if not config:
            raise ValidationError("Nie skonfigurowano podpisywania dokumentów dla tego urzędu.")
        mode = config["mode"]
        if mode not in {"DEMO", "LOCAL_PEM"} or (mode == "DEMO" and not settings.LOCAL):
            raise ValidationError(
                "Podpis DEMO jest dostępny tylko lokalnie. Produkcyjny profil wymaga LOCAL_PEM."
            )
        users = config["authorized_users"]
        fingerprints = config["allowed_certificate_fingerprints"]
        if (
            not isinstance(users, list)
            or not users
            or any(not isinstance(value, str) or "@" not in value for value in users)
            or not isinstance(fingerprints, list)
            or not fingerprints
            or any(
                not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
                for value in fingerprints
            )
        ):
            raise ValidationError(
                "Profil podpisu wymaga listy uprawnionych użytkowników i odcisków dopuszczonych certyfikatów."
            )
        roots = certificates(config.get("trust_root_files", []))
        if not roots:
            raise ValidationError("Wskaż jawne korzenie zaufania dla podpisów dokumentów.")
        if mode != "DEMO" and any(not cert.ca for cert in roots):
            raise ValidationError(
                "Produkcyjne korzenie zaufania muszą być certyfikatami CA, nie certyfikatem podpisującego."
            )

        def responses(name, parser):
            paths = config.get(name, [])
            if not isinstance(paths, list) or len(paths) > 20:
                raise ValidationError("Niepoprawna lista lokalnych danych unieważnienia.")
            return tuple(parser.load(pem.unarmor(secret_text(path).encode())[2]) for path in paths)

        return SignatureProfile(
            mode=mode,
            allowed_users=tuple(value.lower() for value in users),
            allowed_fingerprints=tuple(fingerprints),
            roots=tuple(roots),
            chain=tuple(certificates(config.get("chain_files", []))),
            crls=responses("crl_files", crl.CertificateList),
            ocsps=responses("ocsp_files", ocsp.OCSPResponse),
            seal=config.get("seal", {}),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValidationError(
            "Niepoprawna konfiguracja podpisu, certyfikatów lub danych unieważnienia."
        ) from exc


def require_signing_actor(user, letter, profile):
    require_role(user, "COUNTY", "MAIN")
    if user.office_id != letter.office_id or user.email.lower() not in profile.allowed_users:
        raise PermissionDenied("Brak uprawnienia do podpisania pisma tego urzędu.")


def verify_signed_pdf(payload, original, profile):
    if (
        not isinstance(payload, bytes)
        or not payload.startswith(b"%PDF-")
        or len(payload) > MAX_SIGNED_PDF
        or not payload.startswith(original)
        or len(payload) <= len(original)
    ):
        raise ValidationError(
            "Podpisany PDF musi być podpisaną rewizją oryginału, bez zastępowania jego bajtów (do 10 MB)."
        )
    try:
        base_reader = PdfFileReader(BytesIO(original), strict=True)
        reader = PdfFileReader(BytesIO(payload), strict=True)
        if reader.encrypted or base_reader.encrypted:
            raise ValidationError("Podpisany dokument nie może być zaszyfrowany.")
        signatures = reader.embedded_regular_signatures
        if not signatures or len(signatures) > 5:
            raise ValidationError("PDF musi zawierać od jednego do pięciu podpisów dokumentu.")
        # Porównanie wszystkich aktualizacji z oryginałem wykrywa także zmianę
        # treści PRZED poprawnym kryptograficznie podpisaniem obcego dokumentu.
        original_revision = base_reader.xrefs.total_revisions - 1
        if reader.xrefs.total_revisions <= base_reader.xrefs.total_revisions:
            raise ValidationError("Brak podpisanej rewizji oryginalnego dokumentu.")
        old = reader.get_historical_resolver(original_revision)
        if "/AcroForm" not in old.root:
            # Brak formularza w zweryfikowanym oryginale oznacza pusty zestaw
            # pól. Normalizujemy wyłącznie widok starej rewizji w pamięci;
            # bajty PDF pozostają nietknięte. pyHanko 0.35 wymaga słownika
            # przy porównaniu dodanego pierwszego formularza podpisu.
            old.root[generic.pdf_name("/AcroForm")] = generic.DictionaryObject(
                {
                    generic.pdf_name("/Fields"): generic.ArrayObject(),
                    generic.pdf_name("/SigFlags"): generic.NumberObject(3),
                }
            )
        diff = DEFAULT_DIFF_POLICY.apply(
            old,
            reader.get_historical_resolver(reader.xrefs.total_revisions - 1),
        )
        fields = {sig.fq_name for sig in signatures}
        if diff.modification_level > ModificationLevel.FORM_FILLING or diff.changed_form_fields - fields:
            raise ValidationError("Podpisany plik zmienia treść pisma lub pola niezwiązane z podpisem.")
        results = []
        for index, signature in enumerate(signatures):
            fingerprint = hashlib.sha256(signature.signer_cert.dump()).hexdigest()
            if fingerprint not in profile.allowed_fingerprints:
                raise ValidationError("Certyfikat podpisującego nie jest dopuszczony dla tego urzędu.")
            if signature.sig_object.get("/SubFilter") != SigSeedSubFilter.PADES.value:
                raise ValidationError("Wymagany jest podpis PAdES (ETSI.CAdES.detached).")
            status = validate_pdf_signature(
                signature,
                signer_validation_context=profile.validation_context(),
                key_usage_settings=KeyUsageConstraints(
                    key_usage={"digital_signature", "non_repudiation"}, match_all_key_usages=False
                ),
            )
            if not status.intact or not status.valid or not status.docmdp_ok:
                raise ValidationError(
                    "Podpis PDF jest niepoprawny lub dokument zmieniono poza dopuszczonym zakresem."
                )
            if index == len(signatures) - 1:
                if status.coverage != SignatureCoverageLevel.ENTIRE_FILE:
                    raise ValidationError("Ostatni podpis nie obejmuje całego pliku PDF.")
            elif status.coverage < SignatureCoverageLevel.ENTIRE_REVISION:
                raise ValidationError("Podpis nie obejmuje całej swojej rewizji dokumentu.")
            if not status.trusted:
                raise ValidationError(
                    "Nie potwierdzono łańcucha zaufania i wymaganej polityki unieważnienia certyfikatu."
                )
            cert = signature.signer_cert
            validity = cert["tbs_certificate"]["validity"].native
            cert_now_valid = (
                validity["not_before"] <= datetime.now(datetime_timezone.utc) < validity["not_after"]
            )
            results.append(
                {
                    "fingerprint_sha256": fingerprint,
                    "field": signature.fq_name,
                    "signer_name": cert.subject.native.get("common_name", ""),
                    "intact": status.intact,
                    "valid": status.valid,
                    "trusted": status.trusted,
                    "coverage": status.coverage.name,
                    "certificate_time_valid": cert_now_valid,
                }
            )
        return {
            "validated_at": timezone.now().isoformat(),
            "source_sha256": hashlib.sha256(original).hexdigest(),
            "signed_sha256": hashlib.sha256(payload).hexdigest(),
            "signatures": results,
            "mode": profile.mode,
            "qualification": "NOT_ASSESSED",
            "revocation_policy": "OFFLINE_HARD_FAIL" if profile.mode != "DEMO" else "DEMO_SOFT_FAIL",
            "qualified_timestamp_verified": False,
            "original_content_unchanged": True,
        }
    except ValidationError:
        raise
    except Exception as exc:
        # Nie ujawniamy ścieżek, PEM, tekstu CMS ani szczegółów parsowania.
        raise ValidationError(
            "Nie udało się bezpiecznie zweryfikować podpisanego PDF. Dokument nie został zapisany."
        ) from exc


def local_sign(original, profile, *, reason):
    try:
        value = profile.seal
        if not value:
            raise ValidationError("Brak lokalnego klucza podpisującego. Możesz zaimportować podpisany PDF.")
        password = (
            secret_text(value["password_file"]).rstrip("\r\n").encode()
            if value.get("password_file")
            else None
        )
        key = serialization.load_pem_private_key(secret_text(value["key_file"]).encode(), password=password)
        cert = x509.load_pem_x509_certificate(secret_text(value["certificate_file"]).encode())
        if (
            not isinstance(key, (rsa.RSAPrivateKey, ec.EllipticCurvePrivateKey))
            or isinstance(key, rsa.RSAPrivateKey)
            and key.key_size < 2048
            or isinstance(key, ec.EllipticCurvePrivateKey)
            and key.key_size < 256
        ):
            raise ValidationError("Klucz podpisujący nie spełnia wymagań algorytmu i długości.")
        if key.public_key().public_numbers() != cert.public_key().public_numbers():
            raise ValidationError("Klucz podpisujący nie odpowiada certyfikatowi.")
        now = datetime.now(datetime_timezone.utc)
        if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
            raise ValidationError("Certyfikat podpisujący jest nieważny czasowo.")
        asn_cert = asn1x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))
        if hashlib.sha256(asn_cert.dump()).hexdigest() not in profile.allowed_fingerprints:
            raise ValidationError("Lokalny certyfikat nie jest dopuszczony dla tego urzędu.")
        cert_store = SimpleCertificateStore()
        cert_store.register_multiple(profile.chain)
        signer = SimpleSigner(
            signing_cert=asn_cert,
            signing_key=keys.PrivateKeyInfo.load(
                key.private_bytes(
                    serialization.Encoding.DER,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            ),
            cert_registry=cert_store,
            embed_roots=False,
        )
        metadata = PdfSignatureMetadata(
            field_name="DynaSignature",
            md_algorithm="sha256",
            subfilter=SigSeedSubFilter.PADES,
            reason=reason,
            name=cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value,
        )
        # Niewidoczne pole podpisu: nie nadpisuje treści ani wyglądu pisma.
        output = PdfSigner(metadata, signer=signer).sign_pdf(IncrementalPdfFileWriter(BytesIO(original)))
        return output.getvalue()
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(
            "Nie udało się wykonać podpisu lokalnym kluczem. Sprawdź konfigurację administratora."
        ) from exc


def sign_letter(user, letter, *, uploaded=None, reason="", ip=None):
    profile = load_profile(letter.office_id)
    require_signing_actor(user, letter, profile)
    if not reason.strip() or len(reason) > 500:
        raise ValidationError("Podpisanie wymaga uzasadnienia o długości do 500 znaków.")
    original = bytes(letter.pdf)
    if hashlib.sha256(original).hexdigest() != letter.sha256:
        raise ValidationError("Oryginalny PDF nie przeszedł kontroli sumy SHA-256.")
    if any(
        "Status: niepodpisany." in (page.extract_text() or "") for page in PdfReader(BytesIO(original)).pages
    ):
        raise ValidationError(
            "Archiwalny PDF zawiera stałą adnotację o braku podpisu. Utwórz nową wersję pisma przed podpisaniem."
        )
    if (
        letter.signed_pdf
        or IntegrationJob.objects.filter(letter=letter)
        .exclude(provider="SMTP", operation="DECISION_NOTICE")
        .exists()
    ):
        raise ValidationError(
            "Pismo jest już podpisane lub przekazane do kolejki. Przygotuj nową wersję pisma."
        )
    payload = uploaded if uploaded is not None else local_sign(original, profile, reason=reason)
    report = verify_signed_pdf(payload, original, profile)
    with transaction.atomic():
        current = lock_letter(letter)
        if (
            current.signed_pdf
            or current.sha256 != letter.sha256
            or bytes(current.pdf) != original
            or IntegrationJob.objects.filter(letter=current)
            .exclude(provider="SMTP", operation="DECISION_NOTICE")
            .exists()
        ):
            raise ValidationError("Stan pisma zmienił się podczas podpisywania. Sprawdź aktualny dokument.")
        current.signed_pdf = payload
        current.signed_sha256 = report["signed_sha256"]
        current.signature_report = report
        current.signature_status = "TEST_SIGNED" if profile.mode == "DEMO" else "VERIFIED_SIGNED"
        current.signed_by = user
        current.signed_at = timezone.now()
        current.save(
            update_fields=[
                "signed_pdf",
                "signed_sha256",
                "signature_report",
                "signature_status",
                "signed_by",
                "signed_at",
            ]
        )
        audit(
            user,
            "letter.signed",
            current,
            after={
                "source_sha256": current.sha256,
                "signed_sha256": current.signed_sha256,
                "status": current.signature_status,
                "method": "IMPORT" if uploaded is not None else "LOCAL_PEM",
                "qualification": "NOT_ASSESSED",
            },
            reason=reason,
            ip=ip,
        )
        return current
