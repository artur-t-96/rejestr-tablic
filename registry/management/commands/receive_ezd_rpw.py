from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from registry.connectors.ezdrp import ConnectorError
from registry.ezd_incoming import publish_incoming_link, receive_rpw
from registry.models import User


class Command(BaseCommand):
    help = "Odczytuje RPW i powiązuje dokumenty z wnioskami własnego urzędu."

    def add_arguments(self, parser):
        parser.add_argument("number", type=int)
        parser.add_argument("year", type=int)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--publish-links", action="store_true")

    def handle(self, number, year, actor, reason, publish_links, **options):
        try:
            user = User.objects.get(email=actor, is_active=True)
            rows = receive_rpw(user, number, year, reason=reason)
            for row in rows:
                if publish_links and row.status == "MATCHED":
                    row = publish_incoming_link(user, row.uuid, reason=reason)
                self.stdout.write(f"{row.uuid}: {row.status}; link={row.link_status}")
        except (User.DoesNotExist, PermissionDenied, ValidationError, ConnectorError) as exc:
            raise CommandError(str(exc)) from exc
