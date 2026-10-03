import email

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Odczytuje ostatnią wiadomość z lokalnej skrzynki testowej dla wskazanego konta."

    def add_arguments(self, parser):
        parser.add_argument("address")

    def handle(self, address, **options):
        if not settings.LOCAL:
            raise CommandError("Skrzynka testowa jest dostępna tylko lokalnie.")
        directory = settings.EMAIL_FILE_PATH
        files = (
            sorted(directory.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
            if directory.exists()
            else []
        )
        for file in files:
            message = email.message_from_bytes(file.read_bytes())
            if address.lower() in (message.get("To") or "").lower():
                if message.is_multipart():
                    for part in message.walk():
                        if part.get_content_type() == "text/plain":
                            self.stdout.write(
                                part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8")
                            )
                            return
                self.stdout.write(
                    message.get_payload(decode=True).decode(message.get_content_charset() or "utf-8")
                )
                return
        raise CommandError("Nie ma wiadomości dla tego adresu. Najpierw zamów kod w aplikacji.")
