"""Symulator e-Doręczeń: potwierdzenie adresu, wysyłka, status i dowody.

Przyjęta wiadomość jest od razu „doręczona”, a jej PDF trafia do symulowanego rejestru
przesyłek wpływających (RPW) urzędu adresata — tak w demo pismo „wpływa do EZD”.
"""

import base64
import json
import re
import uuid

from django.db import transaction
from django.utils import timezone

from registry.models import Office, SimulatorObject

from . import MARK, ezd, reply

UA, SE = "/api/v3", "/api/se/v4"


def office_by_ade(value):
    return Office.objects.filter(ade=value).exclude(ade="").first()


def address(office):
    return {"recipientEda": office.ade, "edaStatus": "ACTIVE", "assignmentDegree": 3, "isMainEda": True}


def evidence_xml(kind, message):
    label = "nadania" if kind == "A.1" else "otrzymania"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<dowod symulacja="true" typ="{kind}">\n'
        f"  <uwaga>{MARK}. Dowód {label} wygenerowany przez wbudowany symulator.</uwaga>\n"
        f"  <wiadomosc>{message.key}</wiadomosc>\n"
        f"  <nadawca>{message.data['from']}</nadawca>\n"
        f"  <adresat>{message.data['to']}</adresat>\n"
        f"  <czas>{message.data['submitted'] if kind == 'A.1' else message.data['received']}</czas>\n"
        "</dowod>\n"
    ).encode()


@transaction.atomic
def accept_message(sender, body):
    metadata = body["messageMetadata"]
    recipient = office_by_ade(metadata["to"][0]["eDeliveryAddress"])
    attachment = body["attachments"][0]["file"]
    payload = base64.b64decode(attachment["file"])
    if recipient is None or not payload.startswith(b"%PDF-"):
        return None
    now = timezone.now().isoformat(timespec="seconds")
    message = SimulatorObject.objects.create(
        kind="EDOR_MESSAGE",
        key=f"SIM-WIADOMOSC-{uuid.uuid4().hex}",
        office=recipient,
        data={
            "task": f"SIM-ZADANIE-{uuid.uuid4().hex}",
            "from": sender,
            "to": recipient.ade,
            "subject": metadata.get("subject", ""),
            "submitted": now,
            "received": now,
        },
    )
    sender_office = office_by_ade(sender)
    number, year = ezd.register_incoming(
        recipient.pk,
        payload,
        attachment["fileMetadata"]["filename"],
        f"{sender_office.name if sender_office else sender} (symulator e-Doręczeń)",
    )
    message.data["rpw"] = f"RPW/{number}/{year}"
    message.save(update_fields=["data"])
    return message


def message_by(field, value):
    if field == "key":
        return SimulatorObject.objects.filter(kind="EDOR_MESSAGE", key=value).first()
    return SimulatorObject.objects.filter(kind="EDOR_MESSAGE", data__task=value).first()


def handle(request):
    path, method = request.url.path, request.method
    if path.endswith("/token") and method == "POST":
        return reply(200, {"access_token": "SIM-EDOR", "expires_in": 300, "token_type": "Bearer"})
    if request.headers.get("Authorization") != "Bearer SIM-EDOR":
        return reply(401, {"error": "Brak tokenu symulatora."})
    body = json.loads(request.content) if request.content else {}

    if path == SE + "/search/eda-confirmation":
        office = office_by_ade(body.get("recipientEda"))
        if not office:
            return reply(404, {"error": "Adres nie istnieje w symulatorze."})
        return reply(
            200,
            {
                "recipientEda": address(office),
                "recipient": {"isPublic": True, "entityName": office.name + " (symulator)"},
            },
        )
    if path == SE + "/search/bae_search":
        offices = (
            Office.objects.filter(name__icontains=body.get("entityName", "")).exclude(ade="").order_by("name")
        )
        offset = int(body.get("offset", 0))
        return reply(
            200,
            {
                "baeSearchResponses": [
                    {
                        "recipientEda": address(office),
                        "baeSearchData": [
                            {"index": 1, "isPublic": True, "entityName": office.name + " (symulator)"}
                        ],
                    }
                    for office in offices[offset : offset + 20]
                ],
                "totalResults": offices.count(),
            },
        )
    match = re.fullmatch(UA + r"/(AE:PL-[^/]+)(/.*)", path)
    if not match:
        return reply(404, {"error": "Operacja nieobsługiwana przez symulator e-Doręczeń."})
    sender, rest = match[1], match[2]
    if rest == "/messages" and method == "POST":
        message = accept_message(sender, body)
        if message is None:
            return reply(400, {"error": "Symulator wymaga adresata z rejestru urzędów i załącznika PDF."})
        return reply(202, {"messageTaskId": message.data["task"]})
    if found := re.fullmatch(r"/messages/tasks/([^/]+)(/status)?", rest):
        message = message_by("task", found[1])
        if not message or message.data["from"] != sender:
            return reply(404, {"error": "Brak zadania."})
        if found[2]:
            return reply(200, {"messageTaskStatus": "FINISHED"})
        return reply(200, [{"addressee": {"eDeliveryAddress": message.data["to"]}, "messageId": message.key}])
    if found := re.fullmatch(r"/messages/([^/]+)(/evidences)?", rest):
        message = message_by("key", found[1])
        if not message or message.data["from"] != sender:
            return reply(404, {"error": "Brak wiadomości."})
        if found[2]:
            return reply(
                200,
                {
                    "evidences": [
                        {
                            "messageId": message.key,
                            "evidenceId": f"{message.key}-{kind.replace('.', '')}",
                            "type": kind,
                            "eventDate": message.data["submitted" if kind == "A.1" else "received"],
                            "createDate": message.data["received"],
                        }
                        for kind in ("A.1", "E.1")
                    ]
                },
            )
        return reply(
            200,
            [
                {
                    "messageMetadata": {
                        "messageId": message.key,
                        "from": {"eDeliveryAddress": message.data["from"]},
                        "to": [{"eDeliveryAddress": message.data["to"]}],
                        "subject": message.data["subject"],
                        "shippingService": "electronic",
                        "submissionDate": message.data["submitted"],
                        "receiptDate": message.data["received"],
                    },
                    "messageControlData": {"status": "Doręczona"},
                }
            ],
        )
    if found := re.fullmatch(r"/evidences/purde/(.+)-(A1|E1)", rest):
        message = message_by("key", found[1])
        if not message or message.data["from"] != sender:
            return reply(404, {"error": "Brak dowodu."})
        kind = "A.1" if found[2] == "A1" else "E.1"
        return reply(200, content=evidence_xml(kind, message), content_type="application/xml")
    return reply(404, {"error": "Operacja nieobsługiwana przez symulator e-Doręczeń."})
