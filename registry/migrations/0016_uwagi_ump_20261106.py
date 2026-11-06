from django.db import migrations, models

# Uwagi UMP z 06.11.2026. Wniosek nie zawiera właściciela, adresu, VIN, numeru sprawy
# ani stacji / przeznaczenia. Zamrożone wzory; nie importuj żywego kodu. Zmieniamy tylko
# niezmienione wzory systemowe, własne wzory urzędu zostają bez zmian.
PREVIOUS = {
    "APPLICATION": (
        "${sender} składa wniosek o przydział: ${subject}.\nZnak sprawy: ${case_number}\nWnioskodawca: ${owner}"
        "\nAdres wnioskodawcy: ${owner_address}\nDane pojazdu: ${vehicle}\nStacja / przeznaczenie: ${station}"
        "\nUzasadnienie: ${justification}"
    ),
    "APPROVAL": (
        "W odpowiedzi na wniosek ${reference}, znak sprawy ${case_number}, potwierdzamy możliwość wydania "
        "tablic ${subject}.\nWnioskodawca: ${owner}\nUzasadnienie: ${reason}"
    ),
    "REJECTION": (
        "W odpowiedzi na wniosek ${reference}, znak sprawy ${case_number}, odmawiamy przydziału: ${subject}."
        "\nUzasadnienie: ${reason}"
    ),
    "POOL": "Adresat otrzymuje pulę: ${subject}.\nOkres obowiązywania: ${period}\nStacja / przeznaczenie: ${station}",
}
UPDATED = {
    "APPLICATION": "${sender} składa wniosek o przydział: ${subject}.\nUzasadnienie: ${justification}",
    "APPROVAL": "W odpowiedzi na wniosek ${reference} potwierdzamy możliwość wydania tablic ${subject}."
    "\nUzasadnienie: ${reason}",
    "REJECTION": "W odpowiedzi na wniosek ${reference} odmawiamy przydziału: ${subject}.\nUzasadnienie: ${reason}",
    "POOL": "Adresat otrzymuje pulę: ${subject}.\nOkres obowiązywania: ${period}",
}


def swap(apps, source, target, step, action, reason):
    Template = apps.get_model("registry", "LetterTemplate")
    Audit = apps.get_model("registry", "AuditLog")
    for kind, old_body in source.items():
        new_body = target[kind]
        for row in Template.objects.filter(kind=kind, body=old_body):
            revision = max(1, row.revision + step)
            if Template.objects.filter(pk=row.pk, body=old_body).update(body=new_body, revision=revision):
                Audit.objects.create(
                    action=action,
                    object_type="LetterTemplate",
                    object_id=str(row.pk),
                    before={"title": row.title, "body": old_body, "revision": row.revision},
                    after={"title": row.title, "body": new_body, "revision": revision},
                    reason=reason,
                )


def update_defaults(apps, schema_editor):
    swap(
        apps,
        PREVIOUS,
        UPDATED,
        1,
        "template.default.updated",
        "Wzór bez danych właściciela, numeru sprawy i stacji (uwagi UMP 06.11.2026); archiwalne pisma pozostają zachowane.",
    )


def restore_defaults(apps, schema_editor):
    swap(
        apps,
        UPDATED,
        PREVIOUS,
        -1,
        "template.default.restored",
        "Cofnięcie niezmienionego wzoru systemowego; archiwalne pisma pozostają zachowane.",
    )


def end_reservation_deadlines(apps, schema_editor):
    """Numer z wniosku pozostaje zajęty do rozpatrzenia, bez terminu i przypomnień."""
    PlateRecord = apps.get_model("registry", "PlateRecord")
    PlateRecord.objects.filter(status__in=["RESERVED", "SENT"]).update(reservation_until=None, reminded_until=None)


# Licznik pul przechowywał indeks bloku; teraz przechowuje ostatnią nadaną pozycję.
# Wielkość bloku do 06.11.2026 wynosiła domyślnie 100 (POOL_*_BLOCK), pierwszy blok kończył się na 99.
def counters_to_positions(apps, schema_editor):
    import os

    NumberSequence = apps.get_model("registry", "NumberSequence")
    sizes = {
        "II": int(os.environ.get("POOL_NARROW_BLOCK", "100")),
        "III": int(os.environ.get("POOL_TEMPORARY_BLOCK", "100")),
    }
    for row in NumberSequence.objects.filter(scope__startswith="POOL.", year=1):
        kind = row.scope.split(".")[1]
        if kind in sizes and row.last_value:
            row.last_value = row.last_value * sizes[kind] - 1
            row.save(update_fields=["last_value"])


def positions_to_counters(apps, schema_editor):
    import os

    NumberSequence = apps.get_model("registry", "NumberSequence")
    sizes = {
        "II": int(os.environ.get("POOL_NARROW_BLOCK", "100")),
        "III": int(os.environ.get("POOL_TEMPORARY_BLOCK", "100")),
    }
    for row in NumberSequence.objects.filter(scope__startswith="POOL.", year=1):
        kind = row.scope.split(".")[1]
        if kind in sizes and row.last_value:
            row.last_value = -(-(row.last_value + 1) // sizes[kind])
            row.save(update_fields=["last_value"])


class Migration(migrations.Migration):
    dependencies = [("registry", "0015_pule_automatyczne")]
    operations = [
        migrations.AlterField(
            model_name="request",
            name="case_number",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterField(
            model_name="platerecord",
            name="owner",
            field=models.CharField(blank=True, max_length=180),
        ),
        migrations.RunPython(update_defaults, restore_defaults),
        migrations.RunPython(end_reservation_deadlines, migrations.RunPython.noop),
        migrations.RunPython(counters_to_positions, positions_to_counters),
        migrations.AddField(
            model_name='user',
            name='county_admin',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='platerecord',
            name='status',
            field=models.CharField(choices=[('RESERVED', 'Wniosek w przygotowaniu'), ('SENT', 'Wniosek w toku'), ('ALLOCATED', 'Przydzielony'), ('ISSUED', 'Wydany'), ('SOLD', 'Pojazd zbyty'), ('RELEASED', 'Zwolniony')], default='RESERVED', max_length=12),
        ),
        migrations.AlterField(
            model_name='pool',
            name='kind',
            field=models.CharField(choices=[('II', 'Pula tablic zmniejszonych'), ('III', 'Pula tablic tymczasowych')], max_length=3),
        ),
        migrations.AlterField(
            model_name='request',
            name='kind',
            field=models.CharField(choices=[('I', 'Tablica indywidualna'), ('II', 'Pula tablic zmniejszonych'), ('III', 'Pula tablic tymczasowych')], max_length=3),
        ),
        migrations.AlterField(
            model_name='request',
            name='status',
            field=models.CharField(choices=[('DRAFT', 'Szkic'), ('SENT', 'Oczekuje na rozpatrzenie'), ('APPROVED', 'Zaakceptowany'), ('REJECTED', 'Odrzucony'), ('WITHDRAWN', 'Wycofany'), ('EXPIRED', 'Wygasły')], default='DRAFT', max_length=12),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.UniqueConstraint(condition=models.Q(('county_admin', True), ('removed_at__isnull', True)), fields=('office',), name='one_county_admin_per_office'),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(condition=models.Q(('county_admin', False), ('role', 'COUNTY'), _connector='OR'), name='county_admin_is_county_role'),
        ),
    ]
