from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction

from registry.documents import DEFAULT_TEMPLATES
from registry.management.commands.seed_local import COUNTIES
from registry.models import LetterTemplate, Office, User
from registry.services import audit


class Command(BaseCommand):
    help = (
        "Inicjalizuje pustą instalację: 35 nieaktywnych urzędów i administrator; bez spraw i kont pokazowych."
    )

    def add_arguments(self, parser):
        parser.add_argument("--admin-email", required=True)

    @transaction.atomic
    def handle(self, admin_email, **options):
        email = admin_email.strip().lower()
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError("Podaj poprawny e-mail administratora.") from exc
        if not settings.LOCAL and email.endswith(".invalid"):
            raise CommandError("Instalacja urzędowa wymaga rzeczywistego adresu administratora.")
        if Office.objects.exists() or User.objects.exists() or LetterTemplate.objects.exists():
            raise CommandError(
                "Inicjalizacja wymaga pustej instalacji; istniejące dane nie zostaną zmienione."
            )
        offices = [
            Office(
                id="ump",
                name="Urząd Miasta Poznania – Wydział Komunikacji",
                kind="MAIN",
                city="Poznań",
                active=False,
            )
        ]
        offices += [
            Office(id=code, name="Urząd Miasta " + city, kind="CITY", city=city, active=False)
            for code, city in [("kal", "Kalisz"), ("kon", "Konin"), ("les", "Leszno")]
        ]
        offices += [
            Office(id=code, name="Starostwo Powiatowe w " + location, kind="COUNTY", city=city, active=False)
            for code, _adj, city, location in COUNTIES
        ]
        Office.objects.bulk_create(offices)
        LetterTemplate.objects.bulk_create(
            [
                LetterTemplate(kind=kind, title=title, body=body)
                for kind, (title, body) in DEFAULT_TEMPLATES.items()
            ]
        )
        admin = User(username=email, email=email, role="ADMIN", first_name="Administrator")
        admin.set_unusable_password()
        admin.full_clean()
        admin.save()
        audit(
            admin,
            "installation.initialized",
            admin,
            after={"offices": len(offices)},
            reason="Inicjalizacja pustej instalacji.",
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Utworzono 35 nieaktywnych urzędów, wzory do zatwierdzenia i administratora OTP. Nie wysłano wiadomości."
            )
        )
