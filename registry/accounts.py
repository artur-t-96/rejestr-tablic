"""Usuwanie kont i sposób, w jaki konto jest podpisywane w historii."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone

from .demo import demo_viewer, is_demo_email
from .models import AccountInvitation, LoginCode, User
from .services import audit, require_role

REMOVED_DOMAIN = "usuniete.invalid"


def account_label(user, *, viewer=None, with_email=False):
    """Podpis konta w historii; zamknięte konto zachowuje imię i nazwisko bez adresu."""
    name = user.get_full_name()
    if viewer is not None and demo_viewer(viewer) and not (is_demo_email(user.email) or user.is_demo_removed):
        # Instancja demo jest współdzielona: konto demo nie poznaje danych kont rzeczywistych,
        # także zamkniętych.
        return "Konto urzędowe"
    if user.removed_at:
        return f"{name or 'Użytkownik'} (konto usunięte)"
    if with_email:
        return f"{name} · {user.email}" if name else user.email
    return name or user.email


@transaction.atomic
def remove_account(actor, user_pk, version, reason, ip=None):
    from .forms import account_settings_snapshot

    require_role(actor, "ADMIN")
    user = User.objects.select_for_update(of=("self",)).get(pk=user_pk)
    if user.removed_at:
        raise ValidationError("To konto jest już usunięte.")
    if user.pk == actor.pk:
        raise ValidationError("Własnego konta nie usuniesz. Zrobi to inny administrator.")
    if version != account_settings_snapshot(user):
        raise ValidationError("Konto zmieniło się w międzyczasie. Otwórz ponownie formularz.")
    if not reason.strip():
        raise ValidationError("Podaj powód usunięcia konta.")
    if AccountInvitation.objects.filter(user=user, status="SENDING").exists():
        raise ValidationError("Zaproszenie do tego konta jest właśnie wysyłane. Spróbuj za chwilę.")
    before = {"role": user.role, "office": user.office_id, "is_active": user.is_active}
    try:
        with transaction.atomic():
            AccountInvitation.objects.filter(user=user).delete()
            user.delete()
    except ProtectedError:
        # Konto pracowało w systemie: wnioski, rozpatrzenia i dziennik muszą nadal wskazywać, kto działał.
        user.is_active = False
        user.removed_at = timezone.now()
        # Zamknięte konto demo zachowuje oznaczenie, żeby pozostało widoczne dla kont demo.
        marker = "demo-" if is_demo_email(user.email) else ""
        user.email = user.username = f"usuniete-{marker}{user_pk}@{REMOVED_DOMAIN}"
        user.set_unusable_password()
        user.save(update_fields=["is_active", "removed_at", "email", "username", "password"])
        LoginCode.objects.filter(user=user).delete()
        AccountInvitation.objects.filter(user=user).update(
            status="CANCELLED",
            email=user.email,
            body="Treść usunięta razem z kontem.",
            account_context={},
            claimed_until=None,
        )
        audit(actor, "admin.user_closed", user, before, {"is_active": False}, reason, ip)
        return "closed"
    user.pk = user_pk
    audit(actor, "admin.user_deleted", user, before, {}, reason, ip)
    return "deleted"
