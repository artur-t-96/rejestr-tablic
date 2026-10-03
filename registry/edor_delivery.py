"""Trwała wysyłka i obserwacja e-Doręczeń. Nie zastępuje weryfikacji INT."""

import hashlib
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .connectors.edor import EDorClient, ade, load_profile
from .connectors.ezdrp import ConnectorError
from .documents import document_payload, lock_letter
from .models import DeliveryEvidence, IntegrationJob, Office
from .services import audit, require_role


@transaction.atomic
def enqueue_edor(user, letter, *, ip=None):
    require_role(user, "COUNTY", "MAIN")
    if user.office_id != letter.office_id:
        raise ValidationError("Pismo wysyła wyłącznie urząd nadawcy.")
    Office.objects.select_for_update().get(pk=user.office_id)
    letter = lock_letter(letter)
    existing = IntegrationJob.objects.filter(key=f"EDOR:{letter.uuid}:SEND").first()
    if existing:
        return existing
    try:
        profile = load_profile(user.office_id)
        sender = Office.objects.get(pk=letter.office_id)
        recipient = Office.objects.get(pk=letter.recipient_id)
        if ade(sender.ade) != profile.sender_ade:
            raise ConnectorError("Adres urzędu nadawcy różni się od profilu e-Doręczeń.")
        recipient_ade = ade(recipient.ade)
        if recipient_ade == profile.sender_ade:
            raise ConnectorError("Nadawca i adresat pisma mają ten sam adres do e-Doręczeń.")
    except ConnectorError as exc:
        raise ValidationError(str(exc)) from exc
    payload = document_payload(letter)
    if not payload.startswith(b"%PDF-") or len(payload) > 10 * 1024 * 1024:
        raise ValidationError("Wysyłka wymaga pliku PDF o rozmiarze do 10 MB.")
    if len(letter.body) > 5000:
        raise ValidationError(
            "Treść wiadomości przekracza 5000 znaków. Skróć szablon przed wygenerowaniem pisma."
        )
    scope = letter.request.uuid if letter.request_id else letter.pool.uuid if letter.pool_id else letter.uuid
    job = IntegrationJob.objects.create(
        key=f"EDOR:{letter.uuid}:SEND",
        provider="EDOR",
        letter=letter,
        payload=payload,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        result={
            "target_hash": profile.target_hash,
            "sender_ade": profile.sender_ade,
            "recipient_ade": recipient_ade,
            "subject": letter.title,
            "body": letter.body,
            "scope_id": str(scope),
            "file_id": str(letter.uuid),
            "steps": {},
            "environment": profile.environment,
            "delivery_confirmed": False,
            "submission_guard_version": 1,
        },
    )
    audit(
        user,
        "integration.queued",
        letter,
        after={"provider": "EDOR", "job": str(job.uuid), "environment": profile.environment},
        ip=ip,
    )
    return job


def process_edor(job, *, transport=None):
    from .integrations import checkpoint

    profile = load_profile(job.letter.office_id)
    if profile.target_hash != job.result.get("target_hash"):
        raise ConnectorError(
            "Zmienił się nadawca lub środowisko e-Doręczeń. Wymagana weryfikacja administratora.",
            state="REVIEW_REQUIRED",
        )
    recipient = job.result["recipient_ade"]
    step = job.result.get("steps", {}).get("send", {})
    if step.get("state") != "COMPLETED":
        if (
            type(job.result.get("submission_guard_version")) is not int
            or job.result["submission_guard_version"] != 1
        ):
            raise ConnectorError(
                "Starsze zlecenie nie ma pełnej historii granicy wysyłki. Uzgodnij wynik z operatorem.",
                state="REVIEW_REQUIRED",
            )
        if job.result.get("restore_requires_reconciliation"):
            raise ConnectorError(
                "Odtworzona kopia nie dowodzi braku wysyłki. Uzgodnij wynik z operatorem.",
                state="REVIEW_REQUIRED",
            )
        if "send" in job.result.get("steps", {}) and not (
            step.get("state") == "NOT_ACCEPTED" and step.get("output", {}).get("safe_to_resubmit") is True
        ):
            raise ConnectorError(
                "Brak jednoznacznego potwierdzenia niewysłanej operacji. Ponowienie jest zablokowane.",
                state="REVIEW_REQUIRED",
            )
    with EDorClient(profile, transport=transport) as client:
        client.authenticate()
        if step.get("state") != "COMPLETED":
            confirmation = client.confirm_address(recipient)
            job.result["address_confirmation"] = confirmation
            # Pracownik może wrócić po wygaśnięciu dzierżawy i wznowieniu
            # przez administratora. Granicę POST zapisuje tylko bieżąca próba.
            with transaction.atomic():
                current = IntegrationJob.objects.select_for_update().get(pk=job.pk)
                if (
                    current.status != "PROCESSING"
                    or current.attempts != job.attempts
                    or not current.claimed_until
                    or current.claimed_until <= timezone.now()
                ):
                    raise ConnectorError(
                        "Ta próba utraciła prawo do wysyłki. Bieżąca operacja pozostaje bez zmian.",
                        state="REVIEW_REQUIRED",
                    )
                checkpoint(job, "send", "IN_FLIGHT")
            try:
                output = client.send_message(
                    recipient_ade=recipient,
                    subject=job.result["subject"],
                    body=job.result["body"],
                    payload=bytes(job.payload),
                    file_id=job.result["file_id"],
                    scope_id=job.result["scope_id"],
                )
            except ConnectorError as exc:
                if exc.safe_to_resubmit:
                    checkpoint(job, "send", "NOT_ACCEPTED", {"safe_to_resubmit": True})
                raise
            checkpoint(job, "send", "COMPLETED", output)
            job.result["task_id"] = output["task_id"]
            # Odrębne wywołanie obserwatora. Przyjęcie zadania nie jest nadaniem.
            job.next_attempt_at = timezone.now() + timedelta(seconds=60)
            return "MONITORING"
        task_id = step["output"]["task_id"]
        job.result["task_id"] = task_id
        if not job.remote_id:
            message_id = client.task_message(task_id, recipient)
            if not message_id:
                job.next_attempt_at = timezone.now() + timedelta(seconds=60)
                return "MONITORING"
            job.remote_id = message_id
            job.save(update_fields=["remote_id", "updated_at"])
        remote = client.message_status(job.remote_id, recipient)
        job.result["remote_status"] = remote["status"]
        job.result["submission_date"] = remote["submission_date"]
        job.result["receipt_date"] = remote["receipt_date"]
        for item in client.evidences(job.remote_id):
            # Przed każdym pobraniem przedłużamy dzierżawę. Zapis jest osobny,
            # więc awaria po części dowodów nie pobiera ich ponownie.
            job.claimed_until = timezone.now() + timedelta(minutes=5)
            job.save(update_fields=["claimed_until", "updated_at"])
            existing = DeliveryEvidence.objects.filter(job=job, remote_id=item["id"]).first()
            if existing:
                if (
                    existing.kind != item["kind"]
                    or hashlib.sha256(bytes(existing.content)).hexdigest() != existing.sha256
                ):
                    raise ConnectorError("Niespójny zapis dowodu e-Doręczeń.", state="REVIEW_REQUIRED")
                continue
            content = client.evidence_content(item["id"])
            DeliveryEvidence.objects.create(
                job=job,
                remote_id=item["id"],
                kind=item["kind"],
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
            )
            audit(
                None,
                "edor.evidence.archived",
                job.letter,
                after={
                    "job": str(job.uuid),
                    "id": item["id"],
                    "kind": item["kind"],
                    "sha256": hashlib.sha256(content).hexdigest(),
                },
            )
        kinds = set(job.evidence.values_list("kind", flat=True))
        job.result["submission_evidence_archived"] = bool(
            kinds & {"A.1", "A1", "BP.WP", "BP.WX", "BPWP", "BPWX"}
        )
        receipt_kinds = {"E.1", "E1", "BP.OP", "BP.OX", "BPOP", "BPOX"}
        job.result["receipt_evidence_archived"] = bool(kinds & receipt_kinds)
        job.result["evidence_signature_verified"] = False
        # To potwierdzenie pochodzi z uwierzytelnionego API i zarchiwizowanego
        # dowodu; nie deklarujemy lokalnej walidacji podpisu dowodu operatora.
        job.result["delivery_confirmed"] = remote["status"] == "Doręczona" and bool(kinds & receipt_kinds)
        final = {
            "Doręczona": ("EDOR_DELIVERED", receipt_kinds),
            "Uznana za doręczoną": ("EDOR_DEEMED", {"BP.OP", "BP.OX", "BPOP", "BPOX"}),
            "Odrzucona": ("EDOR_REJECTED", {"A.2", "A2"}),
            "Niedoręczona": ("EDOR_FAILED", {"B.2", "B2", "B.3", "B3", "D.2", "D2", "E.2", "E2"}),
        }
        if remote["status"] in final:
            status, required = final[remote["status"]]
            if kinds & required:
                job.next_attempt_at = None
                return status
        job.next_attempt_at = timezone.now() + timedelta(minutes=5)
        return "MONITORING"


RESUMABLE_STATUSES = {"REVIEW_REQUIRED", "CONFIG_ERROR", "RETRY_EXHAUSTED", "REJECTED"}


def unsent_block_reason(job):
    """Ocena trwałych dowodów; nie traktuje starego NOT_COMPLETED jako dowodu."""
    if job.provider != "EDOR" or job.operation != "SEND" or job.status not in RESUMABLE_STATUSES:
        return "Operacja nie wymaga wznowienia niewysłanej wiadomości."
    if job.claimed_until and job.claimed_until > timezone.now():
        return "Operacja jest nadal zajęta przez pracownika."
    result = job.result
    if not isinstance(result, dict) or not isinstance(result.get("steps", {}), dict):
        return "Niepoprawny zapis etapów operacji."
    if result.get("restore_requires_reconciliation"):
        return "Odtworzona kopia może być starsza niż wysyłka. Uzgodnij wynik z operatorem."
    if type(result.get("submission_guard_version")) is not int or result["submission_guard_version"] != 1:
        return "Starsze zlecenie nie ma pełnej historii granicy wysyłki. Uzgodnij wynik z operatorem."
    if job.remote_id or result.get("task_id") or job.evidence.exists():
        return "Operacja ma identyfikator lub dowód operatora. Można wznowić tylko jej obserwację."
    step = result.get("steps", {}).get("send", {})
    if "send" in result.get("steps", {}) and not (
        isinstance(step, dict)
        and step.get("state") == "NOT_ACCEPTED"
        and isinstance(step.get("output"), dict)
        and step["output"].get("safe_to_resubmit") is True
    ):
        return "Brak jednoznacznego dowodu niewysłanej operacji. Ponowienie jest zablokowane."
    if (
        job.payload is None
        or not bytes(job.payload).startswith(b"%PDF-")
        or len(job.payload) > 10 * 1024 * 1024
        or hashlib.sha256(bytes(job.payload)).hexdigest() != job.payload_sha256
    ):
        return "Archiwalny dokument w kolejce nie przeszedł kontroli integralności."
    if (
        not isinstance(result.get("subject"), str)
        or not result["subject"].strip()
        or not isinstance(result.get("body"), str)
        or len(result["body"]) > 5000
        or not result.get("scope_id")
        or not result.get("file_id")
        or not result.get("target_hash")
        or not result.get("sender_ade")
        or not result.get("recipient_ade")
    ):
        return "Niepełna niezmienna kopia danych wysyłki."
    return ""


def edor_resume_mode(job):
    """Tryb dostępny w panelu; usługi ponownie sprawdzają warunki w transakcji."""
    if job.provider != "EDOR" or job.status not in RESUMABLE_STATUSES or not isinstance(job.result, dict):
        return ""
    if job.claimed_until and job.claimed_until > timezone.now():
        return ""
    steps = job.result.get("steps", {})
    step = steps.get("send", {}) if isinstance(steps, dict) else {}
    if (
        isinstance(step, dict)
        and step.get("state") == "COMPLETED"
        and isinstance(step.get("output"), dict)
        and step["output"].get("task_id")
    ):
        return "OBSERVATION"
    return "" if unsent_block_reason(job) else "UNSENT"


def resume_edor_unsent(user, job_uuid, *, reason="", transport=None, expected_updated_at=None, ip=None):
    """Weryfikuje konfigurację i wznawia to samo zlecenie, bez POST wiadomości."""
    require_role(user, "ADMIN")
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        raise ValidationError("Wznowienie wymaga uzasadnienia do 500 znaków.")
    job = IntegrationJob.objects.select_related("letter__office", "letter__recipient").get(
        uuid=job_uuid, provider="EDOR"
    )
    if expected_updated_at is not None and job.updated_at != expected_updated_at:
        raise ValidationError("Stan operacji zmienił się. Otwórz ponownie formularz.")
    problem = unsent_block_reason(job)
    if problem:
        raise ValidationError(problem)
    profile = load_profile(job.letter.office_id)
    sender, recipient = job.letter.office, job.letter.recipient
    if (
        not sender.active
        or not recipient.active
        or profile.target_hash != job.result["target_hash"]
        or ade(sender.ade) != profile.sender_ade
        or profile.sender_ade != job.result["sender_ade"]
        or ade(recipient.ade) != job.result["recipient_ade"]
        or profile.sender_ade == job.result["recipient_ade"]
    ):
        raise ValidationError("Urząd, nadawca, adresat lub środowisko różnią się od zapisanego zlecenia.")
    # Uwierzytelnienie i potwierdzenie ADE są odczytami. Nie wysyłamy pisma.
    with EDorClient(profile, transport=transport) as client:
        client.authenticate()
        client.confirm_address(job.result["recipient_ade"])
    with transaction.atomic():
        offices = {
            office.pk: office
            for office in Office.objects.select_for_update(no_key=True)
            .filter(pk__in=[sender.pk, recipient.pk])
            .order_by("pk")
        }
        if (
            not offices[sender.pk].active
            or not offices[recipient.pk].active
            or offices[sender.pk].ade != job.result["sender_ade"]
            or offices[recipient.pk].ade != job.result["recipient_ade"]
        ):
            raise ValidationError("Konfiguracja urzędu zmieniła się podczas weryfikacji.")
        current = IntegrationJob.objects.select_for_update().get(pk=job.pk)
        if (
            current.status != job.status
            or current.updated_at != job.updated_at
            or current.result != job.result
            or current.payload_sha256 != job.payload_sha256
        ):
            raise ValidationError("Stan operacji zmienił się podczas weryfikacji.")
        problem = unsent_block_reason(current)
        if problem:
            raise ValidationError(problem)
        previous = {"status": current.status, "attempts": current.attempts}
        current.status = "QUEUED"
        current.next_attempt_at = timezone.now()
        current.claimed_until = None
        current.error = ""
        current.result["consecutive_errors"] = 0
        current.save(
            update_fields=["status", "result", "next_attempt_at", "claimed_until", "error", "updated_at"]
        )
        audit(
            user,
            "edor.unsent.resumed",
            current.letter,
            before=previous,
            after={"job": str(current.uuid), "status": current.status},
            reason=reason.strip(),
            ip=ip,
        )
        return current


def resume_edor_observation(user, job_uuid, *, reason="", transport=None, expected_updated_at=None, ip=None):
    """Wznawia tylko odczyty znanego zadania, nigdy niepewną wysyłkę POST."""
    require_role(user, "ADMIN")
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        raise ValidationError("Wznowienie obserwacji wymaga uzasadnienia do 500 znaków.")
    job = IntegrationJob.objects.select_related("letter").get(uuid=job_uuid, provider="EDOR")
    if job.status not in RESUMABLE_STATUSES:
        raise ValidationError("Operacja nie wymaga wznowienia obserwacji.")
    if expected_updated_at is not None and job.updated_at != expected_updated_at:
        raise ValidationError("Stan operacji zmienił się. Otwórz ponownie formularz.")
    if edor_resume_mode(job) != "OBSERVATION":
        raise ValidationError("Brak potwierdzonego zadania. Nie można bezpiecznie wznowić niepewnej wysyłki.")
    step = job.result["steps"]["send"]
    profile = load_profile(job.letter.office_id)
    if profile.target_hash != job.result.get("target_hash"):
        raise ValidationError("Profil wskazuje innego nadawcę lub środowisko.")
    recipient_ade = ade(job.result.get("recipient_ade"))
    with EDorClient(profile, transport=transport) as client:
        message_id = client.task_message(step["output"]["task_id"], recipient_ade)
        if job.remote_id and message_id != job.remote_id:
            raise ValidationError("Wynik zadania wskazuje inną wiadomość.")
    with transaction.atomic():
        current = IntegrationJob.objects.select_for_update().get(pk=job.pk)
        if current.status != job.status or current.updated_at != job.updated_at:
            raise ValidationError("Stan operacji zmienił się podczas weryfikacji.")
        current.status = "MONITORING"
        current.next_attempt_at = timezone.now()
        current.claimed_until = None
        current.error = ""
        current.result["consecutive_errors"] = 0
        current.save(
            update_fields=["status", "result", "next_attempt_at", "claimed_until", "error", "updated_at"]
        )
        audit(
            user,
            "edor.observation.resumed",
            current.letter,
            after={"job": str(current.uuid), "task_id": step["output"]["task_id"]},
            reason=reason,
            ip=ip,
        )
        return current
