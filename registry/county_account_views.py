"""Konta urzędników prowadzone przez administratora powiatu (uwagi UMP 06.11.2026, pkt 8)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .demo import DOMAIN as DEMO_DOMAIN
from .demo import SEEDED as DEMO_SEEDED
from .demo import demo_viewer, is_demo_email
from .forms import CountyUserForm, account_settings_snapshot
from .models import User
from .services import audit, require_account_manager
from .views import form_errors, ip

TRACKED = ("email", "first_name", "last_name", "is_active")


def county_admin(request):
    user = request.user
    require_account_manager(user)
    if user.role != "COUNTY":
        # Administrator centralny prowadzi konta w panelu administracji.
        raise Http404
    return user


def county_users(user):
    users = User.objects.filter(office_id=user.office_id, role="COUNTY", removed_at__isnull=True)
    if demo_viewer(user):
        # Konto demo widzi i zmienia wyłącznie konta demonstracyjne, nie rzeczywiste konta urzędu.
        users = users.filter(email__endswith="@" + DEMO_DOMAIN)
    return users


@login_required
@require_http_methods(["GET"])
def county_accounts(request):
    actor = county_admin(request)
    return render(
        request,
        "registry/county_accounts.html",
        {"users": county_users(actor).order_by("last_name", "first_name", "email")},
    )


@login_required
@require_http_methods(["GET", "POST"])
def county_account_edit(request, pk=None):
    actor = county_admin(request)
    target = get_object_or_404(county_users(actor), pk=pk) if pk else None
    if target:
        require_account_manager(actor, target)
    demo = demo_viewer(actor)
    if demo and target and target.email in DEMO_SEEDED and target.pk != actor.pk:
        raise Http404
    if target and request.method == "POST" and request.POST.get("action") == "remove":
        return remove(request, actor, target)
    form = CountyUserForm(request.POST or None, instance=target, office=actor.office)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                before = {}
                if target:
                    old = User.objects.select_for_update(of=("self",), no_key=True).get(pk=target.pk)
                    try:
                        version = signing.loads(
                            form.cleaned_data["account_version"], salt="admin-account-version", max_age=1800
                        )
                    except signing.BadSignature as exc:
                        raise ValidationError("Formularz konta wygasł. Otwórz go ponownie.") from exc
                    if version != account_settings_snapshot(old):
                        raise ValidationError("Konto zmieniło się w międzyczasie. Otwórz ponownie formularz.")
                    if old.pk == actor.pk and (
                        form.cleaned_data["email"] != old.email.lower() or not form.cleaned_data["is_active"]
                    ):
                        raise ValidationError(
                            "Własnego adresu e-mail ani blokady konta nie zmienisz sam. Zgłoś to do UMP."
                        )
                    before = {key: getattr(old, key) for key in TRACKED}
                item = form.save(commit=False)
                if demo and not is_demo_email(item.email):
                    raise ValidationError(f"W trybie demo załóż konto z adresem w domenie @{DEMO_DOMAIN}.")
                item.full_clean()
                item.save()
                audit(
                    actor,
                    "county.user_saved",
                    item,
                    before=before,
                    after={"id": str(item.pk), **{key: getattr(item, key) for key in TRACKED}},
                    reason=form.cleaned_data["reason"],
                    ip=ip(request),
                )
                if not target and item.is_active:
                    from .account_invitations import enqueue_invitation

                    enqueue_invitation(actor, item.pk, form.cleaned_data["reason"], ip(request))
        except ValidationError as exc:
            form_errors(form, exc)
        except IntegrityError:
            form.add_error(None, "Konto z tym adresem e-mail już istnieje.")
        else:
            messages.success(
                request,
                "Konto zapisane." + (" Zaproszenie oczekuje na wysyłkę." if not target and item.is_active else ""),
            )
            return redirect("county_accounts")
    return render(
        request,
        "registry/form.html",
        {
            "form": form,
            "title": "Konto urzędnika" if target else "Nowe konto urzędnika",
            "description": f"Urząd: {actor.office.name}. Rola: urzędnik powiatowy.",
            "submit": "Zapisz",
            "remove_version": form.initial.get("account_version") if target and target.pk != actor.pk else "",
        },
    )


def remove(request, actor, target):
    from .accounts import remove_account

    try:
        try:
            version = signing.loads(
                request.POST.get("account_version", ""), salt="admin-account-version", max_age=1800
            )
        except signing.BadSignature as exc:
            raise ValidationError("Formularz konta wygasł. Otwórz go ponownie.") from exc
        result = remove_account(actor, target.pk, version, request.POST.get("reason", ""), ip(request))
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
        return redirect("county_account_edit", pk=target.pk)
    messages.success(
        request,
        "Konto usunięte."
        if result == "deleted"
        else "Konto zamknięte i ukryte. Historia zachowuje imię i nazwisko bez adresu e-mail.",
    )
    return redirect("county_accounts")
