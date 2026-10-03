"""Pomoc dla UMP przy decyzji: historia numeru, ostrzeżenia o treści, wolny zakres puli."""

from django.core.exceptions import ValidationError
from django.db.models import Max

from .models import FlaggedWord, PlateRecord, PoolSlot
from .validation import SMALL_SUFFIXES, TEMPORARY_CAPACITY, validate_number

# Cyfry czytane jak litery; słownik zawiera wyłącznie litery.
LOOKALIKES = str.maketrans("0134578", "OIEASTB")


def content_warnings(number):
    part = number[2:]
    readings = {part, part.translate(LOOKALIKES)}
    return [item for item in FlaggedWord.objects.all() if any(item.word in reading for reading in readings)]


def earlier_records(record):
    return (
        PlateRecord.objects.filter(number=record.number)
        .exclude(pk=record.pk)
        .select_related("office")
        .order_by("-created_at", "-pk")
    )


def verification(record):
    """Wynik kontroli pokazywany przy wniosku; unikalność aktywnego wpisu wymusza baza."""
    try:
        validate_number(record.number)
        format_error = ""
    except ValidationError as error:
        format_error = "; ".join(error.messages)
    return {
        "format_error": format_error,
        "other_active": PlateRecord.objects.filter(number=record.number)
        .exclude(pk=record.pk)
        .exclude(status="RELEASED")
        .exists(),
        "warnings": content_warnings(record.number),
        "earlier": earlier_records(record),
    }


def suggest_pool_range(kind, prefix, count):
    """Pierwsze pozycje za ostatnim numerem w ewidencji; None, gdy pojemność prefiksu się kończy."""
    last = PoolSlot.objects.filter(pool__kind=kind, number__startswith=prefix).aggregate(Max("ordinal"))[
        "ordinal__max"
    ]
    start = (last or 0) + 1
    end = start + count - 1
    capacity = len(SMALL_SUFFIXES) if kind == "II" else TEMPORARY_CAPACITY
    return (start, end) if end <= capacity else None
