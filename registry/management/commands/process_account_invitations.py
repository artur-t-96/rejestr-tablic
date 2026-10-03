import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from registry.account_invitations import process_invitation, recover_invitations
from registry.models import AccountInvitation


class Command(BaseCommand):
    help = "Przetwarza zaproszenia do kont. Nie ponawia automatycznie niepewnej wysyłki SMTP."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--interval", type=int, default=30)

    def handle(self, **options):
        if not 1 <= options["interval"] <= 3600:
            raise CommandError("Przerwa kolejki musi wynosić od 1 do 3600 sekund.")
        try:
            while True:
                close_old_connections()
                recovered = recover_invitations()
                if recovered:
                    self.stdout.write(f"Zaproszenia wymagające sprawdzenia: {recovered}")
                for pk in (
                    AccountInvitation.objects.filter(status="QUEUED")
                    .order_by("created_at")
                    .values_list("pk", flat=True)[:100]
                ):
                    item = process_invitation(pk)
                    self.stdout.write(f"{item.uuid}: {item.status}")
                if not options["watch"]:
                    return
                time.sleep(options["interval"])
        except KeyboardInterrupt:
            self.stdout.write("Proces zaproszeń zatrzymany.")
        finally:
            close_old_connections()
