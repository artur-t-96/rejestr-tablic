"""Symulator EZD RP: sprawy, dokumenty, metadane i rejestr przesyłek wpływających (RPW)."""

import json
import re
import uuid
from datetime import date
from email.parser import BytesParser
from email.policy import HTTP

from django.db import IntegrityError, transaction
from django.utils import timezone

from registry.models import Office, SimulatorObject

from . import reply

PREFIX = "/ezdrp/integrator/v2"


def pid(office_id):
    return f"SIM-PODMIOT-{office_id}"


def workspace(office_id):
    return f"SIM-PRZESTRZEN-{office_id}"


def store_document(office_id, payload, filename, *, case_id=""):
    """Dokument PDF w przestrzeni urzędu; używany też przy symulowanym wpływie z e-Doręczeń."""
    document_id = f"SIM-DOK-{uuid.uuid4().hex}"
    SimulatorObject.objects.create(
        kind="EZD_DOC",
        key=document_id,
        office_id=office_id,
        content=payload,
        data={
            "idDokument": f"SIM-D-{uuid.uuid4().hex[:12]}",
            "idDokumentWersja": f"SIM-W-{uuid.uuid4().hex[:12]}",
            "nazwa": filename,
            "case": case_id,
            "metadata": [],
        },
    )
    return document_id


@transaction.atomic
def register_incoming(office_id, payload, filename, sender):
    """Wpisuje przesyłkę do RPW urzędu adresata pod kolejnym numerem w roku."""
    Office.objects.select_for_update(no_key=True).get(pk=office_id)
    year = timezone.localdate().year
    taken = SimulatorObject.objects.filter(kind="EZD_RPW", office_id=office_id, data__year=year).count()
    document_id = store_document(office_id, payload, filename)
    SimulatorObject.objects.create(
        kind="EZD_RPW",
        key=f"{office_id}:{year}:{taken + 1}",
        office_id=office_id,
        data={
            "number": taken + 1,
            "year": year,
            "date": timezone.localdate().isoformat(),
            "sender": sender,
            "documents": [document_id],
        },
    )
    return taken + 1, year


def document(office_id, document_id):
    return SimulatorObject.objects.filter(kind="EZD_DOC", key=document_id, office_id=office_id).first()


def document_summary(item, office_id):
    return {
        "idDokument": item.data["idDokument"],
        "idDokumentPrzestrzeni": item.key,
        "idDokumentWersja": item.data["idDokumentWersja"],
        "idPrzestrzenRobocza": workspace(office_id),
        "nazwa": item.data["nazwa"],
        "rozszerzenie": "pdf",
    }


def uploaded_file(request):
    message = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + request.headers["Content-Type"].encode() + b"\r\n\r\n" + request.content
    )
    for part in message.iter_parts():
        if part.get_filename():
            return part.get_filename(), part.get_payload(decode=True)
    return None, None


def handle(request, office_id):
    if not Office.objects.filter(pk=office_id).exists():
        return reply(404, {"error": "Nieznany urząd symulatora."})
    path, method = request.url.path, request.method
    if path == "/connect/token" and method == "POST":
        return reply(
            200, {"access_token": "SIM-EZD-" + office_id, "expires_in": 3600, "token_type": "Bearer"}
        )
    if match := re.fullmatch(r"/download/([^/]+)", path):
        item = document(office_id, match[1])
        if not item:
            return reply(404, {"error": "Brak dokumentu."})
        return reply(200, content=bytes(item.content), content_type="application/pdf")
    if not path.startswith(PREFIX) or not request.headers.get("Authorization", "").startswith(
        "Bearer SIM-EZD-"
    ):
        return reply(401, {"error": "Brak tokenu symulatora."})
    path = path[len(PREFIX) :]
    body = (
        json.loads(request.content)
        if request.headers.get("Content-Type", "").startswith("application/json")
        else {}
    )

    if path == "/sprawy" and method == "POST":
        case_id = f"SIM-SPRAWA-{uuid.uuid4().hex[:16]}"
        data = {
            "idSprawa": case_id,
            "tytul": body.get("tytul", ""),
            "idPodmiotWlascicielBiznesowy": pid(office_id),
            "znak": f"SYM.{body.get('idWykaz', '')}.{body.get('numer')}.{body.get('rokZalozenia')}",
        }
        try:
            with transaction.atomic():
                SimulatorObject.objects.create(kind="EZD_CASE", key=case_id, office_id=office_id, data=data)
        except IntegrityError:
            return reply(409, {"error": "Konflikt sprawy."})
        return reply(201, data)
    if match := re.fullmatch(r"/sprawy/([^/]+)", path):
        case = SimulatorObject.objects.filter(kind="EZD_CASE", key=match[1], office_id=office_id).first()
        return reply(200, case.data) if case else reply(404, {"error": "Brak sprawy."})
    if (match := re.fullmatch(r"/sprawy/([^/]+)/dokumenty", path)) and method == "POST":
        if not SimulatorObject.objects.filter(kind="EZD_CASE", key=match[1], office_id=office_id).exists():
            return reply(404, {"error": "Brak sprawy."})
        filename, payload = uploaded_file(request)
        if not payload or not payload.startswith(b"%PDF-"):
            return reply(400, {"error": "Symulator przyjmuje jeden plik PDF."})
        item = document(office_id, store_document(office_id, payload, filename, case_id=match[1]))
        return reply(200, {"lista": [document_summary(item, office_id)]})
    if match := re.fullmatch(r"/dokumenty/([^/]+)(/link|/metadane)?", path):
        item = document(office_id, match[1])
        if not item:
            return reply(404, {"error": "Brak dokumentu."})
        if match[2] == "/link":
            return reply(200, {"link": f"https://{request.url.host}/download/{item.key}"})
        if match[2] == "/metadane":
            if method == "PUT":
                values = {entry["klucz"]: entry for entry in item.data["metadata"]}
                for entry in body.get("metadane", []):
                    values[entry["klucz"]] = {
                        "klucz": entry["klucz"],
                        "nazwa": entry.get("nazwa", ""),
                        "wartosc": entry["wartosc"],
                    }
                item.data["metadata"] = list(values.values())
                item.save(update_fields=["data"])
                return reply(200, {"metadane": item.data["metadata"]})
            return reply(
                200,
                {
                    "idDokumentPrzestrzeni": item.key,
                    "listaKonfiguracji": [
                        {
                            "kluczSystemowy": e["klucz"],
                            "id": e["klucz"],
                            "nazwa": e["nazwa"],
                            "wartosc": e["wartosc"],
                        }
                        for e in item.data["metadata"]
                    ],
                },
            )
        return reply(200, document_summary(item, office_id))
    if match := re.fullmatch(r"/rpw/([0-9]+)/([0-9]{4})/metadane", path):
        entry = SimulatorObject.objects.filter(
            kind="EZD_RPW", key=f"{office_id}:{match[2]}:{match[1]}"
        ).first()
        if not entry:
            return reply(404, {"error": "Brak RPW."})
        attachments = []
        for document_id in entry.data["documents"]:
            item = document(office_id, document_id)
            attachments.append(
                {
                    "idDokumentPrzestrzeni": item.key,
                    "idDokumentWersja": item.data["idDokumentWersja"],
                    "zalaczniki": [],
                }
            )
        return reply(
            200,
            {
                "numerRPW": f"RPW/{match[1]}/{match[2]}",
                "status": 2,
                "idPrzestrzenRobocza": workspace(office_id),
                "nadawca": entry.data["sender"],
                "zalaczniki": attachments,
            },
        )
    if path == "/rpw/_search" and method == "POST":
        start, end = date.fromisoformat(body["dataOd"]), date.fromisoformat(body["dataDo"])
        page = int(body.get("page", 0))
        rows = [
            entry
            for entry in SimulatorObject.objects.filter(kind="EZD_RPW", office_id=office_id).order_by("pk")
            if start <= date.fromisoformat(entry.data["date"]) <= end
        ]
        pages = max(1, -(-len(rows) // 25))
        return reply(
            200,
            {
                "lista": [
                    {
                        "numerRPW": f"RPW/{entry.data['number']}/{entry.data['year']}",
                        "idPodmiotWlascicielBiznesowy": pid(office_id),
                        "czyUsuniety": False,
                    }
                    for entry in rows[page * 25 : page * 25 + 25]
                ],
                "pageInfo": {
                    "pageNumber": page,
                    "pageSize": 25,
                    "isNextPageExists": page + 1 < pages,
                    "pagesCount": pages,
                },
            },
        )
    return reply(404, {"error": "Operacja nieobsługiwana przez symulator EZD RP."})
