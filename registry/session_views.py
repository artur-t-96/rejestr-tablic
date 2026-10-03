"""Odczyt rzeczywistej daty ważności sesji i jawne przedłużenie przez urzędnika."""

from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .authentication import safe_login_return, session_owner
from .services import audit


def session_check(request):
    if not request.user.is_authenticated:
        return None, JsonResponse({"error": "Logowanie wygasło. Zaloguj się ponownie."}, status=401)
    expected = request.headers.get("X-Dyna-Session-Owner") or request.POST.get("session_owner", "")
    if expected != session_owner(request.user):
        return None, JsonResponse(
            {"error": "Zmieniło się konto lub jego uprawnienia. Otwórz formularz ponownie."}, status=409
        )
    expires_at = (
        Session.objects.filter(session_key=request.session.session_key)
        .values_list("expire_date", flat=True)
        .first()
    )
    if expires_at is None or expires_at <= timezone.now():
        return None, JsonResponse({"error": "Logowanie wygasło. Zaloguj się ponownie."}, status=401)
    return expires_at, None


def status_response(expires_at):
    return JsonResponse(
        {
            "remaining_seconds": max(0, int((expires_at - timezone.now()).total_seconds())),
            "warning_seconds": settings.SESSION_WARNING_SECONDS,
        }
    )


@require_GET
def session_status(request):
    expires_at, error = session_check(request)
    return error if error is not None else status_response(expires_at)


@require_POST
def session_extend(request):
    expires_at, error = session_check(request)
    if error is not None:
        return error
    # Zapis SessionMiddleware odnowi termin w bazie. Cookie nadal wygasa
    # przy zamknięciu przeglądarki; nie zmieniamy identyfikatora ani CSRF.
    request.session.set_expiry(None)
    request.session.modified = True
    audit(request.user, "auth.session_extended", request.user, ip=request.META.get("REMOTE_ADDR"))
    if request.headers.get("Accept") == "application/json":
        return status_response(timezone.now() + timedelta(seconds=settings.SESSION_COOKIE_AGE))
    return redirect(safe_login_return(request.POST.get("return_to", "")) or "/panel/")
