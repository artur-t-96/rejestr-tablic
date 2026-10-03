import ipaddress

from django.conf import settings
from django.http import HttpResponseBadRequest


class RenderProxyMiddleware:
    """Odczyt od prawej strony łańcucha, tylko za potwierdzonymi pośrednikami."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.networks = settings.RENDER_PROXY_NETWORKS
        self.edges = settings.RENDER_EDGE_NETWORKS

    def trusted(self, address):
        return any(address in network for network in self.networks)

    def __call__(self, request):
        try:
            peer = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
            if not self.trusted(peer):
                raise ValueError
            forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
            if not forwarded and request.path == "/api/health/":
                client = peer  # Wewnętrzny probe nie wykonuje operacji biznesowych.
            else:
                parts = forwarded.split(",")
                if len(parts) > 20 or len(forwarded) > 1024:
                    raise ValueError
                # Publiczna trasa Render kończy XFF adresem Cloudflare. Sam
                # prywatny peer nie wystarcza do przyjęcia tożsamości klienta.
                edge = ipaddress.ip_address(parts[-1].strip())
                if not any(edge in network for network in self.edges):
                    raise ValueError
                client = None
                for value in reversed(parts):
                    address = ipaddress.ip_address(value.strip())
                    if not self.trusted(address):
                        client = address
                        break
                if client is None:
                    raise ValueError
            proto = request.META.get("HTTP_X_FORWARDED_PROTO", "")
            if not proto and not forwarded and request.path == "/api/health/":
                proto = "http"
            if proto not in {"http", "https"}:
                raise ValueError
        except ValueError:
            return HttpResponseBadRequest("Niepoprawna konfiguracja pośrednika.")
        request.META["REMOTE_ADDR"] = str(client)
        request.META["HTTP_X_FORWARDED_PROTO"] = proto
        for key in ("HTTP_FORWARDED", "HTTP_X_FORWARDED_FOR", "HTTP_X_FORWARDED_HOST",
                    "HTTP_CF_CONNECTING_IP", "HTTP_TRUE_CLIENT_IP", "HTTP_X_DYNA_CLIENT_IP"):
            request.META.pop(key, None)
        return self.get_response(request)
