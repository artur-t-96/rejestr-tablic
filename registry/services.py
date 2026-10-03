import hashlib
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import AuditLog, Letter, Office, PlateRecord, Pool, PoolSlot, Request
from .suggestions import free_suggestions
from .validation import pool_numbers, validate_number, validate_part, validate_vin


def require_role(user, *roles):
    if not user.is_authenticated or not user.is_active or user.role not in roles:
        raise PermissionDenied("Brak uprawnienia do tej operacji.")
    if user.office_id and not user.office.active:
        raise PermissionDenied("Urząd jest nieaktywny.")


def visible(user, queryset):
    require_role(user, "COUNTY", "MAIN")
    return queryset.filter(office_id=user.office_id) if user.role == "COUNTY" else queryset


def audit(actor, action, obj, before=None, after=None, reason="", ip=None):
    return AuditLog.objects.create(
        actor=actor,
        office_id=getattr(obj, "office_id", getattr(actor, "office_id", None)),
        action=action,
        object_type=obj.__class__.__name__,
        object_id=str(obj.pk),
        before=before or {},
        after=after or {},
        reason=reason,
        ip=ip,
    )


@transaction.atomic
def expire_reservations():
    records = (
        PlateRecord.objects.select_for_update()
        .filter(status__in=["RESERVED", "SENT"], reservation_until__lte=timezone.now())
        .order_by("pk")
    )
    count = 0
    for record in records:
        previous = record.status
        record.status = "RELEASED"
        record.version += 1
        record.save(update_fields=["status", "version"])
        requests = (
            Request.objects.select_for_update()
            .filter(record=record, status__in=["DRAFT", "SENT"])
            .order_by("pk")
        )
        for req in requests:
            old_status = req.status
            req.status = "EXPIRED"
            req.save(update_fields=["status"])
            audit(
                None,
                "request.expired",
                req,
                {"status": old_status, "reservation_until": record.reservation_until.isoformat()},
                {"status": "EXPIRED"},
                "Upłynął termin rezerwacji",
            )
        audit(
            None,
            "reservation.expired",
            record,
            {"status": previous, "reservation_until": record.reservation_until.isoformat()},
            {"status": "RELEASED"},
            "Upłynął termin rezerwacji",
        )
        count += 1
    return count


def lock_request(queryset, req_id):
    """W transakcji: zawsze rezerwacja → wniosek, również przy wygaszaniu."""
    snapshot = queryset.values("pk", "record_id").get(uuid=req_id)
    record = (
        PlateRecord.objects.select_for_update().get(pk=snapshot["record_id"])
        if snapshot["record_id"]
        else None
    )
    req = queryset.select_for_update().get(pk=snapshot["pk"])
    if req.record_id != snapshot["record_id"]:
        raise ValidationError("Powiązanie wniosku zmieniło się. Odśwież dane.")
    if record:
        req.record = record
    return req


def require_current_reservation(record):
    if record and (
        record.status not in {"RESERVED", "SENT"}
        or record.reservation_until is None
        or record.reservation_until <= timezone.now()
    ):
        raise ValidationError("Rezerwacja wygasła lub nie jest już aktywna.")


def availability(part, prefix="P", digit=None, *, viewer=None):
    part = validate_part(part)
    if prefix not in ("P", "M") or (
        digit is not None and (not isinstance(digit, int) or not 0 <= digit <= 9)
    ):
        raise ValidationError("Niepoprawny prefiks lub cyfra.")
    expire_reservations()
    occupied = set(PlateRecord.objects.exclude(status="RELEASED").values_list("number", flat=True))
    choices = [
        {
            "number": f"{prefix}{d}{part}",
            "available": f"{prefix}{d}{part}" not in occupied,
        }
        for d in (range(10) if digit is None else (digit,))
    ]
    if viewer is not None:
        try:
            scoped_records = visible(viewer, PlateRecord.objects.all())
        except PermissionDenied:
            pass
        else:
            pending = set(
                scoped_records.filter(
                    number__in=[item["number"] for item in choices],
                    status__in=["RESERVED", "SENT"],
                ).values_list("number", flat=True)
            )
            for item in choices:
                item["reservation_pending"] = item["number"] in pending
    return {
        "part": part,
        "prefix": prefix,
        "digits": choices,
        "suggestions": free_suggestions(part, prefix, digit, occupied),
    }


@transaction.atomic
def create_request(user, data, ip=None):
    require_role(user, "COUNTY", "MAIN")
    kind = data["kind"]
    if kind not in ["I", "II", "III"]:
        raise ValidationError("Niepoprawny typ wniosku.")
    if kind in ["II", "III"]:
        require_role(user, "COUNTY")
    office = user.office
    if not data.get("case_number", "").strip():
        raise ValidationError("Podaj numer sprawy.")
    expire_reservations()
    record = None
    if kind == "I":
        number = validate_number(data.get("number", ""))
        owner = data.get("owner", "").strip()
        if not owner:
            raise ValidationError("Podaj właściciela.")
        try:
            with transaction.atomic():
                record = PlateRecord.objects.create(
                    number=number,
                    office=office,
                    owner=owner,
                    address=data.get("address", ""),
                    vin=validate_vin(data.get("vin", "")),
                    reservation_until=timezone.now() + timedelta(days=settings.RESERVATION_DAYS),
                )
        except IntegrityError as exc:
            raise ValidationError("Ten wyróżnik został już zajęty. Wybierz inny numer.") from exc
        audit(
            user,
            "plate.reserved",
            record,
            after={"number": number, "status": "RESERVED"},
            ip=ip,
        )
    elif not data.get("justification", "").strip():
        raise ValidationError("Wniosek o pulę wymaga uzasadnienia.")
    count = int(data.get("count", 1))
    if not 1 <= count <= 10000:
        raise ValidationError("Liczba numerów musi wynosić 1–10 000.")
    from .numbering import request_number

    reference, reference_year, reference_ordinal = request_number()
    req = Request.objects.create(
        reference_number=reference,
        reference_year=reference_year,
        reference_ordinal=reference_ordinal,
        kind=kind,
        office=office,
        author=user,
        record=record,
        case_number=data["case_number"],
        count=count,
        station=data.get("station", ""),
        justification=data.get("justification", ""),
    )
    audit(user, "request.created", req, after={"status": req.status, "kind": kind}, ip=ip)
    make_letter(user, "APPLICATION", req=req, ip=ip)
    return req


@transaction.atomic
def send_request(user, req_id, ip=None):
    req = lock_request(visible(user, Request.objects.all()), req_id)
    if req.kind in ["II", "III"]:
        require_role(user, "COUNTY")
    require_current_reservation(req.record)
    if req.status != "DRAFT":
        raise ValidationError("Można złożyć tylko aktualny szkic wniosku.")
    if req.record:
        validate_number(req.record.number)
    req.status = "SENT"
    req.sent_at = timezone.now()
    req.save(update_fields=["status", "sent_at"])
    if req.record:
        previous = req.record.status
        req.record.status = "SENT"
        req.record.version += 1
        req.record.save(update_fields=["status", "version"])
        audit(user, "plate.submitted", req.record, {"status": previous}, {"status": "SENT"}, ip=ip)
    audit(user, "request.submitted", req, {"status": "DRAFT"}, {"status": "SENT"}, ip=ip)
    return req


@transaction.atomic
def withdraw_request(user, req_id, reason, ip=None):
    req = lock_request(visible(user, Request.objects.all()), req_id)
    require_current_reservation(req.record)
    if req.status not in ["DRAFT", "SENT"] or not reason.strip():
        raise ValidationError("Wycofanie wymaga aktywnego wniosku i uzasadnienia.")
    old = req.status
    req.status = "WITHDRAWN"
    req.reason = reason
    req.save(update_fields=["status", "reason"])
    if req.record:
        previous = req.record.status
        req.record.status = "RELEASED"
        req.record.version += 1
        req.record.save(update_fields=["status", "version"])
        audit(user, "plate.withdrawn", req.record, {"status": previous}, {"status": "RELEASED"}, reason, ip)
    audit(
        user,
        "request.withdrawn",
        req,
        {"status": old},
        {"status": req.status},
        reason,
        ip,
    )
    return req


@transaction.atomic
def allocate_pool(user, data, req=None, ip=None):
    require_role(user, "MAIN")
    office = Office.objects.get(pk=data["office"], active=True)
    kind, start, end = data["kind"], data["start"], data["end"]
    prefix = data.get("prefix", "P" if kind == "II" else "P0")
    numbers = pool_numbers(kind, prefix, start, end)
    if req and (req.office_id != office.pk or req.kind != kind or req.count != len(numbers)):
        raise ValidationError("Zakres musi odpowiadać urzędowi, rodzajowi i liczbie numerów z wniosku.")
    if kind == "III" and req is None:
        raise ValidationError("Moduł III wymaga zatwierdzanego wniosku urzędu.")
    pool = Pool(
        kind=kind,
        office=office,
        request=req,
        prefix=prefix,
        start=start,
        end=end,
        valid_from=data["valid_from"],
        valid_until=data.get("valid_until") or None,
        station=req.station if req else data.get("station", ""),
    )
    pool.full_clean()
    collision = PoolSlot.objects.filter(number__in=numbers).select_related("pool__office").first()
    if collision:
        raise ValidationError(
            f"Kolizja numeru {collision.number} z pulą urzędu: {collision.pool.office.name}."
        )
    from .pool_capacity import require_capacity_order

    require_capacity_order(kind, prefix, start, end)
    try:
        with transaction.atomic():
            pool.save()
            PoolSlot.objects.bulk_create(
                sorted(
                    [PoolSlot(pool=pool, number=n, ordinal=start + i) for i, n in enumerate(numbers)],
                    key=lambda slot: slot.number,
                )
            )
    except IntegrityError as exc:
        raise ValidationError("Inny przydział zajął ten zakres. Wybierz wolne numery.") from exc
    audit(
        user,
        "pool.allocated",
        pool,
        after={"kind": kind, "prefix": prefix, "start": start, "end": end},
        ip=ip,
    )
    make_letter(user, "POOL", req=req, pool=pool, ip=ip)
    return pool


@transaction.atomic
def decide_request(user, req_id, approve, reason="", pool_data=None, ip=None):
    require_role(user, "MAIN")
    req = lock_request(Request.objects.all(), req_id)
    require_current_reservation(req.record)
    if req.status != "SENT":
        raise ValidationError("Wniosek nie oczekuje na decyzję lub rezerwacja wygasła.")
    if not approve and not reason.strip():
        raise ValidationError("Odmowa wymaga uzasadnienia.")
    if approve and req.record:
        validate_number(req.record.number)
    pool = None
    if req.record:
        record = req.record
        if record.status != "SENT":
            raise ValidationError("Nieaktualny stan rezerwacji.")
        record.status = "ALLOCATED" if approve else "RELEASED"
        record.allocated_at = timezone.now() if approve else None
        record.reservation_until = None
        record.version += 1
        record.save()
        audit(
            user,
            "plate.decided",
            record,
            {"status": "SENT"},
            {"status": record.status},
            reason,
            ip,
        )
    elif approve:
        if not pool_data:
            raise ValidationError("Wskaż zakres puli.")
        pool = allocate_pool(
            user,
            {**pool_data, "office": req.office_id, "kind": req.kind},
            req=req,
            ip=ip,
        )
    req.status = "APPROVED" if approve else "REJECTED"
    req.reason = reason
    req.decided_by = user
    req.decided_at = timezone.now()
    req.save()
    audit(
        user,
        "request.decided",
        req,
        {"status": "SENT"},
        {"status": req.status},
        reason,
        ip,
    )
    if not pool:
        letter = make_letter(user, "APPROVAL" if approve else "REJECTION", req=req, ip=ip)
        if req.record and approve:
            PlateRecord.objects.filter(pk=req.record_id).update(letter_number=letter.number)
    else:
        letter = pool.letters.get(kind="POOL")
    if req.kind == "III":
        from .decision_notifications import enqueue_decision_notice

        enqueue_decision_notice(user, req, letter, ip=ip)
    return req


@transaction.atomic
def extend_reservation(user, record_id, days, reason, ip=None):
    require_role(user, "MAIN")
    record = PlateRecord.objects.select_for_update().get(uuid=record_id)
    require_current_reservation(record)
    if record.status not in ["RESERVED", "SENT"] or not reason.strip() or not 1 <= int(days) <= 90:
        raise ValidationError("Podaj powód i przedłużenie 1–90 dni dla aktywnej rezerwacji.")
    before = record.reservation_until.isoformat()
    record.reservation_until = max(record.reservation_until, timezone.now()) + timedelta(days=int(days))
    record.version += 1
    record.save(update_fields=["reservation_until", "version"])
    audit(
        user,
        "reservation.extended",
        record,
        {"reservation_until": before},
        {"reservation_until": record.reservation_until.isoformat()},
        reason,
        ip,
    )
    return record


EDIT_FIELDS = [
    "owner",
    "address",
    "office_id",
    "status",
    "vin",
    "make",
    "model",
    "registration_date",
    "sale_date",
    "buyer",
    "letter_number",
    "note",
]
COUNTY_FIELDS = ["vin", "make", "model", "registration_date", "sale_date", "buyer"]


def scalar(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


@transaction.atomic
def update_record(user, record_id, data, reason, version, ip=None):
    record = visible(user, PlateRecord.objects.select_for_update()).get(uuid=record_id)
    if record.version != int(version):
        raise ValidationError(
            "Wpis zmienił się od otwarcia formularza. Odśwież stronę i sprawdź aktualne dane."
        )
    if not reason.strip():
        raise ValidationError("Podaj powód zmiany.")
    allowed = EDIT_FIELDS if user.role == "MAIN" else COUNTY_FIELDS
    if set(data) - set(allowed):
        raise PermissionDenied("Próba zmiany pola poza zakresem uprawnień.")
    if "office_id" in data and data["office_id"] != record.office_id:
        if Request.objects.filter(record=record, status__in=["DRAFT", "SENT"]).exists():
            raise ValidationError("Nie można zmienić urzędu, gdy wniosek czeka na rozpatrzenie.")
        if not Office.objects.filter(pk=data["office_id"], active=True).exists():
            raise ValidationError("Wybierz istniejący aktywny urząd prowadzący.")
    if user.role == "COUNTY" and record.status not in ["ALLOCATED", "ISSUED", "SOLD"]:
        raise ValidationError("Dane pojazdu można uzupełnić dopiero po przydziale.")
    before = {k: scalar(getattr(record, k)) for k in set(data) | {"status"}}
    if "vin" in data:
        data["vin"] = validate_vin(data["vin"])
    status = data.get("status", record.status)
    if status in ["RESERVED", "SENT"] and status != record.status:
        raise ValidationError("Rezerwację tworzy wyłącznie wniosek.")
    if status == "RELEASED" and Request.objects.filter(record=record, status__in=["DRAFT", "SENT"]).exists():
        raise ValidationError(
            "Nie można zwolnić numeru z aktywnym wnioskiem; wycofaj wniosek lub podejmij decyzję."
        )
    for key, value in data.items():
        setattr(record, key, value)
    if user.role == "COUNTY":
        if record.sale_date:
            record.status = "SOLD"
        elif record.registration_date:
            record.status = "ISSUED"
    if record.sale_date and (
        not record.buyer or not record.registration_date or record.sale_date < record.registration_date
    ):
        raise ValidationError("Sprzedaż wymaga nabywcy i wcześniejszej daty rejestracji.")
    if record.status in ["ISSUED", "SOLD"] and (not record.vin or not record.registration_date):
        raise ValidationError("Wydanie wymaga VIN i daty rejestracji.")
    if (before["status"] == "RELEASED" and record.status != "RELEASED") or (
        before["status"] not in {"ISSUED", "SOLD"} and record.status in {"ISSUED", "SOLD"}
    ):
        # Dawne wpisy zachowują historię, ale nie mogą omijać aktualnych reguł
        # przy ponownym przydziale ani przy pierwszym wydaniu.
        validate_number(record.number)
    record.version += 1
    record.full_clean()
    try:
        with transaction.atomic():
            record.save()
    except IntegrityError as exc:
        raise ValidationError("Numer jest już zajęty przez inny aktywny wpis.") from exc
    after = {k: scalar(getattr(record, k)) for k in data}
    after["status"] = record.status
    audit(user, "plate.updated", record, before, after, reason, ip)
    return record


@transaction.atomic
def issue_slot(user, pool_id, slot_id, case_number, ip=None):
    pool = visible(user, Pool.objects.select_for_update()).get(uuid=pool_id)
    today = timezone.localdate()
    if pool.valid_from > today or (pool.valid_until and pool.valid_until < today):
        raise ValidationError("Pula nie obowiązuje w dniu wydania.")
    if type(slot_id) is not int or slot_id < 1:
        raise ValidationError("Wskaż numer puli przez dodatni identyfikator całkowity.")
    if not isinstance(case_number, str) or not case_number.strip():
        raise ValidationError("Podaj numer sprawy wydania.")
    if len(case_number) > PoolSlot._meta.get_field("case_number").max_length:
        raise ValidationError("Numer sprawy wydania może mieć najwyżej 100 znaków.")
    slot = pool.slots.select_for_update().get(pk=slot_id)
    if slot.issued_at:
        raise ValidationError("Ten numer został już wydany.")
    slot.issued_at = timezone.now()
    slot.issued_by = user
    slot.case_number = case_number
    slot.save()
    audit(
        user,
        "pool.number_issued",
        pool,
        after={"number": slot.number, "case_number": case_number},
        ip=ip,
    )
    return slot


@transaction.atomic
def make_letter(user, kind, req=None, pool=None, *, ip=None):
    from .documents import letter_content, render_pdf
    from .numbering import letter_number

    sender = req.office if kind == "APPLICATION" else Office.objects.get(kind="MAIN")
    recipient = (
        Office.objects.get(kind="MAIN") if kind == "APPLICATION" else (pool.office if pool else req.office)
    )
    title, body, revision = letter_content(kind, req, pool, sender, recipient)
    number, number_year, number_ordinal = letter_number(sender)
    letter = Letter.objects.create(
        number=number,
        number_year=number_year,
        number_ordinal=number_ordinal,
        kind=kind,
        office=sender,
        recipient=recipient,
        request=req,
        pool=pool,
        title=title,
        body=body,
        template_revision=revision,
        pdf=b"",
        sha256="",
    )
    pdf = render_pdf(letter)
    letter.pdf = pdf
    letter.sha256 = hashlib.sha256(pdf).hexdigest()
    letter.save(update_fields=["pdf", "sha256"])
    audit(
        user,
        "letter.generated",
        letter,
        after={"number": letter.number, "sha256": letter.sha256},
        ip=ip,
    )
    return letter


@transaction.atomic
def create_letter_revision(user, letter, reason, ip=None):
    from .documents import lock_letter, render_pdf
    from .numbering import letter_number

    require_role(user, "COUNTY", "MAIN")
    if letter.office_id != user.office_id:
        raise PermissionDenied("Nową wersję pisma tworzy wyłącznie urząd nadawcy.")
    if not reason.strip() or len(reason) > 500:
        raise ValidationError("Podaj uzasadnienie utworzenia nowej wersji (do 500 znaków).")
    source = lock_letter(letter)
    number, number_year, number_ordinal = letter_number(source.office)
    new = Letter.objects.create(
        number=number,
        number_year=number_year,
        number_ordinal=number_ordinal,
        replaces=source,
        kind=source.kind,
        office=source.office,
        recipient=source.recipient,
        request=source.request,
        pool=source.pool,
        title=source.title,
        body=source.body,
        template_revision=source.template_revision,
        pdf=b"",
        sha256="",
    )
    new.pdf = render_pdf(new)
    new.sha256 = hashlib.sha256(new.pdf).hexdigest()
    new.save(update_fields=["pdf", "sha256"])
    audit(
        user,
        "letter.revised",
        new,
        after={"replaces": str(source.uuid), "sha256": new.sha256},
        reason=reason,
        ip=ip,
    )
    return new
