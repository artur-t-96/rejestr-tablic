"""Jawny import historycznej listy numerów; nie jest nowym przydziałem."""

import csv
import hashlib
from datetime import datetime, time
from functools import lru_cache
from io import StringIO

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from .models import Office, Pool, PoolSlot
from .services import audit, require_role
from .tabular_sources import read_source
from .validation import SMALL_LETTERS, SMALL_SUFFIXES, normalize, pool_numbers

FIELDS = [
    "pool_ref",
    "kind",
    "office_id",
    "prefix",
    "number",
    "valid_from",
    "valid_until",
    "station",
    "issued_on",
    "case_number",
    "source_reference",
]
REQUIRED = {"pool_ref", "kind", "office_id", "prefix", "number", "valid_from", "source_reference"}
METADATA = ("kind", "office_id", "prefix", "valid_from", "valid_until", "station", "source_reference")
MAX_ROWS = 5000
MAX_POOLS = 100
MAX_BYTES = 2_000_000


@lru_cache(maxsize=1)
def small_positions():
    return {suffix: position for position, suffix in enumerate(SMALL_SUFFIXES, 1)}


def number_position(kind, prefix, number):
    if not number.startswith(prefix):
        raise ValidationError("Numer nie odpowiada prefiksowi puli.")
    suffix = number[len(prefix) :]
    try:
        if kind == "II":
            position = small_positions()[suffix]
        elif kind == "III" and len(suffix) == 4:
            position = (
                int(suffix)
                if suffix.isascii() and suffix.isdigit()
                else 9999 + 999 * SMALL_LETTERS.index(suffix[-1]) + int(suffix[:3])
            )
        else:
            raise ValueError
        if pool_numbers(kind, prefix, position, position) != [number]:
            raise ValueError
    except (KeyError, ValueError, IndexError) as error:
        raise ValidationError("Niepoprawny numer dla rodzaju i prefiksu puli.") from error
    return position


def preview_pool_import(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES:
        raise ValidationError("Wybierz plik CSV UTF-8 do 2 MB.")
    source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    reader = csv.DictReader(StringIO(text.removeprefix("\ufeff")), delimiter=";", strict=True)
    try:
        fieldnames = reader.fieldnames
    except csv.Error as error:
        raise ValidationError("Niepoprawny nagłówek CSV; sprawdź cudzysłowy i separator średnik.") from error
    if (
        not fieldnames
        or not REQUIRED.issubset(fieldnames)
        or len(set(fieldnames)) != len(fieldnames)
        or set(fieldnames) - set(FIELDS)
    ):
        raise ValidationError(
            "Niepoprawne nagłówki CSV. Użyj wzoru wykazu pul; każdy nagłówek musi być unikalny."
        )
    offices = {o.pk: o for o in Office.objects.all()}
    rows, groups, errors, seen = [], {}, [], set()
    today = timezone.localdate()
    try:
        for index, raw in enumerate(reader, 2):
            if index > MAX_ROWS + 1:
                errors.append(f"Maksymalnie {MAX_ROWS} numerów w jednym imporcie.")
                break
            try:
                if None in raw or any(value is None for value in raw.values()):
                    raise ValidationError("Liczba wartości nie odpowiada nagłówkom CSV.")
                row = {field: (raw.get(field) or "").strip() for field in FIELDS}
                row["prefix"], row["number"] = normalize(row["prefix"]), normalize(row["number"])
                for field, limit in (
                    ("pool_ref", 100),
                    ("station", 180),
                    ("case_number", 100),
                    ("source_reference", 200),
                ):
                    if len(row[field]) > limit:
                        raise ValidationError(f"Kolumna {field}: najwyżej {limit} znaków.")
                if not row["pool_ref"] or not row["source_reference"]:
                    raise ValidationError("Podaj oznaczenie puli i dokument źródłowy.")
                office = offices.get(row["office_id"])
                if office is None:
                    raise ValidationError("Urząd nie istnieje w słowniku instancji.")
                dates = {}
                for field in ("valid_from", "valid_until", "issued_on"):
                    dates[field] = parse_date(row[field]) if row[field] else None
                    if row[field] and (dates[field] is None or dates[field].isoformat() != row[field]):
                        raise ValidationError("Daty muszą mieć poprawny format RRRR-MM-DD.")
                if not dates["valid_from"] or dates["valid_from"] > today:
                    raise ValidationError("Historyczna pula musi mieć datę początku nie późniejszą niż dziś.")
                if row["kind"] not in ("II", "III"):
                    raise ValidationError("Rodzaj puli musi być II lub III.")
                if row["kind"] == "III" and not dates["valid_until"]:
                    raise ValidationError("Podaj termin końca puli modułu III.")
                if dates["valid_until"] and dates["valid_until"] < dates["valid_from"]:
                    raise ValidationError("Koniec puli nie może poprzedzać początku.")
                if bool(row["issued_on"]) != bool(row["case_number"]):
                    raise ValidationError(
                        "Wydany numer wymaga daty i numeru sprawy; niewydany pozostawia oba pola puste."
                    )
                if dates["issued_on"] and (
                    dates["issued_on"] < dates["valid_from"]
                    or dates["issued_on"] > today
                    or (dates["valid_until"] and dates["issued_on"] > dates["valid_until"])
                ):
                    raise ValidationError(
                        "Data wydania musi mieścić się w okresie puli i nie może być przyszła."
                    )
                row["ordinal"] = number_position(row["kind"], row["prefix"], row["number"])
                if row["number"] in seen:
                    raise ValidationError("Numer powtarza się w pliku, także między różnymi pulami.")
                existing = groups.get(row["pool_ref"])
                if existing and any(existing[key] != row[key] for key in METADATA):
                    raise ValidationError("Wiersze tej samej puli mają sprzeczne metadane.")
                if not existing:
                    if len(groups) >= MAX_POOLS:
                        raise ValidationError(f"Maksymalnie {MAX_POOLS} pul w jednym imporcie.")
                    existing = {
                        **{key: row[key] for key in METADATA},
                        "pool_ref": row["pool_ref"],
                        "office_name": office.name,
                        "rows": [],
                    }
                    groups[row["pool_ref"]] = existing
                existing["rows"].append(row)
                rows.append(row)
                seen.add(row["number"])
            except (ValidationError, ValueError) as error:
                errors.append(f"Wiersz {index}: {error}")
    except csv.Error:
        errors.append("Niepoprawna składnia CSV; sprawdź cudzysłowy i separator średnik.")
    collisions = PoolSlot.objects.filter(number__in=seen).select_related("pool__office")
    for collision in collisions[:100]:
        errors.append(f"Numer {collision.number} jest już w puli urzędu {collision.pool.office.name}.")
    if not rows and not errors:
        errors.append("Plik nie zawiera numerów.")
    summaries = []
    for group in groups.values():
        ordered = sorted(group["rows"], key=lambda row: row["ordinal"])
        group.update(start=ordered[0]["ordinal"], end=ordered[-1]["ordinal"])
        candidate = Pool(
            **{
                key: group[key] or None if key == "valid_until" else group[key]
                for key in ("kind", "office_id", "prefix", "valid_from", "valid_until", "station")
            },
            start=group["start"],
            end=group["end"],
        )
        try:
            candidate.full_clean()
        except ValidationError as error:
            errors.append(f"Pula {group['pool_ref']}: {error}")
        summaries.append(
            {
                **{key: value for key, value in group.items() if key != "rows"},
                "count": len(ordered),
                "issued": sum(bool(r["issued_on"]) for r in ordered),
                "first": ordered[0]["number"],
                "last": ordered[-1]["number"],
            }
        )
    return {"rows": rows, "groups": summaries, "errors": errors, "sha256": source_sha256}


def preview_pool_source(source, filename="", sheet_name=""):
    metadata = read_source(
        source,
        filename,
        sheet_name,
        fields=FIELDS,
        date_fields={"valid_from", "valid_until", "issued_on"},
        max_rows=MAX_ROWS,
    )
    checked = preview_pool_import(metadata["text"])
    checked.update({key: value for key, value in metadata.items() if key != "text"})
    return checked


@transaction.atomic
def apply_pool_import(user, text, expected_sha256, reason, filename="", ip=None, *, sheet_name=""):
    require_role(user, "MAIN")
    if not reason.strip() or len(reason) > 1000:
        raise ValidationError("Podaj uzasadnienie importu do 1000 znaków.")
    checked = preview_pool_source(text, filename, sheet_name)
    if checked["sha256"] != expected_sha256:
        raise ValidationError("Plik zmienił się od podglądu. Sprawdź go ponownie.")
    if checked["errors"]:
        raise ValidationError(checked["errors"])
    pools = []
    all_slots = []
    try:
        with transaction.atomic():
            for group in checked["groups"]:
                pool = Pool.objects.create(
                    **{
                        key: parse_date(group[key]) if key in ("valid_from", "valid_until") else group[key]
                        for key in (
                            "kind",
                            "office_id",
                            "prefix",
                            "start",
                            "end",
                            "valid_from",
                            "valid_until",
                            "station",
                        )
                    }
                )
                for row in checked["rows"]:
                    if row["pool_ref"] != group["pool_ref"]:
                        continue
                    issued_at = (
                        timezone.make_aware(datetime.combine(parse_date(row["issued_on"]), time.min))
                        if row["issued_on"]
                        else None
                    )
                    all_slots.append(
                        PoolSlot(
                            pool=pool,
                            number=row["number"],
                            ordinal=row["ordinal"],
                            issued_at=issued_at,
                            case_number=row["case_number"],
                        )
                    )
                audit(
                    user,
                    "pool.imported",
                    pool,
                    after={
                        **group,
                        "source_sha256": checked["sha256"],
                        "source_filename": filename[:255],
                        "source_format": checked["source_format"],
                        "source_sheet": checked["source_sheet"],
                        "normalized_csv_sha256": checked["normalized_csv_sha256"],
                        "original_issuer_unknown": True,
                        "issuance_precision": "date",
                    },
                    reason=reason.strip(),
                    ip=ip,
                )
                pools.append(pool)
            # Ten sam porządek unikalnych kluczy co w nowym przydziale.
            # Grupy i wiersze pliku mogą występować w dowolnej kolejności.
            PoolSlot.objects.bulk_create(sorted(all_slots, key=lambda slot: slot.number), batch_size=1000)
    except IntegrityError as error:
        raise ValidationError(
            "Kolizja po podglądzie. Nie zapisano żadnej puli ani numeru; sprawdź plik ponownie."
        ) from error
    return pools
