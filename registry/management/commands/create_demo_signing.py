"""Osobny certyfikat demonstracyjny; żadnego kontaktu z usługą zewnętrzną."""

import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from registry.demo_setup import signing_material
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
        files, fingerprint = signing_material(f"DEMO niekwalifikowany | {user.office_id}", days=7)
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
        files["profile.json"] = json.dumps(profile, ensure_ascii=False, indent=2).encode()
        target.mkdir(mode=0o700, parents=True)
        for name, content in files.items():
            fd = os.open(target / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as out:
                out.write(content)
        self.stdout.write(f"DEMO, niekwalifikowany. Ważność: 7 dni. SHA-256 certyfikatu: {fingerprint}")
        self.stdout.write(f"SIGNING_CONFIG_FILE={target / 'profile.json'}")
