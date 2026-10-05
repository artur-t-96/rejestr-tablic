"""Read-only presentation of audit facts, without resolving current business data."""

import json

from django.core.exceptions import FieldDoesNotExist
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from . import models
from .accounts import account_label

ACTION_LABELS = {
    "request.created": "Utworzono wniosek",
    "request.submitted": "Złożono wniosek do UMP",
    "request.withdrawn": "Wycofano wniosek",
    "request.decided": "Zapisano stanowisko UMP",
    "request.expired": "Wygasł wniosek po upływie rezerwacji",
    "plate.reserved": "Zarezerwowano numer",
    "plate.submitted": "Numer oczekuje na rozpatrzenie przez UMP",
    "plate.withdrawn": "Zwolniono numer po wycofaniu wniosku",
    "plate.decided": "Zapisano wynik rozpatrzenia dla numeru",
    "plate.updated": "Zmieniono dane wpisu",
    "plate.transferred": "Przeniesiono wpis do innego urzędu",
    "plate.released": "Zwolniono numer do puli wolnych",
    "plate.transfer_notice": "Powiadomiono nowy urząd o przeniesieniu wpisu",
    "plate.transfer_notice_failed": "Nie udało się powiadomić nowego urzędu o przeniesieniu wpisu",
    "plate.transfer_notice_skipped": "Pominięto powiadomienie o przeniesieniu wpisu: brak adresu e-mail",
    "plate.imported": "Zaimportowano historyczny wpis",
    "reservation.extended": "Przedłużono rezerwację",
    "reservation.expired": "Zwolniono numer po wygaśnięciu rezerwacji",
    "reservation.restored": "Przywrócono rezerwację wygasłego wniosku",
    "reservation.reminder": "Wysłano przypomnienie o terminie rezerwacji",
    "reservation.reminder_failed": "Nie udało się wysłać przypomnienia o terminie rezerwacji",
    "reservation.reminder_skipped": "Pominięto przypomnienie o terminie: brak adresu e-mail",
    "request.restored": "Przywrócono wygasły wniosek",
    "pool.allocated": "Przydzielono pulę numerów",
    "pool.number_issued": "Wydano numer z puli",
    "pool.number_issue_revoked": "Cofnięto wydanie numeru z puli",
    "pool.alert": "Wysłano alert o wykorzystaniu puli",
    "pool.alert_failed": "Nie udało się wysłać alertu o wykorzystaniu puli",
    "pool.alert_skipped": "Pominięto alert o wykorzystaniu puli: brak adresu e-mail",
    "pool.imported": "Zaimportowano historyczną pulę",
    "letter.generated": "Wygenerowano pismo PDF",
    "letter.revised": "Utworzono nową wersję pisma",
    "letter.signed": "Zapisano podpisany dokument",
    "letter.downloaded": "Otworzono lub pobrano pismo PDF",
    "letter.posted": "Odnotowano wysyłkę pisma pocztą",
    "registry.exported": "Wyeksportowano ewidencję",
    "auth.login": "Zalogowano użytkownika",
    "auth.demo_login": "Wejście demonstracyjne na fikcyjne konto",
    "demo.code_rotated": "Zmieniono kod dostępu demo",
    "auth.mail_failed": "Nie udało się wysłać kodu logowania",
    "auth.session_extended": "Przedłużono sesję użytkownika",
    "admin.office_saved": "Zapisano ustawienia urzędu",
    "admin.user_saved": "Zapisano ustawienia konta",
    "admin.user_deleted": "Usunięto konto bez historii",
    "admin.user_closed": "Zamknięto konto z zachowaniem historii",
    "admin.template_saved": "Zapisano szablon pisma",
    "admin.flag_saved": "Zapisano słowo w słowniku ostrzeżeń",
    "account.invitation_queued": "Dodano zaproszenie do kolejki",
    "account.invitation_state": "Zmieniono stan wysyłki zaproszenia",
    "account.invitation_interrupted": "Przerwana wysyłka zaproszenia wymaga sprawdzenia",
    "account.invitation_reconciled": "Uzgodniono wynik wysyłki zaproszenia",
    "integration.queued": "Dodano operację zewnętrzną do kolejki",
    "integration.requeued": "Ponowiono nieudaną wysyłkę e-mail",
    "integration.result": "Zapisano wynik operacji zewnętrznej",
    "integration.reconciled": "Uzgodniono wynik operacji zewnętrznej",
    "integration.interrupted": "Przerwana operacja zewnętrzna wymaga sprawdzenia",
    "integration.worker.superseded": "Pominięto wynik nieaktualnej próby operacji",
    "edor.address.searched": "Wyszukano adres do e-Doręczeń",
    "edor.evidence.archived": "Zarchiwizowano dowód e-Doręczeń",
    "edor.evidence.downloaded": "Pobrano dowód e-Doręczeń",
    "edor.unsent.resumed": "Wznowiono niewysłaną operację e-Doręczeń",
    "edor.observation.resumed": "Wznowiono sprawdzanie statusu e-Doręczeń",
    "ezd.case.planned": "Przygotowano powiązanie sprawy EZD",
    "ezd.case.verified": "Sprawdzono powiązanie sprawy w EZD",
    "ezd.incoming.received": "Zapisano wpływ z EZD",
    "ezd.incoming.read.attempt": "Rozpoczęto odczyt wpływów z EZD",
    "ezd.incoming.read.completed": "Zakończono odczyt wpływów z EZD",
    "ezd.incoming.read.error": "Odczyt wpływów z EZD zakończył się błędem",
    "ezd.incoming.link.attempt": "Rozpoczęto zapis odnośnika do wniosku w EZD",
    "ezd.incoming.link.published": "Zapisano odnośnik do wniosku w EZD",
    "ezd.incoming.link.error": "Zapis odnośnika w EZD zakończył się błędem",
    "installation.initialized": "Zainicjalizowano instalację urzędową",
    "template.default.updated": "Zaktualizowano domyślny szablon pisma",
    "template.default.restored": "Przywrócono domyślny szablon pisma",
}

OBJECT_LABELS = {
    "PlateRecord": "Wpis w ewidencji",
    "Request": "Wniosek",
    "Pool": "Pula numerów",
    "PoolSlot": "Numer z puli",
    "Letter": "Pismo",
    "User": "Konto użytkownika",
    "Office": "Urząd",
    "LetterTemplate": "Szablon pisma",
    "FlaggedWord": "Słowo ze słownika ostrzeżeń",
    "DemoAccessCode": "Kod dostępu demo",
    "IntegrationJob": "Operacja zewnętrzna",
    "AccountInvitation": "Zaproszenie do konta",
    "EZDCaseLink": "Powiązanie sprawy EZD",
    "EZDIncomingDocument": "Wpływ z EZD",
    "DeliveryEvidence": "Dowód doręczenia",
}

FIELD_LABELS = {
    "status": "Status",
    "state": "Stan",
    "number": "Numer",
    "owner": "Właściciel",
    "address": "Adres właściciela",
    "office": "Urząd (identyfikator)",
    "office_id": "Urząd prowadzący (identyfikator)",
    "vin": "VIN",
    "make": "Marka pojazdu",
    "model": "Model pojazdu",
    "registration_date": "Data rejestracji",
    "sale_date": "Data zbycia",
    "buyer": "Nabywca",
    "letter_number": "Numer pisma",
    "note": "Uwagi",
    "reservation_until": "Rezerwacja do",
    "posted_at": "Data nadania pocztą",
    "posted_reference": "Numer nadania",
    "percent": "Wykorzystanie puli (%)",
    "recipients": "Liczba adresatów",
    "scope": "Zakres eksportu",
    "allocated_at": "Data przydziału",
    "issued_at": "Data wydania",
    "valid_from": "Obowiązuje od",
    "valid_until": "Obowiązuje do",
    "case_number": "Znak sprawy",
    "kind": "Rodzaj",
    "prefix": "Prefiks puli",
    "start": "Początek puli (pozycja)",
    "end": "Koniec puli (pozycja)",
    "count": "Liczba",
    "rows": "Liczba wierszy",
    "station": "Stacja / przeznaczenie",
    "reason": "Uzasadnienie",
    "email": "Adres e-mail",
    "first_name": "Imię",
    "last_name": "Nazwisko",
    "role": "Rola użytkownika",
    "is_active": "Aktywne konto",
    "active": "Aktywny urząd",
    "allowed_domains": "Dozwolone domeny e-mail",
    "source_filename": "Plik źródłowy",
    "source_sha256": "SHA-256 pliku źródłowego",
    "source_format": "Format pliku źródłowego",
    "source_sheet": "Arkusz źródłowy",
    "source_row": "Wiersz źródłowy",
    "sha256": "SHA-256 dokumentu",
    "provider": "Usługa zewnętrzna",
    "operation": "Rodzaj operacji",
    "remote_id": "Identyfikator w usłudze zewnętrznej",
    "error": "Błąd",
    "attempts": "Liczba prób",
    "id": "Identyfikator",
    "version": "Wersja wpisu",
}

DATE_FIELDS = {"registration_date", "sale_date", "valid_from", "valid_until"}
TIME_FIELDS = {"reservation_until", "allocated_at", "issued_at", "sent_at", "expires_at"}
LETTER_KINDS = {
    "APPLICATION": "Wniosek o przydział",
    "APPROVAL": "Zgoda na przydział",
    "REJECTION": "Odmowa przydziału",
    "POOL": "Przydział puli",
}


def display_value(event, key, value):
    if value is None or value == "":
        return "Nie podano"
    if isinstance(value, bool):
        return "Tak" if value else "Nie"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    if isinstance(value, str):
        if key == "status" and event.action.startswith("account.invitation"):
            return models.AccountInvitation(status=value).status_label
        if key == "status" and event.action.startswith(("integration.", "edor.unsent.", "edor.observation.")):
            return models.IntegrationJob(status=value).status_label
        if key == "status" and event.action == "letter.signed":
            return {
                "UNSIGNED": "Niepodpisany",
                "TEST_SIGNED": "Podpis testowy",
                "VERIFIED_SIGNED": "Podpis zweryfikowany",
            }.get(value, value)
        if key == "kind" and event.object_type in {"Letter", "LetterTemplate"}:
            return LETTER_KINDS.get(value, value)
        model = getattr(models, event.object_type, None) if event.object_type in OBJECT_LABELS else None
        if model and key in {"status", "kind", "role"}:
            try:
                choices = dict(model._meta.get_field(key).choices or [])
                if value in choices:
                    return choices[value]
            except FieldDoesNotExist:
                pass
        if key == "status" and event.object_type in {"IntegrationJob", "AccountInvitation"}:
            return model(status=value).status_label
        if key == "state" and event.object_type == "EZDCaseLink":
            return models.EZDCaseLink(state=value).state_label
        try:
            if key in DATE_FIELDS and (date := parse_date(value)):
                return date.strftime("%d.%m.%Y")
            if key in TIME_FIELDS and (date := parse_datetime(value)):
                if timezone.is_aware(date):
                    return timezone.localtime(date).strftime("%d.%m.%Y %H:%M:%S %Z")
                return date.strftime("%d.%m.%Y %H:%M:%S") + " (bez strefy czasowej)"
        except ValueError:
            pass
    return str(value)


def present_event(event, viewer=None):
    before, after = event.before, event.after
    if (
        event.object_type == "User"
        and models.User.objects.filter(pk=event.object_id, removed_at__isnull=False).exists()
    ):
        # Dziennik jest niezmienny, więc adres usuniętego konta ukrywamy przy wyświetlaniu.
        before, after = (
            {k: "usunięto z kontem" if k == "email" else v for k, v in values.items()}
            if isinstance(values, dict)
            else values
            for values in (before, after)
        )
    changes = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in dict.fromkeys([*before, *after]):
            if (
                key in before
                and key in after
                and json.dumps(before[key], sort_keys=True) == json.dumps(after[key], sort_keys=True)
            ):
                continue
            changes.append(
                {
                    "label": FIELD_LABELS.get(key, key),
                    "before": display_value(event, key, before[key]) if key in before else "Nie zapisano",
                    "after": display_value(event, key, after[key]) if key in after else "Nie zapisano",
                }
            )
    elif before != {} or after != {}:
        changes.append(
            {
                "label": "Dane zdarzenia",
                "before": display_value(event, "", before),
                "after": display_value(event, "", after),
            }
        )
    return {
        "event": event,
        "label": ACTION_LABELS.get(event.action, "Zdarzenie systemowe"),
        "object_label": OBJECT_LABELS.get(event.object_type, event.object_type),
        "actor_label": account_label(event.actor, viewer=viewer) if event.actor_id else "System",
        "changes": changes,
        "raw_before": json.dumps(before, ensure_ascii=False, indent=2),
        "raw_after": json.dumps(after, ensure_ascii=False, indent=2),
    }
