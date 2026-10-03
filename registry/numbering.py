"""Trwałe numery systemowe. Znak sprawy urzędu jest odrębnym polem."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import Letter, NumberSequence, Request


@transaction.atomic
def next_ordinal(scope, year, documents, ordinal_field):
    # Unikalny (scope, year) serializuje także równoczesne utworzenie
    # pierwszego licznika. Następnie blokujemy jego wiersz do końca transakcji.
    sequence, _ = NumberSequence.objects.get_or_create(scope=scope, year=year)
    sequence = NumberSequence.objects.select_for_update().get(pk=sequence.pk)
    issued = documents.aggregate(last=Max(ordinal_field))["last"] or 0
    value = max(sequence.last_value, issued) + 1
    if value > 9223372036854775807:
        raise ValidationError("Wyczerpano zakres licznika dokumentów. Wymagana interwencja administratora.")
    sequence.last_value = value
    sequence.save(update_fields=["last_value"])
    return value


def request_number():
    year = timezone.localdate().year
    ordinal = next_ordinal("REQUEST", year, Request.objects.filter(reference_year=year), "reference_ordinal")
    return f"W/{year}/{ordinal:05d}", year, ordinal


def letter_number(office):
    year = timezone.localdate().year
    ordinal = next_ordinal(
        f"LETTER.{office.pk}",
        year,
        Letter.objects.filter(office=office, number_year=year),
        "number_ordinal",
    )
    return f"DRT/{office.pk}/{year}/{ordinal:06d}", year, ordinal
