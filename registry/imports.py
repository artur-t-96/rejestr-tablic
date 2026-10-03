import csv
import hashlib
from io import StringIO

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from .models import AuditLog, Office, PlateRecord
from .services import audit, require_role
from .tabular_sources import read_source
from .validation import validate_number, validate_vin

FIELDS = [
    "number",
    "owner",
    "office_id",
    "status",
    "vin",
    "make",
    "model",
    "registration_date",
    "sale_date",
    "buyer",
    "letter_number",
    "address",
    "note",
]
MAX_ROWS = 500
MAX_BYTES = 2_000_000


def preview_import(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES:
        raise ValidationError("Wybierz plik CSV UTF-8 do 2 MB.")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    reader = csv.DictReader(StringIO(text.removeprefix("\ufeff")), delimiter=";", strict=True)
    try:
        headers = reader.fieldnames
    except csv.Error as error:
        raise ValidationError("Niepoprawny nagłówek CSV; sprawdź cudzysłowy i separator średnik.") from error
    if (
        not headers
        or not {"number", "owner", "office_id"}.issubset(headers)
        or len(set(headers)) != len(headers)
        or set(headers) - set(FIELDS)
    ):
        raise ValidationError(
            "Użyj wzoru CSV. Wymagane: number;owner;office_id. Nagłówki muszą być unikalne i znane."
        )
    offices = {office.pk: office for office in Office.objects.filter(active=True)}
    raw_rows, errors = [], []
    try:
        for index, raw in enumerate(reader, 2):
            if index > MAX_ROWS + 1:
                errors.append(f"Maksymalnie {MAX_ROWS} wpisów w jednym imporcie.")
                break
            if None in raw or any(value is None for value in raw.values()):
                errors.append(f"Wiersz {index}: liczba wartości nie odpowiada nagłówkom CSV.")
                continue
            raw_rows.append((index, {field: (raw.get(field) or "").strip() for field in FIELDS}))
    except csv.Error:
        errors.append("Niepoprawna składnia CSV; sprawdź cudzysłowy i separator średnik.")
    requested = set()
    for _, raw in raw_rows:
        try:
            requested.add(validate_number(raw["number"]))
        except ValidationError:
            pass  # Błąd przypisujemy do konkretnego wiersza poniżej.
    active = set(
        PlateRecord.objects.filter(number__in=requested)
        .exclude(status="RELEASED")
        .values_list("number", flat=True)
    )
    rows, seen = [], set()
    today = timezone.localdate()
    for index, row in raw_rows:
        try:
            row["number"] = validate_number(row["number"])
            row["vin"] = validate_vin(row["vin"])
            row["status"] = row["status"] or "ALLOCATED"
            if row["status"] not in ["ALLOCATED", "ISSUED", "SOLD", "RELEASED"]:
                raise ValidationError("Import obsługuje przydzielone, wydane, zbyte i zwolnione wpisy.")
            if not row["owner"] or row["office_id"] not in offices:
                raise ValidationError("Podaj właściciela i istniejący aktywny urząd.")
            dates = {}
            for field in ["registration_date", "sale_date"]:
                dates[field] = parse_date(row[field]) if row[field] else None
                if row[field] and (dates[field] is None or dates[field].isoformat() != row[field]):
                    raise ValidationError("Daty muszą być poprawne i zapisane jako RRRR-MM-DD.")
                if dates[field] and dates[field] > today:
                    raise ValidationError("Historyczna data rejestracji lub zbycia nie może być przyszła.")
            if row["status"] != "RELEASED":
                if row["number"] in seen or row["number"] in active:
                    raise ValidationError("Numer koliduje z aktywną ewidencją lub innym wierszem.")
                seen.add(row["number"])
            if row["status"] in ["ISSUED", "SOLD"] and (not row["vin"] or not row["registration_date"]):
                raise ValidationError("Wydanie wymaga VIN i daty rejestracji.")
            if row["status"] == "SOLD" and (not row["sale_date"] or not row["buyer"]):
                raise ValidationError("Status pojazdu zbytego wymaga daty zbycia i nabywcy.")
            if row["sale_date"] and (
                not row["buyer"]
                or not row["registration_date"]
                or row["sale_date"] < row["registration_date"]
            ):
                raise ValidationError("Zbycie wymaga nabywcy i wcześniejszej rejestracji.")
            if row["sale_date"] and row["status"] not in ["SOLD", "RELEASED"]:
                raise ValidationError("Data zbycia wymaga statusu SOLD lub historycznego RELEASED.")
            candidate = PlateRecord(
                **{key: value or None if key in dates else value for key, value in row.items()}
            )
            # Kolizje sprawdzamy zbiorczo; ostateczną ochroną jest indeks bazy.
            candidate.full_clean(validate_unique=False, validate_constraints=False)
            rows.append(row)
        except (ValidationError, ValueError) as error:
            errors.append(f"Wiersz {index}: {error}")
    if not rows and not errors:
        errors.append("Plik nie zawiera danych.")
    return {
        "rows": rows,
        "errors": errors,
        "sha256": digest,
        "office_names": {key: office.name for key, office in offices.items()},
    }


def preview_source_import(source, filename="", sheet_name=""):
    metadata = read_source(
        source,
        filename,
        sheet_name,
        fields=FIELDS,
        date_fields={"registration_date", "sale_date"},
        max_rows=MAX_ROWS,
    )
    checked = preview_import(metadata["text"])
    checked.update({key: value for key, value in metadata.items() if key != "text"})
    return checked


@transaction.atomic
def apply_import(user, rows, ip=None, *, reason="Zatwierdzony import CSV", source=None):
    require_role(user, "MAIN")
    if not rows:
        raise ValidationError("Brak poprawnego podglądu do zatwierdzenia.")
    if not reason.strip() or len(reason) > 1000:
        raise ValidationError("Podaj uzasadnienie importu do 1000 znaków.")
    stream = StringIO()
    writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    checked = preview_import(stream.getvalue())
    if checked["errors"]:
        raise ValidationError(checked["errors"])
    try:
        with transaction.atomic():
            for row in sorted(checked["rows"], key=lambda row: row["number"]):
                data = dict(row)
                for field in ["registration_date", "sale_date"]:
                    data[field] = parse_date(data[field]) if data[field] else None
                record = PlateRecord.objects.create(**data)
                audit(
                    user,
                    "plate.imported",
                    record,
                    after={**row, **(source or {})},
                    reason=reason.strip(),
                    ip=ip,
                )
    except IntegrityError as exc:
        raise ValidationError(
            "Kolizja po podglądzie. Import nie zapisał żadnego wpisu; sprawdź ponownie."
        ) from exc
    return len(checked["rows"])


@transaction.atomic
def apply_source_import(user, text, expected_sha256, reason, filename="", ip=None, *, sheet_name=""):
    require_role(user, "MAIN")
    checked = preview_source_import(text, filename, sheet_name)
    if checked["sha256"] != expected_sha256:
        raise ValidationError("Plik zmienił się od podglądu. Sprawdź go ponownie.")
    if checked["errors"]:
        raise ValidationError(checked["errors"])
    # Jedna instancja ma jeden urząd główny. Serializujemy zatwierdzanie jego
    # wykazów, także wyłącznie zwolnionych wpisów bez aktywnego indeksu.
    # NO KEY UPDATE pozostaje zgodne z blokadami FK zwykłych spraw.
    Office.objects.select_for_update(no_key=True).get(pk=user.office_id)
    imported = AuditLog.objects.filter(action="plate.imported", after__source_sha256=checked["sha256"])
    if checked["source_sheet"]:
        imported = imported.filter(after__source_sheet=checked["source_sheet"])
    if imported.exists():
        raise ValidationError("Ten sam plik źródłowy został już zaimportowany. Sprawdź historię wpisów.")
    return apply_import(
        user,
        checked["rows"],
        ip,
        reason=reason,
        source={
            "source_sha256": checked["sha256"],
            "source_filename": filename[:255],
            "source_format": checked["source_format"],
            "source_sheet": checked["source_sheet"],
            "normalized_csv_sha256": checked["normalized_csv_sha256"],
            "historical_import": True,
            "original_allocation_date_unknown": True,
        },
    )
