import ipaddress

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponseBadRequest


class OnPremProxyMiddleware:
    """Nginx nadpisuje oba nagłówki; dostęp wyłącznie przez lokalny upstream."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        peer = request.META.get("REMOTE_ADDR", "")
        if peer not in settings.TRUSTED_PROXY_ADDRESSES:
            return HttpResponseBadRequest("Niepoprawna droga dostępu do aplikacji.")
        client = request.META.get("HTTP_X_DYNA_CLIENT_IP", "")
        proto = request.META.get("HTTP_X_FORWARDED_PROTO", "")
        try:
            client = str(ipaddress.ip_address(client))
        except ValueError:
            return HttpResponseBadRequest("Niepoprawna konfiguracja pośrednika.")
        if proto not in {"http", "https"}:
            return HttpResponseBadRequest("Niepoprawna konfiguracja pośrednika.")
        request.META["REMOTE_ADDR"] = client
        # Nie korzystamy z nagłówków klienta ani z list pośredników.
        for key in ("HTTP_FORWARDED", "HTTP_X_FORWARDED_FOR", "HTTP_X_FORWARDED_HOST"):
            request.META.pop(key, None)
        return self.get_response(request)


class AccountMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.access_allowed:
            logout(request)
        response = self.get_response(request)
        if request.path.startswith(("/panel/", "/api/", "/logowanie/")):
            response["Cache-Control"] = "no-store"
        response["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        response["Referrer-Policy"] = "same-origin"
        return response
