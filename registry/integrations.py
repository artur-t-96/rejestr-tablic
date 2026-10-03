"""Kolejka z trwałymi etapami i blokadą niejednoznacznych ponowień."""

import hashlib
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from .connectors.ezdrp import ConnectorError, EZDRPClient, load_profile, opaque_id
from .documents import document_payload, lock_letter
from .models import EZDCaseLink, IntegrationJob, Letter, Office
from .microsoft_mail import configuration_ready, transport_name
from .services import audit, require_role


def configuration_status(office_id=None):
    from .connectors.edor import load_profile as load_edor_profile

    try:
        if office_id:
            load_profile(office_id)
        ezd_configured = bool(office_id)
        ezd_description = "Zapis PDF w sprawie EZD RP API v2. Wysyłka korespondencji jest osobną operacją."
    except ConnectorError as exc:
        ezd_configured = False
        ezd_description = str(exc)
    try:
        profile = load_edor_profile(office_id)
        edor_configured = True
        edor_description = f"Przesyłki elektroniczne, statusy i dowody. Środowisko: {profile.environment}."
    except ConnectorError as exc:
        edor_configured = False
        edor_description = str(exc)
    return [
        {
            "id": "EZD",
            "name": "EZD RP",
            "configured": ezd_configured,
            "description": ezd_description,
            "mode": "Brak testu z rzeczywistą usługą",
        },
        {
            "id": "EDOR",
            "name": "e-Doręczenia",
            "configured": edor_configured,
            "description": edor_description,
            "mode": "Brak testu z rzeczywistą usługą",
        },
        {
            "id": "SMTP",
            "name": "Poczta e-mail",
            "configured": configuration_ready(),
            "description": "Wiadomości lokalne są zapisywane w prywatnym katalogu poczty."
            if settings.LOCAL
            else "Wysyłka przez skonfigurowaną pocztę.",
            "mode": "Lokalna skrzynka plikowa" if settings.LOCAL else transport_name(),
        },
    ]


@transaction.atomic
def enqueue(user, letter, provider, ip=None):
    require_role(user, "COUNTY", "MAIN")
    if user.office_id != letter.office_id:
        raise ValidationError("Pismo wysyła wyłącznie urząd nadawcy.")
    if provider == "EDOR":
        from .edor_delivery import enqueue_edor

        return enqueue_edor(user, letter, ip=ip)
    if provider == "EZD":
        raise ValidationError("Zapis w EZD wymaga wyboru sprawy w formularzu pisma.")
    conf = next((p for p in configuration_status(user.office_id) if p["id"] == provider), None)
    if not conf or not conf["configured"]:
        raise ValidationError("Ta integracja nie jest jeszcze skonfigurowana. Sprawdź zakładkę Integracje.")
    letter = lock_letter(letter)
    existing = IntegrationJob.objects.filter(key=f"{provider}:{letter.uuid}:SEND").first()
    if existing:
        return existing
    payload = document_payload(letter)
    job, created = IntegrationJob.objects.get_or_create(
        key=f"{provider}:{letter.uuid}:SEND",
        defaults={
            "provider": provider,
            "letter": letter,
            "payload": payload,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
        },
    )
    if created:
        audit(
            user,
            "integration.queued",
            letter,
            after={"provider": provider, "job": str(job.uuid)},
            ip=ip,
        )
    return job


def ezd_scope(letter):
    if letter.request_id:
        return (
            "REQUEST",
            letter.request.uuid,
            f"Dyna Rejestr Tablic | {letter.request.reference} | {letter.request.uuid}",
        )
    if letter.pool_id:
        return "POOL", letter.pool.uuid, f"Dyna Rejestr Tablic | pula | {letter.pool.uuid}"
    raise ValidationError("Pismo nie jest powiązane z wnioskiem ani pulą.")


@transaction.atomic
def enqueue_ezd(user, letter, *, case_id="", case_number=None, reason="", ip=None):
    require_role(user, "COUNTY", "MAIN")
    if user.office_id != letter.office_id:
        raise ValidationError("Dokument zapisuje wyłącznie urząd nadawcy.")
    try:
        profile = load_profile(user.office_id)
    except ConnectorError as exc:
        raise ValidationError(str(exc)) from exc
    kind, scope_id, title = ezd_scope(letter)
    # Krótka blokada urzędu serializuje pierwsze powiązanie tej samej sprawy
    # także na PostgreSQL, gdzie SELECT istniejącego linku nie blokuje pustej luki.
    Office.objects.select_for_update(no_key=True).get(pk=user.office_id)
    letter = lock_letter(letter)
    link = EZDCaseLink.objects.select_for_update().filter(office=user.office, scope_id=scope_id).first()
    if link is None:
        if bool(case_id) == bool(case_number) or not reason.strip():
            raise ValidationError(
                "Wskaż istniejącą sprawę lub numer nowej sprawy i podaj uzasadnienie powiązania."
            )
        if case_id:
            try:
                opaque_id(case_id)
            except ConnectorError as exc:
                raise ValidationError("Niepoprawny identyfikator sprawy EZD.") from exc
        if case_number and (not profile.jrwa_id or not profile.archival_category):
            raise ValidationError("Tworzenie spraw wymaga skonfigurowanego JRWA i kategorii archiwalnej.")
        if case_number is not None and not 1 <= int(case_number) <= 2147483647:
            raise ValidationError("Numer nowej sprawy musi być dodatni.")
        link = EZDCaseLink.objects.create(
            office=user.office,
            scope_id=scope_id,
            scope_kind=kind,
            title=title,
            year=timezone.localdate().year,
            number=case_number,
            remote_id=case_id,
            state="UNVERIFIED" if case_id else "UNLINKED",
            target_hash=profile.target_hash,
        )
        audit(
            user,
            "ezd.case.planned",
            letter,
            after={"case_id": case_id, "case_number": case_number, "scope_id": str(scope_id)},
            reason=reason,
            ip=ip,
        )
    elif link.target_hash != profile.target_hash:
        raise ValidationError(
            "Konfiguracja wskazuje inną instancję EZD niż zapisana sprawa. Wymagana weryfikacja administratora."
        )
    elif (case_id and case_id != link.remote_id) or (case_number and case_number != link.number):
        raise ValidationError(
            "Ta sprawa jest już powiązana z EZD. Nie można zmienić powiązania podczas zapisu."
        )
    payload = document_payload(letter)
    job, created = IntegrationJob.objects.get_or_create(
        key=f"EZD:{letter.uuid}:REGISTER",
        defaults={
            "provider": "EZD",
            "operation": "REGISTER",
            "letter": letter,
            "payload": payload,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "result": {"case_link_id": link.pk, "target_hash": profile.target_hash, "steps": {}},
        },
    )
    if created:
        audit(
            user,
            "integration.queued",
            letter,
            after={"provider": "EZD", "job": str(job.uuid), "operation": "REGISTER"},
            ip=ip,
        )
    return job


def checkpoint(job, step, state, output=None):
    """Zapis przed I/O pozwala rozpoznać awarię procesu bez powtórzenia POST."""
    job.result.setdefault("steps", {})[step] = {"state": state, "output": output or {}}
    job.claimed_until = timezone.now() + timedelta(minutes=5)
    job.save(update_fields=["result", "claimed_until", "updated_at"])


def ezd_step(job, name, action):
    previous = job.result.get("steps", {}).get(name, {})
    if previous.get("state") == "COMPLETED":
        return previous["output"]
    if previous.get("state") == "IN_FLIGHT":
        raise ConnectorError("Wynik poprzedniego zapisu w EZD wymaga sprawdzenia.", state="REVIEW_REQUIRED")
    checkpoint(job, name, "IN_FLIGHT")
    try:
        output = action()
    except ConnectorError as exc:
        if exc.state != "REVIEW_REQUIRED":
            checkpoint(job, name, "NOT_COMPLETED")
        raise
    checkpoint(job, name, "COMPLETED", output)
    return output


def register_ezd(job, *, transport=None):
    profile = load_profile(job.letter.office_id)
    if profile.target_hash != job.result.get("target_hash"):
        raise ConnectorError(
            "Zmieniła się instancja EZD. Wznowienie wymaga sprawdzenia powiązań.", state="REVIEW_REQUIRED"
        )
    with EZDRPClient(profile, transport=transport) as client:
        client.authenticate()
        with transaction.atomic():
            link = EZDCaseLink.objects.select_for_update().get(pk=job.result["case_link_id"])
            if link.office_id != job.letter.office_id or link.target_hash != profile.target_hash:
                raise ConnectorError(
                    "Nieprawidłowe powiązanie urzędu ze sprawą EZD.", state="REVIEW_REQUIRED"
                )
            if link.state == "CREATING":
                raise ConnectorError("Inna operacja tworzy tę sprawę EZD.", state="RETRY")
            if link.state == "REVIEW_REQUIRED":
                raise ConnectorError(
                    "Utworzenie sprawy EZD wymaga uzgodnienia wyniku.", state="REVIEW_REQUIRED"
                )
            if not link.remote_id:
                link.state = "CREATING"
                link.save(update_fields=["state"])
        if not link.remote_id:
            try:
                result = ezd_step(
                    job,
                    "create_case",
                    lambda: {
                        key: value
                        for key, value in client.create_case(
                            title=link.title, number=link.number, year=link.year
                        ).items()
                        if key in {"idSprawa", "znak"}
                    },
                )
                link.remote_id = result["idSprawa"]
                link.remote_symbol = result.get("znak", "")
                link.state = "LINKED"
                link.save(update_fields=["remote_id", "remote_symbol", "state"])
            except ConnectorError as exc:
                link.state = "REVIEW_REQUIRED" if exc.state == "REVIEW_REQUIRED" else "UNLINKED"
                link.save(update_fields=["state"])
                raise
            except Exception:
                link.state = "REVIEW_REQUIRED"
                link.save(update_fields=["state"])
                raise
        if link.state == "UNVERIFIED":
            result = client.get_case(link.remote_id)
            link.state = "LINKED"
            link.remote_symbol = result.get("znak") or ""
            link.save(update_fields=["state", "remote_symbol"])
            audit(
                None,
                "ezd.case.verified",
                job.letter,
                after={"case_id": link.remote_id, "symbol": link.remote_symbol},
            )
        document = ezd_step(
            job,
            "add_document",
            lambda: client.add_document(link.remote_id, bytes(job.payload), f"DRT-{job.letter.uuid}.pdf"),
        )
        document_id = document["idDokumentPrzestrzeni"]
        job.remote_id = document_id
        job.save(update_fields=["remote_id"])
        values = {
            "letter_number": job.letter.number,
            "payload_sha256": job.payload_sha256,
            "request_id": str(job.letter.request.uuid)
            if job.letter.request_id
            else str(job.letter.pool.uuid),
            "request_url": f"{settings.APP_URL}/panel/wnioski/{job.letter.request.uuid}/"
            if job.letter.request_id
            else f"{settings.APP_URL}/panel/pule/{job.letter.pool.uuid}/",
        }
        ezd_step(job, "metadata", lambda: client.set_metadata(document_id, values))
        if client.document_sha256(document_id) != job.payload_sha256:
            raise ConnectorError(
                "PDF pobrany z EZD różni się od dokumentu w kolejce.", state="REVIEW_REQUIRED"
            )
        Letter.objects.filter(pk=job.letter_id).update(ezd_id=document_id)
        job.result.update(
            {
                "case_id": link.remote_id,
                "case_symbol": link.remote_symbol,
                "delivery_confirmed": False,
                "registered_in_ezd": True,
                "remote_pdf_sha256_verified": True,
            }
        )
        return "REGISTERED"


def recover_stale_jobs():
    count = 0
    for pk in IntegrationJob.objects.filter(
        status="PROCESSING", claimed_until__lte=timezone.now()
    ).values_list("pk", flat=True):
        with transaction.atomic():
            job = IntegrationJob.objects.select_for_update().get(pk=pk)
            if job.status != "PROCESSING" or not job.claimed_until or job.claimed_until > timezone.now():
                continue
            job.status = "REVIEW_REQUIRED"
            job.error = "Proces przerwano w trakcie operacji. Sprawdź wynik u operatora; automatyczne ponowienie jest zablokowane."
            job.claimed_until = None
            job.save(update_fields=["status", "error", "claimed_until", "updated_at"])
            link_id = job.result.get("case_link_id")
            if link_id:
                EZDCaseLink.objects.filter(pk=link_id, state="CREATING").update(state="REVIEW_REQUIRED")
            audit(
                None,
                "integration.interrupted",
                job.letter,
                after={"job": str(job.uuid), "status": job.status},
            )
            count += 1
    return count


def reconcile_ezd_job(user, job_uuid, *, case_id="", document_id="", reason="", transport=None):
    """Administrator transportu uzgadnia wynik przez odczyt API i hash PDF.

    Nie umożliwia potwierdzenia „na słowo”, że niepewny POST nic nie utworzył.
    """
    require_role(user, "ADMIN")
    if not reason.strip():
        raise ValidationError("Uzgodnienie operacji wymaga uzasadnienia.")
    job = IntegrationJob.objects.select_related("letter").get(uuid=job_uuid, provider="EZD")
    if job.status not in {"REVIEW_REQUIRED", "CONFIG_ERROR", "REJECTED", "RETRY_EXHAUSTED"}:
        raise ValidationError("Operacja nie oczekuje na uzgodnienie ani poprawienie konfiguracji.")
    profile = load_profile(job.letter.office_id)
    if profile.target_hash != job.result.get("target_hash"):
        raise ValidationError("Konfiguracja wskazuje inną instancję lub stanowisko EZD.")
    link = EZDCaseLink.objects.get(pk=job.result["case_link_id"])
    link_before = (link.state, link.remote_id, link.target_hash)
    steps = job.result.get("steps", {})
    with EZDRPClient(profile, transport=transport) as client:
        if case_id and link.remote_id and case_id != link.remote_id:
            raise ValidationError("Podana sprawa jest inna niż zapisane powiązanie.")
        remote_case_id = case_id or link.remote_id
        if not remote_case_id:
            raise ValidationError("Podaj identyfikator utworzonej sprawy EZD po niepewnej operacji.")
        remote_case = client.get_case(remote_case_id)
        if (
            link.state in {"CREATING", "REVIEW_REQUIRED"}
            or steps.get("create_case", {}).get("state") == "IN_FLIGHT"
        ):
            if remote_case.get("tytul") != link.title or remote_case.get("rokZalozenia") != link.year:
                raise ValidationError("Sprawa EZD nie odpowiada planowanemu wnioskowi i rokowi.")
        document = None
        if document_id:
            document = client.get_document(document_id)
            existing_id = steps.get("add_document", {}).get("output", {}).get("idDokumentPrzestrzeni")
            if existing_id and existing_id != document_id:
                raise ValidationError("Operacja wskazuje już inny dokument EZD.")
            if (
                not remote_case.get("idPrzestrzenRobocza")
                or document.get("idPrzestrzenRobocza") != remote_case["idPrzestrzenRobocza"]
            ):
                raise ValidationError("Dokument EZD nie należy do przestrzeni wskazanej sprawy.")
            if client.document_sha256(document_id) != job.payload_sha256:
                raise ValidationError("Pobrany PDF nie odpowiada dokumentowi w kolejce.")
        if steps.get("add_document", {}).get("state") == "IN_FLIGHT" and not document:
            raise ValidationError("Niepewny zapis dokumentu wymaga jego identyfikatora i weryfikacji PDF.")
        if steps.get("metadata", {}).get("state") == "IN_FLIGHT":
            # Ten PUT ustawia wyłącznie mapowane atrybuty jednego dokumentu.
            # Po ponownym zapisaniu tych samych wartości nie powstaje nowy dokument.
            steps["metadata"] = {"state": "NOT_COMPLETED", "output": {}}
    with transaction.atomic():
        current = IntegrationJob.objects.select_for_update().get(pk=job.pk)
        if current.status != job.status or current.updated_at != job.updated_at:
            raise ValidationError("Stan operacji zmienił się podczas uzgadniania; sprawdź go ponownie.")
        link = EZDCaseLink.objects.select_for_update().get(pk=link.pk)
        if (link.state, link.remote_id, link.target_hash) != link_before:
            raise ValidationError("Powiązanie sprawy zmieniło się podczas uzgadniania. Sprawdź je ponownie.")
        link.remote_id = remote_case_id
        link.remote_symbol = remote_case.get("znak") or ""
        link.state = "LINKED"
        link.save(update_fields=["remote_id", "remote_symbol", "state"])
        if case_id and link.number:
            steps["create_case"] = {
                "state": "COMPLETED",
                "output": {"idSprawa": remote_case_id, "znak": link.remote_symbol},
            }
        if document:
            steps["add_document"] = {
                "state": "COMPLETED",
                "output": {
                    key: value
                    for key, value in document.items()
                    if key
                    in {"idDokument", "idDokumentPrzestrzeni", "idDokumentWersja", "idPrzestrzenRobocza"}
                },
            }
            current.remote_id = document_id
        current.result["steps"] = steps
        current.status = "QUEUED"
        current.next_attempt_at = None
        current.claimed_until = None
        current.attempts = 0
        current.error = ""
        current.save(
            update_fields=[
                "status",
                "result",
                "remote_id",
                "next_attempt_at",
                "claimed_until",
                "attempts",
                "error",
                "updated_at",
            ]
        )
        audit(
            user,
            "integration.reconciled",
            current.letter,
            after={"job": str(current.uuid), "case_id": remote_case_id, "document_id": document_id},
            reason=reason,
        )
        return current


def process_job(job, *, transport=None):
    # Rezerwacja pracy w bazie; nie utrzymujemy blokady w trakcie I/O.
    with transaction.atomic():
        job = (
            IntegrationJob.objects.select_for_update(of=("self",))
            .select_related("letter__recipient")
            .get(pk=job.pk)
        )
        if job.status not in ["QUEUED", "RETRY", "MONITORING"] or (
            job.next_attempt_at and job.next_attempt_at > timezone.now()
        ):
            return job
        job.status = "PROCESSING"
        job.attempts += 1
        job.claimed_until = timezone.now() + timedelta(minutes=5)
        if job.payload is None:
            if job.operation == "DECISION_NOTICE":
                job.status = "REVIEW_REQUIRED"
                job.claimed_until = None
                job.error = "Brak zapisanej treści powiadomienia. Wymagana kontrola przed wznowieniem."
                job.save(update_fields=["status", "attempts", "claimed_until", "error", "updated_at"])
                return job
            try:
                job.payload = document_payload(job.letter)
            except ValidationError:
                job.status = "REVIEW_REQUIRED"
                job.claimed_until = None
                job.error = "Archiwalny dokument wymaga kontroli integralności przed wznowieniem kolejki."
                job.save(update_fields=["status", "attempts", "claimed_until", "error", "updated_at"])
                return job
            job.payload_sha256 = hashlib.sha256(bytes(job.payload)).hexdigest()
        job.save(
            update_fields=["status", "attempts", "claimed_until", "payload", "payload_sha256", "updated_at"]
        )
    try:
        if hashlib.sha256(bytes(job.payload)).hexdigest() != job.payload_sha256:
            raise ConnectorError(
                "Niezgodna suma kontrolna danych operacji w kolejce.", state="REVIEW_REQUIRED"
            )
        if job.provider == "EZD":
            job.status = register_ezd(job, transport=transport)
            job.error = ""
        elif job.provider == "EDOR":
            from .edor_delivery import process_edor

            job.status = process_edor(job, transport=transport)
            job.result["consecutive_errors"] = 0
            job.error = ""
        elif job.provider == "SMTP":
            if job.operation == "DECISION_NOTICE":
                from .decision_notifications import send_decision_notice

                job.status = send_decision_notice(job)
            else:
                job.status = send_email(job)
            job.result = {
                "transport": "file" if job.status == "LOCAL_SAVED" else transport_name(),
                "delivery_confirmed": False,
            }
            job.error = ""
        else:
            raise ValidationError("Konektor nie jest jeszcze dostępny.")
    except ConnectorError as exc:
        job.status = exc.state
        job.error = str(exc)
        if exc.state == "RETRY":
            failures = job.attempts
            if job.provider == "EDOR":
                failures = job.result.get("consecutive_errors", 0) + 1
                job.result["consecutive_errors"] = failures
            if failures >= 5:
                job.status = "RETRY_EXHAUSTED"
            else:
                job.next_attempt_at = timezone.now() + timedelta(
                    seconds=max(exc.retry_seconds, 60 * 2 ** (failures - 1))
                )
    except Exception:
        # Wynik SMTP i nieoczekiwanych błędów nie pozwala na bezpieczny retry.
        job.status = "REVIEW_REQUIRED"
        job.error = "Operacja nie została potwierdzona. Sprawdź wynik u operatora przed ponowieniem."
    job.claimed_until = None
    saved = IntegrationJob.objects.filter(pk=job.pk, status="PROCESSING", attempts=job.attempts).update(
        status=job.status,
        result=job.result,
        error=job.error,
        next_attempt_at=job.next_attempt_at,
        claimed_until=None,
        updated_at=timezone.now(),
    )
    if not saved:
        current = IntegrationJob.objects.get(pk=job.pk)
        audit(
            None,
            "integration.worker.superseded",
            current.letter,
            after={"job": str(current.uuid), "attempt": job.attempts, "current_attempt": current.attempts},
        )
        return current
    audit(
        None,
        "integration.result",
        job.letter,
        after={
            "provider": job.provider,
            "status": job.status,
            "job": str(job.uuid),
            "remote_id": job.remote_id,
        },
    )
    return job


def send_email(job):
    letter = job.letter
    if not letter.recipient.email:
        raise ValidationError("Urząd adresata nie ma skonfigurowanego e-maila.")
    email = EmailMessage(
        letter.title,
        letter.body,
        settings.DEFAULT_FROM_EMAIL,
        [letter.recipient.email],
        headers={"Message-ID": f"<{job.uuid}@dyna-rejestr.local>"},
    )
    email.attach(
        f"DRT-{letter.uuid}.pdf",
        bytes(job.payload),
        "application/pdf",
    )
    if email.send() != 1:
        raise ValidationError("Serwer pocztowy nie potwierdził przyjęcia wiadomości.")
    return (
        "LOCAL_SAVED"
        if settings.LOCAL and settings.EMAIL_BACKEND.endswith("filebased.EmailBackend")
        else "ACCEPTED"
    )
