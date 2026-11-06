import hashlib
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .demo import DOMAIN as DEMO_DOMAIN
from .demo import demo_viewer
from .models import AuditLog, Letter, Office, PlateRecord, Pool, PoolSlot, Request
from .suggestions import free_suggestions
from .validation import pool_numbers, validate_number, validate_part, validate_vin


def require_role(user, *roles):
    if not user.is_authenticated or not user.is_active or user.role not in roles:
        raise PermissionDenied("Brak uprawnienia do tej operacji.")
    if user.office_id and not user.office.active:
        raise PermissionDenied("Urząd jest nieaktywny.")


def require_account_manager(actor, target=None):
    """Konta zarządza administrator centralny albo administrator powiatu — tylko w swoim urzędzie.

    Administrator powiatu nie zmienia innego administratora powiatu ani kont spoza swojego urzędu.
    """
    if getattr(actor, "role", None) == "ADMIN":
        require_role(actor, "ADMIN")
        return
    require_role(actor, "COUNTY")
    if not actor.county_admin:
        raise PermissionDenied("Kontami urzędu zarządza administrator powiatu.")
    if target is not None and (
        target.office_id != actor.office_id
        or target.role != "COUNTY"
        or (target.county_admin and target.pk != actor.pk)
    ):
        raise PermissionDenied("Administrator powiatu zarządza wyłącznie kontami urzędników swojego urzędu.")


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


def lock_request(queryset, req_id):
    """W transakcji: zawsze wpis numeru → wniosek."""
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


def require_open_record(record):
    """Numer z wniosku pozostaje zajęty do rozpatrzenia albo wycofania; nie ma terminu."""
    if record and record.status not in {"RESERVED", "SENT"}:
        raise ValidationError("Numer z wniosku nie jest już zajęty przez ten wniosek.")


def availability(part, prefix="P", digit=None, *, viewer=None):
    part = validate_part(part)
    if prefix not in ("P", "M") or (
        digit is not None and (not isinstance(digit, int) or not 0 <= digit <= 9)
    ):
        raise ValidationError("Niepoprawny prefiks lub cyfra.")
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
                item["request_pending"] = item["number"] in pending
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
    if demo_viewer(user) and (
        Request.objects.filter(
            author__email__endswith="@" + DEMO_DOMAIN, created_at__gte=timezone.now() - timedelta(days=1)
        ).count()
        >= settings.DEMO_DAILY_REQUESTS
    ):
        # Wspólna instancja pokazowa: ograniczamy przyrost bazy powodowany przez konta demo.
        raise ValidationError("Dzienny limit wniosków w trybie demonstracyjnym został wyczerpany.")
    record = None
    if kind == "I":
        number = validate_number(data.get("number", ""))
        try:
            with transaction.atomic():
                record = PlateRecord.objects.create(
                    number=number,
                    office=office,
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
    count = 1 if kind == "I" else require_pool_count(data.get("count"))
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
        count=count,
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
    require_open_record(req.record)
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
    require_open_record(req.record)
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
def allocate_pool(user, data, req=None, ip=None, *, slots=None):
    """Zapis puli o wskazanym zakresie; interfejs i API korzystają z `allocate_block`.

    `slots` (pary pozycja, numer) przekazuje tylko `allocate_block`: wolne numery bloku.
    """
    require_role(user, "MAIN")
    office = Office.objects.get(pk=data["office"], active=True)
    kind, start, end = data["kind"], data["start"], data["end"]
    prefix = data.get("prefix", "P" if kind == "II" else "P0")
    automatic = slots is not None
    if slots is None:
        slots = list(enumerate(pool_numbers(kind, prefix, start, end), start))
    numbers = [number for _, number in slots]
    if req and (req.office_id != office.pk or req.kind != kind):
        raise ValidationError("Pula musi odpowiadać urzędowi i rodzajowi z wniosku.")
    pool = Pool(
        kind=kind,
        office=office,
        request=req,
        prefix=prefix,
        start=start,
        end=end,
        valid_from=data["valid_from"],
        valid_until=data.get("valid_until") or None,
        station=data.get("station", ""),
    )
    pool.full_clean()
    collision = PoolSlot.objects.filter(number__in=numbers).select_related("pool__office").first()
    if collision:
        raise ValidationError(
            f"Kolizja numeru {collision.number} z pulą urzędu: {collision.pool.office.name}."
        )
    if not automatic:
        from .pool_capacity import require_capacity_order

        # Bloki automatyczne idą kolejno i biorą wszystkie wolne numery bloku,
        # więc nie zostawiają luk; prefiks M wynika z decyzji UMP, nie z wyczerpania P.
        require_capacity_order(kind, prefix, start, end)
    try:
        with transaction.atomic():
            pool.save()
            PoolSlot.objects.bulk_create(
                sorted(
                    [PoolSlot(pool=pool, number=n, ordinal=ordinal) for ordinal, n in slots],
                    key=lambda slot: slot.number,
                )
            )
    except IntegrityError as exc:
        raise ValidationError("Inny przydział zajął ten zakres. Wybierz wolne numery.") from exc
    audit(
        user,
        "pool.allocated",
        pool,
        after={
            "kind": kind,
            "prefix": prefix,
            "start": start,
            "end": end,
            "first_number": numbers[0],
            "last_number": numbers[-1],
            "automatic": automatic,
        },
        ip=ip,
    )
    make_letter(user, "POOL", req=req, pool=pool, ip=ip)
    return pool


# Uwagi UMP z 06.11.2026: urząd wybiera liczbę numerów puli z listy 10, 20, …, 100.
POOL_COUNTS = tuple(range(10, 101, 10))


def require_pool_count(count):
    if type(count) is not int or count not in POOL_COUNTS:
        raise ValidationError("Liczba tablic w puli: wybierz 10, 20, 30, 40, 50, 60, 70, 80, 90 albo 100.")
    return count


def pool_capacity(kind):
    from .validation import SMALL_SUFFIXES, TEMPORARY_CAPACITY

    return len(SMALL_SUFFIXES) if kind == "II" else TEMPORARY_CAPACITY


def next_numbers(kind, after, count):
    """Kolejne `count` wolnych numerów po pozycji `after`: (początek, koniec, [(pozycja, numer)]).

    Numery zajęte wcześniej (np. z importu historycznego) zostają pominięte, więc kolejne
    układy numeracji nie czekają na brakujące pozycje. Brak tylu wolnych numerów zwraca None.
    """
    prefix = settings.POOL_BLOCKS[kind]["prefix"]
    capacity = pool_capacity(kind)
    position, free = after + 1, []
    while len(free) < count and position <= capacity:
        end = min(position + count - len(free) - 1, capacity)
        numbers = pool_numbers(kind, prefix, position, end)
        taken = set(PoolSlot.objects.filter(number__in=numbers).values_list("number", flat=True))
        free += [(ordinal, number) for ordinal, number in enumerate(numbers, position) if number not in taken]
        position = end + 1
    if len(free) < count:
        return None
    return free[0][0], free[-1][0], free


def pool_counter_scope(kind):
    return f"POOL.{kind}.{settings.POOL_BLOCKS[kind]['prefix']}"


def preview_block(kind, count):
    """Zakres, który dostanie najbliższy przydział; informacja, bez zajmowania numerów."""
    from .models import NumberSequence

    counter = NumberSequence.objects.filter(scope=pool_counter_scope(kind), year=1).first()
    found = next_numbers(kind, counter.last_value if counter else 0, count)
    return (found[2][0][1], found[2][-1][1]) if found else None


@transaction.atomic
def allocate_block(user, kind, office_id, count, *, req=None, ip=None):
    """Nadaje urzędowi `count` kolejnych wolnych numerów; zakres wylicza serwer pod blokadą licznika."""
    from .models import NumberSequence

    require_role(user, "MAIN")
    if kind not in settings.POOL_BLOCKS:
        raise ValidationError("Nieznany rodzaj puli.")
    require_pool_count(count)
    # Licznik ostatniej nadanej pozycji, bez roku (rok techniczny 1); blokada wiersza
    # serializuje równoczesne przydziały wszystkich urzędów.
    counter, _ = NumberSequence.objects.get_or_create(scope=pool_counter_scope(kind), year=1)
    counter = NumberSequence.objects.select_for_update().get(pk=counter.pk)
    found = next_numbers(kind, counter.last_value, count)
    if found is None:
        raise ValidationError("Pojemność numeracji tego rodzaju puli nie wystarcza na tyle numerów.")
    start, end, slots = found
    pool = allocate_pool(
        user,
        {
            "kind": kind,
            "office": office_id,
            "prefix": settings.POOL_BLOCKS[kind]["prefix"],
            "start": start,
            "end": end,
            "valid_from": timezone.localdate(),
            "valid_until": None,
        },
        req=req,
        ip=ip,
        slots=slots,
    )
    counter.last_value = end
    counter.save(update_fields=["last_value"])
    return pool


@transaction.atomic
def decide_request(user, req_id, approve, reason="", pool_data=None, ip=None):
    require_role(user, "MAIN")
    req = lock_request(Request.objects.all(), req_id)
    require_open_record(req.record)
    if req.status != "SENT":
        raise ValidationError("Wniosek nie oczekuje na rozpatrzenie.")
    if not approve and not reason.strip():
        raise ValidationError("Odmowa wymaga uzasadnienia.")
    if approve and req.record:
        validate_number(req.record.number)
    pool = None
    if req.record:
        record = req.record
        if record.status != "SENT":
            raise ValidationError("Nieaktualny stan wpisu numeru.")
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
        # Akceptacja wniosku o pulę nadaje kolejne wolne numery w liczbie z wniosku; zakres
        # podany jawnie służy wyłącznie wewnętrznym danym pokazowym i testom.
        pool = (
            allocate_pool(user, {**pool_data, "office": req.office_id, "kind": req.kind}, req=req, ip=ip)
            if pool_data
            else allocate_block(user, req.kind, req.office_id, req.count, req=req, ip=ip)
        )
        req.count = pool.total
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
    from .decision_notifications import enqueue_decision_notice

    enqueue_decision_notice(user, req, letter, ip=ip)
    return req


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
def update_record(user, record_id, data, reason, version, ip=None, action="plate.updated"):
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
        raise ValidationError("Ten status tworzy wyłącznie wniosek.")
    open_request = Request.objects.filter(record=record, status__in=["DRAFT", "SENT"]).exists()
    if status == "RELEASED" and open_request:
        raise ValidationError(
            "Nie można zwolnić numeru z aktywnym wnioskiem; wycofaj wniosek albo rozpatrz go."
        )
    if status != record.status and open_request:
        # Korekta nie może zastąpić rozpatrzenia: wniosek zostałby bez rozstrzygnięcia i pisma.
        raise ValidationError(
            "Status wpisu z otwartym wnioskiem zmienia rozpatrzenie albo wycofanie wniosku, nie korekta."
        )
    if (
        record.status == "RELEASED"
        and status != "RELEASED"
        and Request.objects.filter(record=record, status__in=["REJECTED", "WITHDRAWN", "EXPIRED"]).exists()
    ):
        raise ValidationError(
            "Ten wpis nie był przydziałem: wniosek odrzucono, wycofano albo wygasł. "
            "Nowy przydział wymaga nowego wniosku."
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
    audit(user, action, record, before, after, reason, ip)
    return record


TRANSFER_STATUSES = {"ALLOCATED", "ISSUED", "SOLD"}


@transaction.atomic
def transfer_record(user, record_id, data, reason, version, ip=None):
    """Pojazd przechodzi do innego urzędu: wpis zmienia urząd prowadzący, a numer pozostaje zajęty.

    To nie jest zwolnienie numeru. Zbycie zostaje w historii wpisu, a nowy urząd prowadzi
    wpis dalej z nowym właścicielem.
    """
    if user.role != "MAIN":
        raise PermissionDenied("Przeniesienie wpisu do innego urzędu wykonuje UMP.")
    record = visible(user, PlateRecord.objects.select_for_update()).get(uuid=record_id)
    if record.status not in TRANSFER_STATUSES:
        raise ValidationError("Przenieść można tylko wpis przydzielony, wydany albo z pojazdem zbytym.")
    office_id = data.get("office_id")
    if office_id == record.office_id:
        raise ValidationError("Wybierz urząd inny niż obecny urząd prowadzący.")
    if not Office.objects.filter(pk=office_id, active=True).exclude(kind="MAIN").exists():
        raise ValidationError("Wybierz aktywny urząd wnioskujący (starostwo lub miasto).")
    owner = (data.get("owner") or record.buyer or "").strip()
    if not owner:
        raise ValidationError("Podaj nowego właściciela pojazdu.")
    fields = {
        "office_id": office_id,
        "owner": owner,
        "address": (data.get("address") or "").strip(),
        # Numer zostaje w użyciu u nowego właściciela; zbycie jest już rozliczone przeniesieniem,
        # a jego dane zachowuje historia wpisu.
        "status": "ISSUED" if record.status == "SOLD" else record.status,
        "sale_date": None,
        "buyer": "",
    }
    if data.get("registration_date"):
        fields["registration_date"] = data["registration_date"]
    record = update_record(user, record_id, fields, reason, version, ip, action="plate.transferred")
    from .notifications import send_transfer_notice

    transaction.on_commit(lambda: send_transfer_notice(record.pk))
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
def record_postal_dispatch(user, letter, posted_at, reference, ip=None):
    """Odnotowuje nadanie papierowe; to oświadczenie urzędu, nie dowód doręczenia."""
    from .documents import lock_letter

    require_role(user, "COUNTY", "MAIN")
    if letter.office_id != user.office_id:
        raise PermissionDenied("Wysyłkę odnotowuje wyłącznie urząd nadawcy.")
    reference = (reference or "").strip()
    limit = Letter._meta.get_field("posted_reference").max_length
    if len(reference) > limit:
        raise ValidationError(f"Numer nadania może mieć najwyżej {limit} znaków.")
    letter = lock_letter(letter)
    if posted_at is None or posted_at > timezone.localdate():
        raise ValidationError("Podaj datę nadania nie późniejszą niż dzisiejsza.")
    if posted_at < timezone.localtime(letter.created_at).date():
        raise ValidationError("Data nadania nie może być wcześniejsza niż data pisma.")
    before = {"posted_at": scalar(letter.posted_at), "posted_reference": letter.posted_reference}
    letter.posted_at = posted_at
    letter.posted_reference = reference
    letter.posted_by = user
    letter.save(update_fields=["posted_at", "posted_reference", "posted_by"])
    audit(
        user,
        "letter.posted",
        letter,
        before if before["posted_at"] else None,
        {"posted_at": posted_at.isoformat(), "posted_reference": reference},
        ip=ip,
    )
    return letter


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
