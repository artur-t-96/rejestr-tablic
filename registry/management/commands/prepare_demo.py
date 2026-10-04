from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from registry.demo_setup import prepare


class Command(BaseCommand):
    help = (
        "Przygotowuje instancję demonstracyjną: konta demo, dane pokazowe, profile symulatorów. Idempotentne."
    )

    def handle(self, **options):
        if not settings.DEMO_MODE:
            raise CommandError("Tryb demonstracyjny jest wyłączony (brak DYNA_DEMO).")
        created = prepare()
        self.stdout.write(
            f"Tryb demo gotowy: konta i profile symulatorów sprawdzone, nowych danych pokazowych: {created}."
        )
