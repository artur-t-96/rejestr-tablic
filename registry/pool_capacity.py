"""Kontrole kolejności pojemności (§ 30 ust. 2 pkt 2/6 i § 31 ust. 3).

Liczymy unikalne rzeczywiste numery, nie końce zakresów ani deklaracje puli.
Numery zachowane w historycznych pulach nadal zajmują pojemność.
"""

from django.core.exceptions import ValidationError
from django.db.models import Count, Q

from .models import PoolSlot
from .validation import SMALL_LETTERS, SMALL_SUFFIXES, TEMPORARY_CAPACITY, TEMPORARY_NUMERIC_CAPACITY


def capacity_pattern(kind, prefix):
    letters = f"[{SMALL_LETTERS}]"
    two_digits = "(?:0[1-9]|[1-9][0-9])"
    three_digits = "(?:00[1-9]|0[1-9][0-9]|[1-9][0-9]{2})"
    if kind == "II":
        return (
            f"^{prefix}(?:{three_digits}|{two_digits}{letters}|[1-9]{letters}[1-9]|"
            f"{letters}{two_digits}|[1-9]{letters}{{2}}|{letters}{{2}}[1-9]|"
            f"{letters}[1-9]{letters})$"
        )
    four_digits = "(?:000[1-9]|00[1-9][0-9]|0[1-9][0-9]{2}|[1-9][0-9]{3})"
    return f"^{prefix}(?:{four_digits}|{three_digits}{letters})$"


def occupied_capacity(kind, prefix):
    # Unikalny indeks PoolSlot.number wraz z dokładnym zbiorem dopuszczalnych
    # formatów sprawia, że równa liczba dowodzi pokrycia całej pojemności.
    return PoolSlot.objects.filter(pool__kind=kind, number__regex=capacity_pattern(kind, prefix)).count()


def require_small_layout_order(prefix, start, end):
    letters = f"[{SMALL_LETTERS}]"
    two_digits = "(?:0[1-9]|[1-9][0-9])"
    layouts = [
        (999, "(?:00[1-9]|0[1-9][0-9]|[1-9][0-9]{2})", "trzy cyfry"),
        (99 * len(SMALL_LETTERS), f"{two_digits}{letters}", "dwie cyfry i litera"),
        (9 * len(SMALL_LETTERS) * 9, f"[1-9]{letters}[1-9]", "cyfra, litera i cyfra"),
        (len(SMALL_LETTERS) * 99, f"{letters}{two_digits}", "litera i dwie cyfry"),
        (9 * len(SMALL_LETTERS) ** 2, f"[1-9]{letters}{{2}}", "cyfra i dwie litery"),
        (len(SMALL_LETTERS) ** 2 * 9, f"{letters}{{2}}[1-9]", "dwie litery i cyfra"),
    ]
    required = []
    first = 1
    for count, pattern, label in layouts:
        last = first + count - 1
        if end <= last:
            break
        required.append((first, last, count, f"^{prefix}{pattern}$", label))
        first = last + 1
    if not required:
        return
    # Jeden odczyt zbiorczy zamiast zapytania dla każdego wcześniejszego układu.
    counts = PoolSlot.objects.filter(pool__kind="II", number__startswith=prefix).aggregate(
        **{f"layout_{i}": Count("pk", filter=Q(number__regex=item[3])) for i, item in enumerate(required)}
    )
    for i, (first, last, count, _, label) in enumerate(required):
        occupied = counts[f"layout_{i}"]
        proposed = max(0, min(end, last) - max(start, first) + 1)
        if occupied + proposed != count:
            raise ValidationError(
                f"Najpierw przydziel cały wcześniejszy układ modułu II: {label} "
                f"(prefiks {prefix}, pozycje {first}–{last}). "
                f"W ewidencji jest {occupied} z {count} numerów tego układu; "
                "nowy zakres nie uzupełnia wszystkich brakujących. "
                "Wcześniejsze przydziały spoza systemu wymagają wprowadzenia do ewidencji."
            )


def require_capacity_order(kind, prefix, start, end):
    if prefix.startswith("M"):
        first_prefix = "P" if kind == "II" else "P[0-9]"
        required = len(SMALL_SUFFIXES) if kind == "II" else 10 * TEMPORARY_CAPACITY
        occupied = occupied_capacity(kind, first_prefix)
        if occupied != required:
            raise ValidationError(
                f"Nie można przydzielić puli z M: pojemność P w module {kind} "
                f"nie jest wyczerpana ({occupied} z {required} numerów w ewidencji). "
                "Wcześniejsze przydziały spoza systemu wymagają wprowadzenia do ewidencji."
            )
    if kind == "II":
        require_small_layout_order(prefix, start, end)
    if kind == "III" and end > TEMPORARY_NUMERIC_CAPACITY:
        numeric_pattern = f"^{prefix}(?:000[1-9]|00[1-9][0-9]|0[1-9][0-9]{{2}}|[1-9][0-9]{{3}})$"
        occupied = PoolSlot.objects.filter(pool__kind=kind, number__regex=numeric_pattern).count()
        # Zakres może w tej samej transakcji kończyć serię cyfrową i zaczynać
        # literową. Kolizje sprawdzono wcześniej dla całego nowego zakresu.
        proposed_numeric = max(0, TEMPORARY_NUMERIC_CAPACITY - start + 1)
        if occupied + proposed_numeric != TEMPORARY_NUMERIC_CAPACITY:
            raise ValidationError(
                f"Najpierw przydziel całą serię {prefix}0001–{prefix}9999. "
                f"W ewidencji jest {occupied} z {TEMPORARY_NUMERIC_CAPACITY} numerów; "
                "nowy zakres nie uzupełnia wszystkich brakujących."
            )
