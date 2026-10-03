import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from registry.services import expire_reservations


class Command(BaseCommand):
    help = "Zwalnia wygasłe rezerwacje i zapisuje historię."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true", help="Pracuj stale w osobnym procesie.")
        parser.add_argument(
            "--interval", type=int, default=30, help="Przerwa między kontrolami, w sekundach (1–3600)."
        )

    def handle(self, **options):
        interval = options["interval"]
        if not 1 <= interval <= 3600:
            raise CommandError("Przerwa musi wynosić 1–3600 sekund.")
        if not options["watch"]:
            self.stdout.write(f"Zwolniono {expire_reservations()} rezerwacji.")
            return
        self.stdout.write(f"Proces wygaszania rezerwacji działa; kontrola co {interval} sekund.")
        try:
            while True:
                close_old_connections()
                count = expire_reservations()
                if count:
                    self.stdout.write(f"Zwolniono {count} rezerwacji.")
                close_old_connections()
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("Proces wygaszania rezerwacji zatrzymany.")
        finally:
            close_old_connections()
