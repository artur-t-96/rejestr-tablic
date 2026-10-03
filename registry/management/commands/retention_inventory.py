"""Zbiorczy, wyłącznie odczytowy raport do ustalenia polityki urzędu."""

import json

from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.db.models import Case, CharField, Count, F, Max, Min, Value, When
from django.utils import timezone

from registry.models import (
    AccountInvitation,
    AuditLog,
    DeliveryEvidence,
    EZDCaseLink,
    EZDIncomingDocument,
    IntegrationJob,
    Letter,
    LetterTemplate,
    LoginCode,
    NumberSequence,
    Office,
    PlateRecord,
    Pool,
    PoolSlot,
    PublicChallenge,
    RateBucket,
    Request,
    User,
)


class Command(BaseCommand):
    help = "Zbiorcza inwentaryzacja retencji: liczby i daty, bez treści, identyfikatorów lub zapisu."

    def handle(self, **options):
        classes = (
            ("plate_records", PlateRecord, "status", "office_id"),
            ("requests", Request, "status", "office_id"),
            ("pools", Pool, "kind", "office_id"),
            ("letters", Letter, "kind", None),
            ("integration_jobs", IntegrationJob, "status", None),
            ("delivery_evidence", DeliveryEvidence, None, None),
            ("ezd_incoming", EZDIncomingDocument, "status", None),
            ("account_invitations", AccountInvitation, "status", None),
            ("audit_logs", AuditLog, None, None),
            ("login_codes", LoginCode, None, None),
            ("ezd_links", EZDCaseLink, None, None),
        )
        result = {}
        for name, model, category, offices in classes:
            rows = model.objects.all()
            summary = rows.aggregate(count=Count("pk"), oldest=Min("created_at"), newest=Max("created_at"))
            allowed = (
                [value for value, _ in (model._meta.get_field(category).choices or [])] if category else []
            )
            if allowed:
                categorized = rows.annotate(
                    category=Case(
                        When(**{f"{category}__in": allowed}, then=F(category)),
                        default=Value("UNKNOWN"),
                        output_field=CharField(),
                    )
                )
                summary["category_field"] = category
                summary["categories"] = list(
                    categorized.order_by("category").values("category").annotate(count=Count("pk"))
                )
            if offices:
                summary["offices_with_data"] = rows.values(offices).distinct().count()
            result[name] = summary
        result["sessions"] = Session.objects.aggregate(
            count=Count("pk"), first_expiry=Min("expire_date"), last_expiry=Max("expire_date")
        )
        for name, model in (
            ("pool_slots", PoolSlot),
            ("accounts", User),
            ("offices", Office),
            ("number_sequences", NumberSequence),
            ("letter_templates", LetterTemplate),
            ("public_challenges", PublicChallenge),
            ("rate_buckets", RateBucket),
        ):
            result[name] = {"count": model.objects.count()}
        self.stdout.write(
            json.dumps(
                {
                    "generated_at": timezone.now().isoformat(),
                    "mode": "read_only",
                    "business_retention_policy": "requires_office_decision",
                    "scope": "aggregate database counts and dates; excludes files, contents and personal identifiers",
                    "classes": result,
                },
                default=lambda value: value.isoformat(),
                ensure_ascii=False,
                indent=2,
            )
        )
