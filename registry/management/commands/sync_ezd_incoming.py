from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from registry.connectors.ezdrp import ConnectorError, EZDRPClient, load_profile
from registry.ezd_incoming import publish_incoming_link, receive_rpw
from registry.models import User
from registry.services import require_role


class Command(BaseCommand):
    help = "Odczytuje stronicowany RPW w jawnym zakresie dat; bez pomijania niepełnego przebiegu."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True)
        parser.add_argument("--to", dest="date_to", type=date.fromisoformat, required=True)
        parser.add_argument("--max-pages", type=int, default=10)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--publish-links", action="store_true")

    def handle(self, actor, date_from, date_to, max_pages, reason, publish_links, **options):
        if not 1 <= max_pages <= 100:
            raise CommandError("Limit stron musi wynosić od 1 do 100.")
        try:
            user = User.objects.get(email=actor, is_active=True)
            require_role(user, "COUNTY", "MAIN")
            if not 1 <= len(reason.strip()) <= 500:
                raise ValidationError("Podaj uzasadnienie do 500 znaków.")
            with EZDRPClient(load_profile(user.office_id)) as client:
                seen = set()
                for page in range(max_pages):
                    numbers, has_next = client.search_incoming(date_from, date_to, page)
                    for number, year in numbers:
                        if (number, year) in seen:
                            continue
                        seen.add((number, year))
                        rows = receive_rpw(user, number, year, reason=reason)
                        for row in rows:
                            if publish_links and row.status == "MATCHED" and row.link_status != "PUBLISHED":
                                publish_incoming_link(user, row.uuid, reason=reason)
                        self.stdout.write(f"RPW {number}/{year}: sprawdzono {len(rows)} PDF")
                    if not has_next:
                        self.stdout.write(f"Odczyt zakończony: {len(seen)} RPW.")
                        return
            raise CommandError("Osiągnięto limit stron. Odczyt jest niepełny; zawęź daty lub zwiększ limit.")
        except (User.DoesNotExist, PermissionDenied, ValidationError, ConnectorError) as exc:
            raise CommandError(str(exc)) from exc
