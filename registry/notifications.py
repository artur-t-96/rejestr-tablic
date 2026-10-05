"""Informacyjne e-maile robocze: przypomnienie o rezerwacji i przeniesienie wpisu do innego urzędu.

Nie zawierają danych właściciela ani pojazdu i nie zastępują pism. Wynik wysyłki
trafia do audytu; nieudana próba nie jest ponawiana automatycznie.
"""

from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from .demo_mail import deliver
from .models import Office, PlateRecord, Request
from .services import audit


def panel_url(name, uuid):
    return settings.APP_URL.rstrip("/") + reverse(name, kwargs={"uuid": uuid})


def send_notice(recipients, subject, body, *, obj, action, details=None):
    recipients = sorted({address.strip().lower() for address in recipients if address})
    if not recipients:
        audit(None, action + "_skipped", obj, after=details, reason="Brak adresu e-mail odbiorcy.")
        return False
    try:
        sent = deliver(EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, recipients)) == 1
    except Exception:
        # Transport poczty zgłasza różne wyjątki; każdy oznacza brak potwierdzenia przyjęcia.
        sent = False
    audit(
        None,
        action if sent else action + "_failed",
        obj,
        after={**(details or {}), "recipients": len(recipients)},
        reason="" if sent else "Serwer pocztowy nie potwierdził przyjęcia wiadomości.",
    )
    return sent


def main_office_email():
    return Office.objects.filter(kind="MAIN", active=True).values_list("email", flat=True).first() or ""


def send_reservation_reminders():
    now = timezone.now()
    due = (
        PlateRecord.objects.filter(
            status__in=["RESERVED", "SENT"],
            reservation_until__gt=now,
            reservation_until__lte=now + timedelta(days=settings.RESERVATION_REMINDER_DAYS),
        )
        .exclude(reminded_until=F("reservation_until"))
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    count = 0
    for pk in list(due):
        with transaction.atomic():
            record = PlateRecord.objects.select_for_update().get(pk=pk)
            if (
                record.status not in {"RESERVED", "SENT"}
                or record.reservation_until is None
                or record.reservation_until <= timezone.now()
                or record.reminded_until == record.reservation_until
            ):
                continue
            req = (
                Request.objects.select_related("author")
                .filter(record=record, status__in=["DRAFT", "SENT"])
                .first()
            )
            record.reminded_until = record.reservation_until
            record.save(update_fields=["reminded_until"])
        if req is None:
            continue
        until = timezone.localtime(record.reservation_until).strftime("%d.%m.%Y %H:%M")
        waiting = record.status == "SENT"
        body = (
            f"Rezerwacja numeru {record.display_number} do wniosku {req.reference} wygasa {until}.\n"
            + (
                "Wniosek czeka na rozpatrzenie przez UMP. UMP może go rozpatrzyć albo przedłużyć rezerwację.\n"
                if waiting
                else "Wniosek jest szkicem. Złóż go do UMP przed tym terminem, inaczej numer zostanie zwolniony.\n"
            )
            + f"\nWniosek: {panel_url('request_detail', req.uuid)}\n"
        )
        sent = send_notice(
            # Autor bez aktywnego konta nie dostaje już informacji o sprawach urzędu.
            [req.author.email if req.author.is_active else "", main_office_email() if waiting else ""],
            f"Rezerwacja {record.display_number} wygasa {until} — Dyna Rejestr Tablic",
            body,
            obj=record,
            action="reservation.reminder",
            details={"reservation_until": record.reservation_until.isoformat()},
        )
        count += sent
    return count


def send_transfer_notice(record_pk):
    record = PlateRecord.objects.select_related("office").get(pk=record_pk)
    body = (
        f"UMP przeniósł do urzędu {record.office.name} wpis numeru {record.display_number}.\n"
        "Pojazd zmienił właściciela i urząd prowadzący. Numer pozostaje zajęty; "
        "nie wrócił do puli wolnych numerów.\n"
        f"\nWpis: {panel_url('record_detail', record.uuid)}\n"
    )
    return send_notice(
        [record.office.email],
        f"Przeniesiono wpis {record.display_number} do Twojego urzędu — Dyna Rejestr Tablic",
        body,
        obj=record,
        action="plate.transfer_notice",
    )
