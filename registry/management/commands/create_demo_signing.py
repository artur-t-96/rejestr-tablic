"""Osobny certyfikat demonstracyjny; żadnego kontaktu z usługą zewnętrzną."""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from registry.models import User


class Command(BaseCommand):
    help = "Tworzy prywatny profil DEMO dla wskazanego urzędnika. Nie nadpisuje istniejącego katalogu."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--directory", required=True)

    def handle(self, email, directory, **options):
        if not settings.LOCAL:
            raise CommandError("Certyfikat DEMO można tworzyć wyłącznie lokalnie.")
        user = User.objects.filter(email__iexact=email, is_active=True, role__in=["COUNTY", "MAIN"]).first()
        if not user or not user.office_id:
            raise CommandError("Wskaż aktywne konto urzędnika przypisane do urzędu.")
        target = Path(directory).resolve()
        if target.exists():
            raise CommandError("Katalog już istnieje. Wybierz nowy katalog; klucze nie zostaną nadpisane.")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(timezone.utc)
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Dyna FIKCYJNA CA DEMONSTRACYJNA")])
        ca = (
            x509.CertificateBuilder()
            .subject_name(ca_name)
            .issuer_name(ca_name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=7))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        cert = (
            x509.CertificateBuilder()
            .subject_name(
                x509.Name(
                    [x509.NameAttribute(NameOID.COMMON_NAME, f"DEMO niekwalifikowany | {user.office_id}")]
                )
            )
            .issuer_name(ca_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=7))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
            )
            .sign(ca_key, hashes.SHA256())
        )
        fingerprint = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
        profile = {
            "offices": {
                user.office_id: {
                    "mode": "DEMO",
                    "authorized_users": [user.email.lower()],
                    "allowed_certificate_fingerprints": [fingerprint],
                    "trust_root_files": [str(target / "ca.pem")],
                    "chain_files": [str(target / "ca.pem")],
                    "seal": {
                        "key_file": str(target / "key.pem"),
                        "certificate_file": str(target / "certificate.pem"),
                    },
                }
            }
        }
        files = {
            "key.pem": key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            ),
            "certificate.pem": cert.public_bytes(serialization.Encoding.PEM),
            "ca.pem": ca.public_bytes(serialization.Encoding.PEM),
            "profile.json": json.dumps(profile, ensure_ascii=False, indent=2).encode(),
        }
        target.mkdir(mode=0o700, parents=True)
        for name, content in files.items():
            fd = os.open(target / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as out:
                out.write(content)
        self.stdout.write(f"DEMO, niekwalifikowany. Ważność: 7 dni. SHA-256 certyfikatu: {fingerprint}")
        self.stdout.write(f"SIGNING_CONFIG_FILE={target / 'profile.json'}")
