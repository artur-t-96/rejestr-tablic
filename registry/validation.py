import re

from django.core.exceptions import ValidationError


def normalize(value):
    return re.sub(r"\s+", "", str(value)).upper()


def display_number(number):
    """Zapis jak na tablicy: litera województwa i cyfra, odstęp, wyróżnik."""
    return number[:2] + " " + number[2:]


def validate_part(value):
    part = normalize(value)
    # § 30 ust. 1 i ust. 2 pkt 4 rozporządzenia Dz.U. 2024 poz. 1709:
    # alfabet obejmuje 25 liter (bez Q); cyfry tylko na dwóch ostatnich pozycjach.
    if not 3 <= len(part) <= 5 or not re.fullmatch(r"[A-PR-Z]+[A-PR-Z0-9]{2}", part):
        raise ValidationError(
            "Wpisz 3–5 znaków. Litery A–Z z wyjątkiem Q; cyfry mogą zajmować tylko dwie ostatnie pozycje."
        )
    return part


def validate_number(value):
    number = normalize(value)
    if not re.fullmatch(r"[PM][0-9].{3,5}", number):
        raise ValidationError("Numer musi zaczynać się od P lub M oraz cyfry 0–9.")
    validate_part(number[2:])
    return number


# Uwagi UMP z 15.11.2026: jeden wniosek o serię numerów, np. P1MAJA1 – P1MAJA9.
SERIES_MAX = 99


def series_numbers(first, last):
    """Kolejne numery serii różniące się wyłącznie końcowymi cyframi; obie granice włącznie."""
    first, last = validate_number(first), validate_number(last)
    head, digits = re.fullmatch(r"(.*?)(\d*)", first).groups()
    last_head, last_digits = re.fullmatch(r"(.*?)(\d*)", last).groups()
    if (
        len(head) < 3
        or not digits
        or head != last_head
        or len(digits) != len(last_digits)
        or int(last_digits) <= int(digits)
    ):
        raise ValidationError(
            "Seria: numery muszą różnić się tylko końcowymi cyframi, rosnąco, np. P1 MAJA1 – P1 MAJA9."
        )
    width = len(digits)
    numbers = [f"{head}{n:0{width}d}" for n in range(int(digits), int(last_digits) + 1)]
    if len(numbers) > SERIES_MAX:
        raise ValidationError(f"Seria może liczyć najwyżej {SERIES_MAX} numerów.")
    for number in numbers:
        validate_number(number)
    return numbers


SMALL_LETTERS = "ACEFGHJKLMNPRSTUVWXY"


def small_suffixes():
    # Kolejność pojemności zgodna z § 30 ust. 2 pkt 2; § 31 wyłącza B D I O Z.
    yield from (f"{n:03d}" for n in range(1, 1000))
    yield from (f"{n:02d}{a}" for n in range(1, 100) for a in SMALL_LETTERS)
    yield from (f"{n}{a}{m}" for n in range(1, 10) for a in SMALL_LETTERS for m in range(1, 10))
    yield from (f"{a}{n:02d}" for a in SMALL_LETTERS for n in range(1, 100))
    yield from (f"{n}{a}{b}" for n in range(1, 10) for a in SMALL_LETTERS for b in SMALL_LETTERS)
    yield from (f"{a}{b}{n}" for a in SMALL_LETTERS for b in SMALL_LETTERS for n in range(1, 10))
    yield from (f"{a}{n}{b}" for a in SMALL_LETTERS for n in range(1, 10) for b in SMALL_LETTERS)


SMALL_SUFFIXES = tuple(small_suffixes())
TEMPORARY_NUMERIC_CAPACITY = 9999
TEMPORARY_CAPACITY = TEMPORARY_NUMERIC_CAPACITY + 999 * len(SMALL_LETTERS)


def temporary_suffix(position):
    if position <= TEMPORARY_NUMERIC_CAPACITY:
        return f"{position:04d}"
    letter, number = divmod(position - TEMPORARY_NUMERIC_CAPACITY - 1, 999)
    return f"{number + 1:03d}{SMALL_LETTERS[letter]}"


def pool_numbers(kind, prefix, start, end, scheme="NUMERIC"):
    if type(start) is not int or type(end) is not int or start < 1 or end < start or end - start >= 10000:
        raise ValidationError("Zakres musi być rosnący, dodatni i liczyć najwyżej 10 000 numerów.")
    if scheme != "NUMERIC":
        raise ValidationError("Nieobsługiwany schemat numeracji puli.")
    if kind == "II":
        if prefix not in ("P", "M") or end > len(SMALL_SUFFIXES):
            raise ValidationError("Niepoprawny prefiks lub zakres tablic zmniejszonych.")
        return [prefix + SMALL_SUFFIXES[n - 1] for n in range(start, end + 1)]
    if kind == "III":
        # Robocza klasyfikacja jako tablice tymczasowe, do potwierdzenia przez UMP.
        if not re.fullmatch(r"[PM][0-9]", prefix) or end > TEMPORARY_CAPACITY:
            raise ValidationError(
                f"Dla tablic tymczasowych wybierz prefiks P0–P9 lub M0–M9 i pozycje 1–{TEMPORARY_CAPACITY}."
            )
        return [prefix + temporary_suffix(n) for n in range(start, end + 1)]
    raise ValidationError("Nieznany rodzaj puli.")


def validate_vin(value):
    vin = normalize(value)
    if vin and not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin):
        raise ValidationError("VIN musi mieć 17 znaków; litery I, O i Q są niedozwolone.")
    return vin
