from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from registry.demo_setup import prepare, reset_data, reset_pending


class Command(BaseCommand):
    help = (
        "Przygotowuje instancję demonstracyjną: konta demo, dane pokazowe, profile symulatorów. Idempotentne."
    )

    def handle(self, **options):
        if not settings.DEMO_MODE:
            raise CommandError("Tryb demonstracyjny jest wyłączony (brak DYNA_DEMO).")
        if reset_pending():
            token = settings.DEMO_RESET_TOKEN
            counts = reset_data(None, f"Reset przy starcie usługi (DYNA_DEMO_RESET={token})", token=token)
            self.stdout.write(
                f"Dane demo wyczyszczone przy starcie: wnioski {counts['requests']}, "
                f"wpisy {counts['records']}, pule {counts['pools']}."
            )
            created = counts["seeded"]
        else:
            created = prepare()
        self.stdout.write(
            f"Tryb demo gotowy: konta i profile symulatorów sprawdzone, nowych danych pokazowych: {created}."
        )
