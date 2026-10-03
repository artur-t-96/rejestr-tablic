"""Trwałe zaproszenia do istniejącego konta; nie zawierają OTP ani uprawnień."""

import hashlib
import json
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from .models import AccountInvitation, User
from .microsoft_mail import configuration_ready
from .services import audit, require_role

PENDING = {"QUEUED", "SENDING", "REVIEW_REQUIRED", "CONFIG_ERROR"}


def context(user):
    return {
        "email": user.email,
        "role": user.role,
        "office_id": user.office_id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "active": user.is_active,
        "office_active": bool(not user.office_id or user.office.active),
        "allowed_domains": user.office.allowed_domains if user.office_id else [],
        "app_url": settings.APP_URL,
    }


def content_hash(invitation):
    value = {
        "email": invitation.email,
        "context": invitation.account_context,
        "subject": invitation.subject,
        "body": invitation.body,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@transaction.atomic
def enqueue_invitation(actor, user_id, reason, ip=None, expected_context=None):
    require_role(actor, "ADMIN")
    if not reason.strip() or len(reason) > 1000:
        raise ValidationError("Podaj podstawę zaproszenia do 1000 znaków.")
    user = User.objects.select_for_update(of=("self",), no_key=True).select_related("office").get(pk=user_id)
    if expected_context is not None and expected_context != context(user):
        raise ValidationError("Konto zmieniło się. Otwórz ponownie formularz zaproszenia.")
    if not user.access_allowed:
        raise ValidationError("Zaproszenie wymaga aktywnego konta, urzędu i dozwolonej domeny e-mail.")
    user.full_clean()
    if AccountInvitation.objects.filter(user=user, status__in=PENDING).exists():
        raise ValidationError(
            "Zaproszenie już oczekuje lub wymaga uzgodnienia. Nie utworzono kolejnej wiadomości."
        )
    snap = context(user)
    invitation = AccountInvitation(
        user=user,
        created_by=actor,
        email=user.email,
        account_context=snap,
        subject="Zaproszenie do Dyna Rejestr Tablic",
        body=f"Administrator utworzył dla Ciebie konto w Dyna Rejestr Tablic.\n"
        f"Rola: {user.get_role_display()}\nUrząd: {user.office.name if user.office_id else 'Administracja systemu'}\n"
        f"Otwórz {settings.APP_URL.rstrip('/')}/logowanie/ i wpisz swój adres e-mail. "
        "Otrzymasz osobny kod ważny 10 minut. Ta wiadomość nie jest kodem logowania.\n"
        "Jeśli nie oczekujesz dostępu, skontaktuj się z administratorem urzędu.",
    )
    invitation.content_sha256 = content_hash(invitation)
    invitation.full_clean()
    invitation.save()
    audit(
        actor,
        "account.invitation_queued",
        user,
        after={"invitation": str(invitation.uuid), "email": user.email},
        reason=reason.strip(),
        ip=ip,
    )
    return invitation


def process_invitation(invitation_id):
    # Kolejność we wszystkich operacjach: konto → wiadomość.
    user_id = AccountInvitation.objects.values_list("user_id", flat=True).get(pk=invitation_id)
    with transaction.atomic():
        user = (
            User.objects.select_for_update(of=("self",), no_key=True).select_related("office").get(pk=user_id)
        )
        item = AccountInvitation.objects.select_for_update().get(pk=invitation_id)
        if item.status != "QUEUED":
            return item
        before = {"status": item.status}
        if item.account_context != context(user) or not user.access_allowed:
            item.status = "CANCELLED"
            item.error = "Konto, urząd lub adres aplikacji zmieniły się. Administrator musi sprawdzić dostęp."
        elif item.content_sha256 != content_hash(item):
            item.status = "REVIEW_REQUIRED"
            item.error = "Treść zaproszenia nie odpowiada sumie kontrolnej. Wysyłka wstrzymana."
        elif not settings.LOCAL and not configuration_ready():
            item.status = "CONFIG_ERROR"
            item.error = "Brak konfiguracji poczty. Wysyłka nie rozpoczęła się."
        else:
            item.status = "SENDING"
            item.attempts += 1
            item.claimed_until = timezone.now() + timedelta(minutes=2)
            item.error = ""
        item.save()
        audit(
            None,
            "account.invitation_state",
            user,
            before=before,
            after={"invitation": str(item.uuid), "status": item.status, "attempts": item.attempts},
        )
        if item.status != "SENDING":
            return item
    # Poczta poza transakcją. Sam Message-ID nie gwarantuje deduplikacji SMTP.
    try:
        sent = EmailMessage(
            item.subject,
            item.body,
            settings.DEFAULT_FROM_EMAIL,
            [item.email],
            headers={"Message-ID": f"<account-{item.uuid}@dyna-rejestr.local>"},
        ).send()
        if sent != 1:
            raise ValidationError("Brak potwierdzenia SMTP")
        status = (
            "LOCAL_SAVED"
            if settings.LOCAL and settings.EMAIL_BACKEND.endswith("filebased.EmailBackend")
            else "ACCEPTED"
        )
        error = ""
    except Exception:
        status = "REVIEW_REQUIRED"
        error = "Nie ustalono wyniku wysyłki. Sprawdź serwer pocztowy przed ponownym zaproszeniem."
    with transaction.atomic():
        user = User.objects.select_for_update(of=("self",), no_key=True).get(pk=user_id)
        current = AccountInvitation.objects.select_for_update().get(pk=item.pk)
        if current.status == "SENDING" and current.claimed_until == item.claimed_until:
            current.status = status
            current.error = error
            current.sent_at = timezone.now() if not error else None
            current.claimed_until = None
            current.save()
            audit(
                None,
                "account.invitation_state",
                user,
                before={"status": "SENDING"},
                after={"invitation": str(current.uuid), "status": status, "attempts": current.attempts},
            )
        return current


@transaction.atomic
def recover_invitations():
    now = timezone.now()
    items = AccountInvitation.objects.select_for_update().filter(status="SENDING", claimed_until__lte=now)
    count = 0
    for item in items:
        item.status = "REVIEW_REQUIRED"
        item.claimed_until = None
        item.error = "Przerwana wysyłka zaproszenia. Sprawdź wynik w serwerze pocztowym."
        item.save()
        audit(
            None,
            "account.invitation_interrupted",
            item,
            before={"status": "SENDING"},
            after={"status": item.status, "user_id": item.user_id},
        )
        count += 1
    return count


@transaction.atomic
def manage_invitation(actor, invitation_id, version, action, reason, proof="", acknowledged=False, ip=None):
    require_role(actor, "ADMIN")
    if not reason.strip() or len(reason) > 1000:
        raise ValidationError("Podaj powód do 1000 znaków.")
    user_id = AccountInvitation.objects.values_list("user_id", flat=True).get(pk=invitation_id)
    user = User.objects.select_for_update(of=("self",), no_key=True).select_related("office").get(pk=user_id)
    item = AccountInvitation.objects.select_for_update().get(pk=invitation_id)
    if version != item.updated_at.isoformat():
        raise ValidationError("Stan zaproszenia zmienił się. Otwórz ponownie formularz.")
    before = {"status": item.status}
    if item.status == "REVIEW_REQUIRED" and (not acknowledged or not proof.strip()):
        raise ValidationError("Podaj wynik sprawdzenia w serwerze pocztowym i potwierdź jego weryfikację.")
    if len(proof) > 2000:
        raise ValidationError("Opis sprawdzenia może mieć do 2000 znaków.")
    if action == "confirm" and item.status == "REVIEW_REQUIRED":
        item.status = "CONFIRMED_SENT"
    elif action == "cancel" and item.status in {"QUEUED", "CONFIG_ERROR", "REVIEW_REQUIRED"}:
        item.status = "CANCELLED"
    elif action == "retry" and item.status in {"CONFIG_ERROR", "REVIEW_REQUIRED"}:
        if item.account_context != context(user) or not user.access_allowed:
            raise ValidationError(
                "Konto lub urząd zmieniły się. Anuluj zaproszenie i sprawdź aktualny dostęp."
            )
        if item.content_sha256 != content_hash(item):
            raise ValidationError("Suma kontrolna wiadomości jest niezgodna. Anuluj zaproszenie.")
        item.status = "QUEUED"
    else:
        raise ValidationError("Ta operacja nie jest dostępna dla aktualnego stanu zaproszenia.")
    item.error = ""
    item.claimed_until = None
    item.save()
    audit(
        actor,
        "account.invitation_reconciled",
        user,
        before=before,
        after={
            "invitation": str(item.uuid),
            "status": item.status,
            "operator_check": proof.strip(),
            "acknowledged": acknowledged,
        },
        reason=reason.strip(),
        ip=ip,
    )
    return item
