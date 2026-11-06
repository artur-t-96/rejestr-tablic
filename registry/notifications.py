"""Informacyjny e-mail roboczy o przeniesieniu wpisu do innego urzędu.

Nie zawierają danych właściciela ani pojazdu i nie zastępują pism. Wynik wysyłki
trafia do audytu; nieudana próba nie jest ponawiana automatycznie.
"""

from django.conf import settings
from django.core.mail import EmailMessage
from django.urls import reverse

from .demo_mail import deliver
from .models import PlateRecord
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
        f"Przeniesiono wpis {record.display_number} do Twojego urzędu — Sprawdź Tablicę",
        body,
        obj=record,
        action="plate.transfer_notice",
    )
