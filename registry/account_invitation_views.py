"""Administracyjne zaproszenia: jawna kolejka i uzgadnianie wyniku SMTP."""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .account_invitations import context, enqueue_invitation, manage_invitation
from .models import AccountInvitation, User
from .services import require_role

SALT = "account-invitation-review-v1"


class InvitationForm(forms.Form):
    version = forms.CharField(widget=forms.HiddenInput)
    action = forms.ChoiceField(label="Operacja")
    reason = forms.CharField(label="Powód", max_length=1000, widget=forms.Textarea(attrs={"rows": 2}))
    proof = forms.CharField(
        label="Wynik sprawdzenia SMTP (bez haseł i tokenów)",
        max_length=2000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    acknowledged = forms.BooleanField(
        required=False,
        label="Sprawdziłem wynik tej wiadomości w serwerze pocztowym. Wznowienie wybieram tylko, gdy nie została przyjęta.",
    )


@login_required
@require_http_methods(["GET", "POST"])
def account_invitations(request, user_pk, uuid=None):
    require_role(request.user, "ADMIN")
    user = get_object_or_404(User.objects.select_related("office"), pk=user_pk, removed_at__isnull=True)
    item = get_object_or_404(AccountInvitation, user=user, uuid=uuid) if uuid else None
    snapshot = {
        "actor": request.user.pk,
        "user": user.pk,
        "invitation": str(item.uuid) if item else None,
        "version": item.updated_at.isoformat() if item else context(user),
    }
    choices = [("invite", "Utwórz zaproszenie")]
    if item:
        choices = []
        if item.status in {"CONFIG_ERROR", "REVIEW_REQUIRED"}:
            choices.append(("retry", "Nie przyjęto wiadomości — wznowienie wysyłki"))
        if item.status == "REVIEW_REQUIRED":
            choices.append(("confirm", "Potwierdź przyjęcie wiadomości przez serwer"))
        if item.status in {"QUEUED", "CONFIG_ERROR", "REVIEW_REQUIRED"}:
            choices.append(("cancel", "Zamknij zaproszenie bez wysyłki"))
    form = InvitationForm(request.POST or None, initial={"version": signing.dumps(snapshot, salt=SALT)})
    form.fields["action"].choices = choices
    if not item or item.status != "REVIEW_REQUIRED":
        form.fields.pop("proof")
        form.fields.pop("acknowledged")
    if request.method == "POST" and form.is_valid():
        try:
            token = signing.loads(form.cleaned_data["version"], salt=SALT, max_age=900)
            if not isinstance(token, dict) or any(
                token.get(k) != snapshot[k] for k in ["actor", "user", "invitation"]
            ):
                raise ValidationError("Formularz nie odpowiada temu kontu. Otwórz go ponownie.")
            if item:
                manage_invitation(
                    request.user,
                    item.pk,
                    token.get("version"),
                    form.cleaned_data["action"],
                    form.cleaned_data["reason"],
                    form.cleaned_data.get("proof", ""),
                    form.cleaned_data.get("acknowledged", False),
                    request.META.get("REMOTE_ADDR"),
                )
            else:
                enqueue_invitation(
                    request.user,
                    user.pk,
                    form.cleaned_data["reason"],
                    request.META.get("REMOTE_ADDR"),
                    token.get("version"),
                )
        except (signing.BadSignature, ValidationError) as exc:
            form.add_error(
                None,
                "; ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else "Formularz wygasł lub został zmieniony. Otwórz go ponownie.",
            )
        else:
            messages.success(
                request,
                "Zapisano operację zaproszenia. Przyjęcie przez SMTP nie potwierdza odbioru przez użytkownika.",
            )
            return redirect("account_invitations", user_pk=user.pk)
    return render(
        request,
        "registry/account_invitations.html",
        {
            "account": user,
            "invitations": user.invitations.order_by("-created_at")[:50],
            "item": item,
            "form": form,
            "has_actions": bool(choices),
        },
    )
