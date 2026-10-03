"""Odczyt rzeczywistego RPW. Powiązanie wymaga zgodnych niezmiennych bajtów pisma."""

import hashlib
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.urls import reverse

from .connectors.ezdrp import ConnectorError, EZDRPClient, load_profile, opaque_id
from .documents import document_payload
from .models import EZDIncomingDocument, Letter, Office
from .services import audit, require_role


def attachment_ids(metadata):
    result, seen = [], set()

    def visit(items, depth=0):
        if depth > 8 or not isinstance(items, list):
            raise ConnectorError("Niepoprawna struktura załączników RPW.", state="REVIEW_REQUIRED")
        for item in items:
            if not isinstance(item, dict):
                raise ConnectorError("Niepoprawny załącznik RPW.", state="REVIEW_REQUIRED")
            doc_id = opaque_id(item.get("idDokumentPrzestrzeni"))
            if doc_id in seen or len(seen) >= 100:
                raise ConnectorError(
                    "Powtórzony lub zbyt rozbudowany załącznik RPW.", state="REVIEW_REQUIRED"
                )
            seen.add(doc_id)
            result.append((doc_id, opaque_id(item.get("idDokumentWersja"))))
            visit(item.get("zalaczniki", []), depth + 1)

    visit(metadata["zalaczniki"])
    return result


def claimed_request_id(profile, metadata):
    """Nie ufamy URL z EZD; czytamy wyłącznie skonfigurowany identyfikator."""
    mapping = profile.metadata.get("request_id")
    if not mapping:
        return None
    values = [
        item.get("wartosc")
        for item in metadata["listaKonfiguracji"]
        if isinstance(item, dict)
        and mapping["key"] in (item.get("kluczSystemowy"), item.get("id"))
        and item.get("wartosc")
    ]
    if not values:
        return None
    try:
        ids = {uuid.UUID(value) for value in values}
    except (ValueError, TypeError, AttributeError) as exc:
        raise ConnectorError(
            "Niepoprawny identyfikator wniosku w metadanych EZD.", state="REVIEW_REQUIRED"
        ) from exc
    if len(ids) != 1:
        raise ConnectorError("Sprzeczne identyfikatory wniosku w EZD.", state="REVIEW_REQUIRED")
    return ids.pop()


def matched_letter(office_id, payload, digest, request_id):
    candidates = list(
        Letter.objects.select_related("request").filter(
            Q(sha256=digest) | Q(signed_sha256=digest),
            recipient_id=office_id,
        )[:2]
    )
    if len(candidates) != 1:
        return None, "Nie znaleziono jednoznacznego pisma o identycznej treści dla tego urzędu."
    letter = candidates[0]
    if not letter.request_id:
        return None, "Dokument nie ma powiązanego wniosku."
    if request_id and letter.request.uuid != request_id:
        return None, "Identyfikator z EZD nie odpowiada treści dokumentu."
    try:
        expected = document_payload(letter, original=digest == letter.sha256)
    except ValidationError:
        return None, "Archiwalny dokument Dyna wymaga kontroli integralności."
    if payload != expected:
        return None, "Treść dokumentu nie odpowiada archiwum Dyna."
    return letter, ""


def _receive_rpw(user, number, year, *, transport=None, reason="", ip=None):
    require_role(user, "COUNTY", "MAIN")
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        raise ValidationError("Odczyt RPW wymaga uzasadnienia do 500 znaków.")
    profile = load_profile(user.office_id)
    results = []
    with EZDRPClient(profile, transport=transport) as client:
        metadata = client.incoming_metadata(number, year)
        workspace = opaque_id(metadata["idPrzestrzenRobocza"])
        for document_id, version_id in attachment_ids(metadata):
            document = client.get_document(document_id)
            if (
                document.get("idDokumentWersja") != version_id
                or document.get("idPrzestrzenRobocza") != workspace
            ):
                raise ConnectorError(
                    "Załącznik nie odpowiada wersji lub przestrzeni RPW.", state="REVIEW_REQUIRED"
                )
            # Nie pobieramy e-maili, plików XML ani obcej korespondencji do archiwum.
            if str(document.get("rozszerzenie", "")).lower().lstrip(".") != "pdf":
                continue
            content = client.document_bytes(document_id)
            if not content.startswith(b"%PDF-"):
                raise ConnectorError("Załącznik RPW nie jest plikiem PDF.", state="REVIEW_REQUIRED")
            digest = hashlib.sha256(content).hexdigest()
            claimed = claimed_request_id(profile, client.document_metadata(document_id))
            # Ponowny odczyt zamyka zmianę wersji w trakcie pobierania.
            current = client.get_document(document_id)
            if (current.get("idDokumentWersja"), current.get("idPrzestrzenRobocza")) != (
                version_id,
                workspace,
            ):
                raise ConnectorError("Dokument zmienił się podczas pobierania.", state="REVIEW_REQUIRED")
            with transaction.atomic():
                if not Office.objects.select_for_update(no_key=True).get(pk=user.office_id).active:
                    raise ValidationError("Urząd został dezaktywowany podczas odczytu.")
                letter, error = matched_letter(user.office_id, content, digest, claimed)
                row, created = EZDIncomingDocument.objects.get_or_create(
                    office_id=user.office_id,
                    target_hash=profile.target_hash,
                    rpw_number=number,
                    rpw_year=year,
                    document_id=document_id,
                    version_id=version_id,
                    defaults={"workspace_id": workspace, "sha256": digest},
                )
                if row.sha256 != digest or row.workspace_id != workspace:
                    raise ValidationError(
                        "Wersja dokumentu RPW ma inną treść niż poprzednio. Uzgodnij wynik z EZD."
                    )
                if row.letter_id and (not letter or row.letter_id != letter.pk):
                    raise ValidationError("Dawne powiązanie RPW wymaga kontroli; nie zostanie zastąpione.")
                newly_matched = bool(letter and not row.letter_id)
                if newly_matched:
                    row.letter = letter
                    row.content = content
                    row.status = "MATCHED"
                    row.request_url = settings.APP_URL.rstrip("/") + reverse(
                        "request_detail", args=[letter.request.uuid]
                    )
                row.error = error
                row.save()
                if created or newly_matched:
                    audit(
                        user,
                        "ezd.incoming.received",
                        row,
                        after={
                            "incoming": str(row.uuid),
                            "rpw_number": number,
                            "rpw_year": year,
                            "sha256": digest,
                            "status": row.status,
                        },
                        reason=reason.strip(),
                        ip=ip,
                    )
                results.append(row)
    return results


def receive_rpw(user, number, year, *, transport=None, reason="", ip=None):
    require_role(user, "COUNTY", "MAIN")
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        raise ValidationError("Odczyt RPW wymaga uzasadnienia do 500 znaków.")
    if (
        type(number) is not int
        or not 1 <= number <= 2147483647
        or type(year) is not int
        or not 2000 <= year <= 9999
    ):
        raise ValidationError("Podaj poprawny numer RPW i rok.")
    audit(
        user,
        "ezd.incoming.read.attempt",
        user.office,
        after={"rpw_number": number, "rpw_year": year},
        reason=reason.strip(),
        ip=ip,
    )
    try:
        rows = _receive_rpw(user, number, year, transport=transport, reason=reason, ip=ip)
    except (ValidationError, ConnectorError) as exc:
        audit(
            user,
            "ezd.incoming.read.error",
            user.office,
            after={"rpw_number": number, "rpw_year": year, "state": getattr(exc, "state", "REVIEW_REQUIRED")},
            reason=reason.strip(),
            ip=ip,
        )
        raise
    audit(
        user,
        "ezd.incoming.read.completed",
        user.office,
        after={"rpw_number": number, "rpw_year": year, "documents": len(rows)},
        reason=reason.strip(),
        ip=ip,
    )
    return rows


def publish_incoming_link(user, incoming_uuid, *, reason="", transport=None, ip=None):
    """Jawny idempotentny PUT tylko skonfigurowanych atrybutów zweryfikowanego pisma."""
    require_role(user, "COUNTY", "MAIN")
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        raise ValidationError("Zapis linku wymaga uzasadnienia do 500 znaków.")
    row = EZDIncomingDocument.objects.select_related("letter__request").get(
        uuid=incoming_uuid, office_id=user.office_id
    )
    if row.status != "MATCHED" or not row.letter_id or row.content is None:
        raise ValidationError("Link można zapisać tylko dla jednoznacznie powiązanego dokumentu.")
    profile = load_profile(user.office_id)
    if (
        profile.target_hash != row.target_hash
        or not all(k in profile.metadata for k in ("request_id", "request_url"))
        or profile.metadata["request_id"]["key"] == profile.metadata["request_url"]["key"]
    ):
        raise ValidationError("Profil EZD zmienił cel lub nie ma mapowania identyfikatora i linku.")
    letter, error = matched_letter(user.office_id, bytes(row.content), row.sha256, row.letter.request.uuid)
    if error or letter.pk != row.letter_id:
        raise ValidationError(error or "Niespójne powiązanie dokumentu.")
    with transaction.atomic():
        current = EZDIncomingDocument.objects.select_for_update().get(pk=row.pk)
        current.link_attempts += 1
        current.link_status = "CHECKING"
        current.link_error = ""
        current.save(update_fields=["link_attempts", "link_status", "link_error", "updated_at"])
        attempt = current.link_attempts
        audit(
            user,
            "ezd.incoming.link.attempt",
            row,
            after={"incoming": str(row.uuid), "attempt": attempt},
            reason=reason.strip(),
            ip=ip,
        )
    try:
        with EZDRPClient(profile, transport=transport) as client:
            rpw = client.incoming_metadata(row.rpw_number, row.rpw_year)
            if (row.document_id, row.version_id) not in attachment_ids(rpw):
                raise ValidationError("Dokument nie należy już do wskazanego RPW.")
            remote = client.get_document(row.document_id)
            if (remote.get("idDokumentWersja"), remote.get("idPrzestrzenRobocza")) != (
                row.version_id,
                row.workspace_id,
            ):
                raise ValidationError("Wersja dokumentu EZD zmieniła się; pobierz wpływ ponownie.")
            if client.document_sha256(row.document_id) != row.sha256:
                raise ValidationError("Dokument EZD ma inną treść niż archiwum wpływu.")
            claimed = claimed_request_id(profile, client.document_metadata(row.document_id))
            if claimed and claimed != row.letter.request.uuid:
                raise ValidationError("EZD wskazuje inny wniosek; nie nadpisano metadanych.")
            EZDIncomingDocument.objects.filter(pk=row.pk, link_attempts=attempt).update(
                link_status="PUBLISHING"
            )
            client.set_metadata(
                row.document_id,
                {
                    "request_id": str(row.letter.request.uuid),
                    "request_url": row.request_url,
                },
            )
    except (ConnectorError, ValidationError) as exc:
        message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        EZDIncomingDocument.objects.filter(pk=row.pk, link_attempts=attempt).update(
            link_status="REVIEW_REQUIRED",
            link_error=message[:300],
        )
        audit(
            user,
            "ezd.incoming.link.error",
            row,
            after={"incoming": str(row.uuid), "attempt": attempt, "state": "REVIEW_REQUIRED"},
            reason=reason.strip(),
            ip=ip,
        )
        raise
    with transaction.atomic():
        current = EZDIncomingDocument.objects.select_for_update().get(pk=row.pk)
        if (
            current.sha256 != row.sha256
            or current.letter_id != row.letter_id
            or current.link_attempts != attempt
        ):
            raise ValidationError("Powiązanie wpływu zmieniło się podczas zapisu linku.")
        current.link_status = "PUBLISHED"
        current.link_error = ""
        current.save(update_fields=["link_status", "link_error", "updated_at"])
        audit(
            user,
            "ezd.incoming.link.published",
            row,
            after={"incoming": str(row.uuid), "document_id": row.document_id},
            reason=reason.strip(),
            ip=ip,
        )
        return current
