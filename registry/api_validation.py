import json
import re
from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError

from .services import COUNTY_FIELDS, EDIT_FIELDS


def parse_payload(body):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValidationError(f"Powtórzone pole JSON: {key}.")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValidationError(f"Niedozwolona wartość JSON: {value}.")

    try:
        payload = json.loads(body or "{}", object_pairs_hook=unique_object, parse_constant=invalid_constant)
    except RecursionError as error:
        raise ValidationError("Zbyt głęboko zagnieżdżona treść JSON.") from error
    if not isinstance(payload, dict):
        raise ValidationError("Treść żądania musi być obiektem JSON.")
    if "reason" in payload and not isinstance(payload["reason"], str):
        raise ValidationError("Pole reason musi być tekstem.")
    return payload


def iso_date(value, name, *, allow_empty=False):
    if allow_empty and (value is None or value == ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValidationError(f"Pole {name}: podaj datę w formacie RRRR-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValidationError(f"Pole {name}: podaj istniejącą datę kalendarzową.") from error


def typed_values(payload, *, text=(), positive=(), booleans=(), dates=(), optional_dates=(), required=()):
    if not isinstance(payload, dict):
        raise ValidationError("Dane operacji muszą być obiektem JSON.")
    allowed = set(text) | set(positive) | set(booleans) | set(dates) | set(optional_dates)
    if set(payload) - allowed:
        raise ValidationError("Nieobsługiwane pola: " + ", ".join(sorted(set(payload) - allowed)) + ".")
    if set(required) - set(payload):
        raise ValidationError("Brak wymaganych pól: " + ", ".join(sorted(set(required) - set(payload))) + ".")
    result = payload.copy()
    for key, value in payload.items():
        if key in positive:
            if type(value) is not int or value < 1:
                raise ValidationError(f"Pole {key} musi być dodatnią liczbą całkowitą JSON.")
        elif key in booleans:
            if not isinstance(value, bool):
                raise ValidationError(f"Pole {key} musi być wartością logiczną.")
        elif key in dates or key in optional_dates:
            result[key] = iso_date(value, key, allow_empty=key in optional_dates)
        elif not isinstance(value, str):
            raise ValidationError(f"Pole {key} musi być tekstem.")
    return result


def request_values(payload):
    return typed_values(
        payload,
        text=("kind", "number", "owner", "address", "vin", "case_number", "station", "justification"),
        positive=("count",),
    )


def pool_values(payload, *, decision=False):
    return typed_values(
        payload,
        text=("prefix",) if decision else ("kind", "office", "prefix", "station"),
        positive=("start", "end"),
        dates=("valid_from",),
        optional_dates=("valid_until",),
        required=("prefix", "start", "end", "valid_from") if decision else (),
    )


def decision_values(payload, kind):
    pool = payload.get("pool")
    values = typed_values(
        {key: value for key, value in payload.items() if key != "pool"},
        booleans=("approve",),
        text=("reason",),
        required=("approve",),
    )
    if kind == "I" or not values["approve"]:
        if pool is not None:
            raise ValidationError("Ta decyzja nie przydziela puli; pomiń pole pool.")
        return values, None
    return values, pool_values(pool, decision=True)


def record_patch(payload, role):
    """Validate JSON types before Django can coerce or clear persisted fields."""
    fields = payload.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise ValidationError("Pole fields musi być niepustym obiektem JSON.")
    allowed = EDIT_FIELDS if role == "MAIN" else COUNTY_FIELDS
    if set(fields) - set(allowed):
        raise PermissionDenied("Próba zmiany pola poza zakresem uprawnień.")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("Pole reason musi zawierać tekstowy powód zmiany.")
    version = payload.get("version")
    if type(version) is not int or version < 1:
        raise ValidationError("Pole version musi być dodatnią liczbą całkowitą.")
    data = fields.copy()
    for key, value in fields.items():
        if key in {"registration_date", "sale_date"}:
            data[key] = iso_date(value, key, allow_empty=True)
        elif not isinstance(value, str):
            raise ValidationError(f"Pole {key} musi być tekstem.")
    return data, reason, version
