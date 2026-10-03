"""Trwałe powiadomienie autora o decyzji; nie zastępuje doręczenia pisma urzędowi."""

import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.db import transaction

from .connectors.ezdrp import ConnectorError
from .documents import document_link
from .models import IntegrationJob, Request
from .services import audit, require_role


@transaction.atomic
def enqueue_decision_notice(user, req, letter, *, ip=None):
    require_role(user, "MAIN")
    req = Request.objects.select_for_update(of=("self",)).select_related("author").get(pk=req.pk)
    approval_kind = "APPROVAL" if req.kind == "I" else "POOL"
    if (
        req.status not in {"APPROVED", "REJECTED"}
        or letter.request_id != req.pk
        or letter.office_id != user.office_id
        or letter.kind != (approval_kind if req.status == "APPROVED" else "REJECTION")
    ):
        raise ValidationError("Powiadomienie wymaga zapisanej decyzji i właściwego pisma.")
    key = f"SMTP:{req.uuid}:DECISION_NOTICE"
    existing = IntegrationJob.objects.filter(key=key).first()
    if existing:
        return existing
    message = {
        "version": 1,
        "to": req.author.email,
        "from": settings.DEFAULT_FROM_EMAIL,
        "subject": f"Decyzja w sprawie {req.reference} — Dyna Rejestr Tablic",
        "body": (
            f"UMP rozpatrzył wniosek {req.reference}.\n"
            f"Decyzja: {req.get_status_display()}.\n\n"
            f"Szczegóły i pismo zwrotne są dostępne po zalogowaniu:\n{document_link(letter)}\n\n"
            "To powiadomienie informacyjne. Doręczenie pisma urzędowi jest osobną operacją.\n"
        ),
    }
    payload = json.dumps(message, ensure_ascii=False, sort_keys=True).encode("utf-8")
    job = IntegrationJob.objects.create(
        key=key,
        provider="SMTP",
        operation="DECISION_NOTICE",
        letter=letter,
        payload=payload,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
    )
    audit(
        user,
        "integration.queued",
        letter,
        after={"provider": "SMTP", "operation": job.operation, "job": str(job.uuid)},
        ip=ip,
    )
    return job


def send_decision_notice(job):
    try:
        message = json.loads(bytes(job.payload))
        if (
            not isinstance(message, dict)
            or set(message) != {"version", "to", "from", "subject", "body"}
            or message["version"] != 1
            or any(not isinstance(message[name], str) for name in ("to", "from", "subject", "body"))
        ):
            raise ValueError("Invalid snapshot")
        for name in ("to", "from"):
            validate_email(message[name])
        if any("\n" in message[name] or "\r" in message[name] for name in ("to", "from", "subject")):
            raise ValueError("Invalid header")
    except (ValueError, TypeError, ValidationError):
        raise ConnectorError(
            "Niepoprawna zapisana treść lub adres powiadomienia. Wymagana kontrola konfiguracji.",
            state="CONFIG_ERROR",
        ) from None
    from .microsoft_mail import BACKEND, SMTP_BACKEND, configuration_ready

    if settings.EMAIL_BACKEND in (BACKEND, SMTP_BACKEND) and not configuration_ready():
        raise ConnectorError("Brak konfiguracji poczty dla powiadomienia o decyzji.", state="CONFIG_ERROR")
    email = EmailMessage(
        message["subject"],
        message["body"],
        message["from"],
        [message["to"]],
        headers={"Message-ID": f"<{job.uuid}@dyna-rejestr.local>"},
    )
    if email.send() != 1:
        raise ValidationError("Nie potwierdzono przyjęcia powiadomienia.")
    return "LOCAL_SAVED" if settings.EMAIL_BACKEND.endswith("filebased.EmailBackend") else "ACCEPTED"
