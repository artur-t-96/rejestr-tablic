import csv
import hashlib
import secrets
from datetime import timedelta
from functools import wraps
from io import StringIO

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .authentication import safe_login_return
from .forms import (
    CheckForm,
    DecisionForm,
    LoginCodeForm,
    LoginEmailForm,
    OfficeForm,
    PoolForm,
    RecordForm,
    RequestForm,
    TemplateForm,
    UserForm,
    account_settings_snapshot,
)
from .models import (
    AuditLog,
    DeliveryEvidence,
    IntegrationJob,
    Letter,
    LetterTemplate,
    LoginCode,
    Office,
    PlateRecord,
    Pool,
    Request,
    User,
)
from .pagination import PAGE_SIZE, list_context, list_page, page_url
from .security import rate_limit
from .services import (
    allocate_pool,
    audit,
    availability,
    create_request,
    decide_request,
    expire_reservations,
    extend_reservation,
    issue_slot,
    require_role,
    send_request,
    update_record,
    visible,
    withdraw_request,
)


def ip(request):
    return request.META.get("REMOTE_ADDR")


def form_errors(form, error):
    form.add_error(
        None,
        "; ".join(error.messages) if isinstance(error, ValidationError) else str(error),
    )


@require_http_methods(["GET", "POST"])
def public(request):
    from .public_protection import public_gate

    values = request.POST if request.method == "POST" else request.GET
    form = CheckForm(values or None)
    result, status, challenge_required, retry = None, 200, False, 0
    if values:
        gate, retry = public_gate(request, request.POST.get("altcha", "") if request.method == "POST" else "")
        if gate == "limited":
            form.is_valid()
            form.add_error(None, "Zbyt wiele zapytań. Spróbuj ponownie za minutę.")
            status = 429
        elif gate == "challenge":
            form.is_valid()
            form.add_error(None, "Przed kolejnym sprawdzeniem potwierdź weryfikację poniżej.")
            status, challenge_required = 403, True
        elif form.is_valid():
            try:
                data = form.cleaned_data
                result = availability(
                    data["part"],
                    data["prefix"],
                    int(data["digit"]) if data["digit"] else None,
                    viewer=request.user,
                )
            except ValidationError as error:
                form_errors(form, error)
    response = render(
        request,
        "registry/public.html",
        {
            "form": form,
            "result": result,
            "challenge_required": challenge_required,
        },
        status=status,
    )
    response["Cache-Control"] = "no-store"
    if retry and status == 429:
        response["Retry-After"] = str(retry)
    return response


@require_http_methods(["GET"])
def public_challenge(request):
    from .public_protection import issue_challenge

    challenge, retry = issue_challenge(request)
    response = JsonResponse(
        challenge or {"error": "Limit pobierania weryfikacji."}, status=200 if challenge else 429
    )
    response["Cache-Control"] = "no-store"
    if retry:
        response["Retry-After"] = str(retry)
    return response


@require_http_methods(["GET", "POST"])
def login_email(request):
    next_path = safe_login_return(
        request.POST.get("next", "") if request.method == "POST" else request.GET.get("next", "")
    )
    if request.user.is_authenticated:
        return redirect(next_path or "dashboard")
    form = LoginEmailForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].lower()
        if not rate_limit("login-ip:" + (ip(request) or ""), 20, 900) or not rate_limit(
            "login-email:" + email, 5, 900
        ):
            form.add_error(None, "Limit prób logowania. Spróbuj ponownie za 15 minut.")
            return render(request, "registry/login.html", {"form": form, "next_path": next_path}, status=429)
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        request.session["login_next"] = next_path
        request.session["login_code_id"] = -1
        if user and user.access_allowed:
            code = f"{secrets.randbelow(1000000):06d}"
            with transaction.atomic():
                LoginCode.objects.filter(user=user, used=False).update(used=True)
                token = LoginCode.objects.create(
                    user=user,
                    digest=make_password(code),
                    expires_at=timezone.now() + timedelta(minutes=10),
                )
                request.session["login_code_id"] = token.pk
            try:
                send_mail(
                    "Kod logowania - Dyna Rejestr Tablic",
                    f"Kod: {code}\nWażny przez 10 minut. Nie przekazuj go innym osobom.\n{settings.APP_URL}",
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                )
            except Exception:
                token.used = True
                token.save(update_fields=["used"])
                audit(
                    None,
                    "auth.mail_failed",
                    user,
                    reason="Wysyłka kodu nie powiodła się; sprawdź konfigurację poczty.",
                    ip=ip(request),
                )
        return redirect("login_code")
    return render(request, "registry/login.html", {"form": form, "next_path": next_path})


@require_http_methods(["GET", "POST"])
def login_code(request):
    form = LoginCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not rate_limit("otp:" + (ip(request) or ""), 20, 900):
            form.add_error(None, "Limit prób. Spróbuj ponownie później.")
        else:
            authenticated = None
            with transaction.atomic():
                token = (
                    LoginCode.objects.select_for_update(of=("self",))
                    .select_related("user__office")
                    .filter(pk=request.session.get("login_code_id", -1))
                    .first()
                )
                if token and not token.used and token.attempts < 5 and token.expires_at > timezone.now():
                    token.attempts += 1
                    if check_password(form.cleaned_data["code"], token.digest) and token.user.access_allowed:
                        token.used = True
                        authenticated = token.user
                    token.save(update_fields=["attempts", "used"])
            if authenticated:
                login(
                    request,
                    authenticated,
                    backend="django.contrib.auth.backends.ModelBackend",
                )
                request.session.pop("login_code_id", None)
                audit(authenticated, "auth.login", authenticated, ip=ip(request))
                return redirect(safe_login_return(request.session.pop("login_next", "")) or "dashboard")
            form.add_error(
                None,
                "Kod niepoprawny, wykorzystany lub wygasły. Po 5 próbach zamów nowy kod.",
            )
    return render(
        request,
        "registry/login.html",
        {
            "form": form,
            "code_step": True,
            "next_path": safe_login_return(request.session.get("login_next", "")),
        },
    )


def csrf_failure(request, reason=""):
    """Nie pokazuj szczegółów zabezpieczeń ani nie ponawiaj odrzuconego POST."""
    if request.path.startswith("/api/"):
        response = JsonResponse(
            {
                "error": "Nie można potwierdzić bezpieczeństwa formularza. Odśwież stronę i zaloguj się ponownie."
            },
            status=403,
        )
    else:
        response = render(
            request,
            "registry/csrf_failure.html",
            {"next_path": safe_login_return(request.path)},
            status=403,
        )
    response["Cache-Control"] = "no-store"
    return response


@require_POST
def logout_view(request):
    logout(request)
    return redirect("public")


@login_required
@require_http_methods(["GET"])
def dashboard(request):
    if request.user.role == "ADMIN":
        return redirect("admin_panel")
    expire_reservations()
    reqs = visible(request.user, Request.objects.select_related("office", "record"))
    records = visible(request.user, PlateRecord.objects.all())
    pools = visible(request.user, Pool.objects.select_related("office"))
    return render(
        request,
        "registry/dashboard.html",
        {
            "requests": reqs[:6],
            "pending_count": reqs.filter(status="SENT").count(),
            "records_count": records.exclude(status="RELEASED").count(),
            "pools_count": pools.count(),
            "alerts": [p for p in pools if p.percent >= 80],
        },
    )


@login_required
@require_http_methods(["GET"])
def requests_list(request):
    expire_reservations()
    return render(
        request,
        "registry/requests.html",
        {**list_context(request, request_queryset(request), "requests"), "statuses": Request.Status.choices},
    )


def request_queryset(request):
    reqs = visible(request.user, Request.objects.select_related("office", "record", "author"))
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    if status:
        reqs = reqs.filter(status=status)
    if q:
        reqs = reqs.filter(
            Q(case_number__icontains=q)
            | Q(record__number__icontains=q.replace(" ", ""))
            | Q(office__name__icontains=q)
        )
    return reqs


@login_required
@require_http_methods(["GET", "POST"])
def request_new(request):
    require_role(request.user, "COUNTY", "MAIN")
    if request.method == "POST" and request.POST.get("kind") in {"II", "III"}:
        require_role(request.user, "COUNTY")
    form = RequestForm(
        request.POST or None,
        user=request.user,
        initial={
            "number": request.GET.get("number", ""),
            "kind": request.GET.get("kind", "I"),
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            req = create_request(request.user, form.cleaned_data, ip(request))
            messages.success(
                request,
                "Wniosek zapisany. Wyróżnik zarezerwowany; pismo PDF jest gotowe."
                if req.kind == "I"
                else "Wniosek o pulę zapisany; pismo PDF jest gotowe.",
            )
            return redirect("request_detail", uuid=req.uuid)
        except ValidationError as error:
            form_errors(form, error)
    return render(
        request,
        "registry/form.html",
        {
            "form": form,
            "title": "Nowy wniosek",
            "description": "Utworzenie wniosku o tablicę indywidualną rezerwuje numer na 14 dni.",
            "submit": "Zapisz wniosek",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def request_detail(request, uuid):
    require_role(request.user, "COUNTY", "MAIN")
    expire_reservations()
    req = get_object_or_404(
        visible(
            request.user,
            Request.objects.select_related("office", "record", "author", "decided_by"),
        ),
        uuid=uuid,
    )
    form = DecisionForm(
        request.POST or None,
        kind=req.kind,
        initial={
            "prefix": "P" if req.kind == "II" else "P0",
            "valid_from": timezone.localdate(),
            "start": 1,
            "end": req.count,
        },
    )
    if request.method == "POST":
        require_role(request.user, "MAIN")
        if form.is_valid():
            data = form.cleaned_data
            try:
                if (
                    data["decision"] == "approve"
                    and req.kind != "I"
                    and (not data["start"] or not data["end"] or not data["valid_from"])
                ):
                    raise ValidationError("Podaj zakres i datę obowiązywania puli.")
                decide_request(
                    request.user,
                    uuid,
                    data["decision"] == "approve",
                    data["reason"],
                    data,
                    ip(request),
                )
                messages.success(request, "Decyzja zapisana. Pismo zwrotne jest dostępne poniżej.")
                return redirect("request_detail", uuid=uuid)
            except ValidationError as error:
                form_errors(form, error)
    # Urząd wnioskujący zachowuje dokumentację własnej sprawy. Powiązanie
    # historycznego wniosku nie daje dostępu do aktualnego wpisu innego urzędu.
    current_record = (
        visible(request.user, PlateRecord.objects.select_related("office")).filter(pk=req.record_id).first()
        if req.record_id
        else None
    )
    event_filter = Q(object_type="Request", object_id=str(req.pk))
    if current_record:
        record_events = Q(object_type="PlateRecord", object_id=str(current_record.pk))
        if request.user.role == "COUNTY":
            record_events &= Q(office_id=request.user.office_id)
        event_filter |= record_events
    letter_events = Q(
        object_type="Letter", object_id__in=[str(pk) for pk in req.letters.values_list("pk", flat=True)]
    )
    if request.user.role == "COUNTY":
        letter_events &= Q(office_id=request.user.office_id)
    event_filter |= letter_events
    from .models import EZDIncomingDocument

    incoming = EZDIncomingDocument.objects.filter(office=request.user.office, letter__request=req)
    event_filter |= Q(
        object_type="EZDIncomingDocument",
        object_id__in=[str(pk) for pk in incoming.values_list("pk", flat=True)],
    )
    history = history_context(request, AuditLog.objects.filter(event_filter))
    return render(
        request,
        "registry/request_detail.html",
        {
            "req": req,
            "current_record": current_record,
            "request_number": req.record.display_number if req.record_id else "",
            "form": form,
            "letters": req.letters.all(),
            **history,
            "incoming": incoming,
            "decision_notices": IntegrationJob.objects.filter(
                letter__request=req, provider="SMTP", operation="DECISION_NOTICE"
            ),
        },
    )


@login_required
@require_POST
def request_action(request, uuid, action):
    try:
        if action == "submit":
            send_request(request.user, uuid, ip(request))
            messages.success(
                request,
                "Wniosek złożony do UMP. Wysłanie korespondencji zewnętrznej wybierz przy piśmie.",
            )
        elif action == "withdraw":
            withdraw_request(request.user, uuid, request.POST.get("reason", ""), ip(request))
            messages.success(request, "Wniosek wycofany; numer zwolniony.")
        else:
            raise Http404
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    except ObjectDoesNotExist:
        raise Http404
    return redirect("request_detail", uuid=uuid)


def record_queryset(request):
    records = visible(request.user, PlateRecord.objects.select_related("office"))
    if request.GET.get("q"):
        q = request.GET["q"].strip()
        records = records.filter(
            Q(number__icontains=q.replace(" ", "")) | Q(owner__icontains=q) | Q(vin__icontains=q)
        )
    if request.GET.get("status"):
        records = records.filter(status=request.GET["status"])
    if request.GET.get("office"):
        records = records.filter(office_id=request.GET["office"])
    return records


@login_required
@require_http_methods(["GET"])
def records_list(request):
    expire_reservations()
    return render(
        request,
        "registry/records.html",
        {
            **list_context(request, record_queryset(request), "records"),
            "statuses": PlateRecord.Status.choices,
            "offices": Office.objects.filter(active=True) if request.user.role == "MAIN" else [],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def record_detail(request, uuid):
    require_role(request.user, "COUNTY", "MAIN")
    expire_reservations()
    record = get_object_or_404(visible(request.user, PlateRecord.objects.select_related("office")), uuid=uuid)
    can_edit = request.user.role == "MAIN" or record.status in {"ALLOCATED", "ISSUED", "SOLD"}
    if request.method == "POST" and not can_edit:
        raise PermissionDenied("W tym statusie powiat może wyłącznie przeglądać wpis.")
    form = RecordForm(request.POST or None, instance=record, user=request.user) if can_edit else None
    if request.method == "POST" and form.is_valid():
        data = {k: v for k, v in form.cleaned_data.items() if k not in ["reason", "version"]}
        if "office" in data:
            data["office_id"] = data.pop("office").pk
        try:
            update_record(
                request.user,
                uuid,
                data,
                form.cleaned_data["reason"],
                form.cleaned_data["version"],
                ip(request),
            )
            messages.success(request, "Dane zapisane. Historia zawiera wartości przed i po zmianie.")
            return redirect("record_detail", uuid=uuid)
        except ValidationError as error:
            form_errors(form, error)
    return render(
        request,
        "registry/record_detail.html",
        {
            "record": record,
            "form": form,
            "can_edit": can_edit,
            "can_extend": request.user.role == "MAIN"
            and record.status in {"RESERVED", "SENT"}
            and record.reservation_until is not None
            and record.reservation_until > timezone.now(),
            "import_event": AuditLog.objects.filter(
                object_type="PlateRecord", object_id=str(record.pk), action="plate.imported"
            )
            .select_related("actor")
            .first(),
            **history_context(
                request, AuditLog.objects.filter(object_type="PlateRecord", object_id=str(record.pk))
            ),
        },
    )


@login_required
@require_POST
def reservation_extend(request, uuid):
    try:
        extend_reservation(
            request.user,
            uuid,
            int(request.POST.get("days", 0)),
            request.POST.get("reason", ""),
            ip(request),
        )
        messages.success(request, "Rezerwacja przedłużona.")
    except PlateRecord.DoesNotExist:
        raise Http404
    except (ValidationError, ValueError) as error:
        messages.error(request, str(error))
    return redirect("record_detail", uuid=uuid)


@login_required
@require_http_methods(["GET"])
def pools_list(request):
    pools = visible(request.user, Pool.objects.select_related("office"))
    return render(request, "registry/pools.html", {"pools": pools})


@login_required
@require_http_methods(["GET", "POST"])
def pool_new(request):
    require_role(request.user, "MAIN")
    form = PoolForm(request.POST or None, initial={"kind": "II", "valid_from": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        data = {**form.cleaned_data, "office": form.cleaned_data["office"].pk}
        try:
            pool = allocate_pool(request.user, data, ip=ip(request))
            messages.success(request, "Pula przydzielona. Pismo informujące jest gotowe.")
            return redirect("pool_detail", uuid=pool.uuid)
        except ValidationError as error:
            form_errors(form, error)
    return render(
        request,
        "registry/form.html",
        {
            "form": form,
            "title": "Przydział puli",
            "description": "Moduł III wymaga wcześniejszego wniosku urzędu. Zakres oznacza pozycje w uporządkowanej pojemności numeracyjnej.",
            "submit": "Przydziel pulę",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def pool_detail(request, uuid):
    pool = get_object_or_404(visible(request.user, Pool.objects.select_related("office")), uuid=uuid)
    slots = Paginator(pool.slots.all(), 100).get_page(request.GET.get("page"))
    if request.method == "POST":
        try:
            issue_slot(
                request.user,
                uuid,
                int(request.POST.get("slot", 0)),
                request.POST.get("case_number", ""),
                ip(request),
            )
            messages.success(request, "Wydanie numeru zapisane.")
            return redirect(reverse("pool_detail", kwargs={"uuid": uuid}) + f"?page={slots.number}")
        except (ValidationError, ValueError, ObjectDoesNotExist) as error:
            messages.error(request, str(error))
    return render(
        request,
        "registry/pool_detail.html",
        {
            "pool": pool,
            "slots": slots,
            "letters": pool.letters.all(),
            "can_issue": pool.valid_from <= timezone.localdate()
            and (pool.valid_until is None or pool.valid_until >= timezone.localdate()),
            "import_event": AuditLog.objects.filter(
                object_type="Pool", object_id=str(pool.pk), action="pool.imported"
            )
            .select_related("actor")
            .first(),
        },
    )


def letter_queryset(user):
    require_role(user, "COUNTY", "MAIN")
    letters = Letter.objects.select_related("office", "recipient", "request", "pool", "replaces").order_by(
        "-created_at", "-pk"
    )
    return (
        letters.filter(Q(office=user.office) | Q(recipient=user.office)) if user.role == "COUNTY" else letters
    )


@login_required
@require_http_methods(["GET"])
def letters_list(request):
    return render(
        request,
        "registry/letters.html",
        list_context(
            request,
            letter_queryset(request.user).defer(
                "pdf", "signed_pdf", "body", "replaces__pdf", "replaces__signed_pdf", "replaces__body"
            ),
            "letters",
        ),
    )


@login_required
@require_http_methods(["GET"])
def letter_pdf(request, uuid):
    from .documents import document_payload

    letter = get_object_or_404(letter_queryset(request.user), uuid=uuid)
    original = request.GET.get("original") == "1"
    try:
        payload = document_payload(letter, original=original)
    except ValidationError as error:
        return HttpResponse("; ".join(error.messages), status=409, content_type="text/plain; charset=utf-8")
    response = HttpResponse(payload, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="DRT-{letter.uuid}.pdf"'
    response["X-Content-SHA256"] = hashlib.sha256(payload).hexdigest()
    audit(request.user, "letter.downloaded", letter, ip=ip(request))
    return response


@login_required
@require_http_methods(["GET", "POST"])
def letter_sign(request, uuid):
    from .forms import SignatureForm
    from .signatures import load_profile, require_signing_actor, sign_letter

    letter = get_object_or_404(letter_queryset(request.user), uuid=uuid)
    if letter.office_id != request.user.office_id:
        raise PermissionDenied("Podpisuje wyłącznie urząd nadawcy.")
    form = SignatureForm(request.POST or None, request.FILES or None)
    profile, config_error = None, ""
    try:
        profile = load_profile(letter.office_id)
        require_signing_actor(request.user, letter, profile)
    except ValidationError as error:
        config_error = "; ".join(error.messages)
    locked = (
        bool(letter.signed_pdf) or letter.jobs.exclude(provider="SMTP", operation="DECISION_NOTICE").exists()
    )
    if request.method == "POST" and form.is_valid() and profile and not locked:
        if not rate_limit(f"sign:{request.user.pk}", 10, 60):
            form.add_error(None, "Limit podpisów. Spróbuj ponownie za minutę.")
        else:
            try:
                values = form.cleaned_data
                upload = values.get("file")
                sign_letter(
                    request.user,
                    letter,
                    uploaded=upload.read() if values["method"] == "IMPORT" else None,
                    reason=values["reason"],
                    ip=ip(request),
                )
                messages.success(
                    request,
                    "Podpisany PDF zweryfikowano i zapisano. Status kwalifikowany nie został oceniony.",
                )
                return redirect("letter_sign", uuid=letter.uuid)
            except ValidationError as error:
                form_errors(form, error)
    return render(
        request,
        "registry/signature.html",
        {
            "letter": letter,
            "form": form,
            "profile": profile,
            "config_error": config_error,
            "locked": locked,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def letter_revision(request, uuid):
    from .forms import LetterRevisionForm
    from .services import create_letter_revision

    letter = get_object_or_404(letter_queryset(request.user), uuid=uuid)
    if letter.office_id != request.user.office_id:
        raise PermissionDenied("Nową wersję tworzy wyłącznie urząd nadawcy.")
    form = LetterRevisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            new = create_letter_revision(request.user, letter, form.cleaned_data["reason"], ip(request))
            messages.success(
                request, "Utworzono nową wersję. Archiwalny dokument i kolejka pozostały zachowane."
            )
            return redirect("letter_sign", uuid=new.uuid)
        except ValidationError as error:
            form_errors(form, error)
    return render(
        request,
        "registry/form.html",
        {
            "form": form,
            "title": "Nowa wersja pisma",
            "description": f"Oryginał {letter.number} zostanie zachowany. Nowa wersja otrzyma osobny numer i datę, z tą samą treścią.",
            "submit": "Utwórz nową wersję",
        },
    )


@login_required
@require_http_methods(["GET"])
def audit_list(request):
    events = AuditLog.objects.select_related("actor", "office")
    if request.user.role == "COUNTY":
        events = events.filter(actor=request.user)
    return render(request, "registry/audit.html", history_context(request, events))


def history_context(request, events):
    page = Paginator(events.select_related("actor", "office").order_by("-created_at", "-pk"), 50).get_page(
        request.GET.get("history_page")
    )
    return {"events": page.object_list, "history_page": page}


@login_required
@require_http_methods(["GET"])
def admin_panel(request):
    require_role(request.user, "ADMIN")
    return render(
        request,
        "registry/admin_panel.html",
        {
            "offices": Office.objects.all(),
            "users": User.objects.select_related("office"),
            "templates": LetterTemplate.objects.all(),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def admin_edit(request, kind, pk=None):
    require_role(request.user, "ADMIN")
    models = {
        "office": (Office, OfficeForm, "urząd"),
        "user": (User, UserForm, "konto"),
        "template": (LetterTemplate, TemplateForm, "szablon pisma"),
    }
    if kind not in models:
        raise Http404
    model, form_class, label = models[kind]
    obj = get_object_or_404(model, pk=pk) if pk else None
    form = form_class(request.POST or None, instance=obj)
    if obj and kind == "office":
        form.fields["id"].disabled = True
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                before = {}
                if kind == "user" and pk:
                    old = User.objects.select_for_update(of=("self",), no_key=True).get(pk=pk)
                    from django.core import signing

                    try:
                        version = signing.loads(
                            form.cleaned_data["account_version"], salt="admin-account-version", max_age=1800
                        )
                    except signing.BadSignature as exc:
                        raise ValidationError(
                            "Formularz konta wygasł lub został zmieniony. Otwórz go ponownie."
                        ) from exc
                    if version != account_settings_snapshot(old):
                        raise ValidationError("Konto zmieniło się w międzyczasie. Otwórz ponownie formularz.")
                    before = {key: getattr(old, key) for key in UserForm.Meta.fields if key != "office"}
                    before["office"] = old.office_id
                item = form.save(commit=False)
                if kind == "template":
                    item.revision += 1
                item.full_clean()
                item.save()
                after = {"id": str(item.pk)}
                if kind == "user":
                    after.update({key: getattr(item, key) for key in UserForm.Meta.fields if key != "office"})
                    after["office"] = item.office_id
                audit(
                    request.user,
                    "admin." + kind + "_saved",
                    item,
                    before=before,
                    after=after,
                    reason=form.cleaned_data.get("reason", ""),
                    ip=ip(request),
                )
                if kind == "user" and not pk and item.is_active:
                    from .account_invitations import enqueue_invitation

                    enqueue_invitation(request.user, item.pk, form.cleaned_data["reason"], ip(request))
        except ValidationError as exc:
            form_errors(form, exc)
        except IntegrityError:
            form.add_error(
                None, "Dane kolidują z istniejącą konfiguracją. Sprawdź adres e-mail i odśwież formularz."
            )
        else:
            messages.success(
                request,
                "Zapisano konfigurację."
                + (
                    " Zaproszenie oczekuje na wysyłkę."
                    if kind == "user" and not pk and item.is_active
                    else ""
                ),
            )
            return redirect("admin_panel")
    return render(
        request,
        "registry/form.html",
        {"form": form, "title": "Konfiguracja: " + label, "submit": "Zapisz"},
    )


@login_required
@require_http_methods(["GET"])
def export_records(request):
    records = record_queryset(request)
    stream = StringIO()
    writer = csv.writer(stream, delimiter=";")
    fields = [
        "number",
        "owner",
        "address",
        "office_id",
        "status",
        "vin",
        "make",
        "model",
        "registration_date",
        "sale_date",
        "buyer",
        "letter_number",
        "note",
    ]
    writer.writerow(fields)

    def safe(value):
        value = str(value or "")
        return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value

    for record in records:
        writer.writerow([safe(getattr(record, f)) for f in fields])
    audit(
        request.user,
        "registry.exported",
        request.user,
        after={"rows": records.count()},
        ip=ip(request),
    )
    response = HttpResponse("\ufeff" + stream.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="ewidencja.csv"'
    return response


@login_required
@require_http_methods(["GET"])
def integrations(request):
    from .integrations import configuration_status

    require_role(request.user, "COUNTY", "MAIN", "ADMIN")

    jobs = (
        IntegrationJob.objects.select_related("letter__office", "letter__recipient")
        .prefetch_related(Prefetch("evidence", queryset=DeliveryEvidence.objects.defer("content")))
        .defer("payload", "letter__pdf", "letter__signed_pdf", "letter__body")
    )
    if request.user.role == "COUNTY":
        jobs = jobs.filter(Q(letter__office=request.user.office) | Q(letter__recipient=request.user.office))
    return render(
        request,
        "registry/integrations.html",
        {"providers": configuration_status(request.user.office_id), **list_context(request, jobs, "jobs")},
    )


@login_required
@require_http_methods(["GET", "POST"])
def ezd_incoming(request):
    from .connectors.ezdrp import ConnectorError
    from .ezd_incoming import receive_rpw
    from .forms import EZDIncomingForm
    from .models import EZDIncomingDocument

    require_role(request.user, "COUNTY", "MAIN")
    form = EZDIncomingForm(request.POST or None, initial={"year": timezone.localdate().year})
    if request.method == "POST" and form.is_valid():
        try:
            rows = receive_rpw(request.user, **form.cleaned_data, ip=ip(request))
            messages.success(request, f"Sprawdzono {len(rows)} dokumentów PDF. Wyniki są widoczne poniżej.")
            return redirect("ezd_incoming")
        except (ValidationError, ConnectorError) as exc:
            form_errors(form, exc)
    rows = (
        EZDIncomingDocument.objects.filter(office=request.user.office)
        .select_related("letter__request")
        .defer("content", "letter__pdf", "letter__signed_pdf", "letter__body")
    )
    return render(
        request, "registry/ezd_incoming.html", {"form": form, **list_context(request, rows, "incoming")}
    )


@login_required
@require_POST
def ezd_incoming_publish(request, uuid):
    from .connectors.ezdrp import ConnectorError
    from .ezd_incoming import publish_incoming_link
    from .models import EZDIncomingDocument

    require_role(request.user, "COUNTY", "MAIN")
    get_object_or_404(EZDIncomingDocument, uuid=uuid, office=request.user.office)
    try:
        publish_incoming_link(request.user, uuid, reason=request.POST.get("reason", ""), ip=ip(request))
        messages.success(request, "EZD potwierdził zapis identyfikatora i linku do wniosku.")
    except (ValidationError, ConnectorError) as exc:
        messages.error(request, "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc))
    return redirect("ezd_incoming")


@login_required
@require_http_methods(["GET"])
def ezd_incoming_pdf(request, uuid):
    from .models import EZDIncomingDocument

    require_role(request.user, "COUNTY", "MAIN")
    row = get_object_or_404(EZDIncomingDocument, uuid=uuid, office=request.user.office, status="MATCHED")
    if row.content is None or hashlib.sha256(bytes(row.content)).hexdigest() != row.sha256:
        return HttpResponse("Dokument wymaga kontroli integralności.", status=409)
    response = HttpResponse(bytes(row.content), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="RPW-{row.rpw_year}-{row.rpw_number}.pdf"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_http_methods(["GET", "POST"])
def edor_resume(request, uuid):
    from .connectors.ezdrp import ConnectorError
    from .edor_delivery import edor_resume_mode, resume_edor_observation, resume_edor_unsent
    from .forms import EDorResumeForm

    require_role(request.user, "ADMIN")
    job = get_object_or_404(IntegrationJob, uuid=uuid, provider="EDOR")
    mode = edor_resume_mode(job)
    form = EDorResumeForm(
        request.POST or None,
        initial={"mode": mode, "expected_updated_at": job.updated_at.isoformat()},
    )
    if request.method == "POST" and form.is_valid():
        if not mode or form.cleaned_data["mode"] != mode:
            form.add_error(None, "Stan operacji nie pozwala na wybrany tryb wznowienia.")
        else:
            action = resume_edor_unsent if mode == "UNSENT" else resume_edor_observation
            try:
                action(
                    request.user,
                    job.uuid,
                    reason=form.cleaned_data["reason"],
                    expected_updated_at=form.cleaned_data["expected_updated_at"],
                    ip=ip(request),
                )
                messages.success(
                    request,
                    "Wznowiono to samo zlecenie. Wysyłkę wykona pracownik kolejki."
                    if mode == "UNSENT"
                    else "Wznowiono wyłącznie odczyt statusów i dowodów. Pismo nie będzie ponownie wysłane.",
                )
                return redirect("integrations")
            except (ValidationError, ConnectorError) as error:
                form_errors(form, error)
    return render(request, "registry/edor_resume.html", {"job": job, "mode": mode, "form": form})


@login_required
@require_http_methods(["GET", "POST"])
def edor_search(request):
    from .connectors.edor import EDorClient, load_profile
    from .connectors.ezdrp import ConnectorError
    from .forms import EDorSearchForm

    require_role(request.user, "COUNTY", "MAIN")
    form = EDorSearchForm(request.POST or None)
    results, config_error = None, ""
    try:
        profile = load_profile(request.user.office_id)
    except ConnectorError as exc:
        config_error = str(exc)
    if request.method == "POST" and form.is_valid() and not config_error:
        if not rate_limit(f"edor-search:{request.user.pk}", limit=20, seconds=60):
            form.add_error(None, "Limit wyszukiwań. Spróbuj ponownie za minutę.")
        else:
            try:
                with EDorClient(profile) as client:
                    results = client.search_public(**form.cleaned_data)
                audit(
                    request.user,
                    "edor.address.searched",
                    request.user,
                    after={"results": len(results["rows"]), "environment": profile.environment},
                    ip=ip(request),
                )
            except ConnectorError as exc:
                form.add_error(None, str(exc))
    return render(
        request,
        "registry/edor_search.html",
        {
            "form": form,
            "results": results,
            "config_error": config_error,
        },
    )


@login_required
@require_http_methods(["GET"])
def delivery_evidence(request, uuid, evidence_pk):
    from .models import DeliveryEvidence

    letter = get_object_or_404(letter_queryset(request.user), uuid=uuid)
    evidence = get_object_or_404(DeliveryEvidence, pk=evidence_pk, job__letter=letter)
    payload = bytes(evidence.content)
    if hashlib.sha256(payload).hexdigest() != evidence.sha256:
        return HttpResponse(
            "Dowód nie przeszedł kontroli sumy SHA-256. Skontaktuj się z administratorem.", status=409
        )
    response = HttpResponse(payload, content_type="application/octet-stream")
    extension = (
        "pdf" if payload.startswith(b"%PDF-") else "zip" if payload.startswith(b"PK\x03\x04") else "bin"
    )
    response["Content-Disposition"] = f'attachment; filename="dowod-{evidence.pk}.{extension}"'
    response["X-Content-SHA256"] = evidence.sha256
    response["Cache-Control"] = "private, no-store"
    audit(
        request.user,
        "edor.evidence.downloaded",
        letter,
        after={"evidence": evidence.pk, "kind": evidence.kind, "sha256": evidence.sha256},
        ip=ip(request),
    )
    return response


@login_required
@require_POST
def letter_send(request, uuid):
    from .integrations import enqueue

    letter = get_object_or_404(letter_queryset(request.user), uuid=uuid)
    if letter.office_id != request.user.office_id:
        raise PermissionDenied("Korespondencję wysyła urząd nadawcy.")
    try:
        enqueue(request.user, letter, request.POST.get("provider", ""), ip(request))
        messages.success(request, "Operacja zapisana w kolejce integracji.")
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    return redirect("integrations")


@login_required
@require_http_methods(["GET", "POST"])
def letter_ezd(request, uuid):
    from .connectors.ezdrp import ConnectorError, load_profile
    from .forms import EZDRegisterForm
    from .integrations import enqueue_ezd, ezd_scope
    from .models import EZDCaseLink

    letter = get_object_or_404(letter_queryset(request.user), uuid=uuid)
    if letter.office_id != request.user.office_id:
        raise PermissionDenied("Zapis w EZD wykonuje urząd nadawcy.")
    _, scope_id, _ = ezd_scope(letter)
    link = EZDCaseLink.objects.filter(office=request.user.office, scope_id=scope_id).first()
    error = ""
    try:
        load_profile(request.user.office_id)
    except ConnectorError as exc:
        error = str(exc)
    form = EZDRegisterForm(request.POST or None, linked=bool(link))
    if request.method == "POST" and form.is_valid():
        try:
            job = enqueue_ezd(request.user, letter, **form.cleaned_data, ip=ip(request))
            messages.success(
                request,
                f"Dokument w kolejce EZD: {job.status_label}. Wynik będzie widoczny w Integracjach.",
            )
            return redirect("integrations")
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "registry/letter_ezd.html",
        {"letter": letter, "link": link, "form": form, "config_error": error},
    )


@require_http_methods(["GET"])
def health(request):
    from django.db import DatabaseError, connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return JsonResponse({"status": "unavailable", "service": "dyna-rejestr-tablic"}, status=503)
    return JsonResponse(
        {
            "status": "ok",
            "service": "dyna-rejestr-tablic",
            "mode": "local" if settings.LOCAL else "office",
            "revision": settings.APP_REVISION,
        }
    )


def api_endpoint(roles=("COUNTY", "MAIN"), *, methods):
    def decorator(fn):
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({"error": "Wymagane logowanie."}, status=401)
            try:
                require_role(request.user, *roles)
                if request.method not in methods:
                    return HttpResponseNotAllowed(methods)
                if request.method != "GET":
                    from .api_validation import parse_payload

                    request.data = parse_payload(request.body)
                return fn(request, *args, **kwargs)
            except PermissionDenied as error:
                return JsonResponse({"error": str(error)}, status=403)
            except ObjectDoesNotExist:
                return JsonResponse({"error": "Nie znaleziono obiektu."}, status=404)
            except (ValidationError, ValueError, TypeError, KeyError) as error:
                return JsonResponse(
                    {
                        "error": "; ".join(error.messages)
                        if isinstance(error, ValidationError)
                        else str(error)
                    },
                    status=400,
                )
            except IntegrityError:
                return JsonResponse({"error": "Konflikt danych."}, status=409)

        return wrapper

    return decorator


@require_http_methods(["GET"])
def api_availability(request):
    from .public_protection import public_gate

    gate, retry = public_gate(request, request.headers.get("X-Altcha-Payload", ""))
    if gate != "allowed":
        response = JsonResponse(
            {"error": "Limit zapytań."}
            if gate == "limited"
            else {
                "error": "Wymagana weryfikacja CAPTCHA.",
                "code": "CAPTCHA_REQUIRED",
                "challenge_url": "/api/public-challenge/",
            },
            status=429 if gate == "limited" else 403,
        )
        response["Cache-Control"] = "no-store"
        if retry:
            response["Retry-After"] = str(retry)
        return response
    try:
        result = availability(
            request.GET.get("part", ""),
            request.GET.get("prefix", "P"),
            int(request.GET["digit"]) if request.GET.get("digit") else None,
            viewer=request.user,
        )
        response = JsonResponse(result)
    except (ValidationError, ValueError) as error:
        response = JsonResponse({"error": str(error)}, status=400)
    response["Cache-Control"] = "no-store"
    return response


@api_endpoint(methods=("GET", "POST"))
def api_requests(request):
    if request.method == "POST":
        from .api_validation import request_values

        form = RequestForm(request_values(request.data))
        if not form.is_valid():
            return JsonResponse({"errors": form.errors.get_json_data()}, status=400)
        req = create_request(request.user, form.cleaned_data, ip(request))
        return JsonResponse(
            {"id": str(req.uuid), "reference": req.reference, "status": req.status},
            status=201,
        )
    expire_reservations()
    page = list_page(request, request_queryset(request))
    return JsonResponse(
        {
            "items": [
                {
                    "id": str(r.uuid),
                    "reference": r.reference,
                    "office": r.office_id,
                    "status": r.status,
                    "kind": r.kind,
                }
                for r in page.object_list
            ],
            "count": page.paginator.count,
            "page": page.number,
            "pages": page.paginator.num_pages,
            "page_size": PAGE_SIZE,
            "next": page_url(request, page.next_page_number()) if page.has_next() else None,
            "previous": page_url(request, page.previous_page_number()) if page.has_previous() else None,
        }
    )


@api_endpoint(methods=("POST",))
def api_request_action(request, uuid, action):
    from .api_validation import decision_values, typed_values

    if action == "submit":
        typed_values(request.data)
        req = send_request(request.user, uuid, ip(request))
    elif action == "withdraw":
        typed_values(request.data, text=("reason",))
        req = withdraw_request(request.user, uuid, request.data.get("reason", ""), ip(request))
    elif action == "decide":
        require_role(request.user, "MAIN")
        kind = Request.objects.only("kind").get(uuid=uuid).kind
        values, pool = decision_values(request.data, kind)
        req = decide_request(
            request.user,
            uuid,
            values["approve"],
            values.get("reason", ""),
            pool,
            ip(request),
        )
    else:
        raise ObjectDoesNotExist
    return JsonResponse({"id": str(req.uuid), "status": req.status})


@api_endpoint(methods=("GET", "PATCH"))
def api_record(request, uuid):
    expire_reservations()
    record = visible(request.user, PlateRecord.objects.all()).get(uuid=uuid)
    if request.method == "PATCH":
        from .api_validation import record_patch

        data, reason, version = record_patch(request.data, request.user.role)
        record = update_record(
            request.user,
            uuid,
            data,
            reason,
            version,
            ip(request),
        )
    from .services import EDIT_FIELDS, scalar

    return JsonResponse(
        {
            "id": str(record.uuid),
            "number": record.number,
            "version": record.version,
            **{k: scalar(getattr(record, k)) for k in EDIT_FIELDS},
        }
    )


@api_endpoint(methods=("GET", "POST"))
def api_pools(request):
    if request.method == "POST":
        from .api_validation import pool_values

        require_role(request.user, "MAIN")
        form = PoolForm(pool_values(request.data))
        if not form.is_valid():
            return JsonResponse({"errors": form.errors.get_json_data()}, status=400)
        data = {**form.cleaned_data, "office": form.cleaned_data["office"].pk}
        pool = allocate_pool(request.user, data, ip=ip(request))
        return JsonResponse({"id": str(pool.uuid), "total": pool.total}, status=201)
    return JsonResponse(
        {
            "items": [
                {
                    "id": str(p.uuid),
                    "office": p.office_id,
                    "kind": p.kind,
                    "total": p.total,
                    "used": p.used,
                }
                for p in visible(request.user, Pool.objects.all())
            ]
        }
    )


@api_endpoint(methods=("POST",))
def api_slot(request, uuid):
    from .api_validation import typed_values

    values = typed_values(
        request.data, positive=("slot",), text=("case_number",), required=("slot", "case_number")
    )
    slot = issue_slot(
        request.user,
        uuid,
        values["slot"],
        values["case_number"],
        ip(request),
    )
    return JsonResponse({"number": slot.number, "issued_at": slot.issued_at.isoformat()})
