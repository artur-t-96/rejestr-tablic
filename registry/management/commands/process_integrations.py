import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from registry.integrations import process_job, recover_stale_jobs
from registry.models import IntegrationJob


class Command(BaseCommand):
    help = "Przetwarza kolejkę skonfigurowanych integracji."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true", help="Pracuj stale w osobnym procesie.")
        parser.add_argument("--interval", type=int, default=30, help="Przerwa między partiami, w sekundach.")
        parser.add_argument("--provider", choices=["SMTP", "EZD", "EDOR"])
        parser.add_argument("--operation", choices=["SEND", "REGISTER", "DECISION_NOTICE"])

    def handle(self, **options):
        from django.core.management.base import CommandError

        if not 1 <= options["interval"] <= 3600:
            raise CommandError("Przerwa kolejki musi wynosić od 1 do 3600 sekund.")
        try:
            while True:
                close_old_connections()
                self.process_batch(options)
                if not options["watch"]:
                    return
                time.sleep(options["interval"])
        except KeyboardInterrupt:
            self.stdout.write("Proces kolejki zatrzymany.")
        finally:
            close_old_connections()

    def process_batch(self, options):
        interrupted = recover_stale_jobs()
        if interrupted:
            self.stdout.write(f"Przerwane operacje wymagające sprawdzenia: {interrupted}")
        jobs = (
            IntegrationJob.objects.filter(status__in=["QUEUED", "RETRY", "MONITORING"])
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now()))
            .order_by("created_at")
        )
        if options["provider"]:
            jobs = jobs.filter(provider=options["provider"])
        if options["operation"]:
            jobs = jobs.filter(operation=options["operation"])
        for job in jobs[:100]:
            result = process_job(job)
            self.stdout.write(f"{result.uuid}: {result.status}")
