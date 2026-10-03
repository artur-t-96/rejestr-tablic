from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from registry.connectors.ezdrp import ConnectorError
from registry.edor_delivery import resume_edor_observation
from registry.models import IntegrationJob, User


class Command(BaseCommand):
    help = "Wznawia odczyt statusów znanego zadania e-Doręczeń po weryfikacji API. Nie wysyła ponownie pisma."

    def add_arguments(self, parser):
        parser.add_argument("job_uuid")
        parser.add_argument("--actor", required=True)
        parser.add_argument("--reason", required=True)

    def handle(self, job_uuid, actor, reason, **options):
        try:
            user = User.objects.get(email=actor, role="ADMIN", is_active=True)
            job = resume_edor_observation(user, job_uuid, reason=reason)
        except (User.DoesNotExist, IntegrationJob.DoesNotExist, ValidationError, ConnectorError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"{job.uuid}: {job.status_label}")
