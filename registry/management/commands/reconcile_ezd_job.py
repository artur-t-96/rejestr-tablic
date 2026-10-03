from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from registry.connectors.ezdrp import ConnectorError
from registry.integrations import reconcile_ezd_job
from registry.models import IntegrationJob, User


class Command(BaseCommand):
    help = "Uzgadnia niepewny zapis EZD przez odczyt API i SHA-256 PDF; bez ponowienia POST w ciemno."

    def add_arguments(self, parser):
        parser.add_argument("job")
        parser.add_argument("--actor", required=True, help="E-mail aktywnego administratora technicznego.")
        parser.add_argument("--case-id", default="")
        parser.add_argument("--document-id", default="")
        parser.add_argument("--reason", required=True)

    def handle(self, job, actor, case_id, document_id, reason, **options):
        try:
            user = User.objects.get(email=actor, role="ADMIN", is_active=True)
            result = reconcile_ezd_job(user, job, case_id=case_id, document_id=document_id, reason=reason)
        except (User.DoesNotExist, IntegrationJob.DoesNotExist):
            raise CommandError("Nie znaleziono aktywnego administratora lub operacji EZD.") from None
        except (ValidationError, ConnectorError) as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(
            self.style.SUCCESS(f"Uzgodniono operację {result.uuid}. Kolejka dokończy potwierdzone etapy.")
        )
