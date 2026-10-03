from django.db import migrations

# Zamrożone wzory obu wersji. Nie importuj żywego kodu generowania PDF.
LEGACY = {
    "APPLICATION": (
        "Wniosek o przydział",
        "Urząd ${sender} zwraca się do ${recipient} o przydział: ${subject}.\nZnak sprawy: ${case_number}.\nWnioskodawca: ${owner}.\nDane pojazdu: ${vehicle}.\nUzasadnienie: ${justification}.\nIdentyfikator wniosku: ${request_id}.\nWniosek w aplikacji: ${request_url}.",
    ),
    "APPROVAL": (
        "Potwierdzenie możliwości wydania tablic indywidualnych",
        "W odpowiedzi na wniosek ${reference}, znak sprawy ${case_number}, potwierdzamy możliwość wydania tablic ${subject}.\nWnioskodawca: ${owner}.\nUzasadnienie decyzji: ${reason}.\nIdentyfikator wniosku: ${request_id}.",
    ),
    "REJECTION": (
        "Odmowa przydziału",
        "W odpowiedzi na wniosek ${reference}, znak sprawy ${case_number}, odmawiamy przydziału: ${subject}.\nUzasadnienie: ${reason}.\nIdentyfikator wniosku: ${request_id}.",
    ),
    "POOL": (
        "Informacja o przydziale puli numerów",
        "Przydzielamy urzędowi ${recipient} pulę: ${subject}.\nOkres obowiązywania: ${period}.\nStacja / przeznaczenie: ${station}.\nIdentyfikator wniosku: ${request_id}.",
    ),
}

UPDATED = {
    "APPLICATION": (
        "Wniosek o przydział",
        "${sender} składa wniosek o przydział: ${subject}.\nZnak sprawy: ${case_number}\nWnioskodawca: ${owner}\nAdres wnioskodawcy: ${owner_address}\nDane pojazdu: ${vehicle}\nStacja / przeznaczenie: ${station}\nUzasadnienie: ${justification}",
    ),
    "APPROVAL": (
        "Potwierdzenie możliwości wydania tablic indywidualnych",
        "W odpowiedzi na wniosek ${reference}, znak sprawy ${case_number}, potwierdzamy możliwość wydania tablic ${subject}.\nWnioskodawca: ${owner}\nUzasadnienie decyzji: ${reason}",
    ),
    "REJECTION": (
        "Odmowa przydziału",
        "W odpowiedzi na wniosek ${reference}, znak sprawy ${case_number}, odmawiamy przydziału: ${subject}.\nUzasadnienie: ${reason}",
    ),
    "POOL": (
        "Informacja o przydziale puli numerów",
        "Adresat otrzymuje pulę: ${subject}.\nOkres obowiązywania: ${period}\nStacja / przeznaczenie: ${station}",
    ),
}


def update_defaults(apps, schema_editor):
    Template = apps.get_model("registry", "LetterTemplate")
    Audit = apps.get_model("registry", "AuditLog")
    for kind, (old_title, old_body) in LEGACY.items():
        for row in Template.objects.filter(kind=kind, title=old_title, body=old_body, revision=1):
            title, body = UPDATED[kind]
            changed = Template.objects.filter(pk=row.pk, title=old_title, body=old_body, revision=1).update(
                title=title, body=body, revision=2
            )
            if changed:
                Audit.objects.create(
                    action="template.default.updated",
                    object_type="LetterTemplate",
                    object_id=str(row.pk),
                    before={"title": old_title, "body": old_body, "revision": 1},
                    after={"title": title, "body": body, "revision": 2},
                    reason="Aktualizacja niezmienionego wzoru systemowego; archiwalne pisma pozostają zachowane.",
                )


def restore_defaults(apps, schema_editor):
    Template = apps.get_model("registry", "LetterTemplate")
    Audit = apps.get_model("registry", "AuditLog")
    for kind, (title, body) in UPDATED.items():
        for row in Template.objects.filter(kind=kind, title=title, body=body, revision=2):
            old_title, old_body = LEGACY[kind]
            if Template.objects.filter(pk=row.pk, title=title, body=body, revision=2).update(
                title=old_title, body=old_body, revision=1
            ):
                Audit.objects.create(
                    action="template.default.restored",
                    object_type="LetterTemplate",
                    object_id=str(row.pk),
                    before={"title": title, "body": body, "revision": 2},
                    after={"title": old_title, "body": old_body, "revision": 1},
                    reason="Cofnięcie niezmienionego wzoru systemowego; archiwalne pisma pozostają zachowane.",
                )


class Migration(migrations.Migration):
    dependencies = [("registry", "0007_ezdincomingdocument")]
    operations = [migrations.RunPython(update_defaults, restore_defaults)]
