import json
from datetime import timedelta

from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from registry.models import LoginCode, PublicChallenge, RateBucket


class Command(BaseCommand):
    help = (
        "Podgląd/usunięcie wygasłego stanu technicznego starszego niż 24 godziny; "
        "--include-auth obejmuje także wygasłe OTP i sesje. Bez danych spraw i audytu."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--include-auth", action="store_true")
        parser.add_argument("--json", action="store_true")

    @transaction.atomic
    def handle(self, **options):
        cutoff = timezone.now() - timedelta(hours=24)
        groups = {
            "captcha": PublicChallenge.objects.filter(expires_at__lte=cutoff),
            "rate_buckets": RateBucket.objects.filter(start__lte=cutoff),
        }
        if options["include_auth"]:
            groups.update(
                login_codes=LoginCode.objects.filter(expires_at__lte=cutoff),
                sessions=Session.objects.filter(expire_date__lte=cutoff),
            )
        counts = {name: rows.count() for name, rows in groups.items()}
        deleted = {}
        if options["apply"]:
            deleted = {name: rows.delete()[0] for name, rows in groups.items()}
        if options["json"]:
            self.stdout.write(
                json.dumps(
                    {
                        "mode": "apply" if options["apply"] else "preview",
                        "cutoff": cutoff.isoformat(),
                        "include_auth": options["include_auth"],
                        "candidates": counts,
                        "deleted": deleted,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            result = deleted if options["apply"] else counts
            self.stdout.write(
                f"{'Usunięto' if options['apply'] else 'Podgląd'}: "
                f"CAPTCHA {result['captcha']}, liczniki {result['rate_buckets']}."
            )
            if options["include_auth"]:
                self.stdout.write(f"Wygasłe OTP {result['login_codes']}, sesje {result['sessions']}.")
