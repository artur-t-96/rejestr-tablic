"""Przygotowanie instancji demonstracyjnej: urzędy, konta, dane pokazowe, profile symulatorów.

Wszystko jest idempotentne i fikcyjne. Nie zmienia list domen urzędów ani kont rzeczywistych.
"""

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone as django_timezone

from . import demo
from .models import DemoAccessCode, DemoMessage, Office, Pool, Request, SimulatorObject, User

SIGNING_DAYS = 365
OFFICE_DEFAULTS = {
    "ump": ("Urząd Miasta Poznania – Wydział Komunikacji", "MAIN", "Poznań"),
    "gni": ("Starostwo Powiatowe w Gnieźnie", "COUNTY", "Gniezno"),
    "pil": ("Starostwo Powiatowe w Pile", "COUNTY", "Piła"),
}


def demo_ade(index):
    return f"AE:PL-9000{index}-0000{index}-DEMO{index}-0{index}"


def write_private(path, content):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(content)
    os.chmod(path, 0o600)


def pem_key(key):
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def signing_material(common_name, days):
    """Fikcyjny urząd certyfikacji i certyfikat podpisu; używa go też `create_demo_signing`."""
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
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    return {
        "key.pem": pem_key(key),
        "certificate.pem": cert.public_bytes(serialization.Encoding.PEM),
        "ca.pem": ca.public_bytes(serialization.Encoding.PEM),
    }, hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def certificate_fresh(path, days=30):
    try:
        cert = x509.load_pem_x509_certificate(path.read_bytes())
    except (OSError, ValueError):
        return False
    return cert.not_valid_after_utc > datetime.now(timezone.utc) + timedelta(days=days)


def write_profiles(directory=None):
    """Profile symulatorów i podpisu demo w prywatnym katalogu danych; sekrety nie trafiają do repo."""
    directory = Path(directory or settings.DEMO_DIR)
    offices = {office.pk: office for office in Office.objects.filter(pk__in=demo.OFFICES)}
    ezd, edor, signing = {}, {}, {}
    for office_id, office in offices.items():
        base = directory / office_id
        host = f"ezd-{office_id}.symulator.invalid"
        if not (base / "ezd-api-key").exists():
            write_private(base / "ezd-api-key", secrets.token_urlsafe(32).encode())
        ezd[office_id] = {
            "api_url": f"https://{host}",
            "token_url": f"https://{host}/connect/token",
            "web_host": host,
            "pid": f"SIM-PODMIOT-{office_id}",
            "aki": f"SIM-KLUCZ-{office_id}",
            "sid": f"SIM-STANOWISKO-{office_id}",
            "api_key_file": str(base / "ezd-api-key"),
            "jrwa_id": "5410",
            "archival_category": "BE10",
            "metadata": {
                name: {"key": f"dyna_{name}", "name": label}
                for name, label in (
                    ("request_id", "Identyfikator wniosku Dyna"),
                    ("request_url", "Link do wniosku Dyna"),
                    ("letter_number", "Numer pisma Dyna"),
                    ("payload_sha256", "SHA-256 dokumentu"),
                )
            },
        }
        if not certificate_fresh(base / "edor-certificate.pem"):
            files, _ = signing_material(f"SYMULATOR e-Doręczeń | {office_id}", SIGNING_DAYS)
            write_private(base / "edor-key.pem", files["key.pem"])
            write_private(base / "edor-certificate.pem", files["certificate.pem"])
        if office.ade:
            edor[office_id] = {
                "environment": "SYMULATOR",
                "sender_ade": office.ade,
                "system_name": "DYNA_DEMO",
                "ua_url": "https://edor.symulator.invalid/api/v3",
                "se_url": "https://edor.symulator.invalid/api/se/v4",
                "token_url": "https://edor.symulator.invalid/auth/token",
                "audience": "https://edor.symulator.invalid/auth",
                "private_key_file": str(base / "edor-key.pem"),
                "certificate_file": str(base / "edor-certificate.pem"),
            }
        if not certificate_fresh(base / "certificate.pem"):
            files, _ = signing_material(f"DEMO niekwalifikowany | {office_id}", SIGNING_DAYS)
            for name, content in files.items():
                write_private(base / name, content)
        fingerprint = hashlib.sha256(
            x509.load_pem_x509_certificate((base / "certificate.pem").read_bytes()).public_bytes(
                serialization.Encoding.DER
            )
        ).hexdigest()
        users = [
            f"{key}@{demo.DOMAIN}"
            for key, _role, account_office, *_ in demo.ACCOUNTS
            if account_office == office_id
        ]
        signing[office_id] = {
            "mode": "DEMO",
            "authorized_users": users,
            "allowed_certificate_fingerprints": [fingerprint],
            "trust_root_files": [str(base / "ca.pem")],
            "chain_files": [str(base / "ca.pem")],
            "seal": {"key_file": str(base / "key.pem"), "certificate_file": str(base / "certificate.pem")},
        }
    for name, content in (("ezdrp.json", ezd), ("edor.json", edor), ("signing.json", signing)):
        write_private(
            directory / name, json.dumps({"offices": content}, ensure_ascii=False, indent=2).encode()
        )
    return directory


@transaction.atomic
def ensure_accounts():
    """Urzędy pokazowe aktywne, z fikcyjnym ADE i kontaktem, oraz cztery konta demo."""
    for index, office_id in enumerate(demo.OFFICES, start=1):
        name, kind, city = OFFICE_DEFAULTS[office_id]
        office, _ = Office.objects.get_or_create(
            pk=office_id, defaults={"name": name, "kind": kind, "city": city, "active": True}
        )
        office.active = True
        office.ade = office.ade or demo_ade(index)
        office.email = office.email or f"kontakt-{office_id}@{demo.DOMAIN}"
        office.save(update_fields=["active", "ade", "email"])
    users = {}
    for key, role, office_id, first, last, _label in demo.ACCOUNTS:
        email = f"{key}@{demo.DOMAIN}"
        user = User.objects.filter(email=email).first()
        if user is None:
            user = User(username=email, email=email, role=role, office_id=office_id)
            user.set_unusable_password()
        if user.removed_at is None:
            user.first_name, user.last_name, user.is_active = first, last, True
            user.role, user.office_id = role, office_id
            user.full_clean(exclude=["password"])
            user.save()
        users[key] = user
    return users


def ensure_access_code():
    current = DemoAccessCode.objects.first()
    return current or DemoAccessCode.objects.create(code=secrets.token_urlsafe(9))


def seed_cases(users):
    """Kilka fikcyjnych spraw, żeby każda rola miała co obejrzeć; pomijane, gdy już istnieją."""
    from .number_checks import suggest_pool_range
    from .services import allocate_pool, create_request, decide_request, send_request

    gniezno, pila, ump = users["powiat-gniezno"], users["powiat-pila"], users["ump"]
    if Request.objects.filter(author__in=[gniezno, pila]).exists():
        return 0
    created = 0
    cases = (
        (gniezno, "P0DEMO", "Osoba Pokazowa Alfa", "approve"),
        (gniezno, "P1URBAN", "Firma Pokazowa Beta", "wait"),
        (pila, "M2PILA", "Osoba Pokazowa Gamma", "draft"),
    )
    for author, number, owner, step in cases:
        try:
            with transaction.atomic():
                req = create_request(
                    author,
                    {
                        "kind": "I",
                        "number": number,
                        "owner": owner,
                        "case_number": "DEMO/" + number,
                        "count": 1,
                    },
                )
                if step != "draft":
                    send_request(author, req.uuid)
                if step == "approve":
                    decide_request(ump, req.uuid, True, "Dane pokazowe")
                created += 1
        except ValidationError:
            # Numer zajęty przez wcześniejsze dane instancji; dane pokazowe nie są warunkiem działania.
            continue
    span = suggest_pool_range("II", "P", 30)
    if span and not Pool.objects.filter(office_id="gni", kind="II").exists():
        try:
            with transaction.atomic():
                allocate_pool(
                    ump,
                    {
                        "kind": "II",
                        "office": "gni",
                        "prefix": "P",
                        "start": span[0],
                        "end": span[1],
                        "valid_from": django_timezone.localdate(),
                    },
                )
                created += 1
        except ValidationError:
            pass
    return created


def purge_old():
    """Stare wiadomości skrzynki i stan symulatorów nie są potrzebne; ograniczają przyrost bazy."""
    limit = django_timezone.now() - timedelta(days=settings.DEMO_KEEP_DAYS)
    DemoMessage.objects.filter(created_at__lt=limit).delete()
    SimulatorObject.objects.filter(created_at__lt=limit).exclude(kind="EZD_CASE").delete()


def prepare():
    users = ensure_accounts()
    write_profiles()
    ensure_access_code()
    purge_old()
    return seed_cases(users)
