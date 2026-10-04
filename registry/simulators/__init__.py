"""Wbudowane symulatory operatorów dla trybu demonstracyjnego.

Istniejące konektory rozmawiają z nimi przez transport `httpx` działający w procesie, więc
kod wysyłki, obserwacji i odczytu wpływów jest ten sam co dla prawdziwej usługi. Stan leży
w bazie (`SimulatorObject`), dlatego widzą go i serwer WWW, i proces kolejki. Nic stąd nie
jest dowodem operatora.
"""

import json

import httpx
from django.conf import settings

MARK = "SYMULACJA — to nie jest odpowiedź operatora"


def reply(status, payload=None, *, content=None, content_type="application/json"):
    if content is None:
        content = json.dumps(payload, ensure_ascii=False).encode()
    return httpx.Response(status, content=content, headers={"Content-Type": content_type})


def handle(request):
    if not settings.DEMO_MODE:
        return reply(503, {"error": "Symulator działa wyłącznie w trybie demonstracyjnym."})
    from . import edor, ezd

    host = request.url.host
    if host.startswith("ezd-"):
        return ezd.handle(request, host.split(".", 1)[0][4:])
    if host.startswith("edor."):
        return edor.handle(request)
    return reply(404, {"error": "Nieznany symulator."})


def transport():
    return httpx.MockTransport(handle)
